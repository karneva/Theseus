# Theseus 단일 서버 셀프호스팅

> 전체 절차(검증 체크리스트, 업그레이드, 실측 메모리, 문제 해결 포함)의 정본은 [docs/operations/self-hosting.md](../../../docs/operations/self-hosting.md)입니다. 이 파일은 이 디렉터리 구성 요약입니다.

서버 한 대(Ubuntu 24.04, 2 vCPU, 3.8GB RAM, 스왑 4GB)에 docker compose로 전체 스택을 올리는 구성입니다.

- **이미지는 개발 노트북에서 빌드**하고 서버로 옮깁니다. 서버에서는 빌드하지 않습니다.
- **LLM**은 노트북의 Ollama(파인튜닝 모델)를 reverse SSH tunnel로 서버에 연결해 씁니다.
- 외부에는 nginx의 **80/443만** 열립니다. API(8080), Core(8086), Kafka, DB는 publish하지 않습니다.

> **보안 주의: PLAN 승인은 코드 실행 권한을 주는 것과 같습니다.** 승인된 PLAN으로 BUILD된 Tool은 sandbox가 아니라
> **Core 프로세스 안에서** 실행됩니다. 생성 코드는 Core의 env(`INTERNAL_API_KEY`, `POSTGRES_PASSWORD`, LLM 키), 내부 네트워크
> (Kafka, API 내부 엔드포인트)와 docker-proxy에 그대로 닿고, docker-proxy는 컨테이너 생성 옵션을 검사하지 않으므로
> privileged 컨테이너를 만들어 **호스트 root까지** 얻을 수 있습니다. 관리자는 승인 전에 PLAN이 만들 코드의 동작을 확인하고,
> `canCreateTool` 권한은 서버 root를 맡길 수 있는 사람에게만 줍니다. 실행 격리(Tool Runner 분리)는 후속 과제입니다.

```
 Internet ─▶ :80/:443 [nginx] ─┬─▶ [frontend]                        (edge)
                               └─▶ [api :8080] ──▶ [mysql] [redis]     (edge + data)
                                      │  ▲
                              Kafka ◀─┘  └─ HTTP ── [core :8086] ──▶ [postgres+pgvector]
                                                      │  └─▶ host.docker.internal:11434 ─(SSH -R)─▶ 노트북 Ollama
                                                      └─▶ [docker-proxy] ─▶ docker.sock ─▶ sandbox 컨테이너(network none)
```

| 파일 | 역할 |
|---|---|
| `docker-compose.yml` | 전체 서비스, 네트워크(edge / data(internal) / docker-api(internal)), 볼륨, 헬스체크, 메모리 제한 |
| `.env.example` | 서버 env 템플릿. 서버에서는 `/opt/theseus/theseus.env`로 복사해 씁니다 |
| `nginx/` | 엣지 nginx 이미지. `templates/http`(인증서 발급 전)와 `templates/https`를 인증서 유무로 자동 선택 |
| `mysql/conf.d/low-memory.cnf` | MySQL 저메모리 설정(performance_schema OFF, buffer pool 128M) |
| `postgres/initdb/001_pgvector.sql` | 첫 기동 시 pgvector 확장 생성 |
| `../../../scripts/*.sh` | 서버 준비, 이미지 빌드·전송, 배포, 비밀 생성, 인증서, 백업, LLM 터널 |

## 1. 메모리 예산

RAM 3.8GB 중 컨테이너 상한 합계를 약 3.34GiB로 잡고, 순간적으로 넘치는 양은 스왑(4GB)이 받습니다.
`mem_limit`은 하드 상한이고, Docker는 스왑이 있으면 기본으로 같은 양까지 스왑을 더 쓰게 합니다(core는 `memswap_limit: 3g`로 명시).

| 서비스 | mem_limit | 설정 근거 |
|---|---:|---|
| core | 1536m | torch(CPU)와 sentence-transformers를 로드합니다. 스왑 포함 3g까지 허용 |
| api | 640m | `JAVA_TOOL_OPTIONS=-Xmx384m -XX:+UseSerialGC -XX:MaxMetaspaceSize=160m ...` |
| kafka | 448m | `KAFKA_HEAP_OPTS=-Xmx256m -Xms256m`, KRaft 단일 노드 |
| mysql | 384m | buffer pool 128M, performance_schema OFF, max_connections 40 |
| postgres | 160m | shared_buffers 64MB, max_connections 40 |
| redis | 64m | maxmemory 48mb(volatile-lru), AOF |
| nginx | 64m | |
| certbot | 64m | 12시간마다 renew |
| frontend | 32m | 정적 파일 |
| docker-proxy | 32m | haproxy |
| **합계** | **3424m** | 약 3.34GiB |

- 일회성 서비스: kafka-init 256m, core-permissions 32m. 기동할 때 잠깐 돌고 끝납니다.
- sandbox 컨테이너는 BUILD 단계의 Tool 검증마다 `SANDBOX_MEMORY_LIMIT`(기본 128m)로 잠깐 실행됩니다. 승인된 Tool은 sandbox가 아니라 Core 프로세스 안에서 실행됩니다.
- `ops` 프로필의 kafka-ui(384m)는 예산에 넣지 않았습니다. 필요할 때만 띄웁니다.
- 실제 사용량은 `docker stats --no-stream`으로 확인합니다. core가 자주 스왑을 쓰면 임베딩 모델을 원격으로 돌리거나 서버 메모리를 늘립니다.

## 2. 첫 기동

### 2.1 서버 준비(처음 한 번)

새 서버에는 아직 `/opt/theseus/app`이 없고 SSH 사용자가 docker 그룹에 없어서 `ship-images.sh`가 동작하지 않습니다.
다른 파일에 의존하지 않는 `server-bootstrap.sh`만 먼저 복사해 실행합니다(Docker Engine과 compose 플러그인은 설치되어 있어야 합니다).

```bash
# 노트북
scp scripts/server-bootstrap.sh <서버별칭>:/tmp/
ssh -t <서버별칭> 'sudo bash /tmp/server-bootstrap.sh'
# 4G swapfile, vm.swappiness, /opt/theseus 디렉터리(app은 배포 사용자 소유), theseus.env(600 빈 파일),
# docker 그룹 추가, ufw 22/80/443, LLM 터널용 sshd 설정을 합니다.
# docker 그룹은 다음 로그인부터 적용되므로 SSH 연결을 새로 엽니다(ControlMaster를 쓰면 ssh -O exit <서버별칭>).
```

### 2.2 노트북(Windows + Docker Desktop, Git Bash)

```bash
# 1) 이미지 빌드. 태그를 생략하면 git short sha를 씁니다.
scripts/build-images.sh            # 예: TAG=3f2a1bc

# 2) 서버로 전송(서버 SSH 별칭은 ~/.ssh/config에 둡니다). --with-config는 compose/스크립트도 함께 복사합니다.
scripts/ship-images.sh --with-config <서버별칭> 3f2a1bc
```

`ship-images.sh`는 `docker save | gzip | ssh <서버> docker load`로 옮깁니다. 서버 사용자가 docker 그룹에 있어야 합니다(2.1).
전송 전에 서버에서 docker 사용 권한과 설정 복사 위치를 확인하고, 준비가 안 되어 있으면 바로 멈춥니다.
`--with-config`를 쓰면 `infra/docker/selfhost`와 `scripts`가 서버의 `/opt/theseus/app`(기본값)에 풀립니다.
서버에서 `git clone`해서 써도 됩니다.

### 2.3 서버

```bash
# 1) env 작성(sudo 없이 배포 사용자로). bootstrap이 /opt/theseus/theseus.env를 배포 사용자 소유 600 빈 파일로 만들어 둡니다.
cp /opt/theseus/app/infra/docker/selfhost/.env.example /opt/theseus/theseus.env
chmod 600 /opt/theseus/theseus.env
/opt/theseus/app/scripts/gen-secrets.sh --fill /opt/theseus/theseus.env   # 비어 있는 비밀값만 새로 채웁니다
vi /opt/theseus/theseus.env   # DOMAIN, CERTBOT_EMAIL, IMAGE_TAG, THESEUS_MODEL, INITIAL_ADMIN_* 입력

# 2) 배포: 이미지 확인 -> compose config 검증 -> up -d(빌드 없음) -> 모든 서비스가 healthy가 될 때까지 대기
/opt/theseus/app/scripts/deploy.sh
```

기동 순서는 compose의 `depends_on: service_healthy`가 맞춥니다.
mysql/redis/kafka(+kafka-init으로 토픽 4개와 DLT 2개 생성) → api(Flyway 마이그레이션) → core(postgres, docker-proxy, sandbox 이미지 확인) → frontend → nginx 순서입니다.

- **관리자 계정**: `INITIAL_ADMIN_EMPLOYEE_NUMBER/NAME/PASSWORD`(EMAIL 선택)를 넣고 처음 기동하면 SUPER_ADMIN이 생성됩니다. 로그인을 확인한 뒤 env 파일에서 `INITIAL_ADMIN_PASSWORD`를 지우고 `deploy.sh`를 다시 실행합니다.
- **sandbox 이미지**: `SANDBOX_STARTUP_STRICT=true`(기본)라 `theseus-sandbox:py311-tools`가 서버에 없으면 core가 기동하지 않습니다. `build-images.sh`와 `ship-images.sh`가 함께 처리합니다.
- **점검**: 서버에서 `ss -tlnp`로 22/80/443(그리고 터널 11434)만 열렸는지, 외부에서 `curl -i https://<도메인>/api/internal/auth/verify`가 404인지 확인합니다.

### 2.4 업데이트

노트북에서 새 태그로 `build-images.sh` → `ship-images.sh`를 실행하고, 서버 env의 `IMAGE_TAG`를 바꾼 뒤 `deploy.sh`를 실행합니다.
DB, custom-tools, core-data는 볼륨과 `/opt/theseus` 아래에 있으므로 `docker compose down && up -d`에도 유지됩니다.
이전 이미지는 `docker image prune`으로 정리합니다.

## 3. TLS(Let's Encrypt)

nginx 컨테이너는 기동할 때 `/etc/letsencrypt/live/$DOMAIN/`에 인증서가 있는지 보고 템플릿을 고릅니다.

1. 도메인 A 레코드를 서버 공인 IP로 지정합니다. 클라우드 보안그룹도 22/80/443만 엽니다.
2. 인증서가 없으면 nginx는 **HTTP 템플릿**으로 뜹니다. ACME webroot(`/.well-known/acme-challenge/`)와 앱을 HTTP로 서빙합니다.
3. 인증서를 발급합니다. 발급에 성공하면 스크립트가 nginx를 재시작해 **HTTPS 템플릿**(80→443 리다이렉트, HSTS)으로 바꿉니다.
   ```bash
   /opt/theseus/app/scripts/issue-cert.sh            # 처음에는 --staging으로 연습해도 됩니다
   ```
4. 갱신은 자동입니다. certbot 컨테이너가 12시간마다 `certbot renew`를 실행하고, nginx가 6시간마다 reload합니다.

- HTTP 단계에서는 prod 프로필이 refresh 쿠키에 `Secure`를 붙이므로 access 토큰이 만료(기본 1시간)되면 다시 로그인해야 합니다. 도메인 없이 IP로만 시험한다면 `JWT_REFRESH_TOKEN_COOKIE_SECURE=false`로 잠시 바꿉니다.
- 인증서 문제로 nginx가 뜨지 않으면 `NGINX_TLS_MODE=http`로 HTTP 템플릿을 강제할 수 있습니다.
- HSTS는 `HSTS_MAX_AGE`(기본 1년)로 조절합니다. HTTPS를 처음 켤 때 불안하면 300 같은 작은 값으로 시작합니다.

## 4. LLM 터널(노트북 Ollama → 서버 Core)

Core는 `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`로 LLM을 호출합니다.
`host.docker.internal`은 `extra_hosts: host-gateway`로 호스트의 docker0 IP(기본 `172.17.0.1`)로 해석됩니다.

sshd는 원격 포워드를 기본으로 `127.0.0.1`에만 열기 때문에, 컨테이너에서 접근하려면 docker0 IP에 열어야 합니다.
이 구성은 **sshd `GatewayPorts clientspecified` + `PermitListen`으로 docker0 IP에 직접 바인딩**하는 방식을 씁니다.
sidecar 컨테이너가 없어 메모리를 더 쓰지 않고, 터널이 끊겨도 서버 쪽에서 다시 맞출 상태가 없습니다.

- `server-bootstrap.sh`가 설정하는 내용입니다.
  - `/etc/ssh/sshd_config.d/60-theseus-llm-tunnel.conf`
    ```
    GatewayPorts clientspecified
    PermitListen 172.17.0.1:11434 127.0.0.1:11434 localhost:11434
    ClientAliveInterval 15
    ClientAliveCountMax 3
    ```
    `PermitListen` 때문에 원격 포워드는 이 주소와 포트로만 열 수 있습니다(임의 주소, 0.0.0.0 공개는 거부됩니다).
    `ClientAlive*`는 노트북이 잠들거나 네트워크가 바뀐 뒤 남은 세션을 약 45초 안에 끊어, 터널이 같은 포트로 다시 열리게 합니다.
  - ufw: `allow in on theseus-edge to 172.17.0.1 port 11434 proto tcp`. compose의 edge 네트워크는 브리지 이름을 `theseus-edge`로 고정해 둡니다.
    ufw의 기본 정책(incoming deny)이 컨테이너에서 호스트로 들어오는 트래픽도 막기 때문에 필요합니다. 외부 인터페이스에서는 11434가 열리지 않습니다.
- 노트북에서 실행합니다(끊기면 자동으로 다시 연결).
  ```bash
  scripts/llm-tunnel.sh <서버별칭>                        # Git Bash / Linux / macOS
  ```
  ```powershell
  .\scripts\llm-tunnel.ps1 -SshHost <서버별칭>             # Windows PowerShell(OpenSSH 클라이언트)
  ```
  실제로는 `ssh -N -R 172.17.0.1:11434:127.0.0.1:11434 <서버별칭>`입니다. docker0 IP가 다르면 `--bind`(`-BindAddress`)로 바꿉니다.
- 서버 env에는 `THESEUS_MODEL=ollama/<모델명>`을 넣습니다. 노트북 모델은 응답이 느릴 수 있어 `THESEUS_LLM_TIMEOUT_SECONDS=300`을 기본으로 둡니다. 컨텍스트가 짧은 모델이면 `LLM_MAX_OUTPUT_TOKENS`를 낮춥니다.
- 노트북 Ollama는 `OLLAMA_CONTEXT_LENGTH=16384` 이상으로 실행합니다. 기본 컨텍스트(VRAM 24GB 미만 GPU에서 4096)로는 Core 프롬프트가 들어가지 않아 채팅이 HTTP 400으로 실패합니다.
- 확인: 서버에서 `curl -s http://172.17.0.1:11434/api/tags`, 컨테이너 안에서 `docker compose ... exec core python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').read()[:200])"`.
- 터널이 끊겨 있는 동안 채팅과 PLAN/BUILD는 LLM 연결 오류로 실패합니다. 다른 기능(로그인, 프로젝트, Tool 목록)은 영향이 없습니다.

## 5. 백업과 복구

```bash
# 매일 03:30 백업(root crontab). 기본 보관 기간은 14일입니다(BACKUP_RETENTION_DAYS).
30 3 * * * /opt/theseus/app/scripts/backup.sh >> /opt/theseus/backups/backup.log 2>&1
```

`backup.sh`는 `/opt/theseus/backups/<시각>/`에 다음을 만듭니다.

| 파일 | 내용 |
|---|---|
| `mysql-theseus.sql.gz` | `mysqldump --single-transaction` (API DB) |
| `postgres-theseus_core.dump` | `pg_dump -Fc` (Core DB, pgvector 포함) |
| `files.tar.gz` | `/opt/theseus/custom-tools`, `/opt/theseus/core-data` |

Redis(refresh 토큰, Run 상태)와 Kafka는 일시 데이터라 백업하지 않습니다. 복구하면 사용자는 다시 로그인합니다.
백업 디렉터리는 같은 디스크에 있으므로 주기적으로 서버 밖(노트북, 오브젝트 스토리지)으로 복사합니다.

복구 절차(빈 서버 또는 볼륨을 지운 뒤):

```bash
B=/opt/theseus/backups/<시각>
C="docker compose -f /opt/theseus/app/infra/docker/selfhost/docker-compose.yml --env-file /opt/theseus/theseus.env"

$C up -d --wait mysql postgres                # 데이터 계층만 먼저. 첫 초기화(임시 서버)가 끝나 healthy가 될 때까지 기다립니다
gunzip -c $B/mysql-theseus.sql.gz | $C exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot'
$C exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < $B/postgres-theseus_core.dump
sudo tar -xzf $B/files.tar.gz -C /opt/theseus  # custom-tools, core-data
/opt/theseus/app/scripts/deploy.sh             # 나머지 기동(core-permissions가 소유권을 다시 맞춥니다)
```

복구 리허설을 한 번은 해 둡니다.

## 6. 운영 메모

- 상태 확인: `docker compose -f ... --env-file ... ps`, 로그: `... logs -f --tail=200 api core`
- Kafka UI: `... --profile ops up -d kafka-ui` 후 노트북에서 `ssh -L 8091:127.0.0.1:8091 <서버별칭>` → `http://localhost:8091`
- 로그는 컨테이너마다 json-file 10MB × 3개로 회전합니다.
- docker-proxy는 Core에 containers/images API만 열어 줍니다. 생성 옵션까지 검사하지는 않고, 승인된 Tool은 Core 권한으로 실행되므로, 외부 사용자에게 Tool 생성을 열기 전에는 Tool Runner 분리(별도 격리 런타임)가 필요합니다.
- compose가 볼륨·네트워크 이름(`theseus-*`)을 고정하므로 `-p`로 프로젝트 이름을 바꿔도 같은 데몬의 스택과 분리되지 않습니다. 서버에서 `down -v`를 실행하면 실제 데이터 볼륨이 지워집니다.
