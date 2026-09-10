import { useEffect, useState } from 'react';
import { remoteWorkspaceApi } from '../api/remoteWorkspace';
import { useChatSessionStore } from '../stores/useChatSessionStore';
import type { RemoteWorkspaceResponse } from '../types/project';

export function useRemoteWorkspaces(projectId: string | undefined) {
  const [remoteWorkspaces, setRemoteWorkspaces] = useState<RemoteWorkspaceResponse[]>([]);
  const { selectedRemoteWorkspaceId, setSelectedRemoteWorkspaceId } = useChatSessionStore();

  useEffect(() => {
    if (!projectId) return;

    let cancelled = false;
    const fetchRemoteWorkspaces = async () => {
      try {
        const responses = await remoteWorkspaceApi.getRemoteWorkspaces(projectId);
        if (cancelled) return;

        setRemoteWorkspaces(responses);
        const hasSelectedWorkspace = responses.some(
          (workspace) => workspace.remoteWorkspaceId === selectedRemoteWorkspaceId,
        );
        if (selectedRemoteWorkspaceId && !hasSelectedWorkspace) {
          setSelectedRemoteWorkspaceId(null);
        }
      } catch (error) {
        if (!cancelled) {
          console.warn('Failed to load remote workspaces', error);
        }
      }
    };

    void fetchRemoteWorkspaces();
    return () => {
      cancelled = true;
    };
  }, [projectId, selectedRemoteWorkspaceId, setSelectedRemoteWorkspaceId]);

  return remoteWorkspaces;
}
