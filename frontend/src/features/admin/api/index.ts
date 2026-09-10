import { http } from '@/api/http';

import type { PageResponse } from '@/api/types';
import type {
  UserResponse,
  ProjectSummaryResponse,
  ProjectCreateRequest,
  ProjectUpdateRequest,
  ProjectResponse,
  UserCreateRequest,
  UserUpdateRequest,
} from '../types';

export type * from '../types';
export type { PageResponse } from '@/api/types';

export const adminApi = {
  /**
   * 사용자 목록 조회
   */
  getUsers: async (page = 0, size = 10) => {
    return http.get<PageResponse<UserResponse>>('/api/v1/admin/users', {
      params: { page, size },
    });
  },

  /**
   * 사용자 계정 발급
   */
  createUser: async (data: UserCreateRequest) => {
    return http.post<UserResponse>('/api/v1/admin/users', data);
  },

  /**
   * 사용자 기본 정보 수정
   */
  updateUser: async (userId: number, data: UserUpdateRequest) => {
    return http.patch<UserResponse>(`/api/v1/admin/users/${userId}`, data);
  },

  /**
   * 사용자 상태 변경
   */
  updateUserStatus: async (userId: number, status: 'ACTIVE' | 'INACTIVE') => {
    return http.patch<UserResponse>(`/api/v1/admin/users/${userId}/status`, { status });
  },

  /**
   * 전체 프로젝트 목록 조회
   */
  getProjects: async (page = 0, size = 8) => {
    return http.get<PageResponse<ProjectSummaryResponse>>('/api/v1/admin/projects', {
      params: { page, size },
    });
  },

  /**
   * 사번으로 사용자 조회
   */
  searchUserByEmployeeNumber: async (employeeNumber: string) => {
    return http.get<UserResponse>('/api/v1/admin/users/search', {
      params: { employeeNumber },
    });
  },

  /**
   * 프로젝트 생성
   */
  createProject: async (data: ProjectCreateRequest) => {
    return http.post<ProjectResponse>('/api/v1/projects', data);
  },

  /**
   * 프로젝트 수정
   */
  updateProject: async (projectId: number, data: ProjectUpdateRequest) => {
    return http.patch<ProjectResponse>(`/api/v1/projects/${projectId}`, data);
  },
};
