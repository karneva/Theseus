#!/usr/bin/env bash
# 노트북의 Ollama(127.0.0.1:11434)를 서버의 docker0 IP(기본 172.17.0.1:11434)로 여는 reverse SSH tunnel입니다.
# 서버 Core 컨테이너는 http://host.docker.internal:11434/v1 로 이 터널을 통해 모델을 호출합니다.
# 서버 쪽 sshd 설정(GatewayPorts clientspecified, PermitListen)은 server-bootstrap.sh가 합니다.
# 연결이 끊기면 잠시 후 다시 연결합니다(--once로 끌 수 있음).
set -euo pipefail

usage() {
    cat <<'EOF'
사용법: scripts/llm-tunnel.sh [옵션] <ssh-host>

  ssh-host            ~/.ssh/config의 서버 별칭(또는 user@host). 환경변수 THESEUS_SSH_HOST로도 줄 수 있습니다
  --bind ADDR         서버 쪽 바인딩 주소(기본: 172.17.0.1, 서버 docker0 IP)
  --remote-port PORT  서버 쪽 포트(기본: 11434)
  --local-port PORT   노트북 Ollama 포트(기본: 11434)
  --once              끊겨도 다시 연결하지 않음
  -h, --help          도움말
EOF
}

host="${THESEUS_SSH_HOST:-}"
bind_addr="172.17.0.1"
remote_port="11434"
local_port="11434"
once=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bind) bind_addr="${2:?}"; shift 2 ;;
        --remote-port) remote_port="${2:?}"; shift 2 ;;
        --local-port) local_port="${2:?}"; shift 2 ;;
        --once) once=true; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) usage; echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
        *) host="$1"; shift ;;
    esac
done

[[ -n "$host" ]] || { usage; exit 1; }
command -v ssh >/dev/null 2>&1 || { echo "ssh가 필요합니다." >&2; exit 1; }

# 노트북 Ollama가 떠 있는지 미리 확인합니다(실패해도 터널은 엽니다).
if command -v curl >/dev/null 2>&1 && ! curl -fsS -m 3 "http://127.0.0.1:${local_port}/api/tags" >/dev/null 2>&1; then
    echo "경고: 127.0.0.1:${local_port}에서 Ollama 응답이 없습니다. 'ollama serve'가 실행 중인지 확인하세요." >&2
fi

trap 'echo; echo "터널 종료" >&2; exit 0' INT TERM

while :; do
    echo "[$(date '+%H:%M:%S')] 터널 연결: ${host} ${bind_addr}:${remote_port} -> 127.0.0.1:${local_port}" >&2
    # ExitOnForwardFailure: 서버에서 포트를 못 열면(이전 세션이 남아 있음 등) 바로 실패해 재시도하게 합니다.
    # ServerAlive*: 네트워크가 끊긴 것을 90초 안에 감지합니다.
    ssh -N \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -R "${bind_addr}:${remote_port}:127.0.0.1:${local_port}" \
        "$host" || true
    [[ "$once" == false ]] || break
    echo "[$(date '+%H:%M:%S')] 연결이 끊겼습니다. 5초 후 다시 연결합니다(Ctrl+C로 종료)." >&2
    sleep 5
done
