import { http } from '@/api/http';
import type { ProjectMemberResponse } from '@/features/projects/api';
import type {
  ProjectMemberCreateRequest,
  ProjectMemberUpdateRequest,
} from '@/features/projects/types/member';

export const memberApi = {
  /**
   * 프로젝트 멤버 목록 조회
   */
  getMembers: async (projectId: string | number, page = 0, size = 20, status?: string) => {
    return http.get<ProjectMemberResponse[]>(`/api/v1/projects/${projectId}/members`, {
      params: { page, size, status },
    });
  },

  /**
   * 프로젝트 멤버 등록
   */
  addMember: async (projectId: string | number, data: ProjectMemberCreateRequest) => {
    return http.post<ProjectMemberResponse>(`/api/v1/projects/${projectId}/members`, data);
  },

  /**
   * 프로젝트 멤버 권한 및 상태 수정
   */
  updateMember: async (
    projectId: string | number,
    projectMemberId: number,
    data: ProjectMemberUpdateRequest,
  ) => {
    return http.patch<ProjectMemberResponse>(
      `/api/v1/projects/${projectId}/members/${projectMemberId}`,
      data,
    );
  },
};
