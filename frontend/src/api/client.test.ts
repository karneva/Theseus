import axios, { AxiosError, AxiosHeaders } from 'axios';
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAuthStore } from '@/store/useAuthStore';

const user = { id: 1, name: 'Tester', systemRole: 'USER' as const };

interface FakeServer {
  refreshCalls: number;
  refreshFails: boolean;
  refreshFailStatus: number;
  validToken: string;
}

const server: FakeServer = {
  refreshCalls: 0,
  refreshFails: false,
  refreshFailStatus: 401,
  validToken: 'fresh',
};

function respond(
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown,
): Promise<AxiosResponse> {
  const response: AxiosResponse = {
    data,
    status,
    statusText: String(status),
    headers: {},
    config,
  };
  if (status >= 400) {
    return Promise.reject(
      new AxiosError('failed', AxiosError.ERR_BAD_REQUEST, config, null, response),
    );
  }
  return Promise.resolve(response);
}

const fakeAdapter: AxiosAdapter = async (config) => {
  const url = config.url ?? '';
  await new Promise((resolve) => setTimeout(resolve, 5));

  if (url.endsWith('/api/v1/auth/refresh')) {
    server.refreshCalls += 1;
    return server.refreshFails
      ? respond(config, server.refreshFailStatus, { code: 'AUTH-003' })
      : respond(config, 200, { result: { accessToken: server.validToken } });
  }
  if (url.endsWith('/api/v1/auth/login')) {
    return respond(config, 401, { code: 'AUTH-002', message: 'bad credentials' });
  }
  if (url.endsWith('/forbidden')) {
    return respond(config, 403, { isSuccess: false, code: 'COMMON-004', message: 'no permission' });
  }
  if (url.endsWith('/forbidden-without-body')) {
    return respond(config, 403, '');
  }

  // API의 JSON 401 EntryPoint 응답(SecurityErrorResponseWriter)과 같은 형식
  const authorization = AxiosHeaders.from(config.headers).get('Authorization');
  if (authorization !== `Bearer ${server.validToken}`) {
    return respond(config, 401, { isSuccess: false, code: 'AUTH-001', message: 'unauthorized' });
  }
  return respond(config, 200, { result: url });
};

// client 모듈이 만드는 axios 인스턴스가 실제 네트워크 대신 fakeAdapter를 쓰게 한다.
const realCreate = axios.create.bind(axios);
vi.spyOn(axios, 'create').mockImplementation((config) =>
  realCreate({ ...config, adapter: fakeAdapter }),
);
const { apiClient } = await import('./client');
const { authApi } = await import('./auth');

describe('apiClient 인증 인터셉터', () => {
  beforeEach(() => {
    Object.assign(server, {
      refreshCalls: 0,
      refreshFails: false,
      refreshFailStatus: 401,
      validToken: 'fresh',
    });
    useAuthStore.setState({ accessToken: 'expired', user, isAuthenticated: true });
  });

  it('병렬 요청이 동시에 401을 받아도 refresh는 한 번만 호출한다', async () => {
    const results = await Promise.all([
      apiClient.get('/api/v1/a'),
      apiClient.get('/api/v1/b'),
      apiClient.get('/api/v1/c'),
    ]);

    expect(results.map((r) => (r.data as { result: string }).result)).toEqual([
      '/api/v1/a',
      '/api/v1/b',
      '/api/v1/c',
    ]);
    expect(server.refreshCalls).toBe(1);
    expect(useAuthStore.getState()).toMatchObject({ accessToken: 'fresh', isAuthenticated: true });
  });

  it('본문 없는 403도 인증 실패로 보지 않고 refresh하지 않는다', async () => {
    await expect(apiClient.get('/api/v1/forbidden-without-body')).rejects.toMatchObject({
      response: { status: 403 },
    });
    expect(server.refreshCalls).toBe(0);
    expect(useAuthStore.getState()).toMatchObject({
      accessToken: 'expired',
      isAuthenticated: true,
    });
  });

  it('권한 부족 403(COMMON-004)은 refresh하지 않는다', async () => {
    useAuthStore.setState({ accessToken: 'fresh' });

    await expect(apiClient.get('/api/v1/forbidden')).rejects.toMatchObject({
      response: { status: 403 },
    });
    expect(server.refreshCalls).toBe(0);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it('로그인 실패(401)는 refresh 없이 그대로 호출부에 전달한다', async () => {
    useAuthStore.setState({ accessToken: null, user: null, isAuthenticated: false });

    await expect(authApi.login({ loginId: 'x', password: 'y' })).rejects.toMatchObject({
      response: { status: 401 },
    });
    expect(server.refreshCalls).toBe(0);
  });

  it('refresh가 거절되면 로컬 세션을 지운다', async () => {
    server.refreshFails = true;

    await expect(apiClient.get('/api/v1/a')).rejects.toBeInstanceOf(AxiosError);
    expect(server.refreshCalls).toBe(1);
    expect(useAuthStore.getState()).toMatchObject({
      accessToken: null,
      user: null,
      isAuthenticated: false,
    });
  });

  it.each([429, 502, 503])('refresh가 %i(일시적 실패)이면 세션을 유지한다', async (status) => {
    server.refreshFails = true;
    server.refreshFailStatus = status;

    await expect(apiClient.get('/api/v1/a')).rejects.toMatchObject({ response: { status } });
    expect(server.refreshCalls).toBe(1);
    expect(useAuthStore.getState()).toMatchObject({ user, isAuthenticated: true });
  });
});

describe('isRefreshRejected', () => {
  it('401만 세션 거절로 본다', async () => {
    const { isRefreshRejected } = await import('./client');
    const errorWith = (status: number) =>
      new AxiosError('failed', AxiosError.ERR_BAD_REQUEST, undefined, null, {
        data: null,
        status,
        statusText: String(status),
        headers: {},
        config: { headers: new AxiosHeaders() },
      });

    expect(isRefreshRejected(errorWith(401))).toBe(true);
    expect(isRefreshRejected(errorWith(429))).toBe(false);
    expect(isRefreshRejected(errorWith(502))).toBe(false);
    expect(isRefreshRejected(new AxiosError('Network Error', AxiosError.ERR_NETWORK))).toBe(false);
    expect(isRefreshRejected(new Error('boom'))).toBe(false);
  });
});
