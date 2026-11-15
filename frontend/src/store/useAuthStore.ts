import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SystemRole } from '@/api/auth';

interface User {
  id: number;
  name: string;
  systemRole: SystemRole;
}

interface AuthState {
  /** 메모리에만 두는 access token. 새로고침하면 사라지고 앱 부팅 시 refresh 쿠키로 다시 받는다. */
  accessToken: string | null;
  user: User | null;
  isAuthenticated: boolean;

  login: (accessToken: string, user: User) => void;
  logout: () => void;
  setAccessToken: (token: string) => void;
}

type PersistedAuthState = Pick<AuthState, 'user' | 'isAuthenticated'>;

const AUTH_STORAGE_KEY = 'auth-storage';

/**
 * 인증 상태 store.
 *
 * localStorage에는 화면 표시용 사용자 정보와 로그인 여부만 남긴다. access token을 저장하면
 * XSS 한 번으로 토큰이 유출될 수 있으므로 메모리에만 두고, refresh token은 HttpOnly 쿠키가 맡는다.
 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      isAuthenticated: false,

      login: (accessToken, user) =>
        set({
          accessToken,
          user,
          isAuthenticated: true,
        }),

      logout: () => {
        set({
          accessToken: null,
          user: null,
          isAuthenticated: false,
        });
        localStorage.removeItem(AUTH_STORAGE_KEY);
      },

      setAccessToken: (token) =>
        set({
          accessToken: token,
        }),
    }),
    {
      name: AUTH_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state): PersistedAuthState => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
      // 예전 버전이 localStorage에 남긴 accessToken은 복원하지 않는다.
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<PersistedAuthState>;
        const user = saved.user ?? null;
        return { ...current, user, isAuthenticated: Boolean(saved.isAuthenticated && user) };
      },
    },
  ),
);
