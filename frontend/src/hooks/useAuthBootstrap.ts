import { useEffect, useState } from 'react';
import { isRefreshRejected, refreshAccessToken } from '@/api/client';
import { useAuthStore } from '@/store/useAuthStore';

/**
 * 앱 부팅 시 access token을 복구한다.
 *
 * access token은 메모리에만 있으므로 새로고침하면 사라진다. 로그인 기록(persist된 user)이
 * 있으면 화면을 그리기 전에 refresh 쿠키로 새 access token을 받아 두어, 첫 API 요청들이
 * 토큰 없이 나가 연달아 실패하지 않게 한다. 서버가 refresh를 거절(401)하면 로컬 세션을 지워
 * ProtectedRoute가 /login으로 보내게 한다. 429·5xx·네트워크 오류는 일시적이므로 세션을 유지하고,
 * 첫 API 요청의 401 처리에서 refresh를 다시 시도한다.
 *
 * @returns 복구가 끝나 라우터를 그려도 되면 true
 */
export function useAuthBootstrap(): boolean {
  const [ready, setReady] = useState(() => {
    const { isAuthenticated, accessToken } = useAuthStore.getState();
    return !isAuthenticated || Boolean(accessToken);
  });

  useEffect(() => {
    if (ready) return;

    let cancelled = false;
    // StrictMode에서 effect가 두 번 돌아도 refreshAccessToken이 single-flight라 요청은 한 번만 나간다.
    refreshAccessToken()
      .catch((error: unknown) => {
        if (isRefreshRejected(error)) {
          useAuthStore.getState().logout();
        }
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });

    return () => {
      cancelled = true;
    };
  }, [ready]);

  return ready;
}
