#!/usr/bin/env bash
# 서버에서 셀프호스팅 스택을 기동하거나 갱신합니다.
# 흐름: 이미지 존재 확인 -> compose config 검증 -> up -d(빌드 없음) -> 모든 서비스가 healthy가 될 때까지 대기 -> 상태 출력
# 앱 이미지는 ship-images.sh로 미리 받아 둬야 합니다. 서드파티 이미지(mysql 등)는 없을 때만 pull합니다.
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=lib/selfhost.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/selfhost.sh"

usage() {
    cat <<'EOF'
사용법: scripts/deploy.sh [옵션] [서비스...]

  서비스              일부 서비스만 기동/갱신(기본: 전체)
  --env-file FILE     env 파일(기본: /opt/theseus/theseus.env, 환경변수 THESEUS_ENV_FILE)
  --timeout SEC       healthy 대기 시간(기본: 900)
  -h, --help          도움말
EOF
}

timeout_sec=900
services=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file) THESEUS_ENV_FILE="${2:?--env-file 값이 필요합니다}"; shift 2 ;;
        --timeout) timeout_sec="${2:?--timeout 값이 필요합니다}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) usage; die "알 수 없는 옵션: $1" ;;
        *) services+=("$1"); shift ;;
    esac
done

require_cmd docker
require_env_file

# env 파일에는 비밀값이 있으므로 다른 사용자가 읽을 수 없어야 합니다.
perm="$(stat -c '%a' "$THESEUS_ENV_FILE" 2>/dev/null || echo '')"
if [[ -n "$perm" && "$perm" != "600" && "$perm" != "400" ]]; then
    log "경고: $THESEUS_ENV_FILE 권한이 $perm 입니다. chmod 600을 권장합니다."
fi

tag="$(env_get "$THESEUS_ENV_FILE" IMAGE_TAG)"
registry="$(env_get "$THESEUS_ENV_FILE" IMAGE_REGISTRY)"
sandbox_image="$(env_get "$THESEUS_ENV_FILE" SANDBOX_IMAGE "$DEFAULT_SANDBOX_IMAGE")"
[[ -n "$tag" ]] || die "env 파일에 IMAGE_TAG가 없습니다."

# 서버는 앱 이미지를 빌드하지 않습니다. 없으면 pull을 시도하다 실패하므로 미리 명확하게 알려 줍니다.
missing=()
for component in "${THESEUS_APP_COMPONENTS[@]}" sandbox; do
    ref="$(image_ref "$component" "$registry" "$tag" "$sandbox_image")"
    docker image inspect "$ref" >/dev/null 2>&1 || missing+=("$ref")
done
if [[ ${#missing[@]} -gt 0 && -z "$registry" ]]; then
    die "서버에 없는 이미지: ${missing[*]} (노트북에서 scripts/ship-images.sh <host> $tag 실행)"
fi

log "compose 설정 검증"
compose config --quiet

log "기동: ${services[*]:-전체} (IMAGE_TAG=$tag)"
compose up -d --no-build --pull missing --remove-orphans "${services[@]}"

# 일회성 서비스는 exit 0이면 정상이고, 상시 서비스는 running이면서 healthcheck가 있으면 healthy여야 합니다.
log "healthy 대기(최대 ${timeout_sec}초)"
deadline=$((SECONDS + timeout_sec))
while :; do
    pending=()
    failed=()
    while IFS='|' read -r svc state health exit_code; do
        [[ -n "$svc" ]] || continue
        case "$state" in
            exited)
                [[ "$exit_code" == "0" ]] || failed+=("$svc(exit $exit_code)") ;;
            running)
                case "$health" in
                    ""|healthy) ;;
                    unhealthy) pending+=("$svc(unhealthy)") ;;
                    *) pending+=("$svc($health)") ;;
                esac ;;
            *) pending+=("$svc($state)") ;;
        esac
    done < <(compose ps -a --format '{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}')

    if [[ ${#failed[@]} -gt 0 ]]; then
        compose ps -a
        die "실패한 서비스: ${failed[*]} (compose logs <서비스>로 확인)"
    fi
    if [[ ${#pending[@]} -eq 0 ]]; then
        break
    fi
    if (( SECONDS >= deadline )); then
        compose ps -a
        die "시간 초과. 아직 준비되지 않은 서비스: ${pending[*]}"
    fi
    log "대기 중: ${pending[*]}"
    sleep 10
done

compose ps
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' | grep -E 'NAME|theseus-' || true
log "배포 완료 (IMAGE_TAG=$tag)"
