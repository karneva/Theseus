import axios from 'axios';
import type { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/store/useAuthStore';
import { API_BASE_URL } from './config';
import type { ApiResponse } from './types';

type RetryableRequest = InternalAxiosRequestConfig & { _retry?: boolean };

const clientConfig = {
  baseURL: API_BASE_URL,
  withCredentials: true,
};

export const apiClient = axios.create({
  ...clientConfig,
  headers: { 'Content-Type': 'application/json' },
});

const refreshClient = axios.create(clientConfig);

async function refreshAccessToken(): Promise<string> {
  const { data } =
    await refreshClient.post<ApiResponse<{ accessToken: string }>>('/api/v1/auth/refresh');
  const { accessToken } = data.result;
  useAuthStore.getState().setAccessToken(accessToken);
  return accessToken;
}

apiClient.interceptors.request.use((config) => {
  const { accessToken } = useAuthStore.getState();
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const request = error.config as RetryableRequest | undefined;
    const status = error.response?.status;

    if (!request || request._retry || (status !== 401 && status !== 403)) {
      return Promise.reject(error);
    }

    request._retry = true;
    try {
      const accessToken = await refreshAccessToken();
      request.headers.Authorization = `Bearer ${accessToken}`;
      return apiClient(request);
    } catch (refreshError) {
      useAuthStore.getState().logout();
      window.location.href = '/login';
      return Promise.reject(refreshError);
    }
  },
);
