import { http } from '@/api/http';
import type { ToolUsageListResponse } from '@/features/projects/types/toolUsage';

export const toolUsageApi = {
  getToolUsages: async (projectId: string | number): Promise<ToolUsageListResponse> => {
    return http.get<ToolUsageListResponse>(`/api/v1/projects/${projectId}/admin/tool-usages`);
  },
};
