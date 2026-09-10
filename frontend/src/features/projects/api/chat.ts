import { http } from '@/api/http';
import type { PageResponse } from '@/api/types';
import { ToolPlanMode } from '@/features/projects/types/chat';
import type {
  ChatMessage,
  ChatSession,
  ChatSessionDetailResponse,
  ToolPlanDetailResponse,
  ToolPlanGenerationRequest,
  ToolPlanGenerationResponse,
  ToolPlanRegenerationRequest,
  ToolPlanRunStateResponse,
} from '@/features/projects/types/chat';

export const chatApi = {
  createSession: async (projectId: string) => {
    return http.post<ChatSession>(`/api/v1/projects/${projectId}/sessions`, {
      title: '새로운 대화 세션',
    });
  },

  getSessions: async (projectId: string | undefined, page = 0, size = 20) => {
    if (!projectId) return { content: [], totalElements: 0, totalPages: 0, size: 20 };
    return http.get<PageResponse<ChatSession>>(`/api/v1/projects/${projectId}/sessions`, {
      params: { page, size },
    });
  },

  getSessionDetails: async (
    projectId: string,
    sessionId: string,
  ): Promise<ChatSessionDetailResponse> => {
    return http.get<ChatSessionDetailResponse>(
      `/api/v1/projects/${projectId}/sessions/${sessionId}`,
    );
  },

  updateSessionTitle: async (projectId: string, sessionId: string, title: string) => {
    return http.patch<ChatSession>(`/api/v1/projects/${projectId}/sessions/${sessionId}`, {
      title,
    });
  },

  closeSession: async (projectId: string, sessionId: string) => {
    return http.patch<ChatSession>(`/api/v1/projects/${projectId}/sessions/${sessionId}/close`);
  },

  createMessage: async (projectId: string, sessionId: string, content: string) => {
    return http.post<ChatMessage>(`/api/v1/projects/${projectId}/sessions/${sessionId}/messages`, {
      content,
      messageType: 'CHAT',
      contentType: 'TEXT',
    });
  },

  requestToolPlanApproval: async (projectId: string, toolPlanId: string) => {
    return http.post<unknown>(
      `/api/v1/projects/${projectId}/tool-plans/${toolPlanId}/approval-requests`,
    );
  },

  generateToolPlan: async (
    projectId: string,
    sessionId: string,
    payload: { userMessage: string; mode?: ToolPlanMode; remoteWorkspaceId?: number },
  ): Promise<ToolPlanGenerationResponse> => {
    const apiPayload: ToolPlanGenerationRequest = {
      mode: payload.mode || ToolPlanMode.PLAN,
      prompt: payload.userMessage,
      remoteWorkspaceId: payload.remoteWorkspaceId,
    };
    return http.post<ToolPlanGenerationResponse>(
      `/api/v1/projects/${projectId}/sessions/${sessionId}/tool-plans/generate`,
      apiPayload,
    );
  },

  regenerateToolPlan: async (
    projectId: string,
    sessionId: string,
    toolPlanId: string,
    payload: {
      basePlanVersion: number;
      feedbackItems: Array<{ blockId: string; comment: string }>;
      mode?: ToolPlanMode;
      remoteWorkspaceId?: number;
    },
  ): Promise<ToolPlanGenerationResponse> => {
    const apiPayload: ToolPlanRegenerationRequest = {
      mode: payload.mode || ToolPlanMode.PLAN,
      basePlanVersion: payload.basePlanVersion,
      feedbackItems: payload.feedbackItems,
      remoteWorkspaceId: payload.remoteWorkspaceId,
    };
    return http.patch<ToolPlanGenerationResponse>(
      `/api/v1/projects/${projectId}/sessions/${sessionId}/tool-plans/${toolPlanId}/regenerate`,
      apiPayload,
    );
  },

  getToolPlanDetail: async (
    projectId: string,
    sessionId: string,
    toolPlanId: string,
  ): Promise<ToolPlanDetailResponse> => {
    return http.get<ToolPlanDetailResponse>(
      `/api/v1/projects/${projectId}/sessions/${sessionId}/tool-plans/${toolPlanId}`,
    );
  },

  getToolPlanRunState: async (
    projectId: string,
    sessionId: string,
    runId: string,
  ): Promise<ToolPlanRunStateResponse> => {
    return http.get<ToolPlanRunStateResponse>(
      `/api/v1/projects/${projectId}/sessions/${sessionId}/tool-plan-runs/${runId}/state`,
    );
  },
};
