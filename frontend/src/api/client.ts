import axios from 'axios';
import type { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/store/useAuthStore';
import { API_BASE_URL } from './config';
import type { ApiResponse } from './types';

declare module 'axios' {
  interface AxiosRequestConfig {
    /** true면 401을 받아도 access token refresh와 재시도를 하지 않는다(인증 API 전용). */
    skipAuthRefresh?: boolean;
  }
}

type RetryableRequest = InternalAxiosRequestConfig & { _retry?: boolean };

/**
 * refresh 대상에서 빼는 인증 API. 로그인 실패(401)가 refresh로 이어지면 오류 문구가 사라지고,
 * refresh 쿠키가 남아 있을 때는 로그인 시도마다 refresh token이 회전된다.
 */
const AUTH_ENDPOINTS = ['/api/v1/auth/login', '/api/v1/auth/refresh', '/api/v1/auth/logout'];

/** 여러 탭이 같은 refresh 쿠키로 동시에 refresh하지 않도록 거는 Web Locks 이름 */
const REFRESH_LOCK_NAME = 'theseus-auth-refresh';

const clientConfig = {
  baseURL: API_BASE_URL,
  withCredentials: true,
};

export const apiClient = axios.create({
  ...clientConfig,
  headers: { 'Content-Type': 'application/json' },
});

const refreshClient = axios.create(clientConfig);

let refreshPromise: Promise<string> | null = null;

async function requestNewAccessToken(): Promise<string> {
  const { data } =
    await refreshClient.post<ApiResponse<{ accessToken: string }>>('/api/v1/auth/refresh');
  const { accessToken } = data.result;
  useAuthStore.getState().setAccessToken(accessToken);
  return accessToken;
}

/**
 * refresh 쿠키로 새 access token을 받아 store에 넣는다(single-flight).
 *
 * 백엔드는 refresh token을 매번 회전시키고, 회전된 직전 토큰은 짧은 grace(10초) 동안만 받아 준 뒤
 * 그 이후 재사용되면 해당 사용자의 토큰을 전부 지운다. 불필요한 회전을 줄이려고 진행 중인 refresh가
 * 있으면 같은 Promise를 공유하고, 가능하면 Web Locks로 탭 간에도 직렬화한다(락을 얻은 시점에는 앞선
 * 탭이 갱신한 쿠키를 쓴다). Web Locks가 없는 HTTP 배포에서는 백엔드 grace가 동시 refresh를 받아 준다.
 */
export function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
    const run = locks
      ? locks.request(REFRESH_LOCK_NAME, requestNewAccessToken)
      : requestNewAccessToken();
    refreshPromise = run.finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

/**
 * refresh 실패가 "서버가 세션을 거절함"(401, AUTH-003 등)인지 판단한다.
 *
 * 429(엣지 요청 제한), 5xx(배포 중 502 등), 네트워크 오류는 일시적인 실패라 세션을 지우지 않는다.
 * 이때 지우면 새로고침 한 번에 로그인 화면으로 튕긴다.
 */
export function isRefreshRejected(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 401;
}

function isAuthEndpoint(url?: string): boolean {
  if (!url) return false;
  return AUTH_ENDPOINTS.some((endpoint) => url.endsWith(endpoint));
}

/**
 * 이 실패 응답이 "토큰이 없거나 만료됨"을 뜻하는지 판단한다.
 *
 * API는 토큰이 없거나 만료·위조되면 JSON 401(ApiResponse, AUTH-001 등)을 준다.
 * 403(COMMON-004 등)은 실제 권한 부족이므로 refresh 대상이 아니다.
 */
function isAuthFailure(response?: AxiosResponse): boolean {
  return response?.status === 401;
}

function bearerTokenOf(request: InternalAxiosRequestConfig): string | null {
  const header = request.headers.Authorization;
  if (typeof header !== 'string' || !header.startsWith('Bearer ')) return null;
  return header.slice('Bearer '.length);
}

apiClient.interceptors.request.use((config) => {
  const { accessToken } = useAuthStore.getState();
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

/**
 * 인증 실패 시 흐름: (1) 다른 요청이 이미 토큰을 갱신했으면 그 토큰으로 바로 재시도,
 * (2) 아니면 single-flight refresh 후 한 번만 재시도, (3) refresh도 실패하면 로컬 세션을 지운다.
 * 세션을 지우면 ProtectedRoute가 /login으로 보내므로 전체 페이지를 새로고침하지 않는다.
 */
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const request = error.config as RetryableRequest | undefined;

    if (
      !request ||
      request._retry ||
      request.skipAuthRefresh ||
      isAuthEndpoint(request.url) ||
      !isAuthFailure(error.response)
    ) {
      return Promise.reject(error);
    }

    request._retry = true;

    let accessToken: string;
    try {
      const currentToken = useAuthStore.getState().accessToken;
      const sentToken = bearerTokenOf(request);
      accessToken =
        currentToken && currentToken !== sentToken ? currentToken : await refreshAccessToken();
    } catch (refreshError) {
      // 서버가 refresh를 거절(401)한 경우에만 세션을 지운다. 429·5xx·네트워크 오류는 세션을 유지한다.
      if (isRefreshRejected(refreshError)) {
        useAuthStore.getState().logout();
      }
      throw refreshError;
    }

    request.headers.Authorization = `Bearer ${accessToken}`;
    return apiClient(request);
  },
);
