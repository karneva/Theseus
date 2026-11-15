# 모니터링

별도 모니터링 스택(Prometheus, Grafana 등)은 두지 않습니다. 단일 서버에서는 compose 상태, 컨테이너 healthcheck, 로그, `docker stats`로 점검합니다.
명령과 기준값은 [셀프호스팅 가이드의 운영 점검](./self-hosting.md#11-운영-점검)과 [메모리 예산](./self-hosting.md#12-메모리-예산)에 있습니다.

```bash
C="docker compose -f /opt/theseus/app/infra/docker/selfhost/docker-compose.yml --env-file /opt/theseus/theseus.env"
$C ps                                   # 상태와 health
$C logs -f --tail=200 api core          # 로그
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
```

| 대상 | 헬스체크 |
| --- | --- |
| nginx | `GET /healthz`(외부에서 호출 가능) |
| api | `GET /actuator/health`(컨테이너 내부 전용, 외부는 404) |
| core | `GET /health`(컨테이너 내부 전용) |
| frontend, docker-proxy, mysql, postgres, redis, kafka | compose `healthcheck` |

- Kafka 토픽과 consumer group: [Kafka UI](./prod-kafka-ui.md)(`ops` 프로필, SSH 포트포워딩)
- 백업 결과: `/opt/theseus/backups/backup.log`
- 장애 사례: [트러블슈팅](./troubleshooting.md)
