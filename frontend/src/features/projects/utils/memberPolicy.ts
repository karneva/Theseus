import type { ProjectMemberResponse } from '../types/project';

export const DEFAULT_MEMBER_ACCESS_LEVEL = 1;
export const MAX_MEMBER_ACCESS_LEVEL = 5;
export const ADMIN_ACCESS_LEVEL = 5;

export const clampMemberAccessLevel = (value: number) =>
  Math.min(MAX_MEMBER_ACCESS_LEVEL, Math.max(DEFAULT_MEMBER_ACCESS_LEVEL, value));

const ROLE_ORDER: Record<ProjectMemberResponse['projectRole'], number> = {
  ADMIN: 0,
  MANAGER: 1,
  MEMBER: 2,
};

export function compareProjectMembers(a: ProjectMemberResponse, b: ProjectMemberResponse): number {
  if (a.status !== b.status) return a.status === 'IN_PROGRESS' ? -1 : 1;
  const roleDifference = (ROLE_ORDER[a.projectRole] ?? 99) - (ROLE_ORDER[b.projectRole] ?? 99);
  return (
    roleDifference || b.accessLevel - a.accessLevel || (a.name || '').localeCompare(b.name || '')
  );
}
