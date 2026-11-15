#!/bin/sh
# certbot 컨테이너가 갱신한 인증서를 반영하려고 nginx를 주기적으로 reload합니다.
# reload는 무중단이고, 인증서가 바뀌지 않았으면 아무 영향이 없습니다.
set -eu

interval="${NGINX_RELOAD_INTERVAL:-6h}"

(
    while sleep "$interval"; do
        nginx -s reload || true
    done
) >/dev/null 2>&1 &

echo "40-theseus-reload-loop: nginx reload every ${interval}"
