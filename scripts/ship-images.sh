#!/usr/bin/env bash
# 노트북에서 빌드한 이미지를 SSH로 서버에 옮깁니다: docker save | gzip | ssh <host> docker load
# 레지스트리 없이 배포하는 방식이라 서버는 이미지를 빌드하거나 pull하지 않습니다.
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=lib/selfhost.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/selfhost.sh"

usage() {
    cat <<'EOF'
사용법: scripts/ship-images.sh [옵션] <ssh-host> [TAG]

  ssh-host            ~/.ssh/config의 서버 별칭(또는 user@host). 환경변수 THESEUS_SSH_HOST로도 줄 수 있습니다
  TAG                 보낼 이미지 태그(기본: git short sha, scripts/build-images.sh와 같은 규칙)
  --only LIST         쉼표로 구분한 구성 요소만 전송(api,core,frontend,nginx,sandbox)
  --registry PREFIX   빌드할 때 쓴 레지스트리 접두사
  --sandbox-image REF sandbox 이미지 이름(기본: theseus-sandbox:py311-tools)
  --with-config       infra/docker/selfhost와 scripts도 서버의 --remote-dir에 복사
  --remote-dir DIR    설정 복사 위치(기본: /opt/theseus/app)
  -h, --help          도움말

서버 SSH 사용자는 docker 그룹에 속해 있어야 합니다(server-bootstrap.sh가 추가합니다).
EOF
}

host="${THESEUS_SSH_HOST:-}"
tag=""
only=""
registry="${IMAGE_REGISTRY:-}"
sandbox_image="${SANDBOX_IMAGE:-$DEFAULT_SANDBOX_IMAGE}"
with_config=false
remote_dir="/opt/theseus/app"
gzip_level="${GZIP_LEVEL:-3}"
positional=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --only) only="${2:?--only 값이 필요합니다}"; shift 2 ;;
        --registry) registry="${2:?--registry 값이 필요합니다}"; shift 2 ;;
        --sandbox-image) sandbox_image="${2:?--sandbox-image 값이 필요합니다}"; shift 2 ;;
        --with-config) with_config=true; shift ;;
        --remote-dir) remote_dir="${2:?--remote-dir 값이 필요합니다}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) usage; die "알 수 없는 옵션: $1" ;;
        *) positional+=("$1"); shift ;;
    esac
done

if [[ ${#positional[@]} -ge 1 ]]; then host="${positional[0]}"; fi
if [[ ${#positional[@]} -ge 2 ]]; then tag="${positional[1]}"; fi
[[ ${#positional[@]} -le 2 ]] || { usage; die "인자가 너무 많습니다."; }
[[ -n "$host" ]] || { usage; die "ssh-host가 필요합니다."; }

require_cmd docker ssh gzip
[[ -n "$tag" ]] || tag="$(default_image_tag)"
mapfile -t components < <(parse_components "$only")

images=()
for component in "${components[@]}"; do
    ref="$(image_ref "$component" "$registry" "$tag" "$sandbox_image")"
    docker image inspect "$ref" >/dev/null 2>&1 || die "로컬에 이미지가 없습니다: $ref (scripts/build-images.sh 먼저 실행)"
    images+=("$ref")
done

# 몇 분 걸리는 전송을 시작하기 전에 서버 준비 상태를 확인합니다(server-bootstrap.sh 실행과 재로그인 여부).
log "서버 확인: $host"
ssh "$host" 'docker info >/dev/null 2>&1' \
    || die "서버 사용자가 docker를 쓸 수 없습니다. 서버에서 server-bootstrap.sh를 먼저 실행하고(sudo) SSH로 다시 로그인하세요."
if [[ "$with_config" == true ]]; then
    remote_dir_q="$(printf '%q' "$remote_dir")"
    # 경로를 클라이언트에서 %q로 인용해 원격 셸 명령에 넣는 것이 의도입니다.
    # shellcheck disable=SC2029
    ssh "$host" "mkdir -p $remote_dir_q 2>/dev/null && test -w $remote_dir_q" \
        || die "서버의 $remote_dir 에 쓸 수 없습니다. server-bootstrap.sh가 배포 사용자 소유로 만듭니다(--owner 확인)."
fi

log "전송 대상: ${images[*]}"
log "서버: $host (gzip -$gzip_level). core 이미지가 커서 몇 분 걸릴 수 있습니다."
docker save "${images[@]}" | gzip "-$gzip_level" | ssh "$host" 'gunzip | docker load'

if [[ "$with_config" == true ]]; then
    require_cmd tar
    log "설정 복사: infra/docker/selfhost, scripts -> $host:$remote_dir"
    # 경로를 클라이언트에서 %q로 인용해 원격 셸 명령에 넣는 것이 의도입니다.
    # shellcheck disable=SC2029
    tar -C "$THESEUS_REPO_ROOT" -czf - infra/docker/selfhost scripts \
        | ssh "$host" "mkdir -p $remote_dir_q && tar -xzf - -C $remote_dir_q && chmod +x $remote_dir_q/scripts/*.sh"
fi

log "완료. 서버 env의 IMAGE_TAG=$tag 로 맞춘 뒤 scripts/deploy.sh를 실행하세요."
