import { http } from '@/api/http';
import { apiClient } from './client';
import type { ApiResponse } from './types';
export type { ApiResponse } from './types';

export type SystemRole = 'SUPER_ADMIN' | 'USER';

export interface LoginRequest {
  loginId: string;
  password: string;
}

export interface LoginResponse {
  tokenType: string;
  accessToken: string;
  userId: number;
  name: string;
  systemRole: SystemRole;
}

/**
 * 인증 API. 세 요청 모두 `skipAuthRefresh`로 401 refresh 재시도 대상에서 뺀다.
 * refresh token은 HttpOnly 쿠키로만 오가므로 로그아웃도 access token 없이 동작한다.
 */
export const authApi = {
  /**
   * 로그인 API. 성공하면 서버가 refresh 쿠키를 설정하고 access token을 본문으로 준다.
   */
  login: async (data: LoginRequest) => {
    return http.post<LoginResponse>('/api/v1/auth/login', data, { skipAuthRefresh: true });
  },

  /**
   * 로그아웃 API. 서버의 refresh token을 지우고 쿠키를 만료시킨다.
   */
  logout: async () => {
    const response = await apiClient.post<ApiResponse<void>>('/api/v1/auth/logout', undefined, {
      skipAuthRefresh: true,
    });
    return response.data;
  },
};
