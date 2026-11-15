import { Outlet } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import { useLogout } from '@/hooks/useLogout';

export default function AdminLayout() {
  const user = useAuthStore((state) => state.user);
  const handleLogout = useLogout();

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      {/* Top App Bar */}
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-white/10 bg-[#051424] px-6">
        <div className="flex items-center gap-2">
          {/* Logo or Title */}
          <h1 className="text-xl font-semibold tracking-wide text-white">
            Theseus <span className="font-medium text-white/60">Admin</span>
          </h1>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-sm text-white/80">{user?.name} 님</span>
          <button
            onClick={() => void handleLogout()}
            className="flex items-center gap-2 text-sm text-white/60 transition-colors hover:text-white"
          >
            <LogOut className="h-4 w-4" />
            <span>로그아웃</span>
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 overflow-auto bg-[#051424]">
        <div className="mx-auto w-[1302px] pt-[20px] pb-10">
          <div className="mb-[20px]">
            <h2 className="text-[32px] font-medium tracking-[-0.8px] text-[#d4e4fa]">
              관리자 페이지
            </h2>
          </div>

          <Outlet />
        </div>
      </main>
    </div>
  );
}
