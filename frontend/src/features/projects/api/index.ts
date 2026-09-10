import { http } from '@/api/http';
import { apiClient } from '@/api/client';
import type { ApiResponse } from '@/api/types';
import type { PageResponse } from '@/api/types';
import type { ProjectResponse } from '@/features/admin/types';

import type { MyProjectResponse, ProjectMemberResponse } from '../types/project';

export type { MyProjectResponse, ProjectMemberResponse };

export const projectApi = {
  /**
   * 내 프로젝트 목록 조회
   */
  getMyProjects: async (page = 0, size = 20) => {
    return http.get<PageResponse<MyProjectResponse>>('/api/v1/projects', {
      params: { page, size },
    });
  },

  /**
   * 내 프로젝트 권한 조회
   */
  getProjectMe: async (projectId: string | number) => {
    const response = await apiClient.get<ApiResponse<ProjectMemberResponse>>(
      `/api/v1/projects/${projectId}/me`,
    );
    // 백엔드 응답 구조에 맞춰 result 또는 data 자체를 반환
    return response.data.result || (response.data as unknown as ProjectMemberResponse);
  },

  /**
   * 프로젝트 상세 조회
   */
  getProject: async (projectId: string | number) => {
    return http.get<ProjectResponse>(`/api/v1/projects/${projectId}`);
  },

  /**
   * 프로젝트 정보 수정
   */
  updateProject: async (
    projectId: string | number,
    data: { name: string; description: string; status: 'ACTIVE' | 'INACTIVE' },
  ) => {
    // data: ProjectUpdateRequest (name, description, status)
    return http.patch<unknown>(`/api/v1/projects/${projectId}`, data);
  },
};
