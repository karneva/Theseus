import { createBrowserRouter } from 'react-router-dom';
import AuthLayout from '@/layouts/AuthLayout';
import LoginPage from '@/pages/auth/LoginPage';
import AdminLayout from '@/layouts/AdminLayout';
import SuperAdminPage from '@/pages/admin/SuperAdminPage';
import UserLayout from '@/layouts/UserLayout';
import ProjectListPage from '@/pages/user/ProjectListPage';
import ProjectLayout from '@/layouts/ProjectLayout';
import ProtectedRoute from './ProtectedRoute';
import ChatSessionPage from '@/pages/user/projects/ChatSessionPage';
import ProjectSettingsPage from '@/pages/user/projects/ProjectSettingsPage';
import ToolListPage from '@/pages/user/projects/ToolListPage';
import ProjectIndexPage from '@/pages/user/projects/ProjectIndexPage';
import type { RouteObject } from 'react-router-dom';

const routes: RouteObject[] = [
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <UserLayout />,
        children: [
          {
            path: '',
            element: <ProjectListPage />,
          },
        ],
      },
      {
        path: '/projects/:projectId',
        element: <ProjectLayout />,
        children: [
          {
            index: true,
            element: <ProjectIndexPage />,
          },
          {
            path: 'sessions',
            element: (
              <div className="flex h-full items-center justify-center p-8 text-slate-500">
                좌측 메뉴에서 대화 세션을 선택하거나 '새 대화'를 시작하세요.
              </div>
            ),
          },
          {
            path: 'sessions/:sessionId',
            element: <ChatSessionPage />,
          },
          {
            path: 'tools',
            element: <ToolListPage />,
          },
          {
            path: 'settings',
            element: <ProjectSettingsPage />,
          },
        ],
      },
      {
        // 관리자 화면은 SUPER_ADMIN만. API도 hasRole로 막지만 일반 사용자에게 UI가 보이지 않게 한다.
        element: <ProtectedRoute allowedRoles={['SUPER_ADMIN']} />,
        children: [
          {
            path: '/admin',
            element: <AdminLayout />,
            children: [
              {
                path: '',
                element: <SuperAdminPage />,
              },
            ],
          },
        ],
      },
    ],
  },
  {
    path: '/login',
    element: <AuthLayout />,
    children: [
      {
        path: '',
        element: <LoginPage />,
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
