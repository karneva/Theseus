<#
.SYNOPSIS
노트북 Ollama를 서버 docker0 IP로 여는 reverse SSH tunnel(Windows OpenSSH 클라이언트용).

.DESCRIPTION
노트북의 127.0.0.1:11434(Ollama)를 서버의 172.17.0.1:11434로 엽니다.
서버 Core 컨테이너는 http://host.docker.internal:11434/v1 로 이 터널을 통해 모델을 호출합니다.
서버 쪽 sshd 설정(GatewayPorts clientspecified, PermitListen)은 scripts/server-bootstrap.sh가 합니다.
연결이 끊기면 5초 후 다시 연결합니다(-Once로 끌 수 있음).

.EXAMPLE
.\scripts\llm-tunnel.ps1 -SshHost my-server
#>
param(
    # ~/.ssh/config의 서버 별칭(또는 user@host)
    [Parameter(Mandatory = $true)]
    [string]$SshHost,
    # 서버 쪽 바인딩 주소(서버 docker0 IP)
    [string]$BindAddress = '172.17.0.1',
    [int]$RemotePort = 11434,
    [int]$LocalPort = 11434,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw 'ssh가 필요합니다(Windows 설정 > 선택적 기능 > OpenSSH 클라이언트).'
}

# 노트북 Ollama가 떠 있는지 미리 확인합니다(실패해도 터널은 엽니다).
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$LocalPort/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Warning "127.0.0.1:$LocalPort 에서 Ollama 응답이 없습니다. 'ollama serve'가 실행 중인지 확인하세요."
}

$forward = '{0}:{1}:127.0.0.1:{2}' -f $BindAddress, $RemotePort, $LocalPort

while ($true) {
    Write-Host ('[{0}] 터널 연결: {1} {2}:{3} -> 127.0.0.1:{4}' -f (Get-Date -Format 'HH:mm:ss'), $SshHost, $BindAddress, $RemotePort, $LocalPort)
    # ExitOnForwardFailure: 서버에서 포트를 못 열면 바로 실패해 재시도합니다.
    # ServerAlive*: 네트워크가 끊긴 것을 90초 안에 감지합니다.
    & ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R $forward $SshHost
    if ($Once) { break }
    Write-Host ('[{0}] 연결이 끊겼습니다. 5초 후 다시 연결합니다(Ctrl+C로 종료).' -f (Get-Date -Format 'HH:mm:ss'))
    Start-Sleep -Seconds 5
}
