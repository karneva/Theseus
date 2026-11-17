#!/usr/bin/env bash
# 셀프호스팅 서버를 한 번 준비합니다(Ubuntu 24.04, Docker와 compose 플러그인 설치 완료 가정). 여러 번 실행해도 안전합니다.
#   1) 스왑 파일(기본 4G)과 vm.swappiness
#   2) /opt/theseus 아래 bind 디렉터리와 소유권(Core uid/gid 999)
#   3) docker.sock 그룹 ID 기록, 배포 사용자를 docker 그룹에 추가
#   4) ufw: SSH, 80, 443 허용 + 컨테이너 -> 호스트 LLM 터널 포트 허용
#   5) sshd: 노트북 Ollama reverse tunnel을 docker0 IP에 바인딩할 수 있게 설정
# --only-ci-deploy: 위 단계는 건너뛰고 GitHub Actions 자동 배포용 forced command 스크립트만 설치합니다.
set -euo pipefail

usage() {
    cat <<'EOF'
사용법: sudo scripts/server-bootstrap.sh [옵션]

  --root DIR          데이터 루트(기본: /opt/theseus)
  --owner USER        /opt/theseus/app 소유자이자 docker 그룹에 넣을 사용자(기본: sudo를 실행한 사용자)
  --swap-size SIZE    스왑 파일 크기(기본: 4G). 이미 스왑이 있으면 만들지 않습니다
  --swappiness N      vm.swappiness(기본: 10)
  --ssh-port PORT     ufw에서 추가로 허용할 SSH 포트. sshd가 실제로 듣는 포트(sshd -T, ssh.socket)는 항상 허용합니다
  --llm-port PORT     LLM 터널 포트(기본: 11434)
  --no-ufw            ufw 설정을 건너뜁니다
  --no-llm-tunnel     sshd/ufw의 LLM 터널 설정을 건너뜁니다
  --only-ci-deploy    다른 단계 없이 GitHub Actions 자동 배포용 scripts/ci-deploy.sh만 <root>/bin에 설치·갱신
  -h, --help          도움말
EOF
}

log() { printf '[bootstrap] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

root_dir="/opt/theseus"
owner="${SUDO_USER:-}"
swap_size="4G"
swappiness="10"
ssh_port=""
llm_port="11434"
setup_ufw=true
setup_tunnel=true
only_ci_deploy=false
# Core 이미지의 appuser uid/gid입니다(backend/theseus-core-server/Dockerfile의 APP_UID/APP_GID).
core_uid=999
core_gid=999

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root) root_dir="${2:?}"; shift 2 ;;
        --owner) owner="${2:?}"; shift 2 ;;
        --swap-size) swap_size="${2:?}"; shift 2 ;;
        --swappiness) swappiness="${2:?}"; shift 2 ;;
        --ssh-port) ssh_port="${2:?}"; shift 2 ;;
        --llm-port) llm_port="${2:?}"; shift 2 ;;
        --no-ufw) setup_ufw=false; shift ;;
        --no-llm-tunnel) setup_tunnel=false; shift ;;
        --only-ci-deploy) only_ci_deploy=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "알 수 없는 인자: $1" ;;
    esac
done

[[ "$(id -u)" -eq 0 ]] || die "root로 실행하세요(sudo)."
command -v docker >/dev/null 2>&1 || die "Docker가 설치되어 있지 않습니다."

# ── 자동 배포 진입점만 설치(--only-ci-deploy) ────────────────────────────────
# 배포 키의 forced command로 쓰는 스크립트는 배포 때 교체되는 $root_dir/app 밖에 root 소유로 둡니다.
# 배포 사용자가 고칠 수 없어야 배포 키로 실행되는 범위가 이 스크립트로 고정됩니다.
# 원본은 이 bootstrap 스크립트와 같은 디렉터리의 ci-deploy.sh입니다(검토한 저장소 사본에서 실행하세요).
if [[ "$only_ci_deploy" == true ]]; then
    src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ci-deploy.sh"
    [[ -f "$src" ]] || die "ci-deploy.sh를 찾지 못했습니다: $src"
    for cmd in git rsync flock gzip; do
        command -v "$cmd" >/dev/null 2>&1 || die "'$cmd'가 필요합니다(apt install $cmd)."
    done
    install -d -m 0755 -o root -g root "$root_dir/bin"
    install -m 0755 -o root -g root "$src" "$root_dir/bin/ci-deploy.sh"
    log "자동 배포 스크립트 설치: $root_dir/bin/ci-deploy.sh (authorized_keys 등록은 셀프호스팅 가이드 10.1 참고)"
    exit 0
fi

# ── 1. 스왑 ──────────────────────────────────────────────────────────────────
# RAM 3.8GB에서 컨테이너 상한 합계가 약 3.4GB라, 순간 피크를 스왑이 받아야 OOM kill을 피합니다.
if [[ -n "$(swapon --show --noheadings 2>/dev/null)" ]]; then
    log "스왑이 이미 있습니다: $(swapon --show --noheadings | awk '{print $1" "$3}' | tr '\n' ' ')"
else
    if [[ ! -f /swapfile ]]; then
        log "스왑 파일 생성: /swapfile ($swap_size)"
        fallocate -l "$swap_size" /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count="$(( $(numfmt --from=iec "$swap_size") / 1048576 ))" status=none
        chmod 600 /swapfile
        mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
    grep -qE '^/swapfile\s' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
    log "스왑 활성화 완료"
fi

# 스왑은 비상용이라 가능한 한 RAM을 먼저 쓰게 합니다.
printf 'vm.swappiness=%s\n' "$swappiness" >/etc/sysctl.d/99-theseus.conf
sysctl -q -p /etc/sysctl.d/99-theseus.conf
log "vm.swappiness=$swappiness"

# ── 2. 디렉터리 ──────────────────────────────────────────────────────────────
# sandbox-tmp, custom-tools, core-data는 Core 컨테이너와 호스트 Docker(sandbox)가 같은 경로로 공유합니다.
install -d -m 0755 "$root_dir"
install -d -m 0770 -o "$core_uid" -g "$core_gid" "$root_dir/sandbox-tmp"
install -d -m 0750 -o "$core_uid" -g "$core_gid" "$root_dir/custom-tools" "$root_dir/core-data"
# Remote Workspace SSH 키(선택). 비어 있어도 Core가 기동합니다.
install -d -m 0700 -o "$core_uid" -g "$core_gid" "$root_dir/ssh-keys"
install -d -m 0700 "$root_dir/backups"
if [[ -n "$owner" && "$owner" != "root" ]]; then
    install -d -m 0755 -o "$owner" -g "$(id -gn "$owner")" "$root_dir/app"
else
    install -d -m 0755 "$root_dir/app"
fi
log "디렉터리 준비: $root_dir/{sandbox-tmp,custom-tools,core-data,ssh-keys,backups,app}"

# env 파일은 배포 사용자가 sudo 없이 채우고(gen-secrets.sh) deploy.sh가 읽어야 하므로, $root_dir(root 소유)
# 아래에 배포 사용자 소유 600 빈 파일로 미리 만듭니다. 이미 있으면 건드리지 않습니다.
env_file="$root_dir/theseus.env"
if [[ ! -e "$env_file" ]]; then
    if [[ -n "$owner" && "$owner" != "root" ]]; then
        install -m 0600 -o "$owner" -g "$(id -gn "$owner")" /dev/null "$env_file"
    else
        install -m 0600 /dev/null "$env_file"
    fi
    log "env 파일 생성: $env_file (소유자 ${owner:-root}, 600)"
fi

# ── 3. Docker 그룹 ───────────────────────────────────────────────────────────
# Core는 docker-socket-proxy를 거치므로 compose에는 필요 없지만, 진단과 수동 설정을 위해 기록해 둡니다.
docker_gid="$(stat -c '%g' /var/run/docker.sock)"
echo "$docker_gid" >"$root_dir/docker-gid"
log "docker.sock gid=$docker_gid ($root_dir/docker-gid)"
if [[ -n "$owner" && "$owner" != "root" ]] && ! id -nG "$owner" | tr ' ' '\n' | grep -qx docker; then
    usermod -aG docker "$owner"
    log "$owner 를 docker 그룹에 추가했습니다(다시 로그인해야 적용). ship-images.sh의 docker load에 필요합니다."
fi

# docker0 브리지 IP입니다. compose의 host-gateway(host.docker.internal)가 이 주소로 해석됩니다.
docker0_ip="$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n 1)"
docker0_ip="${docker0_ip:-172.17.0.1}"
log "docker0 IP=$docker0_ip"

# ── 4. 방화벽 ────────────────────────────────────────────────────────────────
# Docker가 publish한 포트(80/443)는 ufw를 우회하지만, 의도를 남기고 다른 포트가 열리지 않게 기본 거부를 켭니다.
if [[ "$setup_ufw" == true ]]; then
    command -v ufw >/dev/null 2>&1 || die "ufw가 없습니다(apt install ufw) 또는 --no-ufw를 주세요."
    # 기본 거부를 켜기 전에 sshd가 실제로 듣는 포트를 모두 허용해야 현재와 이후 SSH 접속이 끊기지 않습니다.
    # 포트를 바꾼 서버(Port 2222)나 ssh.socket(ListenStream)을 고친 서버도 있으므로 22를 가정하지 않습니다.
    ssh_ports=()
    [[ -z "$ssh_port" ]] || ssh_ports+=("$ssh_port")
    mapfile -t -O "${#ssh_ports[@]}" ssh_ports < <(
        {
            sshd -T 2>/dev/null | awk '$1 == "port" { print $2 }'
            systemctl show ssh.socket -p Listen --value 2>/dev/null | grep -oE ':[0-9]+ ' | tr -d ': '
        } | sort -un
    )
    if [[ ${#ssh_ports[@]} -eq 0 ]]; then
        log "경고: sshd 포트를 찾지 못해 22를 허용합니다. 다르면 --ssh-port로 지정하세요."
        ssh_ports=(22)
    fi
    for port in "${ssh_ports[@]}"; do
        [[ "$port" =~ ^[0-9]+$ ]] || die "SSH 포트가 숫자가 아닙니다: $port"
        ufw allow "${port}/tcp" comment 'ssh' >/dev/null
    done
    ufw allow 80/tcp comment 'theseus http' >/dev/null
    ufw allow 443/tcp comment 'theseus https' >/dev/null
    if [[ "$setup_tunnel" == true ]]; then
        # 컨테이너(edge 브리지 theseus-edge)에서 호스트 docker0 IP의 터널 포트로 들어오는 트래픽만 허용합니다.
        ufw allow in on theseus-edge to "$docker0_ip" port "$llm_port" proto tcp comment 'theseus core -> llm tunnel' >/dev/null
    fi
    ufw --force enable >/dev/null
    log "ufw 활성화: $(printf '%s/tcp, ' "${ssh_ports[@]}")80/tcp, 443/tcp$([[ "$setup_tunnel" == true ]] && echo ", theseus-edge -> ${docker0_ip}:${llm_port}")"
fi

# ── 5. LLM 터널용 sshd 설정 ──────────────────────────────────────────────────
# sshd는 원격 포워드를 기본으로 127.0.0.1에만 엽니다. 컨테이너가 닿으려면 docker0 IP에 열어야 하므로
# 클라이언트가 바인딩 주소를 고르게 하되(GatewayPorts clientspecified), PermitListen으로 허용 주소와 포트를 못 박아
# 0.0.0.0 같은 공개 바인딩은 거부합니다.
# ClientAlive*: 노트북이 잠들거나 네트워크가 바뀌면 sshd가 끊긴 세션을 알아채지 못해 이전 세션이 터널 포트를
# 계속 잡고 있고, 새 터널은 'remote port forwarding failed'로 다시 열리지 못합니다. 15초 x 3회(약 45초) 응답이
# 없으면 세션을 끊어 포트를 풀어 줍니다.
if [[ "$setup_tunnel" == true ]]; then
    conf=/etc/ssh/sshd_config.d/60-theseus-llm-tunnel.conf
    cat >"$conf" <<EOF
# Theseus: 노트북 Ollama reverse tunnel (scripts/llm-tunnel.sh)
GatewayPorts clientspecified
PermitListen ${docker0_ip}:${llm_port} 127.0.0.1:${llm_port} localhost:${llm_port}
ClientAliveInterval 15
ClientAliveCountMax 3
EOF
    chmod 644 "$conf"
    sshd -t || { rm -f "$conf"; die "sshd 설정 검증 실패로 $conf 를 되돌렸습니다."; }
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || log "경고: ssh 서비스를 reload하지 못했습니다. 수동으로 reload하세요."
    log "sshd 터널 설정: $conf (bind ${docker0_ip}:${llm_port})"
fi

log "완료. 다시 로그인한 뒤(docker 그룹 적용) 배포 사용자로: env 작성(.env.example -> $root_dir/theseus.env), scripts/gen-secrets.sh --fill, scripts/deploy.sh"
