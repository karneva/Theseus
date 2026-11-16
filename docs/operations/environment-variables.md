# 환경 변수

실행 환경별 템플릿이 값의 기준이고, 이 문서는 이름·필수 여부·기본값·용도를 한곳에 모은 참조표입니다.
관리 원칙(커밋 금지, 템플릿 갱신 규칙)은 [conventions/environment-variables.md](../conventions/environment-variables.md)에 있습니다.

| 실행 환경 | 템플릿 | 실제 파일(커밋 금지) |
| --- | --- | --- |
| 단일 서버 셀프호스팅 | [`infra/docker/selfhost/.env.example`](../../infra/docker/selfhost/.env.example) | `/opt/theseus/theseus.env`(권한 600) |
| 로컬 개발(local compose, IDE의 API) | [`infra/docker/local/.env.local.example`](../../infra/docker/local/.env.local.example) | `infra/docker/local/.env.local` |
| Core 단독 실행(uvicorn) | [`backend/theseus-core-server/.env.example`](../../backend/theseus-core-server/.env.example) | `backend/theseus-core-server/.env` |
| Frontend | [`frontend/.env.example`](../../frontend/.env.example) | `frontend/.env.local` |

서비스 사이에 공유하는 이름은 `INTERNAL_API_KEY`(API·Core 같은 값)와 `KAFKA_TOPIC_TOOL_PLAN_REQUEST` / `_PLAN_EVENT` / `_BUILD_REQUEST` / `_BUILD_EVENT`(API·Core·kafka-init)입니다.

## 1. 셀프호스팅 env 파일

`docker-compose.yml`은 이 파일을 `--env-file`로만 읽어 변수를 치환하고, 각 컨테이너에는 필요한 값만 골라 넘깁니다. 필수 항목이 비어 있으면 compose가 멈춥니다.
**비밀값** 표시는 `scripts/gen-secrets.sh --fill`이 채우는 키입니다.

| 이름 | 필수 | 기본값 | 용도 / 전달 대상 |
| --- | :---: | --- | --- |
| `DOMAIN` | ✅ | | nginx `server_name`, 인증서 경로, `issue-cert.sh` 대상 |
| `CERTBOT_EMAIL` | ✅ | | Let's Encrypt 계정 메일(`issue-cert.sh`) |
| `TZ` | | `Asia/Seoul` | 모든 컨테이너 시간대, JDBC `serverTimezone` |
| `THESEUS_HOST_ROOT` | | `/opt/theseus` | 호스트 bind 루트. Core의 `SANDBOX_HOST_TEMP_ROOT`, `THESEUS_CUSTOM_TOOLS_HOST_DIR`를 여기서 만듭니다 |
| `IMAGE_TAG` | ✅ | | api/core/frontend/nginx 이미지 태그 |
| `IMAGE_REGISTRY` | | (빈 값) | 레지스트리 접두사(끝에 `/`). 비우면 로컬 이미지 이름 |
| `SANDBOX_IMAGE` | | `theseus-sandbox:py311-tools` | Core sandbox 이미지 |
| `JWT_SECRET` | ✅ 비밀값 | | API JWT HMAC 키(32바이트 이상) |
| `INTERNAL_API_KEY` | ✅ 비밀값 | | API·Core 공유 키 |
| `MYSQL_ROOT_PASSWORD` | ✅ 비밀값 | | MySQL root(백업, healthcheck) |
| `MYSQL_PASSWORD` | ✅ 비밀값 | | API DB 비밀번호 → `SPRING_DATASOURCE_PASSWORD` |
| `POSTGRES_PASSWORD` | ✅ 비밀값 | | Core DB 비밀번호 → `CORE_POSTGRES_PASSWORD` |
| `REDIS_PASSWORD` | ✅ 비밀값 | | Redis `requirepass` → `SPRING_DATA_REDIS_PASSWORD` |
| `KAFKA_CLUSTER_ID` | ✅ 비밀값 | | KRaft `CLUSTER_ID`(base64url 22자). kafka 볼륨을 지우기 전까지 고정 |
| `MYSQL_DATABASE` / `MYSQL_USER` | | `theseus` / `theseus` | API DB 이름·사용자 → `SPRING_DATASOURCE_URL` / `_USERNAME` |
| `POSTGRES_DB` / `POSTGRES_USER` | | `theseus_core` / `theseus` | Core DB 이름·사용자 → `CORE_POSTGRES_DB` / `_USER` |
| `ALLOWED_ORIGINS` | | (빈 값) | API CORS. same-origin이면 비움(CORS off). Core에는 항상 빈 값 |
| `JWT_REFRESH_TOKEN_COOKIE_SECURE` | | `true` | HTTP로만 시험할 때만 `false` |
| `INITIAL_ADMIN_EMPLOYEE_NUMBER` / `_NAME` / `_EMAIL` / `_PASSWORD` | | (빈 값) | SUPER_ADMIN이 없을 때 최초 관리자 생성. EMAIL만 선택 |
| `JAVA_TOOL_OPTIONS` | | `-Xms192m -Xmx384m -Xss512k -XX:MaxMetaspaceSize=160m -XX:ReservedCodeCacheSize=64m -XX:MaxDirectMemorySize=64m -XX:+UseSerialGC -XX:+ExitOnOutOfMemoryError` | API JVM 옵션 |
| `THESEUS_MODEL` | ✅ | | Core 모델(provider 접두사, 예: `ollama/<모델>`) |
| `OLLAMA_BASE_URL` | | `http://host.docker.internal:11434/v1` | 노트북 Ollama(reverse SSH tunnel) |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` | | (빈 값) | 외부 provider를 쓸 때만 |
| `THESEUS_LLM_TIMEOUT_SECONDS` | | `300` | LLM 호출 timeout(Core 코드 기본 120보다 길게) |
| `LLM_MAX_OUTPUT_TOKENS` | | `32768` | Core 출력 토큰 상한. 작은 로컬 모델이면 낮춤(예: 4096) |
| `CORE_TOOL_PLAN_CONSUMER_ENABLED` / `CORE_TOOL_BUILD_CONSUMER_ENABLED` | | `true` | Core Kafka consumer 스위치 |
| `SANDBOX_STARTUP_STRICT` | | `true` | sandbox 이미지가 없으면 Core 기동 거부 |
| `SANDBOX_MEMORY_LIMIT` | | `128m` | sandbox 컨테이너 메모리 |
| `REMOTE_WORKSPACE_KEYS_DIR` | | `<THESEUS_HOST_ROOT>/ssh-keys` | Remote Workspace SSH 키 디렉터리 → Core `/home/appuser/.ssh:ro` |
| `KAFKA_TOPIC_TOOL_PLAN_REQUEST` / `_PLAN_EVENT` / `_BUILD_REQUEST` / `_BUILD_EVENT` | | `theseus.tool-plan.request` / `theseus.tool-plan.event` / `theseus.tool-build.request` / `theseus.tool-build.event` | api, core, kafka-init 공유. DLT는 `<EVENT 토픽>.DLT` |
| `KAFKA_TOPIC_PARTITIONS` | | `3` | 업무 토픽 파티션 수(DLT는 1) |
| `KAFKA_HEAP_OPTS` | | `-Xmx256m -Xms256m` | Kafka 브로커 힙(템플릿에는 없음, compose 기본값) |
| `NGINX_TLS_MODE` | | `auto` | `auto`(인증서 유무로 선택) / `http` / `https` |
| `HSTS_MAX_AGE` | | `31536000` | HTTPS HSTS max-age(초) |
| `KAFKA_UI_PORT` | | `8091` | `ops` 프로필 kafka-ui 루프백 포트(템플릿에는 없음) |

compose가 값을 고정해 넘기는 항목(env 파일에서 바꾸지 않음): API의 `SPRING_PROFILES_ACTIVE=prod`, `SERVER_PORT=8080`, `SPRINGDOC_ENABLED=false`, `THESEUS_CORE_BASE_URL=http://core:8086`, Core의 `ENV=prod`, `AUTH_MODE=spring`, `SPRING_BOOT_INTERNAL_URL=http://api:8080`, `DOCKER_HOST=tcp://docker-proxy:2375`, sandbox·custom-tools·데이터 경로.

### 스크립트 옵션(서비스 env 아님)

| 이름 | 기본값 | 쓰는 스크립트 |
| --- | --- | --- |
| `THESEUS_ENV_FILE` | `/opt/theseus/theseus.env` | deploy, backup, issue-cert |
| `SELFHOST_COMPOSE_FILE` | `<저장소>/infra/docker/selfhost/docker-compose.yml` | deploy, backup, issue-cert |
| `THESEUS_SSH_HOST` | (빈 값) | ship-images, llm-tunnel(인자 대신) |
| `BUILD_PLATFORM` | `linux/amd64` | build-images |
| `GZIP_LEVEL` | `3` | ship-images |
| `BACKUP_RETENTION_DAYS` | `14` | backup |

## 2. API Server(Spring Boot)

기본값은 `application.yaml`(공통)과 `application-local.yml` / `application-prod.yml`(차이) 기준입니다. local 프로필은 `./.env.local`과 `../../infra/docker/local/.env.local`을 properties로 읽습니다.

| 이름 | 필수 | 기본값 | 용도 |
| --- | :---: | --- | --- |
| `SPRING_PROFILES_ACTIVE` | | `local`(profiles.default) | `local` 또는 `prod` |
| `SPRING_DATASOURCE_URL` | ✅ | local: `jdbc:mysql://localhost:13306/theseus` | MySQL 접속 URL |
| `SPRING_DATASOURCE_USERNAME` | ✅ | local: `theseus` | MySQL 사용자 |
| `SPRING_DATASOURCE_PASSWORD` | ✅ | | MySQL 비밀번호 |
| `SPRING_DATA_REDIS_HOST` | | `localhost` | Redis(refresh 토큰, Run 상태) |
| `SPRING_DATA_REDIS_PORT` | | `6379`(local `16379`) | Redis 포트 |
| `SPRING_DATA_REDIS_PASSWORD` | | (빈 값) | Redis 비밀번호 |
| `SPRING_KAFKA_BOOTSTRAP_SERVERS` | ✅ | local: `localhost:19092` | Kafka 브로커 |
| `SPRING_KAFKA_CONSUMER_GROUP_ID` | | `theseus-api-tool-generation` | 결과 이벤트 consumer group |
| `THESEUS_CORE_BASE_URL` | ✅ | local: `http://localhost:8086` | Core base URL(prod 기본값 없음) |
| `JWT_SECRET` | ✅ | | JWT HMAC 키. 32바이트 미만이면 기동 실패 |
| `INTERNAL_API_KEY` | ✅ | (빈 값) | Core ↔ API 내부 호출 키. 비면 `/api/internal/**` 전부 401 |
| `ALLOWED_ORIGINS` | | (빈 값 = CORS off), local: `http://localhost:5173,http://localhost:3000` | 쉼표 구분 origin. prod에서 `*`는 기동 거부 |
| `KAFKA_TOPIC_*` | | 위 셀프호스팅 표와 같음 | PLAN/BUILD 요청·결과 토픽 |
| `INITIAL_ADMIN_*` | | (빈 값) | 최초 SUPER_ADMIN(사번·이름·비밀번호 필수, 이메일 선택) |
| `SERVER_PORT` | | `8080` | HTTP 포트 |
| `SPRINGDOC_ENABLED` | | `true`(prod `false`) | Swagger UI, api-docs |
| `JWT_ACCESS_TOKEN_EXPIRATION_MILLIS` | | `3600000` | access 토큰 만료(1시간) |
| `JWT_REFRESH_TOKEN_EXPIRATION_MILLIS` | | `1209600000` | refresh 토큰 만료(14일) |
| `JWT_REFRESH_TOKEN_COOKIE_SECURE` | | `false`(prod `true`) | refresh 쿠키 Secure |
| `JWT_REFRESH_TOKEN_COOKIE_NAME` / `_PATH` / `_SAME_SITE` | | `refresh_token` / `/api/v1/auth` / `Lax` | refresh 쿠키 속성 |
| `SPRING_MVC_ASYNC_REQUEST_TIMEOUT_MILLIS` | | `1800000` | 스트림 async 타임아웃 |
| `THESEUS_TOOL_GENERATION_STATE_TTL_MINUTES` | | `30` | Redis Run 상태 TTL |
| `THESEUS_TOOL_GENERATION_SSE_TIMEOUT_MILLIS` | | `1800000` | SSE emitter 타임아웃 |
| `THESEUS_TOOL_PLAN_RUN_TIMEOUT_SCHEDULER_ENABLED` | | `true` | 결과 이벤트가 오지 않은 Run을 실패 처리 |
| `THESEUS_TOOL_PLAN_RUN_TIMEOUT_MINUTES` / `_CHECK_DELAY_MILLIS` / `_BATCH_SIZE` | | `30` / `60000` / `20` | 타임아웃 스케줄러(MINUTES는 GENERATING Run 기준) |
| `THESEUS_TOOL_PLAN_REQUESTED_RUN_TIMEOUT_MINUTES` | | `180` | Core 대기열에서 아직 시작되지 않은 REQUESTED Run의 제한 시간 |
| `JAVA_TOOL_OPTIONS` | | 이미지: `-XX:MaxRAMPercentage=75` | JVM 옵션 |
| `TZ` | | 이미지: `Asia/Seoul` | 시간대 |

## 3. Core Server(FastAPI, theseus_engine)

`src/config.py`와 `theseus_engine/config.py` 기준입니다. `ENV=prod`이면 `INTERNAL_API_KEY`, `THESEUS_MODEL`이 비어 있거나 `SPRING_BOOT_INTERNAL_URL`이 localhost면 기동하지 않습니다.
엔진 튜닝 항목(agent loop, repair 횟수, RAG, 디버그 덤프 등)은 [`.env.example`](../../backend/theseus-core-server/.env.example)의 주석을 참고하세요.

| 이름 | 필수 | 기본값 | 용도 |
| --- | :---: | --- | --- |
| `ENV` | | `local` | `local` / `prod`(dev, test는 하위호환). prod는 fail-fast 검증 |
| `PORT` | | `8086` | uvicorn 포트(이미지 CMD, HEALTHCHECK) |
| `INTERNAL_API_KEY` | ✅ | (빈 값) | API와 공유하는 키. 예전 이름 `SPRING_BOOT_INTERNAL_API_KEY`도 읽음 |
| `SPRING_BOOT_INTERNAL_URL` | ✅ | `http://localhost:8080` | API base URL. `/api/internal/...` 경로는 코드가 조합 |
| `SPRING_BOOT_AUTH_VERIFY_URL` 등 `SPRING_BOOT_*_URL` 5개 | | (base + 경로) | 개별 URL override. 보통 비움 |
| `AUTH_MODE` | | `spring` | `spring` / `mock`(mock은 local·dev·test만) |
| `ALLOWED_ORIGINS` | | (빈 값) | 비면 local은 개발 서버 origin 허용, prod는 CORS off |
| `CORE_POSTGRES_HOST` / `_PORT` / `_DB` / `_USER` / `_PASSWORD` | ✅ | `localhost` / `15432` / `theseus_core` / `root` / (빈 값) | Postgres + pgvector. `POSTGRES_*` 별칭도 읽음 |
| `CORE_POSTGRES_SCHEMA` | | `public` | public이 아니면 `search_path=<schema>,public` |
| `CORE_POSTGRES_POOL_SIZE` / `_MAX_OVERFLOW` | | `5` / `10` | SQLAlchemy 커넥션 풀 |
| `CORE_KAFKA_BOOTSTRAP_SERVERS` | ✅ | `localhost:19092` | Kafka |
| `CORE_KAFKA_CONSUMER_ENABLED` | | `true` | 모든 consumer master 스위치 |
| `CORE_TOOL_PLAN_CONSUMER_ENABLED` / `CORE_TOOL_BUILD_CONSUMER_ENABLED` | | `true` / `true` | PLAN·BUILD 요청 consumer |
| `KAFKA_TOPIC_*` | | 위와 같음 | PLAN/BUILD 토픽 |
| `THESEUS_MODEL` | ✅(prod) | local: `gpt-4o` 대체값 | provider 접두사 모델(`ollama/`, `vllm/`, `openai/`, `anthropic/`, `gemini/`, `deepseek/`) |
| `OLLAMA_BASE_URL` | | `http://localhost:11434/v1` | `ollama/*` endpoint |
| `OPENAI_BASE_URL` | | OpenAI SDK 기본(vLLM은 `http://localhost:8000/v1`) | OpenAI 호환 / vLLM endpoint |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` | | (빈 값) | 사용하는 provider 키 |
| `GEMINI_BASE_URL` / `DEEPSEEK_BASE_URL` | | 각 provider 공식 endpoint | endpoint override |
| `THESEUS_LLM_TIMEOUT_SECONDS` | | `120` | LLM 호출 timeout |
| `THESEUS_LLM_MAX_RETRIES` | | `3` | LLM 재시도 횟수 |
| `LLM_MAX_OUTPUT_TOKENS` | | `32768` | PLAN/BUILD/repair/stream 출력 토큰 상한 |
| `CORE_STREAM_MAX_AGENT_TURNS` / `CORE_TOOL_PLAN_MAX_AGENT_TURNS` | | `30` / `30` | 채팅 스트림·PLAN의 최대 agent turn |
| `DOCKER_HOST` | | docker SDK 기본 | sandbox용 Docker daemon |
| `SANDBOX_IMAGE` | | `theseus-sandbox:py311-tools` | sandbox 이미지 |
| `SANDBOX_HOST_TEMP_ROOT` / `SANDBOX_CONTAINER_TEMP_ROOT` | | (OS 임시 디렉터리) | Core 컨테이너와 호스트가 공유하는 작업 경로. 둘 다 설정하거나 둘 다 비움 |
| `SANDBOX_MEMORY_LIMIT` / `SANDBOX_CPU_QUOTA` / `SANDBOX_CPU_PERIOD` | | `128m` / `50000` / `100000` | sandbox 자원 제한 |
| `SANDBOX_STARTUP_CHECK` / `SANDBOX_STARTUP_STRICT` / `SANDBOX_PULL_ON_STARTUP` / `SANDBOX_KEEP_FAILED_CONTAINERS` | | `true` / `false` / `false` / `false` | 기동 검사와 디버깅 |
| `THESEUS_DATA_DIR` | | 이미지: `/home/appuser/.theseus/data` | 엔진 런타임 데이터 |
| `THESEUS_CUSTOM_TOOLS_DIR` / `THESEUS_PROJECT_CUSTOM_TOOLS_DIR` / `THESEUS_CUSTOM_TOOLS_HOST_DIR` | | (패키지 내부 custom_tools) | 생성 Tool 저장 경로 |
| `HF_HOME` | | 이미지: `/home/appuser/.cache/huggingface` | 선택 기능(`requirements-torch.txt`의 sentence-transformers)용 모델 캐시. Tool RAG 모델은 이미지에 들어 있어 쓰지 않음 |
| `THESEUS_TRACING_ENABLED` / `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` / `LANGCHAIN_PROJECT` | | `false` / `false` / (빈 값) / `Theseus-Core-Server`(`.env.example`은 `theseus-core`) | LangSmith tracing. 대화 내용이 외부로 나가므로 명시적으로만 켬 |

### Tool RAG

도구 검색([설계와 측정](../architecture/tool-rag.md)) 설정입니다. 모두 `theseus_engine/config.py`의 `get_tool_rag_settings()` 한 곳에서 읽고,
기본값은 평가셋 dev 분할에서 고른 값입니다. Core 서버와 CLI/TUI가 같은 값을 씁니다.

| 이름 | 기본값 | 용도 |
| --- | --- | --- |
| `THESEUS_TOOL_RAG_ENABLED` | `true`(구 `THESEUS_DYNAMIC_TOOL_RETRIEVAL`도 읽음) | 끄면 보이는 도구 전부를 보냄 |
| `THESEUS_SERVER_TOOL_RAG` | `true` | 서버 조립(`get_query_engine`)에서만 검색을 끄는 스위치 |
| `THESEUS_EMBED_BACKEND` | `onnx` | `onnx` 또는 `sentence-transformers`(비교용, `requirements-torch.txt` 필요) |
| `THESEUS_EMBED_MODEL_DIR` | 이미지: `/opt/models/e5-small-int8`. 미설정 시 그 경로 → `~/.theseus/models/e5-small-int8` 순으로 찾음 | ONNX 모델 디렉터리(`model.onnx`, `sentencepiece.bpe.model`, `embedder.json`). 파인튜닝 모델로 바꿀 때 이 값만 바꿉니다 |
| `THESEUS_EMBED_MODEL_ID` / `THESEUS_EMBED_MODEL_REVISION` | `intfloat/multilingual-e5-small` / `614241f6…` | sentence-transformers 백엔드용 모델과 리비전 |
| `THESEUS_EMBED_THREADS` | `min(2, CPU 수)` | onnxruntime intra-op 스레드 |
| `THESEUS_EMBED_MAX_LENGTH` | `512` | 토큰 최대 길이 |
| `THESEUS_TOOL_RAG_CALIBRATION_FILE` | (빈 값) | none 판정 보정 파일 경로(`THESEUS_TOOL_RAG_NONE_MODE=soft`일 때만 읽음). 비우면 모델 디렉터리 → 패키지 동봉 파일 순. 모델 sha256이나 레시피 버전이 다르면 none 판정을 끔 |
| `THESEUS_TOOL_RAG_BM25_BETA` | `0.10` | 순위 점수의 BM25 가중치(0이면 dense만) |
| `THESEUS_TOOL_RAG_COST_BUDGET` / `THESEUS_TOOL_RAG_RANK_ALPHA` / `THESEUS_TOOL_RAG_MAX_CANDIDATES` | `700` / `1.0` / `12` | 비용 인지 슬롯: 순위 i의 후보는 `i^alpha × 스키마 글자수/4 ≤ budget`이면 포함(1위는 항상), 상위 max개까지 |
| `THESEUS_TOOL_RAG_NONE_MODE` / `THESEUS_TOOL_RAG_SOFT_KEEP` | `off` / `3` | `off`(기본): "맞는 도구 없음" 판정 안 함. `soft`: 판정되면 슬롯을 상위 N개로 줄임(tool_search는 일부만 보내는 턴에 항상 들어감). 판정이 다른 작성자의 질의로 전이되지 않아 기본으로 끕니다([Tool RAG 문서 4.4절](../architecture/tool-rag.md)) |
| `THESEUS_TOOL_RAG_SMALL_SET` | `12` | 보이는 도구가 이 수 이하이면 검색하지 않고 전부 보냄 |
| `THESEUS_TOOL_RAG_HOOK_BUDGET` / `THESEUS_TOOL_RAG_HOOK_MAX_INJECT_PER_TURN` | `400` / `6` | 도구 실행 뒤 사후 훅이 보이는 도구 중에서 주입할 때의 비용 예산과 턴(서버 요청·CLI 입력 1회)당 상한(측정하지 않은 제안값). 구 이름 `..._PER_SESSION`도 읽습니다. |
| `THESEUS_TOOL_RAG_CACHE_DIR` | `${THESEUS_DATA_DIR}/tool_rag_cache` | 도구 벡터 디스크 캐시(npz). 빈 값이면 끔 |
| `THESEUS_TOOL_RAG_FEEDBACK` / `THESEUS_TOOL_RAG_FEEDBACK_MAX_PER_TOOL` | `cli`(이미지: `off`) / `5` | 사용 이력 few-shot 보강. 서버는 멀티테넌트 격리를 위해 끔 |

## 4. Frontend(Vite)

| 이름 | 필수 | 기본값 | 용도 |
| --- | :---: | --- | --- |
| `VITE_API_BASE_URL` | | (빈 값) | 빌드 시점 API base URL. 비우면 same-origin(`/api`). Docker build arg로도 받음 |
| `VITE_DEV_API_PROXY_TARGET` | | `http://localhost:8080` | `npm run dev`에서 `/api` 요청을 넘길 API 주소(빌드 결과에 포함되지 않음) |
