# Theseus 엣지 nginx 이미지입니다. 개발 노트북에서 빌드해 서버로 옮깁니다(scripts/build-images.sh).
# 도메인은 이미지에 넣지 않고 기동 시 DOMAIN env로 템플릿을 렌더링하므로, 한 이미지를 어느 도메인에도 씁니다.
FROM nginx:1.31.9-alpine

# envsubst는 DOMAIN, HSTS_MAX_AGE만 치환합니다. 나머지 $host 같은 nginx 변수는 그대로 둡니다.
ENV NGINX_ENVSUBST_FILTER='^(DOMAIN|HSTS_MAX_AGE)$' \
    HSTS_MAX_AGE=31536000 \
    NGINX_TLS_MODE=auto

RUN rm -f /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf
COPY snippets/ /etc/nginx/snippets/
COPY templates/ /etc/nginx/theseus-templates/
COPY docker-entrypoint.d/ /docker-entrypoint.d/

# Windows 작업 트리(autocrlf)에서 빌드해도 셸 스크립트가 깨지지 않도록 CR을 제거합니다.
RUN sed -i 's/\r$//' /docker-entrypoint.d/18-theseus-tls-mode.envsh /docker-entrypoint.d/40-theseus-reload-loop.sh \
    && chmod 0755 /docker-entrypoint.d/18-theseus-tls-mode.envsh /docker-entrypoint.d/40-theseus-reload-loop.sh

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
