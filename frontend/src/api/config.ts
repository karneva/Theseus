/**
 * API 서버 base URL.
 *
 * 비워 두면('') 페이지와 같은 origin의 `/api/...`로 요청한다. 운영에서는 nginx가 `/api`를
 * API 서버로 프록시하므로 이미지 하나를 어느 도메인/IP에 배포해도 다시 빌드할 필요가 없다.
 * 로컬 개발은 vite dev server의 `/api` 프록시를 쓰고, API를 다른 origin에 둘 때만 지정한다.
 * `||` 대신 `??`를 써서 빈 문자열(same-origin)을 명시적으로 고를 수 있게 한다.
 */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');
