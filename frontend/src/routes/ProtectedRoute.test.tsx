import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { useAuthStore } from '@/store/useAuthStore';
import ProtectedRoute from './ProtectedRoute';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<p>user home</p>} />
          <Route element={<ProtectedRoute allowedRoles={['SUPER_ADMIN']} />}>
            <Route path="/admin" element={<p>admin page</p>} />
          </Route>
        </Route>
        <Route path="/login" element={<p>login page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProtectedRoute', () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: null, user: null, isAuthenticated: false });
  });

  it('로그인하지 않았으면 /login으로 보낸다', () => {
    renderAt('/admin');

    expect(screen.getByText('login page')).toBeInTheDocument();
  });

  it('일반 사용자가 /admin에 들어오면 / 로 돌려보낸다', () => {
    useAuthStore.setState({
      accessToken: 't',
      isAuthenticated: true,
      user: { id: 1, name: 'u', systemRole: 'USER' },
    });

    renderAt('/admin');

    expect(screen.getByText('user home')).toBeInTheDocument();
    expect(screen.queryByText('admin page')).not.toBeInTheDocument();
  });

  it('SUPER_ADMIN은 /admin을 볼 수 있다', () => {
    useAuthStore.setState({
      accessToken: 't',
      isAuthenticated: true,
      user: { id: 1, name: 'a', systemRole: 'SUPER_ADMIN' },
    });

    renderAt('/admin');

    expect(screen.getByText('admin page')).toBeInTheDocument();
  });
});
