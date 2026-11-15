import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { authApi } from '@/api/auth';
import { useAuthStore } from '@/store/useAuthStore';

/**
 * 모든 레이아웃이 함께 쓰는 로그아웃 동작.
 *
 * 서버 로그아웃(refresh token 삭제와 쿠키 만료)을 먼저 시도하고, 실패하더라도 로컬 세션은
 * 반드시 지운 뒤 /login으로 보낸다. 로컬 상태만 지우면 refresh 쿠키가 살아 있어 세션이 남는다.
 */
export function useLogout() {
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.logout);

  return useCallback(async () => {
    try {
      await authApi.logout();
    } catch (error) {
      console.warn('Logout API failed:', error);
    } finally {
      clearSession();
      void navigate('/login', { replace: true });
    }
  }, [clearSession, navigate]);
}
