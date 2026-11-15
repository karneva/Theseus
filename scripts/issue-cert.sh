#!/usr/bin/env bash
# Let's Encrypt 인증서를 처음 발급하고 nginx를 HTTPS 템플릿으로 전환합니다.
# nginx가 HTTP 템플릿으로 떠 있어야 합니다(인증서가 없으면 자동으로 HTTP 템플릿). 발급은 webroot 방식이고,
# 이후 갱신은 certbot 컨테이너의 renew 루프가 자동으로 합니다.
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=lib/selfhost.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/selfhost.sh"

usage() {
    cat <<'EOF'
사용법: scripts/issue-cert.sh [옵션]

  --env-file FILE   env 파일(기본: /opt/theseus/theseus.env). DOMAIN, CERTBOT_EMAIL을 읽습니다
  --staging         Let's Encrypt staging 서버로 연습 발급(발급 횟수 제한 회피)
  --force           기존 인증서가 있어도 다시 발급(staging에서 실제 인증서로 바꿀 때)
  -h, --help        도움말
EOF
}

extra=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file) THESEUS_ENV_FILE="${2:?--env-file 값이 필요합니다}"; shift 2 ;;
        --staging) extra+=(--staging); shift ;;
        --force) extra+=(--force-renewal); shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "알 수 없는 인자: $1" ;;
    esac
done

require_cmd docker
require_env_file

domain="$(env_get "$THESEUS_ENV_FILE" DOMAIN)"
email="$(env_get "$THESEUS_ENV_FILE" CERTBOT_EMAIL)"
[[ -n "$domain" ]] || die "env 파일에 DOMAIN이 없습니다."
[[ -n "$email" ]] || die "env 파일에 CERTBOT_EMAIL이 없습니다."

if [[ -z "$(compose ps --status running -q nginx)" ]]; then
    die "nginx가 실행 중이 아닙니다. scripts/deploy.sh로 먼저 기동하세요."
fi

log "인증서 발급: $domain"
compose run --rm --no-deps --entrypoint certbot certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$domain" -m "$email" \
    --agree-tos --no-eff-email --non-interactive \
    "${extra[@]}"

# 기동 시 인증서 유무로 템플릿을 고르므로 재시작해야 HTTPS 템플릿이 적용됩니다.
log "nginx 재시작(HTTPS 템플릿 적용)"
compose restart nginx
compose logs --tail=20 nginx | grep -E 'TLS mode|emerg|error' || true
log "완료. https://$domain 으로 접속해 확인하세요."
