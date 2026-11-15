# 배포

Theseus는 서버 한 대에 docker compose로 전체 스택을 올리는 구성을 기준으로 배포합니다. 전체 절차는 [셀프호스팅 가이드](./self-hosting.md)에 있습니다.

## 흐름 요약

```text
노트북                                       서버(/opt/theseus)
scripts/build-images.sh <태그>
scripts/ship-images.sh --with-config ──SSH──▶ docker load, app/ 에 compose·scripts 복사
                                             theseus.env 의 IMAGE_TAG=<태그>
                                             scripts/deploy.sh  (up -d --no-build, healthy 대기)
scripts/llm-tunnel.sh <서버> ─────ssh -R────▶ 172.17.0.1:11434 → core 의 host.docker.internal
```

| 단계 | 명령 | 자세한 내용 |
| --- | --- | --- |
| 서버 준비(한 번) | `sudo scripts/server-bootstrap.sh` | [2장](./self-hosting.md#2-서버-준비) |
| 빌드·전송 | `scripts/build-images.sh`, `scripts/ship-images.sh` | [3장](./self-hosting.md#3-노트북에서-이미지-빌드와-전송) |
| 비밀값 | `scripts/gen-secrets.sh --fill /opt/theseus/theseus.env` | [4장](./self-hosting.md#4-env-파일과-비밀값) |
| 기동·갱신 | `scripts/deploy.sh [서비스...]` | [5장](./self-hosting.md#5-첫-기동), [10장](./self-hosting.md#10-업그레이드) |
| 인증서 | `scripts/issue-cert.sh` | [6장](./self-hosting.md#6-tlslets-encrypt) |
| LLM 터널 | `scripts/llm-tunnel.sh` / `scripts/llm-tunnel.ps1` | [7장](./self-hosting.md#7-llm-연결노트북-ollama-reverse-tunnel) |
| 백업 | `scripts/backup.sh`(cron) | [9장](./self-hosting.md#9-백업과-복구) |

## CI

[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)은 PR과 `dev`/`main` push마다 API 테스트, Core 테스트, Frontend lint·test·build, compose 설정 검증, gitleaks 비밀 검사를 실행합니다.
CI는 검증만 하고 이미지 푸시나 배포는 하지 않습니다. 배포는 위 스크립트로 수동 실행합니다.
