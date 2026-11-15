#!/usr/bin/env bash
# 서버 데이터를 /opt/theseus/backups/<시각>/에 백업하고 보관 기간이 지난 백업을 지웁니다.
#   mysql-<db>.sql.gz         API DB(mysqldump --single-transaction, 잠금 없이 일관된 스냅샷)
#   postgres-<db>.dump        Core DB(pg_dump custom 형식, pg_restore로 복구)
#   files.tar.gz              생성 Tool(custom-tools)과 Core 런타임 데이터(core-data)
# Redis와 Kafka는 일시 데이터라 백업하지 않습니다. core-data를 읽으려면 root로 실행합니다(cron 권장).
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=lib/selfhost.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/selfhost.sh"

usage() {
    cat <<'EOF'
사용법: sudo scripts/backup.sh [옵션]

  --env-file FILE   env 파일(기본: /opt/theseus/theseus.env)
  --dest DIR        백업 위치(기본: <THESEUS_HOST_ROOT>/backups)
  --retention DAYS  보관 일수(기본: 14, 환경변수 BACKUP_RETENTION_DAYS)
  -h, --help        도움말

cron 예: 30 3 * * * /opt/theseus/app/scripts/backup.sh >> /opt/theseus/backups/backup.log 2>&1
EOF
}

dest=""
retention="${BACKUP_RETENTION_DAYS:-14}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file) THESEUS_ENV_FILE="${2:?--env-file 값이 필요합니다}"; shift 2 ;;
        --dest) dest="${2:?--dest 값이 필요합니다}"; shift 2 ;;
        --retention) retention="${2:?--retention 값이 필요합니다}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "알 수 없는 인자: $1" ;;
    esac
done

[[ "$retention" =~ ^[0-9]+$ ]] || die "--retention은 숫자여야 합니다."
require_cmd docker gzip tar find
require_env_file

host_root="$(env_get "$THESEUS_ENV_FILE" THESEUS_HOST_ROOT /opt/theseus)"
mysql_db="$(env_get "$THESEUS_ENV_FILE" MYSQL_DATABASE theseus)"
pg_db="$(env_get "$THESEUS_ENV_FILE" POSTGRES_DB theseus_core)"
[[ -n "$dest" ]] || dest="$host_root/backups"

umask 077
stamp="$(date '+%Y%m%d-%H%M%S')"
out="$dest/$stamp"
mkdir -p "$out"
# 중간에 실패하면 불완전한 백업 디렉터리를 남기지 않습니다.
on_exit() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        rm -rf "$out"
        log "백업 실패(rc=$rc), $out 삭제"
    fi
}
trap on_exit EXIT

# 아래 sh -c 명령의 $변수는 컨테이너 안에서 펼쳐져야 하므로 일부러 작은따옴표를 씁니다.
log "MySQL 백업: $mysql_db"
# 비밀번호는 컨테이너 env(MYSQL_ROOT_PASSWORD)에서 읽어 이 셸의 프로세스 목록에 나타나지 않게 합니다.
# shellcheck disable=SC2016
compose exec -T mysql sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --databases "$MYSQL_DATABASE"' \
    | gzip >"$out/mysql-${mysql_db}.sql.gz"

log "PostgreSQL 백업: $pg_db"
# shellcheck disable=SC2016
compose exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$out/postgres-${pg_db}.dump"

file_dirs=()
for d in custom-tools core-data; do
    [[ -d "$host_root/$d" ]] && file_dirs+=("$d")
done
if [[ ${#file_dirs[@]} -gt 0 ]]; then
    log "파일 백업: ${file_dirs[*]}"
    # core-data에는 Core가 실행 중에 계속 덧붙이는 로그가 있어, 백업하는 동안 파일이 바뀌면 GNU tar가 1로 끝납니다.
    # 1은 "읽는 동안 바뀐 파일이 있음"일 뿐 아카이브는 만들어졌으므로 실패로 보지 않습니다. 이미 받은 DB 덤프까지
    # 지우지 않도록 2 이상(치명적 오류)만 실패로 처리합니다.
    tar_rc=0
    tar --warning=no-file-changed --warning=no-file-removed \
        -czf "$out/files.tar.gz" -C "$host_root" "${file_dirs[@]}" || tar_rc=$?
    if [[ $tar_rc -eq 1 ]]; then
        log "경고: 백업하는 동안 바뀐 파일이 있습니다(실행 중인 Core 로그 등). 아카이브는 정상으로 만들었습니다."
    elif [[ $tar_rc -ne 0 ]]; then
        log "파일 백업 실패(tar rc=$tar_rc)"
        exit "$tar_rc"
    fi
fi

log "보관 기간(${retention}일)이 지난 백업 삭제"
find "$dest" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$retention" -exec rm -rf {} +

du -sh "$out" >&2
log "백업 완료: $out"
