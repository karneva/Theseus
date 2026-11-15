import { beforeEach, describe, expect, it } from 'vitest';
import { useAuthStore } from './useAuthStore';

const user = { id: 1, name: 'Tester', systemRole: 'USER' as const };

describe('useAuthStore', () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: null, user: null, isAuthenticated: false });
    localStorage.clear();
  });

  it('accessToken은 localStorage에 저장하지 않는다', () => {
    useAuthStore.getState().login('secret-access-token', user);

    const saved = localStorage.getItem('auth-storage') ?? '';
    expect(saved).not.toContain('secret-access-token');
    expect(JSON.parse(saved)).toMatchObject({ state: { user, isAuthenticated: true } });
    expect(useAuthStore.getState().accessToken).toBe('secret-access-token');
  });

  it('예전 버전이 저장한 accessToken은 복원하지 않는다', async () => {
    localStorage.setItem(
      'auth-storage',
      JSON.stringify({
        state: { accessToken: 'legacy-token', user, isAuthenticated: true },
        version: 0,
      }),
    );

    await useAuthStore.persist.rehydrate();

    expect(useAuthStore.getState()).toMatchObject({
      accessToken: null,
      user,
      isAuthenticated: true,
    });
  });

  it('logout은 메모리와 저장소를 모두 비운다', () => {
    useAuthStore.getState().login('token', user);

    useAuthStore.getState().logout();

    expect(useAuthStore.getState()).toMatchObject({
      accessToken: null,
      user: null,
      isAuthenticated: false,
    });
    expect(localStorage.getItem('auth-storage')).toBeNull();
  });
});
