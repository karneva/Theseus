import type { AxiosRequestConfig } from 'axios';
import { apiClient } from './client';
import type { ApiResponse } from './types';

export const http = {
  async get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await apiClient.get<ApiResponse<T>>(url, config);
    return data.result;
  },

  async post<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await apiClient.post<ApiResponse<T>>(url, body, config);
    return data.result;
  },

  async patch<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await apiClient.patch<ApiResponse<T>>(url, body, config);
    return data.result;
  },
};
