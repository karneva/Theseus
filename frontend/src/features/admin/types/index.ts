export interface UserResponse {
  id: number;
  employeeNumber: string;
  name: string;
  email: string;
  systemRole: 'SUPER_ADMIN' | 'USER';
  status: 'ACTIVE' | 'INACTIVE';
  createdAt: string;
  updatedAt: string;
}

export type ProjectSummaryResponse = ProjectResponse;

export interface ProjectCreateRequest {
  name: string;
  description?: string;
  adminEmployeeNumber: string;
  adminName: string;
}

export interface ProjectUpdateRequest {
  name?: string;
  description?: string;
  status?: 'ACTIVE' | 'INACTIVE';
  adminEmployeeNumber?: string;
  adminName?: string;
}

export interface ProjectResponse {
  projectId: number;
  name: string;
  description: string;
  status: 'ACTIVE' | 'INACTIVE';
  projectAdminUserId: number;
  projectAdminEmployeeNumber: string;
  projectAdminName: string;
  createdAt: string;
  updatedAt: string;
}

export interface UserCreateRequest {
  employeeNumber: string;
  name: string;
  email: string;
  password?: string;
  systemRole?: 'SUPER_ADMIN' | 'USER';
  status?: 'ACTIVE' | 'INACTIVE';
}

export interface UserUpdateRequest {
  name?: string;
  email?: string;
}
