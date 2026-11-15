# Theseus API Server

Spring Boot based API Server for Theseus.

## Local Development

Recommended flow:

1. Run MySQL, Kafka, Redis with Docker Compose.
2. Run the API Server from the IDE for debugging and fast restart.
3. Use host machine endpoints from the IDE process.

```text
SPRING_DATASOURCE_URL=jdbc:mysql://localhost:13306/theseus
SPRING_KAFKA_BOOTSTRAP_SERVERS=localhost:19092
SPRING_DATA_REDIS_HOST=localhost
SPRING_DATA_REDIS_PORT=16379
```

Docker Compose internal endpoints are different:

- Kafka: `theseus-local-kafka:29092`
- Redis: `theseus-local-redis:6379`

Use the internal endpoints only when the API Server itself runs as a Docker
container. If the API Server runs from the IDE, use `localhost` endpoints.

Stop the API Server container before starting the API Server from the IDE:

```bash
docker stop theseus-local-api-server
```

## Profiles

- `local` (default when `SPRING_PROFILES_ACTIVE` is unset): localhost defaults for MySQL/Redis/Kafka/Core,
  `ddl-auto=update`, SQL logging, CORS allowed for the Vite dev server.
- `prod`: no connection defaults, `ddl-auto=validate` (schema is owned by Flyway `db/migration`),
  springdoc disabled, refresh cookie `Secure` by default.

Schema changes go into a new Flyway file (`src/main/resources/db/migration/V2__*.sql`, ...).
Existing databases created by `ddl-auto` are baselined at V1 automatically (`baseline-on-migrate`).

## Environment

| Variable | Required (prod) | Default | Purpose |
|---|---|---|---|
| `SPRING_PROFILES_ACTIVE` | yes | `local` | `local` or `prod` |
| `SPRING_DATASOURCE_URL` / `_USERNAME` / `_PASSWORD` | yes | local only | MySQL connection |
| `SPRING_DATA_REDIS_HOST` / `_PORT` / `_PASSWORD` | yes | `localhost` / `6379` / empty | Redis (refresh tokens, run state) |
| `SPRING_KAFKA_BOOTSTRAP_SERVERS` | yes | local only | Kafka brokers |
| `THESEUS_CORE_BASE_URL` | yes | local only | Core server base URL |
| `JWT_SECRET` | yes | - | HMAC key, at least 32 bytes |
| `INTERNAL_API_KEY` | yes | empty (internal API rejects all) | Shared key for Core <-> API internal calls |
| `ALLOWED_ORIGINS` | no | empty (CORS off) | Comma separated origins; `*` is rejected in prod |
| `KAFKA_TOPIC_TOOL_PLAN_REQUEST` / `_EVENT`, `KAFKA_TOPIC_TOOL_BUILD_REQUEST` / `_EVENT` | no | `theseus.tool-plan.*`, `theseus.tool-build.*` | Topics shared with Core |
| `INITIAL_ADMIN_EMPLOYEE_NUMBER` / `_NAME` / `_EMAIL` / `_PASSWORD` | first boot | - | Creates the first SUPER_ADMIN when none exists |
| `JWT_REFRESH_TOKEN_COOKIE_SECURE` | no | `false` (local), `true` (prod) | Refresh cookie `Secure` flag |
| `THESEUS_TOOL_PLAN_RUN_TIMEOUT_SCHEDULER_ENABLED` | no | `true` | Fails runs that never receive a result event |
| `THESEUS_TOOL_PLAN_RUN_TIMEOUT_MINUTES` / `THESEUS_TOOL_PLAN_REQUESTED_RUN_TIMEOUT_MINUTES` | no | `30` / `180` | Timeout for GENERATING runs (since last change) / REQUESTED runs still queued in Core |
| `JAVA_TOOL_OPTIONS`, `TZ` | no | `-XX:MaxRAMPercentage=75`, `Asia/Seoul` (image) | JVM and timezone |

Result events that cannot be processed are retried with backoff and then published to
`<topic>.DLT` (`theseus.tool-plan.event.DLT`, `theseus.tool-build.event.DLT`).
The health endpoint for container checks is `GET /actuator/health`.

## Tests

`./gradlew test` starts MySQL 8.4, Redis and Kafka with Testcontainers, so Docker must be running.
