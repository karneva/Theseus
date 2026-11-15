# Infra

| 경로 | 용도 |
|---|---|
| `docker/local/` | 로컬 개발용 compose(인프라, API, Core). 호스트 포트는 모두 `127.0.0.1`에만 열립니다 |
| `docker/selfhost/` | 단일 서버 셀프호스팅 compose와 nginx 이미지. 절차는 [`docker/selfhost/README.md`](docker/selfhost/README.md) |
| `../scripts/` | 셀프호스팅 이미지 빌드·전송·배포·백업·LLM 터널 스크립트 |

## 로컬 개발

### 1. env 파일

```bash
cp infra/docker/local/.env.local.example infra/docker/local/.env.local
```

비밀번호, `JWT_SECRET`(32바이트 이상), `INTERNAL_API_KEY`를 로컬 전용 값으로 채웁니다.
이 파일은 local compose 컨테이너와 IDE에서 띄운 API Server(local 프로필)가 함께 읽고, git에는 올라가지 않습니다.
`SPRING_DATASOURCE_PASSWORD`는 `MYSQL_PASSWORD`와 같은 값이어야 하고, Redis는 `SPRING_DATA_REDIS_PASSWORD`를 비밀번호로 씁니다.

### 2. 인프라만 띄우고 API는 IDE에서 실행(권장)

```bash
docker compose -f infra/docker/local/docker-compose.infra.yml up -d
```

| 서비스 | 호스트 주소 | 컨테이너 네트워크 주소 |
|---|---|---|
| MySQL | `127.0.0.1:13306` | `theseus-local-mysql:3306` |
| PostgreSQL + pgvector | `127.0.0.1:15432` | `theseus-local-postgres:5432` |
| Redis(비밀번호 필요) | `127.0.0.1:16379` | `theseus-local-redis:6379` |
| Kafka | `127.0.0.1:19092` | `theseus-local-kafka:29092` |
| Kafka UI | `http://127.0.0.1:18080` | – |

kafka-init이 업무 토픽 4개와 DLT 토픽 2개(`theseus.tool-plan.event.DLT`, `theseus.tool-build.event.DLT`)를 만듭니다.
IDE의 API Server는 local 프로필로 `infra/docker/local/.env.local`을 읽습니다.
compose의 API 컨테이너와 동시에 띄우면 둘 다 8080을 쓰므로 충돌합니다.

```bash
docker exec -it theseus-local-redis sh -c 'REDISCLI_AUTH="$SPRING_DATA_REDIS_PASSWORD" redis-cli ping'
docker exec -it theseus-local-kafka kafka-topics --bootstrap-server theseus-local-kafka:29092 --list
```

### 3. 전체 Docker 통합 확인

```bash
docker compose \
  -f infra/docker/local/docker-compose.infra.yml \
  -f infra/docker/local/docker-compose.api.yml \
  -f infra/docker/local/docker-compose.core.yml \
  up -d
```

- core compose는 `backend/theseus-core-server/Dockerfile.sandbox`로 `theseus-sandbox:py311-tools`를 빌드합니다.
- Core는 `docker.sock`을 직접 마운트하지 않고 `theseus-local-docker-proxy`(containers/images API만 허용)를 거쳐 sandbox 컨테이너를 만듭니다. `DOCKER_GID`를 맞출 필요가 없습니다.
- 생성 Tool은 `theseus-local-custom-tools` 볼륨(`/custom-tools`)에 저장되어 컨테이너를 다시 만들어도 남습니다.
- Core는 `host.docker.internal:11434`로 노트북의 Ollama에 닿습니다(`THESEUS_MODEL=ollama/<모델>`).

## 셀프호스팅

서버 한 대(2 vCPU, 3.8GB RAM)에 전체 스택을 올리는 방법, 메모리 예산, TLS, LLM 터널, 백업은
[`docker/selfhost/README.md`](docker/selfhost/README.md)에 있습니다.
