/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 서버 base URL. 비우면 same-origin(`/api`). */
  readonly VITE_API_BASE_URL?: string;
  /** vite dev server가 `/api`를 넘길 대상. 기본값 http://localhost:8080 */
  readonly VITE_DEV_API_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
