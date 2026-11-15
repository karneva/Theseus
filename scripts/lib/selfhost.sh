# shellcheck shell=bash
# 셀프호스팅 스크립트 공통 함수입니다. 각 스크립트가 source합니다(단독 실행 X).
#
# 기본 경로(환경변수로 바꿀 수 있습니다)
#   THESEUS_ENV_FILE       서버 env 파일(기본 /opt/theseus/theseus.env)
#   SELFHOST_COMPOSE_FILE  compose 파일(기본 <저장소>/infra/docker/selfhost/docker-compose.yml)

THESEUS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SELFHOST_COMPOSE_FILE="${SELFHOST_COMPOSE_FILE:-$THESEUS_REPO_ROOT/infra/docker/selfhost/docker-compose.yml}"
THESEUS_ENV_FILE="${THESEUS_ENV_FILE:-/opt/theseus/theseus.env}"

# 빌드·전송·배포가 같은 목록을 쓰도록 이미지 구성 요소를 한 곳에 둡니다.
THESEUS_APP_COMPONENTS=(api core frontend nginx)
DEFAULT_SANDBOX_IMAGE="theseus-sandbox:py311-tools"

log() {
    printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2
}

die() {
    log "ERROR: $*"
    exit 1
}

require_cmd() {
    local cmd
    for cmd in "$@"; do
        command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' 명령이 필요합니다."
    done
}

# env 파일에서 KEY의 마지막 값을 읽습니다. source하지 않으므로 값에 $나 공백이 있어도 실행되지 않습니다.
# 앞뒤 따옴표와 CR(Windows에서 편집한 파일)을 벗겨 냅니다.
env_get() {
    local file="$1" key="$2" default="${3:-}" line value
    line="$(grep -E "^${key}=" "$file" 2>/dev/null | tail -n 1 || true)"
    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
    if [[ -z "$line" || -z "$value" ]]; then
        printf '%s' "$default"
    else
        printf '%s' "$value"
    fi
}

require_env_file() {
    [[ -f "$THESEUS_ENV_FILE" ]] || die "env 파일이 없습니다: $THESEUS_ENV_FILE (infra/docker/selfhost/.env.example을 복사하세요)"
    # 읽지 못하면 env_get이 빈 값을 돌려 'IMAGE_TAG가 없습니다' 같은 엉뚱한 오류가 나므로 먼저 알려 줍니다.
    [[ -r "$THESEUS_ENV_FILE" ]] || die "env 파일을 읽을 수 없습니다: $THESEUS_ENV_FILE ($(id -un) 사용자). 소유자를 배포 사용자로 바꾸세요(sudo chown $(id -un) $THESEUS_ENV_FILE)."
}

# 셀프호스팅 compose를 env 파일과 함께 실행합니다.
compose() {
    docker compose -f "$SELFHOST_COMPOSE_FILE" --env-file "$THESEUS_ENV_FILE" "$@"
}

# 구성 요소 이름(api, core, frontend, nginx, sandbox)을 이미지 이름으로 바꿉니다.
# sandbox는 Core가 SANDBOX_IMAGE 이름 그대로 찾으므로 레지스트리 접두사와 태그를 붙이지 않습니다.
image_ref() {
    local component="$1" registry="$2" tag="$3" sandbox_image="${4:-$DEFAULT_SANDBOX_IMAGE}"
    if [[ "$component" == "sandbox" ]]; then
        printf '%s' "$sandbox_image"
    else
        printf '%stheseus-%s:%s' "$registry" "$component" "$tag"
    fi
}

# 쉼표로 구분한 --only 값을 검증해 구성 요소 배열로 펼칩니다. 비어 있으면 전체 목록입니다.
parse_components() {
    local only="$1" item
    local -a items
    local -a all=("${THESEUS_APP_COMPONENTS[@]}" sandbox)
    if [[ -z "$only" ]]; then
        printf '%s\n' "${all[@]}"
        return
    fi
    IFS=',' read -r -a items <<<"$only"
    for item in "${items[@]}"; do
        case " ${all[*]} " in
            *" $item "*) printf '%s\n' "$item" ;;
            *) die "알 수 없는 구성 요소: $item (가능: ${all[*]})" ;;
        esac
    done
}

# 기본 이미지 태그: git short sha. 커밋되지 않은 변경이 있으면 -dirty를 붙여 재현 불가능한 빌드임을 표시합니다.
default_image_tag() {
    local sha
    sha="$(git -C "$THESEUS_REPO_ROOT" rev-parse --short HEAD 2>/dev/null)" || die "git 저장소가 아닙니다. 태그를 직접 지정하세요."
    if [[ -n "$(git -C "$THESEUS_REPO_ROOT" status --porcelain 2>/dev/null)" ]]; then
        sha="${sha}-dirty"
    fi
    printf '%s' "$sha"
}
