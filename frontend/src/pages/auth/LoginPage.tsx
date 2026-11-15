import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Terminal, User, Lock, LogIn, AlertCircle } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { authApi } from '@/api/auth';
import { useAuthStore } from '@/store/useAuthStore';
import { useNavigate } from 'react-router-dom';

const loginSchema = z.object({
  loginId: z.string().min(1, '사번을 입력해주세요.'),
  password: z.string().min(1, '비밀번호를 입력해주세요.'),
});

type LoginFormData = z.infer<typeof loginSchema>;

interface LoginFormProps {
  role: 'USER' | 'ADMIN';
  isLoading: boolean;
  onSubmit: (data: LoginFormData, role: 'USER' | 'ADMIN') => void;
  errorMsg: string | null;
}

const LoginForm = ({ role, isLoading, onSubmit, errorMsg }: LoginFormProps) => {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  return (
    <form onSubmit={handleSubmit((data) => onSubmit(data, role))} className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        {/* ID Input */}
        <div className="relative">
          <label className="absolute -top-2 left-2 z-10 bg-[#0d1c2d] px-1 text-[12px] font-medium tracking-[0.6px] text-[#c1c7d3]">
            사번
          </label>
          <div
            className={`border bg-[#010f1f] ${errors.loginId ? 'border-red-500' : 'border-[rgba(65,71,81,0.3)]'} relative mt-2 flex h-[50px] items-center rounded-[4px] px-4 transition-colors focus-within:border-[#60a5fa] focus-within:ring-1 focus-within:ring-[#60a5fa]/50`}
          >
            <User
              className={`mr-3 h-4 w-4 ${errors.loginId ? 'text-red-500' : 'text-[#8b919d]'}`}
            />
            <input
              type="text"
              placeholder="사번"
              className="w-full border-none bg-transparent text-[16px] text-[#8b919d] outline-none"
              {...register('loginId')}
            />
          </div>
          {errors.loginId && (
            <span className="mt-1 ml-1 block text-[12px] text-red-500">
              {errors.loginId.message}
            </span>
          )}
        </div>

        {/* Password Input */}
        <div className="relative">
          <label className="absolute -top-2 left-2 z-10 bg-[#0d1c2d] px-1 text-[12px] font-medium tracking-[0.6px] text-[#c1c7d3]">
            비밀번호
          </label>
          <div
            className={`border bg-[#010f1f] ${errors.password ? 'border-red-500' : 'border-[rgba(65,71,81,0.3)]'} relative mt-2 flex h-[50px] items-center rounded-[4px] px-4 transition-colors focus-within:border-[#60a5fa] focus-within:ring-1 focus-within:ring-[#60a5fa]/50`}
          >
            <Lock
              className={`mr-3 h-4 w-4 ${errors.password ? 'text-red-500' : 'text-[#8b919d]'}`}
            />
            <input
              type="password"
              placeholder="비밀번호"
              className="w-full border-none bg-transparent text-[16px] text-[#8b919d] outline-none"
              {...register('password')}
            />
          </div>
          {errors.password && (
            <span className="mt-1 ml-1 block text-[12px] text-red-500">
              {errors.password.message}
            </span>
          )}
        </div>

        {/* Error Message */}
        {errorMsg && (
          <div className="flex items-center gap-2 rounded-[4px] border border-red-400/20 bg-red-400/10 p-3 text-[13px] text-red-400">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <p>{errorMsg}</p>
          </div>
        )}
      </div>

      {/* Action Button */}
      <button
        type="submit"
        disabled={isLoading}
        className="flex h-[50px] w-full items-center justify-center gap-2 rounded-[4px] bg-[#60a5fa] text-[18px] font-medium text-[#003a6b] transition-colors hover:bg-[#3b82f6] disabled:opacity-70"
      >
        {isLoading ? '로그인 중...' : '로그인'}
        {!isLoading && <LogIn className="h-4 w-4" />}
      </button>
    </form>
  );
};

export default function LoginPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>(() => {
    return localStorage.getItem('loginTab') || 'user';
  });
  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    localStorage.setItem('loginTab', value);
    setErrorMsg(null); // Clear error message when switching tabs
  };

  const handleLogin = async (data: LoginFormData, role: 'USER' | 'ADMIN') => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const res = await authApi.login(data);

      // 권한 검증: 관리자 탭에서 일반 유저 로그인 시도 시
      if (role === 'ADMIN' && res.systemRole === 'USER') {
        setErrorMsg('해당 계정은 관리자 권한이 없습니다. 사용자 탭을 이용해주세요.');
        return;
      }

      // 권한 검증: 사용자 탭에서 관리자 로그인 시도 시
      if (role === 'USER' && res.systemRole === 'SUPER_ADMIN') {
        setErrorMsg('해당 계정은 관리자입니다. 관리자 탭을 이용해주세요.');
        return;
      }

      // Use the response data to populate auth store
      login(res.accessToken, {
        id: res.userId,
        name: res.name,
        systemRole: res.systemRole,
      });

      // Redirect based on role
      if (res.systemRole === 'SUPER_ADMIN') {
        void navigate('/admin');
      } else {
        void navigate('/');
      }
    } catch (err: unknown) {
      console.error('Login Error:', err);
      const axiosErr = err as { response?: { status?: number } };
      if (axiosErr.response?.status === 401) {
        setErrorMsg('아이디 또는 비밀번호가 올바르지 않습니다.');
      } else {
        setErrorMsg('서버와 통신 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex w-full flex-col items-center">
      {/* Brand Identity Section */}
      <div className="mb-8 flex flex-col items-center">
        <div className="relative mb-4 flex h-[50px] w-[58px] items-center justify-center rounded-xl border border-[#254670] bg-[#0F223A] shadow-[0_0_20px_rgba(37,99,235,0.2)]">
          <Terminal className="h-7 w-7 text-[#60a5fa]" />
        </div>
        <h1 className="font-['Space_Grotesk'] text-[32px] leading-tight font-bold tracking-[-1.6px] text-[#d4e4fa]">
          Theseus
        </h1>
        <p className="mt-1 text-[12px] font-semibold tracking-[1.2px] text-[#c1c7d3] uppercase">
          AI LAB SYSTEM
        </p>
      </div>

      {/* Login Card */}
      <div className="relative w-full max-w-[420px] overflow-hidden rounded-[8px] border border-[rgba(65,71,81,0.2)] bg-[#0d1c2d] shadow-[0px_20px_50px_0px_rgba(0,0,0,0.5)] backdrop-blur-[12px]">
        {/* Decorative Corner Accents */}
        <div className="pointer-events-none absolute top-0 left-0 h-[48px] w-[48px] border-t border-l border-[rgba(65,71,81,0.3)]" />
        <div className="pointer-events-none absolute top-0 right-0 h-[48px] w-[48px] border-t border-r border-[rgba(65,71,81,0.3)]" />
        <div className="pointer-events-none absolute bottom-0 left-0 h-[48px] w-[48px] border-b border-l border-[rgba(65,71,81,0.3)]" />
        <div className="pointer-events-none absolute right-0 bottom-0 h-[48px] w-[48px] border-r border-b border-[rgba(65,71,81,0.3)]" />

        <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
          {/* Tabs */}
          <TabsList className="flex h-auto w-full rounded-none border-b border-[rgba(65,71,81,0.2)] bg-transparent p-0">
            <TabsTrigger
              value="user"
              className="h-[58px] flex-1 rounded-none text-[18px] font-medium text-[#c1c7d3] transition-none data-[state=active]:border-b-2 data-[state=active]:border-[#60a5fa] data-[state=active]:bg-[rgba(28,43,60,0.4)] data-[state=active]:text-[#60a5fa] data-[state=active]:shadow-none"
            >
              사용자
            </TabsTrigger>
            <TabsTrigger
              value="admin"
              className="h-[58px] flex-1 rounded-none text-[18px] font-medium text-[#c1c7d3] transition-none data-[state=active]:border-b-2 data-[state=active]:border-[#60a5fa] data-[state=active]:bg-[rgba(28,43,60,0.4)] data-[state=active]:text-[#60a5fa] data-[state=active]:shadow-none"
            >
              관리자
            </TabsTrigger>
          </TabsList>

          <TabsContent
            value="user"
            className="m-0 p-6 focus-visible:ring-0 focus-visible:outline-none"
          >
            <LoginForm
              role="USER"
              isLoading={isLoading}
              onSubmit={handleLogin}
              errorMsg={errorMsg}
            />
          </TabsContent>

          <TabsContent
            value="admin"
            className="m-0 p-6 focus-visible:ring-0 focus-visible:outline-none"
          >
            <LoginForm
              role="ADMIN"
              isLoading={isLoading}
              onSubmit={handleLogin}
              errorMsg={errorMsg}
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
