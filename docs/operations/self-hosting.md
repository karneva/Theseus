# 셀프호스팅 가이드

Theseus 전체 스택을 서버 한 대에 docker compose로 올리는 절차의 정본입니다.
구성 파일은 [`infra/docker/selfhost/`](../../infra/docker/selfhost/), 운영 스크립트는 [`scripts/`](../../scripts/)에 있습니다.
서비스 구성과 데이터 흐름은 [시스템 아키텍처](../architecture/system-architecture.md), 환경 변수 전체 목록은 [환경 변수](./environment-variables.md)를 참고하세요.

## 목차

1. [전제와 구성](#1-전제와-구성)
2. [서버 준비](#2-서버-준비)
3. [노트북에서 이미지 빌드와 전송](#3-노트북에서-이미지-빌드와-전송)
4. [env 파일과 비밀값](#4-env-파일과-비밀값)
5. [첫 기동](#5-첫-기동)
6. [TLS(Let's Encrypt)](#6-tlslets-encrypt)
7. [LLM 연결(노트북 Ollama reverse tunnel)](#7-llm-연결노트북-ollama-reverse-tunnel)
8. [검증 체크리스트](#8-검증-체크리스트)
9. [백업과 복구](#9-백업과-복구)
10. [업그레이드](#10-업그레이드)
11. [운영 점검](#11-운영-점검)
12. [메모리 예산](#12-메모리-예산)
13. [문제 해결](#13-문제-해결)
14. [보안 메모와 알려진 제한](#14-보안-메모와-알려진-제한)

---

## 1. 전제와 구성

| 항목 | 기준 |
| --- | --- |
| 서버 | Ubuntu 24.04, 2 vCPU, RAM 3.8GB, 스왑 4GB(부트스트랩 스크립트가 생성) |
| 서버 소프트웨어 | Docker Engine과 compose 플러그인(v2). healthcheck `start_interval`을 쓰므로 Docker Engine 25 이상 |
| 개발 노트북 | Docker(빌드용), Git Bash 또는 Linux/macOS 셸, OpenSSH 클라이언트, Ollama |
| 외부 노출 | nginx의 80/443만 publish. API(8080), Core(8086), Kafka, DB, Redis는 publish하지 않음 |
| 도메인 | HTTPS를 쓰려면 서버 공인 IP를 가리키는 A 레코드 |

운영 원칙은 다음과 같습니다.

- **서버는 이미지를 빌드하지 않습니다.** 노트북에서 빌드해 SSH로 옮기거나(수동), `dev` push 때 GitHub Actions가 빌드해 GHCR에 올리고 서버가 받습니다([자동 배포](#101-자동-배포github-actions)). 서버는 `up -d --no-build`만 합니다.
- **LLM은 노트북의 Ollama**를 reverse SSH tunnel로 서버에 연결합니다. Core는 `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`로 호출합니다.
- **비밀값은 저장소 밖**의 `/opt/theseus/theseus.env`(권한 600)에만 둡니다.

서버 디렉터리 배치(`THESEUS_HOST_ROOT`, 기본 `/opt/theseus`)입니다.

| 경로 | 내용 |
| --- | --- |
| `/opt/theseus/theseus.env` | 서버 env 파일(비밀값 포함, 600) |
| `/opt/theseus/app/` | compose 파일과 `scripts/`(`ship-images.sh --with-config`로 복사하거나 `git clone`) |
| `/opt/theseus/custom-tools/` | 생성된 Tool 코드와 메타데이터(프로젝트별 하위 디렉터리) |
| `/opt/theseus/core-data/` | Core 엔진 런타임 데이터 |
| `/opt/theseus/sandbox-tmp/` | Core와 sandbox 컨테이너가 공유하는 임시 작업 디렉터리 |
| `/opt/theseus/ssh-keys/` | Remote Workspace SSH 키(선택) |
| `/opt/theseus/backups/` | `backup.sh` 출력 |

DB, Redis, Kafka, 임베딩 모델 캐시, 인증서는 named volume(`theseus-mysql-data`, `theseus-postgres-data`, `theseus-redis-data`, `theseus-kafka-data`, `theseus-hf-cache`, `theseus-certbot-conf`, `theseus-certbot-www`)에 둡니다.

## 2. 서버 준비

Docker Engine과 compose 플러그인을 먼저 설치하고 `docker compose version`으로 확인합니다.
[`scripts/server-bootstrap.sh`](../../scripts/server-bootstrap.sh)는 다른 파일에 의존하지 않으므로 이 파일만 먼저 복사해 실행해도 됩니다. 여러 번 실행해도 안전합니다.

```bash
# 노트북
scp scripts/server-bootstrap.sh <서버별칭>:/tmp/

# 서버
sudo bash /tmp/server-bootstrap.sh            # 옵션: --swap-size 4G --swappiness 10 --ssh-port <추가 포트> --no-ufw --no-llm-tunnel
```

부트스트랩이 하는 일은 다음과 같습니다.

1. 스왑이 없으면 `/swapfile`(기본 4G)을 만들고 `vm.swappiness=10`을 `/etc/sysctl.d/99-theseus.conf`에 씁니다.
2. `/opt/theseus/{sandbox-tmp,custom-tools,core-data,ssh-keys,backups,app}`를 만들고 Core 디렉터리 소유권을 uid/gid 999(Core 이미지의 appuser)로 맞춥니다. `app`과 `theseus.env`(600 빈 파일)는 배포 사용자 소유로 만들어 이후 단계를 sudo 없이 진행합니다.
3. sudo를 실행한 사용자를 docker 그룹에 추가합니다. 다시 로그인해야 적용되고, `ship-images.sh`의 `docker load`에 필요합니다.
4. ufw: SSH(sshd가 실제로 듣는 포트를 `sshd -T`와 `ssh.socket`에서 찾아 모두 허용), 80, 443을 허용하고, compose edge 브리지(`theseus-edge`)에서 docker0 IP의 11434 포트로 들어오는 트래픽만 허용한 뒤 ufw를 켭니다.
5. sshd: `/etc/ssh/sshd_config.d/60-theseus-llm-tunnel.conf`에 `GatewayPorts clientspecified`, `PermitListen <docker0 IP>:11434 127.0.0.1:11434 localhost:11434`, `ClientAliveInterval 15`/`ClientAliveCountMax 3`(끊긴 터널 세션을 약 45초 안에 정리)을 쓰고 `sshd -t` 검증 후 reload합니다.

클라우드 보안그룹을 쓰는 환경이라면 인바운드도 22/80/443만 엽니다.

## 3. 노트북에서 이미지 빌드와 전송

Windows에서는 Git Bash에서 실행합니다. 서버 SSH 별칭은 `~/.ssh/config`에 둡니다.

```bash
# api, core, frontend, nginx, sandbox 이미지를 linux/amd64로 빌드합니다. 태그를 생략하면 git short sha(변경이 있으면 -dirty)를 씁니다.
bash scripts/build-images.sh 2026-11-15

# 이미지를 docker save | gzip | ssh docker load로 옮깁니다. --with-config는 infra/docker/selfhost와 scripts를 /opt/theseus/app에 풉니다.
bash scripts/ship-images.sh --with-config <서버별칭> 2026-11-15
```

| 이미지 | 크기(E2E 측정) |
| --- | ---: |
| `theseus-api:<태그>` | 476MB |
| `theseus-core:<태그>` | 2.46GB |
| `theseus-frontend:<태그>` | 76MB |
| `theseus-nginx:<태그>` | 74MB |
| `theseus-sandbox:py311-tools` | 356MB |

- `--only api,frontend`처럼 일부만 빌드·전송할 수 있습니다. 구성 요소 이름은 `api`, `core`, `frontend`, `nginx`, `sandbox`입니다.
- 레지스트리를 쓰면 `--registry registry.example.com/theseus/`로 접두사를 붙이고, 서버 env의 `IMAGE_REGISTRY`에 같은 값을 넣습니다.
- sandbox 이미지는 태그 없이 `SANDBOX_IMAGE`(기본 `theseus-sandbox:py311-tools`) 이름 그대로 씁니다.
- 서버에서 `git clone`해 `/opt/theseus/app`에 두어도 됩니다. 스크립트는 자기 위치 기준으로 compose 파일을 찾습니다.

## 4. env 파일과 비밀값

```bash
cp /opt/theseus/app/infra/docker/selfhost/.env.example /opt/theseus/theseus.env
chmod 600 /opt/theseus/theseus.env
/opt/theseus/app/scripts/gen-secrets.sh --fill /opt/theseus/theseus.env
vi /opt/theseus/theseus.env
```

`gen-secrets.sh --fill`은 비어 있는 키만 채우고 이미 값이 있는 키는 덮어쓰지 않습니다. 대상은 `JWT_SECRET`, `INTERNAL_API_KEY`, `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `KAFKA_CLUSTER_ID` 7개입니다.

직접 채워야 하는 값은 다음과 같습니다.

| 키 | 예 | 비고 |
| --- | --- | --- |
| `DOMAIN` | `theseus.example.com` | nginx `server_name`과 인증서 경로 |
| `CERTBOT_EMAIL` | `ops@example.com` | Let's Encrypt 계정 메일 |
| `IMAGE_TAG` | `2026-11-15` | `build-images.sh`에 준 태그 |
| `THESEUS_MODEL` | `ollama/<모델명>` | provider 접두사 필수. 비어 있으면 Core가 기동하지 않습니다 |
| `INITIAL_ADMIN_EMPLOYEE_NUMBER`, `INITIAL_ADMIN_NAME`, `INITIAL_ADMIN_PASSWORD` | | 최초 SUPER_ADMIN. `INITIAL_ADMIN_EMAIL`은 선택 |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | 작은 로컬 모델이면 기본값 32768에서 낮춥니다 |

- 필수 항목이 비어 있으면 `docker compose config/up`이 `IMAGE_TAG must be set`처럼 빠진 변수를 알려 주고 멈춥니다.
- DB·Redis 비밀번호는 `MYSQL_*`, `POSTGRES_*`, `REDIS_PASSWORD`에만 두고, compose가 API의 `SPRING_DATASOURCE_*`, `SPRING_DATA_REDIS_PASSWORD`와 Core의 `CORE_POSTGRES_*`로 넘깁니다.
- 볼륨이 처음 초기화된 뒤에는 DB 비밀번호를 env에서만 바꿔도 DB 계정 비밀번호는 바뀌지 않습니다. 회전 절차는 [SECURITY.md](../../SECURITY.md)를 따릅니다.
- `KAFKA_CLUSTER_ID`는 `theseus-kafka-data` 볼륨을 지우기 전까지 바꾸지 않습니다.

## 5. 첫 기동

```bash
/opt/theseus/app/scripts/deploy.sh               # 옵션: --env-file FILE, --timeout 900, [서비스...]
```

`deploy.sh`는 앱 이미지와 sandbox 이미지가 서버에 있는지 확인하고, `compose config --quiet`로 검증한 뒤 `up -d --no-build --pull missing --remove-orphans`를 실행합니다.
그다음 일회성 서비스는 exit 0, 상시 서비스는 healthy가 될 때까지 기다리고 상태와 `docker stats`를 출력합니다. env 파일 권한이 600/400이 아니면 경고합니다.

기동 순서는 `depends_on`의 `service_healthy`/`service_completed_successfully`가 맞춥니다.

```text
mysql, redis, kafka ─▶ kafka-init(토픽 4개 + DLT 2개) ─▶ api(Flyway 마이그레이션) ─┐
postgres, docker-proxy, core-permissions(디렉터리 소유권) ──────────────────────────┴▶ core
frontend, api ─▶ nginx
```

E2E 환경에서는 `up` 후 57초 만에 상시 서비스 10개가 모두 healthy가 되었습니다(22코어 노트북 기준). 2 vCPU 서버의 기동 시간은 아직 측정하지 않았고, api/core healthcheck의 `start_period`는 180초입니다.

- **최초 관리자**: SUPER_ADMIN이 한 명도 없을 때 `INITIAL_ADMIN_*` 값으로 한 번 생성됩니다. 로그인 ID는 사번(`INITIAL_ADMIN_EMPLOYEE_NUMBER`) 또는 이메일입니다. 로그인을 확인한 뒤 env 파일에서 `INITIAL_ADMIN_PASSWORD`를 지우고 `deploy.sh`를 다시 실행합니다.
- **sandbox 이미지**: `SANDBOX_STARTUP_STRICT=true`(selfhost 기본)라 `SANDBOX_IMAGE`가 서버에 없으면 core가 기동하지 않습니다.
- **임베딩 모델**: Tool RAG 모델(`intfloat/multilingual-e5-small` ONNX int8, 약 113 MiB)은 이미지 빌드 때 만들어 이미지에 들어 있습니다(`/opt/models/e5-small-int8`). Core는 런타임에 모델을 내려받지 않고, 기동 직후 백그라운드에서 약 1~2초 동안 로드합니다. 로드가 끝나기 전의 요청은 보이는 도구 전부를 받습니다. `theseus-hf-cache` 볼륨은 선택 기능(`requirements-torch.txt`)용입니다. 자세한 내용은 [Tool RAG](../architecture/tool-rag.md)를 참고하세요.

## 6. TLS(Let's Encrypt)

nginx 컨테이너는 기동할 때 `/etc/letsencrypt/live/$DOMAIN/`에 인증서가 있는지 보고 템플릿을 고릅니다(`NGINX_TLS_MODE=auto`).

1. 인증서가 없으면 **HTTP 템플릿**으로 뜹니다. ACME webroot(`/.well-known/acme-challenge/`)와 앱을 HTTP로 서빙합니다.
2. 첫 인증서를 발급합니다. 성공하면 스크립트가 nginx를 재시작해 **HTTPS 템플릿**(80→443 리다이렉트, HTTP/2, HSTS)으로 바뀝니다.

   ```bash
   /opt/theseus/app/scripts/issue-cert.sh --staging   # 연습 발급(발급 횟수 제한 회피)
   /opt/theseus/app/scripts/issue-cert.sh --force     # staging 인증서를 실제 인증서로 교체
   ```

3. 갱신은 자동입니다. certbot 컨테이너가 12시간마다 `certbot renew`를 실행하고, nginx가 6시간마다 reload합니다.

- prod 프로필은 refresh 쿠키에 `Secure`를 붙입니다. HTTPS 전 HTTP 단계에서는 access 토큰이 만료되면(기본 1시간) 다시 로그인해야 합니다. 도메인 없이 HTTP로만 시험할 때만 `JWT_REFRESH_TOKEN_COOKIE_SECURE=false`로 둡니다.
- 인증서 문제로 nginx가 뜨지 않으면 `NGINX_TLS_MODE=http`로 HTTP 템플릿을 강제합니다.
- HSTS는 `HSTS_MAX_AGE`(기본 31536000초)로 조절합니다. 처음에는 300 같은 작은 값으로 시작해도 됩니다.

## 7. LLM 연결(노트북 Ollama reverse tunnel)

```text
core ─▶ host.docker.internal:11434 (= 서버 docker0 IP, 기본 172.17.0.1) ─ ssh -R ─▶ 노트북 127.0.0.1:11434 (Ollama)
```

`host.docker.internal`은 compose의 `extra_hosts: host-gateway`로 docker0 IP에 해석됩니다.
sshd는 원격 포워드를 기본으로 127.0.0.1에만 열기 때문에, 부트스트랩이 설정한 `GatewayPorts clientspecified` + `PermitListen`으로 docker0 IP에만 바인딩합니다. 0.0.0.0 같은 공개 바인딩은 거부됩니다.

### 7.1 노트북 Ollama 설정

권장 방식은 [`infra/docker/llm-gateway`](../../infra/docker/llm-gateway/docker-compose.yml)의 LLM 게이트웨이입니다. Ollama(GPU, 아래 표의 설정이 들어 있음) 앞에 nginx 필터를 두어, 터널로는 core가 쓰는 `GET /v1/models`와 `POST /v1/chat/completions`만 통과시키고 `/api/pull`·`/api/delete`·`/api/create` 같은 관리 API는 403으로 막습니다. 노트북에서 직접 하는 관리 작업은 `127.0.0.1:11434`로 Ollama에 바로 붙습니다.

```bash
docker compose -f infra/docker/llm-gateway/docker-compose.yml up -d
docker compose -f infra/docker/llm-gateway/docker-compose.yml exec ollama ollama pull qwen3:4b-instruct-2507-q4_K_M
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:11435/v1/models   # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:11435/api/pull   # 403
```

Docker Desktop에서 GPU를 쓰려면 WSL2 백엔드와 NVIDIA 드라이버가 필요합니다. 게이트웨이를 쓰면 7.2의 터널을 `--local-port 11435`(PowerShell은 `-LocalPort 11435`)로 엽니다. Windows Ollama 앱을 직접 쓰는 경우에는 필터 없이 11434로 연결되므로 아래 환경 변수를 직접 설정합니다.

Ollama는 VRAM이 24GB 미만인 GPU에서 기본 컨텍스트를 4096으로 잡습니다. Core의 ASK 프롬프트만으로 약 4,500토큰이라 기본값 그대로 두면 모든 채팅이 `HTTP 400 ... exceeds the available context size`로 실패합니다.
E2E에서 요청당 프롬프트와 출력 합은 중앙값 7,343, 최대 11,231토큰이었으므로 **`OLLAMA_CONTEXT_LENGTH=16384`** 이상으로 둡니다.

| 변수 | 값 | 이유 |
| --- | --- | --- |
| `OLLAMA_CONTEXT_LENGTH` | `16384` | 필수. 12k는 빠듯합니다 |
| `OLLAMA_FLASH_ATTENTION` | `1` | KV 캐시 메모리 절감 |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | 6GB GPU에서 4B 모델을 16k 컨텍스트로 GPU에 모두 올림(3.9GB) |
| `OLLAMA_KEEP_ALIVE` | `30m` | 모델 재로드 방지. 첫 콜드 호출은 약 50초 |

Windows Ollama 앱은 `setx OLLAMA_CONTEXT_LENGTH 16384`처럼 사용자 환경 변수를 설정한 뒤 앱을 다시 시작합니다. `ollama ps`의 CONTEXT 열로 적용을 확인합니다.

### 7.2 터널 열기

```bash
bash scripts/llm-tunnel.sh --local-port 11435 <서버별칭>  # Git Bash / Linux / macOS (LLM 게이트웨이 사용 시)
bash scripts/llm-tunnel.sh <서버별칭>                     # Ollama 앱을 11434로 직접 연결할 때
```

```powershell
.\scripts\llm-tunnel.ps1 -SshHost <서버별칭>              # Windows PowerShell(OpenSSH 클라이언트)
```

실제 명령은 `ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 172.17.0.1:11434:127.0.0.1:11434 <서버별칭>`이고, 끊기면 5초 후 다시 연결합니다(`--once`/`-Once`로 끄기).
docker0 IP가 다르면 `--bind`(`-BindAddress`)로 바꿉니다. 부트스트랩이 `PermitListen`에 쓴 IP와 같아야 합니다.

### 7.3 확인

```bash
curl -s http://172.17.0.1:11434/api/tags                       # 서버 호스트에서
C="docker compose -f /opt/theseus/app/infra/docker/selfhost/docker-compose.yml --env-file /opt/theseus/theseus.env"
$C exec -T core python -c "import os,urllib.request;print(urllib.request.urlopen(os.environ['OLLAMA_BASE_URL']+'/models',timeout=10).read()[:300])"
```

- `THESEUS_LLM_TIMEOUT_SECONDS`는 selfhost 기본 300초입니다. E2E(qwen3 4B, RTX 4050 6GB)에서 PLAN 구조화 생성이 111~117초, BUILD 코드 생성이 약 20초, ASK 응답이 약 2초였습니다.
- 터널이 끊겨 있으면 채팅과 PLAN/BUILD만 LLM 연결 오류로 실패하고, 로그인·프로젝트·Tool 목록은 영향이 없습니다.
- 외부 provider를 쓰려면 `THESEUS_MODEL`을 `openai/...`, `anthropic/...`, `gemini/...`, `deepseek/...`로 바꾸고 해당 키를 채웁니다. 이때는 터널이 필요 없습니다.

## 8. 검증 체크리스트

`BASE=https://<도메인>`(HTTP 단계면 `http://`)로 두고 확인합니다.

**엣지와 노출 범위**

```bash
curl -s -o /dev/null -w '%{http_code}\n' $BASE/healthz                    # 200
curl -s -o /dev/null -w '%{http_code}\n' $BASE/                           # 200 (SPA)
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/v1/projects            # 401 (인증 필요)
for p in /api/internal/auth/verify /swagger-ui/index.html /v3/api-docs /actuator/health; do
  curl -s --path-as-is -o /dev/null -w "$p %{http_code}\n" $BASE$p        # 모두 404
done
```

- [ ] 서버에서 `ss -tlnp`: 22, 80, 443과 터널이 열려 있으면 `172.17.0.1:11434`만 LISTEN
- [ ] `docker ps`에서 포트를 publish한 컨테이너는 nginx 하나(`ops` 프로필의 kafka-ui는 `127.0.0.1:8091`)
- [ ] `/api/v1/auth/login` 연속 요청 시 20회 burst 이후 429(분당 10회 제한), `/api/v1/auth/refresh`(분당 60회)와 다른 API 경로는 영향 없음
- [ ] 응답 헤더에 `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`가 있고, HTTPS에서는 `Strict-Transport-Security`도 있음

**제품 흐름(웹 화면)**

- [ ] 최초 관리자 사번으로 로그인 → SUPER_ADMIN
- [ ] 프로젝트 생성, 채팅 세션 생성
- [ ] 관리자 화면에서 일반 사용자 생성 → 프로젝트 멤버(MEMBER)로 추가 → 그 사용자로 로그인. 이 사용자로 Tool 승인·사용 이력 같은 프로젝트 관리자 API를 호출하면 403
- [ ] ASK 메시지: 응답이 한 번에 오지 않고 조각으로 이어서 표시됨(nginx SSE 무버퍼링)
- [ ] AGENT 메시지: 내장 도구(`glob`, `grep` 등) 호출과 결과가 표시됨
- [ ] PLAN 요청 → 진행 상태가 SSE로 표시되고 계획이 REVIEW 상태로 완료
- [ ] 승인 요청 → 관리자가 접근 레벨(1~5)을 정해 승인 → BUILD 진행(검증, sandbox, 활성화) → BUILT
- [ ] Tool 목록에 새 Tool이 APPROVED로 표시되고, 새 세션의 AGENT 모드에서 그 Tool이 호출됨
- [ ] 새로고침 후에도 로그인 유지(refresh 쿠키), 로그아웃 후 refresh 401

**운영**

- [ ] `docker stats --no-stream`에서 mem_limit에 근접한 컨테이너가 없는지(kafka는 원래 높게 보입니다, [12장](#12-메모리-예산))
- [ ] `backup.sh` 수동 1회 실행 성공, cron 등록
- [ ] 복구 리허설 1회

## 9. 백업과 복구

```bash
# root crontab: 매일 03:30. 기본 보관 14일(--retention 또는 BACKUP_RETENTION_DAYS)
30 3 * * * /opt/theseus/app/scripts/backup.sh >> /opt/theseus/backups/backup.log 2>&1
```

`backup.sh`는 `/opt/theseus/backups/<YYYYmmdd-HHMMSS>/`에 다음을 만들고, 실패하면 불완전한 디렉터리를 지웁니다.

| 파일 | 내용 |
| --- | --- |
| `mysql-theseus.sql.gz` | `mysqldump --single-transaction --routines --triggers --events` (API DB) |
| `postgres-theseus_core.dump` | `pg_dump -Fc` (Core DB, pgvector 포함) |
| `files.tar.gz` | `/opt/theseus/custom-tools`, `/opt/theseus/core-data` |

Redis(refresh 토큰, Run 상태)와 Kafka는 일시 데이터라 백업하지 않습니다. 복구 후 사용자는 다시 로그인합니다.
백업은 같은 디스크에 있으므로 주기적으로 서버 밖(노트북, 오브젝트 스토리지)으로 복사합니다. env 파일(`/opt/theseus/theseus.env`)도 별도의 안전한 위치에 보관합니다.

복구 절차(빈 서버, 또는 볼륨을 지운 뒤):

```bash
B=/opt/theseus/backups/<시각>
C="docker compose -f /opt/theseus/app/infra/docker/selfhost/docker-compose.yml --env-file /opt/theseus/theseus.env"

$C up -d --wait mysql postgres                # 데이터 계층만 먼저. 첫 초기화(임시 서버)가 끝나 healthy가 될 때까지 기다립니다
gunzip -c $B/mysql-theseus.sql.gz | $C exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot'
$C exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < $B/postgres-theseus_core.dump
sudo tar -xzf $B/files.tar.gz -C /opt/theseus  # custom-tools, core-data
/opt/theseus/app/scripts/deploy.sh             # 나머지 기동(core-permissions가 소유권을 다시 맞춥니다)
```

복구에는 백업 당시와 같은 env 파일(특히 DB 비밀번호)이 필요합니다.

## 10. 업그레이드

```bash
# 노트북
bash scripts/build-images.sh <새태그>
bash scripts/ship-images.sh --with-config <서버별칭> <새태그>

# 서버: env의 IMAGE_TAG를 <새태그>로 바꾼 뒤
/opt/theseus/app/scripts/deploy.sh
docker image prune                             # 이전 이미지 정리(선택)
```

- `IMAGE_TAG`는 api/core/frontend/nginx가 함께 씁니다. 일부만 새 태그로 빌드하면 나머지 이미지가 없어 `deploy.sh`가 멈춥니다. 새 태그로 전체를 빌드하거나(빌드 캐시로 빠름), 같은 태그로 일부만 다시 빌드해 덮어씁니다.

  ```bash
  bash scripts/build-images.sh --only core <현재태그>
  bash scripts/ship-images.sh --only core <서버별칭> <현재태그>
  /opt/theseus/app/scripts/deploy.sh core      # 서버
  ```

- DB 스키마는 API가 기동할 때 Flyway(`db/migration`)로 올립니다. 마이그레이션이 있는 업그레이드 전에는 `backup.sh`를 먼저 실행합니다.
- DB, custom-tools, core-data는 볼륨과 `/opt/theseus` 아래에 있으므로 `down`(볼륨 유지) 후 `up -d`에도 남습니다.

### 10.1 자동 배포(GitHub Actions)

`dev`에 push하고 CI(테스트, compose 검증, gitleaks)가 모두 통과하면 [`deploy.yml`](../../.github/workflows/deploy.yml)이 배포합니다.

```text
dev push -> CI 통과 -> 러너에서 이미지 5개 빌드 -> GHCR push(ghcr.io/<owner>/theseus-*:<sha7>)
         -> SSH(배포 전용 키, forced command)로 "deploy <커밋 SHA>"만 전달 -> 서버 ci-deploy.sh
            -> 저장소(DEPLOY_GIT_URL)를 직접 fetch, 커밋이 dev에 포함됐는지 확인, 그 커밋의 compose·scripts 추출
            -> 새 compose 검증 -> GHCR pull, 이미지 라벨(revision)이 커밋과 같은지 확인, 로컬 이름으로 retag
            -> DB 덤프(MySQL, PostgreSQL) -> 설정·IMAGE_TAG 반영 -> deploy.sh(healthy 대기, 최대 8분)
            -> 실패하면 직전 IMAGE_TAG·설정으로 롤백
         -> 러너에서 https://<도메인>/healthz 확인
```

- 서버는 빌드하지 않고 레지스트리에서 바뀐 레이어만 받습니다. 빌드 캐시는 GHCR의 `:buildcache` 태그에 둡니다.
- 서버에서 실행 중인 커밋 이후 문서(`*.md`, `docs/`, `exec/`)만 바뀌었으면 컨테이너를 다시 만들지 않습니다.
- 배포는 한 번에 하나씩 합니다. 진행 중인 배포는 취소하지 않고, 기다리는 배포가 있으면 더 새 커밋의 배포로 바뀝니다.
- GitHub job이 취소되거나 SSH가 끊겨도 서버 쪽 배포·롤백은 끝까지 진행합니다. 결과는 `~/.theseus-deploy/last-deploy.log`에 남고 `status`로도 볼 수 있습니다.
- **롤백**: Actions 탭에서 Deploy 워크플로를 `ref`에 이전 커밋 SHA(7자 `IMAGE_TAG`도 가능)를 넣어 수동 실행합니다. GHCR에 있는 태그면 다시 빌드하지 않습니다.
- **DB 마이그레이션**: API는 기동할 때 Flyway를 적용하고, 이미지 롤백으로는 스키마가 되돌아가지 않습니다. 자동 롤백은 하위 호환(컬럼·테이블 추가만) 마이그레이션에서만 안전합니다. 배포 전 덤프는 `~/.theseus-deploy/predeploy-dumps/`에 최근 5개를 남깁니다.
- 노트북 수동 배포(`build-images.sh` → `ship-images.sh` → `deploy.sh`)도 그대로 쓸 수 있습니다. 두 방식 모두 로컬 이미지 이름이 `theseus-*:<태그>`로 같습니다.

**보안 설계**

| 항목 | 방식 |
| --- | --- |
| 배포 키 | 배포 전용 ed25519 키. `authorized_keys`에서 `restrict,command=`로 `ci-deploy.sh`만 실행(셸, 포트 포워딩, pty 불가) |
| 서버 진입점 | `/opt/theseus/bin/ci-deploy.sh`(root 소유). 명령은 `deploy <40자 SHA> <사용자>`, `status`만 받고 형식을 검사 |
| 실행할 코드 | 클라이언트는 코드·설정을 보내지 않음. 서버가 `DEPLOY_GIT_URL`에서 직접 가져오고 `dev`에 포함된 커밋만 배포 |
| 이미지 | 서버 env의 `DEPLOY_PULL_REGISTRY`에서만 받고, `org.opencontainers.image.revision` 라벨이 요청한 커밋과 다르면 중단 |
| 레지스트리 인증 | 배포 job의 `GITHUB_TOKEN`(`packages: read`, job이 끝나면 만료)을 stdin으로만 전달하고 임시 `DOCKER_CONFIG`에서 쓰고 지움 |
| 호스트 확인 | 서버 호스트 키를 `DEPLOY_SSH_KNOWN_HOSTS`로 고정(`StrictHostKeyChecking yes`) |
| 비밀값 | `theseus.env`는 GitHub에 올라가지 않음. 자동 배포는 `IMAGE_TAG` 줄만 바꿈 |

- 배포 키가 유출돼도 할 수 있는 일은 **`dev`에 이미 있는 커밋을 다시 배포(롤백 포함)하는 것**뿐입니다.
- 반대로 `dev`에 push할 수 있는 사람은 서버에서 코드를 실행할 수 있습니다(배포 사용자는 docker 그룹이라 사실상 root 권한). `dev` 브랜치 보호(PR 필수, CI 통과 필수)를 켜 두세요.

**1회 설정**

1. 서버: 새 `scripts/`를 서버에 올리고(처음 한 번), 배포 진입점을 설치합니다. env에 자동 배포 값을 적습니다.

   ```bash
   # 노트북(자동 배포가 들어간 커밋에서): 설정과 스크립트만 복사
   tar -czf - infra/docker/selfhost scripts | ssh <서버별칭> 'tar -xzf - -C /opt/theseus/app'

   # 서버
   sudo /opt/theseus/app/scripts/server-bootstrap.sh --only-ci-deploy   # ci-deploy.sh만 설치(다른 단계는 실행하지 않음)
   # /opt/theseus/theseus.env 에 추가
   DEPLOY_PULL_REGISTRY=ghcr.io/<owner>/
   DEPLOY_GIT_URL=https://github.com/<owner>/<repo>.git
   IMAGE_REGISTRY=
   ```

   `ci-deploy.sh`는 자동 배포로 갱신되지 않습니다. 이 파일이 바뀌면 배포된 뒤 `--only-ci-deploy`를 다시 실행합니다.

2. 노트북: 배포 전용 키를 만들고 공개 키를 forced command로 등록합니다.

   ```bash
   ssh-keygen -t ed25519 -N '' -C theseus-ci-deploy -f ./theseus-ci-deploy
   printf 'restrict,command="/opt/theseus/bin/ci-deploy.sh" %s\n' "$(cat ./theseus-ci-deploy.pub)" \
     | ssh <서버별칭> 'cat >> ~/.ssh/authorized_keys'
   ssh -i ./theseus-ci-deploy -o IdentitiesOnly=yes <user>@<서버 호스트> status   # IMAGE_TAG와 서비스 상태가 나오면 성공
   ssh-keyscan -t ed25519,rsa,ecdsa <서버 호스트> > ./known_hosts.theseus
   ssh-keygen -lf ./known_hosts.theseus   # 서버에서 ssh-keygen -lf /etc/ssh/ssh_host_*_key.pub 결과와 지문이 같은지 확인
   ```

3. GitHub 저장소 Settings:
   - Environments → `production` 생성
     - Deployment branches and tags: Selected branches → `dev`
     - Secrets: `DEPLOY_SSH_KEY`(개인 키 `theseus-ci-deploy` 전체), `DEPLOY_SSH_KNOWN_HOSTS`(`known_hosts.theseus` 내용)
     - Variables: `DEPLOY_SSH_HOST`(서버 호스트), `DEPLOY_SSH_USER`(예: `ubuntu`), `DEPLOY_DOMAIN`(외부 확인용)
     - 필요하면 Required reviewers를 켜서 배포 전에 승인을 받습니다.
   - Variables(저장소): `DEPLOY_ENABLED=true`. 이 값이 없으면 dev push에서 배포 job을 건너뜁니다.

   GitHub CLI로는 다음과 같습니다(환경과 브랜치 정책은 웹에서 만듭니다).

   ```bash
   gh secret set DEPLOY_SSH_KEY --env production < ./theseus-ci-deploy
   gh secret set DEPLOY_SSH_KNOWN_HOSTS --env production < ./known_hosts.theseus
   gh variable set DEPLOY_SSH_HOST --env production --body <서버 호스트>
   gh variable set DEPLOY_SSH_USER --env production --body ubuntu
   gh variable set DEPLOY_DOMAIN --env production --body <도메인>
   gh variable set DEPLOY_ENABLED --body true
   rm ./theseus-ci-deploy   # GitHub에 등록한 뒤 로컬 개인 키는 지웁니다
   ```

4. 첫 배포: Actions 탭에서 Deploy 워크플로를 `dev` 브랜치, `ref=dev`로 수동 실행합니다. GHCR 패키지(theseus-api, -core, -frontend, -nginx, -sandbox)는 저장소에 연결된 private 패키지로 만들어지고, 서버는 배포 job의 토큰으로 받습니다.

- 서버 보안 그룹(방화벽)이 GitHub Actions 러너의 SSH(22) 접속을 허용해야 합니다. 러너 IP는 고정되지 않습니다.
- 서버 디스크: 구성 요소별로 `DEPLOY_KEEP_TAGS`(기본 3)개 태그와 현재·직전 태그만 남기고 정리합니다. 저장소 사본은 `~/.theseus-deploy/repo.git`에 둡니다.

## 11. 운영 점검

```bash
C="docker compose -f /opt/theseus/app/infra/docker/selfhost/docker-compose.yml --env-file /opt/theseus/theseus.env"
$C ps                                          # 상태와 health
$C logs -f --tail=200 api core                 # 로그(json-file 10MB x 3개 회전)
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
```

| 대상 | 확인 방법 |
| --- | --- |
| nginx | `/healthz` 200, 컨테이너 healthcheck |
| api | 컨테이너 안 `http://127.0.0.1:8080/actuator/health`(외부에서는 404로 막힘) |
| core | 컨테이너 안 `http://127.0.0.1:8086/health` |
| Kafka 토픽·consumer group | `ops` 프로필 Kafka UI([Kafka UI 문서](./prod-kafka-ui.md)) |
| 백업 | `/opt/theseus/backups/backup.log`, 최근 디렉터리 크기 |

- Core의 PLAN/BUILD consumer는 INFO 수준에서 LLM HTTP 호출 외에는 로그가 거의 없습니다. sandbox 검증, repair, 활성화 단계는 화면의 SSE 진행 상태와 API 로그로 확인합니다.
- 컨테이너 메모리 상세는 `docker exec <컨테이너> cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events`로 봅니다.

## 12. 메모리 예산

`mem_limit`은 하드 상한이고, 넘치는 순간 사용량은 스왑(4GB)이 받습니다. core는 `memswap_limit: 3g`로 스왑 사용을 명시합니다.
아래 실측값은 E2E 실행(노트북, 22 CPU / 31GB, kafka만 잠시 `--cpus 2`)에서 `docker stats`(비활성 파일 캐시 제외)로 잰 값입니다.

| 서비스 | mem_limit | 설정 근거 | 기동 직후 | 흐름 후 유휴 | PLAN·BUILD 중 최대 |
| --- | ---: | --- | ---: | ---: | ---: |
| core | 1536m | torch(CPU), sentence-transformers. 스왑 포함 3g | 178MiB | 889MiB | 1065MiB |
| api | 640m | `-Xmx384m`, SerialGC, metaspace 160m | 418MiB | 421MiB | 421MiB |
| kafka | 448m | `KAFKA_HEAP_OPTS=-Xmx256m -Xms256m`, KRaft 단일 노드 | 353MiB | 344MiB | 418MiB |
| mysql | 384m | buffer pool 128M, performance_schema OFF | 202MiB | 204MiB | 205MiB |
| postgres | 160m | shared_buffers 64MB, max_connections 40 | 65MiB | 73MiB | 67MiB |
| redis | 64m | maxmemory 48mb(volatile-lru), AOF | 9MiB | 11MiB | 11MiB |
| nginx | 64m | | 19MiB | 19MiB | 20MiB |
| certbot | 64m | 12시간마다 renew | 2MiB | 2MiB | 2MiB |
| frontend | 32m | 정적 파일 nginx | 20MiB | 21MiB | 20MiB |
| docker-proxy | 32m | haproxy | 8MiB | 8MiB | 9MiB |
| **합계** | **3424m** | 약 3.34GiB | **약 1274MiB** | **약 1992MiB** | **동시 최대 2164MiB** |

- 일회성 서비스: kafka-init 256m, core-permissions 32m(기동 시 잠깐). sandbox 컨테이너는 BUILD 검증마다 `SANDBOX_MEMORY_LIMIT`(기본 128m)로 1초 남짓 실행됩니다. `ops` 프로필 kafka-ui(384m)는 예산 밖입니다.
- core는 첫 AGENT/PLAN 요청 때 임베딩 모델을 올리면서 약 900MiB로 늘고 그 뒤로 유지됩니다(cgroup `memory.peak` 1156M).
- 위 core 수치는 Tool RAG v1(torch, sentence-transformers) 이미지로 잰 값입니다. v2 이미지(ONNX int8, torch 없음)는 같은 조건의 전체 스택 E2E를 다시 재지 않았습니다. 대신 컨테이너 프로브(`--cpus=2 --memory=1.5g`, `import src.main` 뒤 검색 1회)에서 core 프로세스 RSS가 v1 이미지 1079~1091MiB, v2 이미지 419~421MiB였습니다([Tool RAG 결과](../architecture/tool-rag.md#53-자원)).
- E2E 동안 OOM kill과 재시작은 없었습니다. 3.8GB 서버에서 OS 몫(약 0.3~0.4GB)을 빼면 페이지 캐시와 sandbox에 약 1.2GB가 남습니다.
- **kafka가 가장 빠듯합니다.** 브로커 자체는 283~297MiB(anon)이지만, 30초마다 healthcheck가 같은 cgroup 안에서 JVM(`kafka-broker-api-versions`, `-Xmx64m`)을 띄워 1.3초 동안 71~81MB를 더 씁니다. 그래서 cgroup이 448M에 자주 닿고 페이지 캐시를 회수합니다(`memory.events max` 약 20분에 2504회). OOM은 아니지만 서버에서 스왑이나 지연이 보이면 TCP healthcheck로 바꾸거나 `mem_limit`을 512m로 올립니다.
- frontend/nginx는 `worker_processes auto`라 CPU 수만큼 worker를 띄웁니다. 22코어 노트북에서 frontend `memory.peak`가 31M/32M이었고, 2 vCPU 서버에서는 더 적게 씁니다.

## 13. 문제 해결

| 증상 | 원인과 조치 |
| --- | --- |
| `deploy.sh`: `서버에 없는 이미지: ...` | 노트북에서 같은 태그로 `ship-images.sh` 실행. env의 `IMAGE_TAG`와 보낸 태그가 같은지 확인 |
| `compose config`: `XXX must be set` | env 파일의 필수 항목이 비어 있음. 메시지에 나온 변수를 채움 |
| `deploy.sh`: `chmod 600을 권장합니다` | `chmod 600 /opt/theseus/theseus.env`. Windows NTFS에서 시험할 때는 경고만 나오고 진행됨 |
| core가 기동하지 않음 | `$C logs core`: sandbox 이미지 없음(`SANDBOX_STARTUP_STRICT=true`), `THESEUS_MODEL`/`INTERNAL_API_KEY` 비어 있음(prod 검증), `SPRING_BOOT_INTERNAL_URL`이 localhost |
| api가 healthy가 안 됨 | `JWT_SECRET`이 32바이트 미만, 기존 볼륨과 DB 비밀번호 불일치, `ALLOWED_ORIGINS='*'`(prod에서 거부) |
| 채팅이 `exceeds the available context size`로 실패 | 노트북 Ollama 컨텍스트가 4096. `OLLAMA_CONTEXT_LENGTH=16384` 설정 후 Ollama 재시작([7.1](#71-노트북-ollama-설정)) |
| 채팅·PLAN이 LLM 연결 오류 | 터널 끊김. 서버에서 `curl http://172.17.0.1:11434/api/tags`, 노트북의 `llm-tunnel` 로그 확인 |
| 터널이 바로 끊기고 재시도만 반복 | 이전 세션이 서버 포트를 잡고 있음(`ExitOnForwardFailure`). 잠시 기다리거나 서버에서 남은 sshd 세션 종료. docker0 IP와 `PermitListen` 주소 불일치도 확인 |
| 기동 직후 첫 요청에 도구가 전부 붙음 | Tool RAG 모델 백그라운드 로드(약 1~2초) 전이라 보이는 도구 전부를 보냄. 로그 `[ToolRAG] 워밍업 완료`가 나온 뒤에는 일부만 보냄. 워밍업 실패 경고가 있으면 `THESEUS_EMBED_MODEL_DIR`와 이미지 빌드 로그 확인 |
| PLAN이 2분 가까이 걸림 | 작은 로컬 모델의 구조화 생성 시간(E2E 111~117초). `THESEUS_LLM_TIMEOUT_SECONDS`(300)와 API Run 타임아웃(30분) 안이면 정상 |
| HTTP 단계에서 1시간마다 로그아웃 | prod 프로필 refresh 쿠키가 `Secure`. HTTPS 적용 또는 시험용으로만 `JWT_REFRESH_TOKEN_COOKIE_SECURE=false` |
| nginx가 인증서 오류로 기동 실패 | `NGINX_TLS_MODE=http`로 임시 우회 후 `issue-cert.sh` 재실행 |
| 로그인 시 429 | `/api/v1/auth/` 분당 10회(burst 20) 제한(refresh는 별도로 분당 60회). 잠시 후 재시도. refresh가 429·5xx로 실패해도 로그인 상태는 유지됩니다 |
| Tool 사용 이력 화면이 비어 있음 | 알려진 제한([14장](#14-보안-메모와-알려진-제한)) |
| Git Bash에서 `/api/...`, `/opt/...` 인자가 `C:/Program Files/Git/...`로 바뀜 | MSYS 경로 변환. `export MSYS_NO_PATHCONV=1` |

**`down -v` 주의**: compose 파일이 네트워크(`theseus-edge`, `theseus-data`, `theseus-docker-api`)와 볼륨(`theseus-mysql-data` 등) 이름을 고정합니다. `-p`로 프로젝트 이름을 바꿔도 같은 Docker 데몬의 실제 스택과 분리되지 않고, 어떤 프로젝트 이름으로든 `down -v`를 실행하면 이 볼륨들이 지워집니다. 서버에서는 시험용 스택을 띄우거나 `down -v`를 실행하지 않습니다.

## 14. 보안 메모와 알려진 제한

- **외부 노출**: nginx만 80/443을 publish합니다. `/api/internal/**`, `/swagger-ui`, `/v3/api-docs`, `/actuator`는 nginx에서 404로 막고(`%69` 인코딩, `//`, `/../` 우회 포함), API는 prod에서 Swagger를 끕니다.
- **서버 간 인증**: API와 Core는 `INTERNAL_API_KEY`를 고정 시간 비교로 검증합니다. 비어 있으면 내부 엔드포인트가 모두 401입니다.
- **sandbox 범위**: sandbox 컨테이너(네트워크 차단, uid 65534, cap_drop ALL, read-only rootfs, pids·메모리 제한)는 **BUILD 단계의 검증 게이트**에서만 씁니다. 승인된 Tool은 Core 서버 레지스트리에 로드되어 **Core 프로세스 안에서 실행**되므로, 생성 코드가 Core 권한(docker-proxy 접근, DB 자격 증명, `INTERNAL_API_KEY`)으로 돕니다. 신뢰할 수 없는 사용자에게 Tool 생성을 열기 전에는 실행 격리가 필요합니다.
- **docker-proxy**: Core에 containers/images API와 쓰기 메서드만 열고 exec, build, networks, volumes 등은 막습니다. 컨테이너 생성 옵션 자체는 검사하지 않으므로 완전한 격리가 아니라 노출면 축소입니다.
- **Tool 사용 이력 미기록**: API에 `ToolUsageLog`를 쓰는 경로가 아직 없어(`ToolUsageService`의 TODO) 사용 이력 화면은 Tool 실행 후에도 비어 있습니다.
- **토큰 사용량 0**: 도구가 붙은 스트림(ASK/AGENT)에서는 Core가 `stream_options.include_usage`를 보내지 않아 사용량이 0으로 기록됩니다.
