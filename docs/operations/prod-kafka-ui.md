# Kafka UI

셀프호스팅 compose의 `ops` 프로필에 읽기 전용 Kafka UI(`kafbat/kafka-ui`)가 있습니다. 평소에는 띄우지 않고, 점검할 때만 켭니다(mem_limit 384m, 메모리 예산 밖).

## 실행과 접속

```bash
# 서버
C="docker compose -f /opt/theseus/app/infra/docker/selfhost/docker-compose.yml --env-file /opt/theseus/theseus.env"
$C --profile ops up -d kafka-ui

# 노트북
ssh -L 8091:127.0.0.1:8091 <서버별칭>
# 브라우저에서 http://localhost:8091
```

포트는 `KAFKA_UI_PORT`(기본 8091)로 바꿀 수 있습니다. 다 본 뒤에는 `$C --profile ops stop kafka-ui`로 멈춥니다.

## 확인할 항목

- 클러스터 이름 `theseus`
- 토픽 6개: `theseus.tool-plan.request`, `theseus.tool-plan.event`, `theseus.tool-build.request`, `theseus.tool-build.event`와 DLT `theseus.tool-plan.event.DLT`, `theseus.tool-build.event.DLT`(이름은 `KAFKA_TOPIC_*`로 바뀔 수 있음)
- consumer group: Core의 `theseus-core-tool-plan`, `theseus-core-tool-build`와 API의 `theseus-api-tool-generation`
- DLT에 메시지가 쌓이면 API가 결과 이벤트를 처리하지 못한 것입니다. API 로그에서 원인을 찾습니다.

## 보안

- 포트는 서버 루프백(`127.0.0.1:${KAFKA_UI_PORT:-8091}`)에만 열리므로 SSH 터널이 유일한 접근 경로입니다. UI 자체 인증은 없습니다.
- `KAFKA_CLUSTERS_0_READONLY=true`라 UI에서 토픽이나 메시지를 바꿀 수 없습니다.
- 공개 인터페이스에 바인딩하려면 먼저 인증을 켜고 방화벽에서 출발지 IP를 제한합니다.
