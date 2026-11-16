#!/usr/bin/env bash
# GitHub Actions 자동 배포의 서버 쪽 진입점입니다.
#
# 배포 전용 SSH 키의 authorized_keys 항목에 forced command로 고정해서 씁니다(셀프호스팅 가이드 10.1).
#   restrict,command="/opt/theseus/bin/ci-deploy.sh" ssh-ed25519 AAAA... theseus-ci-deploy
#
# 요청은 SSH_ORIGINAL_COMMAND(클라이언트가 보낸 명령 문자열)로 받습니다.
#   deploy <커밋 SHA 40자> <레지스트리 사용자>   stdin 1행: 레지스트리 읽기 토큰(GitHub Actions의 GITHUB_TOKEN)
#   status                                       현재 IMAGE_TAG, 서비스 상태, 마지막 배포 로그
#
# 신뢰 경계: 클라이언트(배포 키)가 정할 수 있는 것은 "어느 커밋을 배포할지"뿐입니다.
#   - 실행할 스크립트와 compose 설정은 클라이언트가 보내지 않습니다. 서버가 DEPLOY_GIT_URL 저장소를 직접 fetch하고,
#     그 커밋이 dev 브랜치에 포함됐는지 확인한 뒤 git archive로 꺼냅니다.
#   - 이미지는 서버 env의 DEPLOY_PULL_REGISTRY에서만 받고, 이미지 라벨(org.opencontainers.image.revision)이
#     요청한 커밋과 같은지 확인합니다.
#   그래서 배포 키가 유출돼도 할 수 있는 일은 "dev에 이미 있는 커밋을 다시 배포(롤백 포함)"로 제한됩니다.
#   단, dev에 push할 수 있는 사람은 곧 서버에서 코드를 실행할 수 있는 사람입니다(CD의 본질). dev 브랜치를 보호하세요.
#
# deploy 흐름:
#   입력 검증 -> 잠금 -> 출력을 SSH 세션과 분리(세션이 끊겨도 배포·롤백 계속) -> 저장소 fetch·dev 포함 확인·설정 추출
#   -> 새 compose config 검증 -> 이미지 pull·라벨 확인·로컬 이름으로 retag -> DB 덤프 -> 이전 설정 백업
#   -> 설정 반영·IMAGE_TAG 변경 -> scripts/deploy.sh(healthy 대기) -> 실패 시 이전 태그·설정으로 롤백 -> 오래된 이미지 정리
#
# 이 스크립트는 배포 때 교체되는 /opt/theseus/app 밖(/opt/theseus/bin, root 소유)에 설치합니다.
# 실행 중인 bash 스크립트 파일을 덮어쓰면 남은 부분을 엉뚱하게 읽을 수 있고, 배포 사용자가 고칠 수 없어야 하기 때문입니다.
# 같은 이유로 app/scripts/lib/selfhost.sh를 source하지 않고 필요한 함수만 따로 둡니다.
set -euo pipefail
# 임시 파일과 상태 디렉터리는 본인만 읽게 만들고, 서버에 반영하는 설정 파일 권한은 git의 모드(644/755)를 따릅니다.
umask 022

THESEUS_ROOT="${THESEUS_ROOT:-/opt/theseus}"
APP_DIR="$THESEUS_ROOT/app"
ENV_FILE="${THESEUS_ENV_FILE:-$THESEUS_ROOT/theseus.env}"
STATE_DIR="${DEPLOY_STATE_DIR:-$HOME/.theseus-deploy}"
LOCK_FILE="$STATE_DIR/deploy.lock"
LOG_FILE="$STATE_DIR/last-deploy.log"
REPO_DIR="$STATE_DIR/repo.git"
PREV_CONFIG_DIR="$STATE_DIR/prev-config"
DUMP_DIR="$STATE_DIR/predeploy-dumps"
DEPLOY_BRANCH="dev"
COMPONENTS=(api core frontend nginx)
DEFAULT_SANDBOX_IMAGE="theseus-sandbox:py311-tools"
# deploy.sh의 healthy 대기 상한. 배포 + 롤백 두 번 기다려도 deploy.yml의 job timeout(45분) 안에 끝나도록 잡습니다.
HEALTH_TIMEOUT=480

WORK_DIR=""
TEE_PID=""

log() { printf '[ci-deploy %s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

cleanup() {
    [[ -z "$WORK_DIR" ]] || rm -rf "$WORK_DIR"
    # 마지막 로그가 tee를 거쳐 클라이언트와 파일에 다 쓰이도록 출력을 닫고 tee를 기다립니다.
    if [[ -n "$TEE_PID" ]]; then
        exec 1>&- 2>&-
        wait "$TEE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# scripts/lib/selfhost.sh의 env_get과 같은 규칙: 마지막 값, 따옴표와 CR 제거, source하지 않음.
env_get() {
    local key="$1" default="${2:-}" line value
    line="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
    if [[ -z "$line" || -z "$value" ]]; then printf '%s' "$default"; else printf '%s' "$value"; fi
}

# env 파일의 IMAGE_TAG를 바꿉니다. 첫 IMAGE_TAG 줄 자리에 한 번만 쓰고 중복 줄은 지웁니다.
# /opt/theseus는 root 소유라 sed -i(같은 디렉터리에 임시 파일 생성)를 쓸 수 없어 내용만 덮어씁니다(권한·소유자 유지).
set_env_tag() {
    local file="$1" tag="$2" tmp
    tmp="$(mktemp "$STATE_DIR/env.XXXXXX")"
    awk -v t="$tag" '
        /^IMAGE_TAG=/ { if (!done) { print "IMAGE_TAG=" t; done = 1 } ; next }
        { print }
        END { if (!done) print "IMAGE_TAG=" t }
    ' "$file" >"$tmp"
    cat "$tmp" >"$file"
    rm -f "$tmp"
}

compose_with() {
    local compose_file="$1" env_file="$2"
    shift 2
    docker compose -f "$compose_file" --env-file "$env_file" "$@"
}

# 설정을 디렉터리 단위로 맞춥니다. 파일 내용을 제자리에서 덮어써서(--inplace) mysql cnf처럼
# 실행 중인 컨테이너가 bind mount한 파일도 같은 inode를 유지합니다.
sync_config() {
    local src="$1"
    mkdir -p "$APP_DIR/infra/docker/selfhost" "$APP_DIR/scripts"
    rsync -a --inplace --delete "$src/infra/docker/selfhost/" "$APP_DIR/infra/docker/selfhost/"
    rsync -a --inplace --delete "$src/scripts/" "$APP_DIR/scripts/"
}

# 배포 전 DB 덤프. API는 기동할 때 Flyway 마이그레이션을 적용하고, 마이그레이션은 이미지 롤백으로 되돌릴 수 없습니다.
# 현재(배포 전) compose로 실행하며, 비밀번호는 컨테이너 env에서 읽어 프로세스 목록에 남기지 않습니다(backup.sh와 같은 방식).
dump_databases() {
    local label="$1" compose_file="$APP_DIR/infra/docker/selfhost/docker-compose.yml" out
    out="$DUMP_DIR/$(date '+%Y%m%d-%H%M%S')-$label"
    (umask 077; mkdir -p "$out")
    if ! compose_with "$compose_file" "$ENV_FILE" ps --status running --services 2>/dev/null | grep -qx mysql; then
        log "mysql이 실행 중이 아니라 배포 전 덤프를 건너뜁니다(첫 기동)."
        rmdir "$out"
        return 0
    fi
    log "배포 전 DB 덤프: $out"
    # 호출하는 쪽이 `dump_databases || die`로 부르면 함수 안에서 set -e가 꺼지므로 단계마다 직접 확인합니다.
    # shellcheck disable=SC2016  # $MYSQL_* / $POSTGRES_*는 컨테이너 안에서 펼칩니다.
    if ! compose_with "$compose_file" "$ENV_FILE" exec -T mysql sh -c \
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --databases "$MYSQL_DATABASE"' \
        | gzip >"$out/mysql.sql.gz"; then
        log "mysqldump 실패"
        return 1
    fi
    # shellcheck disable=SC2016
    if ! compose_with "$compose_file" "$ENV_FILE" exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
        >"$out/postgres.dump"; then
        log "pg_dump 실패"
        return 1
    fi
    chmod 600 "$out"/* || return 1
    # 최근 5개만 남깁니다.
    find "$DUMP_DIR" -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n +6 | xargs -r rm -rf
}

# 구성 요소별로 최근 태그 KEEP개와 현재·이전 태그를 남기고 나머지 이미지를 지웁니다.
# 실행 중인 컨테이너가 쓰는 이미지는 docker rmi가 거부하므로 그대로 남습니다.
prune_images() {
    local keep="$1" current="$2" previous="$3" component repo tag n
    for component in "${COMPONENTS[@]}"; do
        repo="theseus-$component"
        n=0
        while read -r tag; do
            [[ -n "$tag" && "$tag" != "<none>" ]] || continue
            n=$((n + 1))
            [[ "$tag" == "$current" || "$tag" == "$previous" ]] && continue
            (( n <= keep )) && continue
            if docker rmi "$repo:$tag" >/dev/null 2>&1; then log "이미지 정리: $repo:$tag"; fi
        done < <(docker image ls "$repo" --format '{{.CreatedAt}}|{{.Tag}}' | sort -r | cut -d'|' -f2)
    done
    docker image prune -f >/dev/null 2>&1 || true
}

# 신뢰할 수 있는 원본(DEPLOY_GIT_URL)에서 sha를 받아 dev 포함 여부를 확인하고 배포 설정을 꺼냅니다.
fetch_config() {
    local sha="$1" git_url="$2" dest="$3"
    if [[ ! -d "$REPO_DIR" ]]; then
        log "저장소 최초 clone: $git_url"
        git clone --quiet --bare "$git_url" "$REPO_DIR"
    fi
    git -C "$REPO_DIR" remote set-url origin "$git_url"
    git -C "$REPO_DIR" fetch --quiet --prune origin "+refs/heads/$DEPLOY_BRANCH:refs/remotes/origin/$DEPLOY_BRANCH"
    git -C "$REPO_DIR" cat-file -e "$sha^{commit}" 2>/dev/null || die "저장소에 없는 커밋입니다: $sha"
    git -C "$REPO_DIR" merge-base --is-ancestor "$sha" "refs/remotes/origin/$DEPLOY_BRANCH" \
        || die "$DEPLOY_BRANCH 브랜치에 포함되지 않은 커밋은 배포하지 않습니다: $sha"
    mkdir -p "$dest"
    git -C "$REPO_DIR" archive --format=tar "$sha" infra/docker/selfhost scripts | tar -xf - -C "$dest" --no-same-owner
    [[ -f "$dest/infra/docker/selfhost/docker-compose.yml" && -f "$dest/scripts/deploy.sh" ]] \
        || die "커밋 $sha 에 infra/docker/selfhost/docker-compose.yml 또는 scripts/deploy.sh가 없습니다."
}

cmd_status() {
    [[ -r "$ENV_FILE" ]] || die "env 파일을 읽을 수 없습니다: $ENV_FILE"
    printf 'IMAGE_TAG=%s\n' "$(env_get IMAGE_TAG)"
    compose_with "$APP_DIR/infra/docker/selfhost/docker-compose.yml" "$ENV_FILE" ps \
        --format 'table {{.Service}}\t{{.State}}\t{{.Health}}' || true
    if [[ -f "$LOG_FILE" ]]; then
        printf '\n--- 마지막 배포 로그(끝 20줄): %s\n' "$LOG_FILE"
        tail -n 20 "$LOG_FILE"
    fi
}

cmd_deploy() {
    local sha="$1" registry_user="$2"
    local tag registry registry_host git_url sandbox_image keep_tags prev_tag prev_sandbox_id token component ref label
    local new_compose rollback_ok

    # 입력은 셸·docker 인자로 쓰므로 형식을 좁게 제한합니다.
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "커밋 SHA 형식이 잘못됐습니다(40자 16진수): $sha"
    [[ "$registry_user" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?$ ]] || die "레지스트리 사용자 형식이 잘못됐습니다: $registry_user"
    tag="${sha::7}"

    [[ -f "$ENV_FILE" && -r "$ENV_FILE" && -w "$ENV_FILE" ]] || die "env 파일을 읽고 쓸 수 없습니다: $ENV_FILE"
    registry="$(env_get DEPLOY_PULL_REGISTRY)"
    [[ -n "$registry" ]] || die "env 파일에 DEPLOY_PULL_REGISTRY가 없습니다(예: ghcr.io/<owner>/)."
    [[ "$registry" == */ ]] || registry="$registry/"
    [[ "$registry" =~ ^[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+/$ ]] || die "DEPLOY_PULL_REGISTRY 형식이 잘못됐습니다: $registry"
    registry_host="${registry%%/*}"
    git_url="$(env_get DEPLOY_GIT_URL)"
    [[ "$git_url" =~ ^https://[A-Za-z0-9.-]+/[A-Za-z0-9._/-]+$ ]] || die "env 파일의 DEPLOY_GIT_URL이 없거나 https URL이 아닙니다: ${git_url:-(없음)}"
    [[ -z "$(env_get IMAGE_REGISTRY)" ]] || die "IMAGE_REGISTRY가 비어 있어야 합니다. 자동 배포는 pull한 이미지를 로컬 이름(theseus-*)으로 retag합니다."
    sandbox_image="$(env_get SANDBOX_IMAGE "$DEFAULT_SANDBOX_IMAGE")"
    keep_tags="$(env_get DEPLOY_KEEP_TAGS 3)"
    [[ "$keep_tags" =~ ^[1-9][0-9]?$ ]] || die "DEPLOY_KEEP_TAGS는 1~99: $keep_tags"

    (umask 077; mkdir -p "$STATE_DIR")
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "다른 배포가 진행 중입니다($LOCK_FILE)."

    # 토큰은 세션과 분리하기 전에 stdin에서 읽습니다. 그 뒤 stdin은 닫습니다.
    IFS= read -r token || true
    token="${token%$'\r'}"
    [[ -n "$token" ]] || die "stdin 첫 줄에서 레지스트리 토큰을 읽지 못했습니다."
    exec </dev/null

    # SSH 세션이 끊겨도(job 취소, 시간 초과, 네트워크) 배포와 롤백이 끝까지 가도록 출력을 세션과 분리합니다.
    # 모든 출력은 tee가 받아 파일에 쓰고 클라이언트에도 보냅니다. 클라이언트 쪽이 닫히면 tee는 경고만 하고 파일 쓰기를 계속합니다.
    # SIGPIPE/SIGHUP을 무시하는 설정은 deploy.sh 같은 자식 프로세스에도 이어집니다.
    trap '' PIPE HUP
    exec 3>&2
    exec > >(tee --output-error=warn "$LOG_FILE" >&3 2>/dev/null) 2>&1
    TEE_PID=$!
    exec 3>&-
    log "배포 요청: $sha (IMAGE_TAG=$tag), 로그: $LOG_FILE"

    WORK_DIR="$(mktemp -d "$STATE_DIR/work.XXXXXX")"

    log "설정 가져오기: $git_url ($DEPLOY_BRANCH 포함 확인)"
    fetch_config "$sha" "$git_url" "$WORK_DIR/new"

    log "새 compose 설정 검증"
    new_compose="$WORK_DIR/new/infra/docker/selfhost/docker-compose.yml"
    (umask 077; cp "$ENV_FILE" "$WORK_DIR/env.check")
    set_env_tag "$WORK_DIR/env.check" "$tag"
    compose_with "$new_compose" "$WORK_DIR/env.check" config --quiet || die "새 compose 설정 검증 실패. 아무것도 바꾸지 않았습니다."
    rm -f "$WORK_DIR/env.check"

    prev_tag="$(env_get IMAGE_TAG)"
    prev_sandbox_id="$(docker image inspect --format '{{.Id}}' "$sandbox_image" 2>/dev/null || true)"
    log "현재 IMAGE_TAG=${prev_tag:-없음} -> $tag"

    # 레지스트리 로그인 정보는 작업 디렉터리 안의 임시 DOCKER_CONFIG에만 두고, 끝나면 디렉터리째 지웁니다.
    log "레지스트리 로그인: $registry_host"
    export DOCKER_CONFIG="$WORK_DIR/docker"
    (umask 077; mkdir -p "$DOCKER_CONFIG")
    printf '%s' "$token" | docker login "$registry_host" -u "$registry_user" --password-stdin >/dev/null \
        || die "레지스트리 로그인 실패: $registry_host"
    unset token
    for component in "${COMPONENTS[@]}" sandbox; do
        ref="${registry}theseus-$component:$tag"
        log "pull: $ref"
        docker pull --quiet "$ref" >/dev/null || die "이미지를 받지 못했습니다: $ref"
        label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$ref")"
        [[ "$label" == "$sha" ]] || die "이미지 라벨이 요청한 커밋과 다릅니다: $ref (revision=$label)"
    done
    docker logout "$registry_host" >/dev/null 2>&1 || true
    unset DOCKER_CONFIG
    rm -rf "$WORK_DIR/docker"

    # compose는 로컬 이름(theseus-*:<tag>)을 씁니다. sandbox 이름은 실행 중인 Core가 바로 쓰므로 반영 직전에 바꿉니다.
    for component in "${COMPONENTS[@]}"; do
        docker tag "${registry}theseus-$component:$tag" "theseus-$component:$tag"
    done

    dump_databases "before-$tag" || die "배포 전 DB 덤프 실패. 아무것도 바꾸지 않았습니다."

    # 이전 설정은 작업 디렉터리 밖에 둡니다. 배포가 중간에 끊겨도 수동 복구에 쓸 수 있습니다.
    log "이전 설정 백업: $PREV_CONFIG_DIR"
    rm -rf "$PREV_CONFIG_DIR"
    mkdir -p "$PREV_CONFIG_DIR/infra/docker/selfhost" "$PREV_CONFIG_DIR/scripts"
    rsync -a "$APP_DIR/infra/docker/selfhost/" "$PREV_CONFIG_DIR/infra/docker/selfhost/" 2>/dev/null || true
    rsync -a "$APP_DIR/scripts/" "$PREV_CONFIG_DIR/scripts/" 2>/dev/null || true
    printf '%s\n' "$prev_tag" >"$PREV_CONFIG_DIR/IMAGE_TAG"

    log "설정 반영, IMAGE_TAG=$tag"
    docker tag "${registry}theseus-sandbox:$tag" "$sandbox_image"
    for component in "${COMPONENTS[@]}" sandbox; do
        docker rmi "${registry}theseus-$component:$tag" >/dev/null 2>&1 || true
    done
    sync_config "$WORK_DIR/new"
    set_env_tag "$ENV_FILE" "$tag"

    if "$APP_DIR/scripts/deploy.sh" --env-file "$ENV_FILE" --timeout "$HEALTH_TIMEOUT"; then
        log "배포 성공: IMAGE_TAG=$tag"
        prune_images "$keep_tags" "$tag" "$prev_tag"
        return 0
    fi

    # 롤백은 단계 하나가 실패해도 나머지를 끝까지 시도합니다(set -e로 중간에 멈추지 않게 각 단계를 감쌉니다).
    log "배포 실패. 이전 상태로 롤백합니다(IMAGE_TAG=${prev_tag:-없음})."
    if [[ -z "$prev_tag" || ! -f "$PREV_CONFIG_DIR/scripts/deploy.sh" ]]; then
        die "이전 IMAGE_TAG 또는 설정 백업이 없어 롤백하지 않았습니다(현재 IMAGE_TAG=$tag)."
    fi
    rollback_ok=false
    sync_config "$PREV_CONFIG_DIR" || log "경고: 이전 설정 복원 실패"
    set_env_tag "$ENV_FILE" "$prev_tag" || log "경고: IMAGE_TAG 복원 실패"
    if [[ -n "$prev_sandbox_id" ]]; then
        docker tag "$prev_sandbox_id" "$sandbox_image" || log "경고: sandbox 이미지 복원 실패"
    fi
    if "$APP_DIR/scripts/deploy.sh" --env-file "$ENV_FILE" --timeout "$HEALTH_TIMEOUT"; then
        rollback_ok=true
    fi
    if [[ "$rollback_ok" == true ]]; then
        die "배포에 실패해 IMAGE_TAG=$prev_tag 로 롤백했습니다. DB 마이그레이션이 적용됐다면 $DUMP_DIR 의 덤프를 확인하세요."
    fi
    die "배포와 롤백 모두 실패했습니다. 서버에서 직접 확인이 필요합니다(이전 설정: $PREV_CONFIG_DIR, DB 덤프: $DUMP_DIR)."
}

main() {
    local -a args=()
    # 공백으로만 나눕니다(glob 확장 없음). 따옴표나 메타 문자는 형식 검사에서 걸러집니다.
    read -r -a args <<<"${SSH_ORIGINAL_COMMAND:-}" || true
    case "${args[0]:-}" in
        deploy)
            [[ ${#args[@]} -eq 3 ]] || die "사용법: deploy <커밋 SHA 40자> <레지스트리 사용자>"
            cmd_deploy "${args[1]}" "${args[2]}" ;;
        status)
            [[ ${#args[@]} -eq 1 ]] || die "사용법: status"
            cmd_status ;;
        *)
            die "허용되지 않은 명령입니다: ${SSH_ORIGINAL_COMMAND:-(없음)} (deploy, status만 허용)" ;;
    esac
}

main
