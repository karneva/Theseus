# Theseus Frontend

React 19 + Vite 8 + TypeScript, Zustand, axios, Tailwind v4. 빌드 결과는 nginx 이미지로 서빙합니다.

## 요구 사항

- Node.js 20.19 이상(권장: `.nvmrc`의 24)
- 의존성 설치는 lockfile 그대로 `npm ci`

## 스크립트

| 명령                              | 설명                                                                                          |
| --------------------------------- | --------------------------------------------------------------------------------------------- |
| `npm run dev`                     | 개발 서버. `/api` 요청은 `VITE_DEV_API_PROXY_TARGET`(기본 `http://localhost:8080`)으로 프록시 |
| `npm run build`                   | 타입 검사(`tsc -b`) 후 `dist/` 빌드                                                           |
| `npm run lint`                    | ESLint(타입 기반 규칙 포함)                                                                   |
| `npm test`                        | Vitest. CI에서는 `npm test -- --run`                                                          |
| `npm run format` / `format:check` | Prettier 적용 / 검사                                                                          |

## 환경 변수

`.env.example` 참고. 모두 선택값입니다.

- `VITE_API_BASE_URL`: 비우면 same-origin(`/api`)으로 요청합니다. 운영에서는 앞단 nginx가 `/api`를 API 서버로
  프록시하므로, 비워 두면 이미지 하나를 어느 도메인/IP에도 그대로 배포할 수 있습니다.
- `VITE_DEV_API_PROXY_TARGET`: 개발 서버 프록시 대상.

## 인증 흐름 요약

- access token은 메모리에만 두고, refresh token은 HttpOnly 쿠키로 오갑니다.
- 새로고침하면 `useAuthBootstrap`이 `/api/v1/auth/refresh`로 access token을 다시 받습니다.
- 401(그리고 API가 JSON 401을 주기 전까지는 code 없는 403)을 받으면 refresh를 single-flight로 한 번만 호출하고
  원래 요청을 재시도합니다(`src/api/client.ts`).
