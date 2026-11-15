#!/usr/bin/env bash
# 셀프호스팅에 필요한 비밀값을 새로 만듭니다(openssl).
# 기본은 KEY=VALUE를 출력만 하고, --fill FILE이면 env 파일에서 비어 있는 키만 채웁니다.
# 이미 값이 있는 키는 덮어쓰지 않습니다. DB 비밀번호를 바꾸면 기존 볼륨과 맞지 않게 되기 때문입니다.
set -euo pipefail

usage() {
    cat <<'EOF'
사용법: scripts/gen-secrets.sh [--fill FILE]

  (옵션 없음)   새 비밀값을 KEY=VALUE 형식으로 출력합니다
  --fill FILE   FILE에서 값이 비어 있거나 없는 키만 새 값으로 채우고 권한을 600으로 맞춥니다
  -h, --help    도움말

생성하는 키: JWT_SECRET, INTERNAL_API_KEY, MYSQL_ROOT_PASSWORD, MYSQL_PASSWORD,
            POSTGRES_PASSWORD, REDIS_PASSWORD, KAFKA_CLUSTER_ID
EOF
}

SECRET_KEYS=(JWT_SECRET INTERNAL_API_KEY MYSQL_ROOT_PASSWORD MYSQL_PASSWORD POSTGRES_PASSWORD REDIS_PASSWORD KAFKA_CLUSTER_ID)

# 비밀번호는 hex로 만들어 JDBC URL, redis 명령행, 셸 어디에 넣어도 이스케이프가 필요 없게 합니다.
generate() {
    case "$1" in
        # HMAC-SHA 키는 32바이트 이상이어야 합니다. 48바이트를 base64로 씁니다.
        JWT_SECRET) openssl rand -base64 48 | tr -d '\n' ;;
        INTERNAL_API_KEY) openssl rand -hex 32 ;;
        # KRaft 클러스터 ID는 16바이트 UUID의 base64url(패딩 없음, 22자)입니다.
        KAFKA_CLUSTER_ID) openssl rand 16 | openssl base64 -A | tr '+/' '-_' | tr -d '=' ;;
        *) openssl rand -hex 24 ;;
    esac
}

fill=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fill) fill="${2:?--fill 파일 경로가 필요합니다}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; echo "알 수 없는 인자: $1" >&2; exit 1 ;;
    esac
done

command -v openssl >/dev/null 2>&1 || { echo "openssl이 필요합니다." >&2; exit 1; }

if [[ -z "$fill" ]]; then
    for key in "${SECRET_KEYS[@]}"; do
        printf '%s=%s\n' "$key" "$(generate "$key")"
    done
    exit 0
fi

[[ -f "$fill" ]] || { echo "파일이 없습니다: $fill" >&2; exit 1; }
umask 077
# 작업 사본은 env 파일 옆이 아니라 임시 디렉터리에 둡니다. env 파일이 있는 디렉터리(/opt/theseus)는 root 소유라
# 배포 사용자가 새 파일을 만들 수 없습니다. 결과는 원본에 내용만 덮어쓰므로 같은 파일 시스템일 필요가 없습니다.
tmp="$(mktemp)"
trap 'rm -f "$tmp" "$tmp.new"' EXIT
cp "$fill" "$tmp"
# Windows에서 체크아웃·편집한 파일은 줄 끝에 CR이 남습니다. 'KEY=\r'을 값이 있는 것으로 오인하지 않도록 지웁니다.
sed -i 's/\r$//' "$tmp"

for key in "${SECRET_KEYS[@]}"; do
    if grep -qE "^${key}=[^[:space:]]" "$tmp"; then
        echo "유지: $key" >&2
        continue
    fi
    value="$(generate "$key")"
    if grep -qE "^${key}=" "$tmp"; then
        # 빈 'KEY=' 줄을 제자리에서 바꿔 템플릿의 순서와 주석을 유지합니다.
        awk -v k="$key" -v v="$value" 'index($0, k "=") == 1 && !done { print k "=" v; done = 1; next } { print }' "$tmp" >"${tmp}.new"
        mv "${tmp}.new" "$tmp"
    else
        printf '%s=%s\n' "$key" "$value" >>"$tmp"
    fi
    echo "생성: $key" >&2
done

# 원본 파일의 소유자를 유지하려고 내용만 덮어씁니다.
# cp 직후의 env 파일은 0644일 수 있으므로 비밀값을 쓰기 전에 권한부터 줄이고, 줄이지 못하면 쓰지 않습니다.
chmod 600 "$fill" || { echo "권한을 600으로 바꿀 수 없어 비밀값을 쓰지 않았습니다: $fill" >&2; exit 1; }
perm="$(stat -c '%a' "$fill" 2>/dev/null || echo 600)"
[[ "$perm" == "600" ]] || { echo "권한이 600이 아니어서($perm) 비밀값을 쓰지 않았습니다: $fill" >&2; exit 1; }
cat "$tmp" >"$fill"
echo "완료: $fill (권한 600)" >&2
