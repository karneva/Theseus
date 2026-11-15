#!/usr/bin/env bash
# 개발 노트북에서 셀프호스팅 이미지(api, core, frontend, nginx, sandbox)를 빌드합니다.
# 서버는 빌드하지 않고 이 이미지를 받아서(scripts/ship-images.sh) 실행만 합니다.
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=lib/selfhost.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/selfhost.sh"

usage() {
    cat <<'EOF'
사용법: scripts/build-images.sh [옵션] [TAG]

  TAG                  이미지 태그(기본: git short sha, 변경이 있으면 <sha>-dirty)
  --only LIST          쉼표로 구분한 구성 요소만 빌드(api,core,frontend,nginx,sandbox)
  --platform PLATFORM  대상 플랫폼(기본: linux/amd64, 환경변수 BUILD_PLATFORM)
  --registry PREFIX    이미지 이름 앞에 붙일 레지스트리(예: registry.example.com/theseus/)
  --sandbox-image REF  sandbox 이미지 이름(기본: theseus-sandbox:py311-tools)
  -h, --help           도움말

예:
  scripts/build-images.sh
  scripts/build-images.sh --only api,frontend 2026-11-15
EOF
}

tag=""
only=""
platform="${BUILD_PLATFORM:-linux/amd64}"
registry="${IMAGE_REGISTRY:-}"
sandbox_image="${SANDBOX_IMAGE:-$DEFAULT_SANDBOX_IMAGE}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --only) only="${2:?--only 값이 필요합니다}"; shift 2 ;;
        --platform) platform="${2:?--platform 값이 필요합니다}"; shift 2 ;;
        --registry) registry="${2:?--registry 값이 필요합니다}"; shift 2 ;;
        --sandbox-image) sandbox_image="${2:?--sandbox-image 값이 필요합니다}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) usage; die "알 수 없는 옵션: $1" ;;
        *) [[ -z "$tag" ]] || die "TAG는 하나만 지정합니다."; tag="$1"; shift ;;
    esac
done

require_cmd docker git
[[ -n "$tag" ]] || tag="$(default_image_tag)"
mapfile -t components < <(parse_components "$only")

# BuildKit은 API Dockerfile의 RUN --mount=type=cache에 필요합니다.
export DOCKER_BUILDKIT=1

build() {
    local ref="$1" context="$2"
    shift 2
    log "빌드: $ref ($platform)"
    docker build --platform "$platform" -t "$ref" "$@" "$context"
}

for component in "${components[@]}"; do
    ref="$(image_ref "$component" "$registry" "$tag" "$sandbox_image")"
    case "$component" in
        api)
            build "$ref" "$THESEUS_REPO_ROOT/backend/theseus-api-server" ;;
        core)
            build "$ref" "$THESEUS_REPO_ROOT/backend/theseus-core-server" ;;
        frontend)
            # 비우면 same-origin(/api)으로 호출하므로 한 이미지를 어느 도메인에도 씁니다.
            build "$ref" "$THESEUS_REPO_ROOT/frontend" --build-arg VITE_API_BASE_URL= ;;
        nginx)
            build "$ref" "$THESEUS_REPO_ROOT/infra/docker/selfhost/nginx" ;;
        sandbox)
            build "$ref" "$THESEUS_REPO_ROOT/backend/theseus-core-server" \
                -f "$THESEUS_REPO_ROOT/backend/theseus-core-server/Dockerfile.sandbox" ;;
    esac
done

log "완료. 서버 env의 IMAGE_TAG=$tag"
for component in "${components[@]}"; do
    docker image ls --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' "$(image_ref "$component" "$registry" "$tag" "$sandbox_image")"
done
printf '%s\n' "$tag"
