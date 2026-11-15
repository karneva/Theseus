import { Outlet, useNavigate } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import { useLogout } from '@/hooks/useLogout';

export default function UserLayout() {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const handleLogout = useLogout();

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-[#010f1f] text-foreground">
      {/* Top App Bar */}
      <header className="relative z-10 flex h-16 shrink-0 items-center justify-between border-b border-white/10 bg-[rgba(5,20,36,0.8)] px-6 backdrop-blur-md">
        <div className="flex items-center gap-2">
          {/* Logo or Title */}
          <h1
            className="cursor-pointer text-xl font-semibold tracking-wide text-white"
            onClick={() => navigate('/')}
          >
            Theseus
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
      <main className="relative z-10 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
