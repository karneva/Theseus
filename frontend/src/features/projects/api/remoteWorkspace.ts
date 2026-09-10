import { http } from '@/api/http';
import type {
  RemoteWorkspaceConnectionTestResponse,
  RemoteWorkspaceCreateRequest,
  RemoteWorkspaceResponse,
} from '../types/project';

export const remoteWorkspaceApi = {
  getRemoteWorkspaces: async (projectId: string) => {
    return http.get<RemoteWorkspaceResponse[]>(`/api/v1/projects/${projectId}/remote-workspaces`);
  },

  createRemoteWorkspace: async (projectId: string, payload: RemoteWorkspaceCreateRequest) => {
    return http.post<RemoteWorkspaceResponse>(
      `/api/v1/projects/${projectId}/remote-workspaces`,
      payload,
    );
  },

  deleteRemoteWorkspace: async (projectId: string, remoteWorkspaceId: number) => {
    return http.patch<RemoteWorkspaceResponse>(
      `/api/v1/projects/${projectId}/remote-workspaces/${remoteWorkspaceId}/delete`,
    );
  },

  testConnection: async (projectId: string, remoteWorkspaceId: number) => {
    return http.post<RemoteWorkspaceConnectionTestResponse>(
      `/api/v1/projects/${projectId}/remote-workspaces/${remoteWorkspaceId}/test-connection`,
    );
  },
};
