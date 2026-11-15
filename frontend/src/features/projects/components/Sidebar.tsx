import { NavLink, useNavigate } from 'react-router-dom';
import {
  Wrench,
  Settings,
  UserCircle,
  LogOut,
  User,
  Key,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import theseusLogo from '@/assets/theseus-logo.webp';
import { useProjectStore } from '../stores/useProjectStore';
import { useAuthStore } from '@/store/useAuthStore';
import { useLogout } from '@/hooks/useLogout';
import { useSidebarStore } from '@/store/useSidebarStore';
import { SessionList } from './SessionList';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

const PermissionItem = ({ label, active }: { label: string; active?: boolean }) => (
  <div className="flex items-center gap-1.5">
    {active ? (
      <Check className="h-2.5 w-2.5 text-blue-400" />
    ) : (
      <X className="h-2.5 w-2.5 text-slate-600" />
    )}
    <span
      className={cn(
        'text-[9px] font-medium tracking-tight',
        active ? 'text-slate-300' : 'text-slate-600',
      )}
    >
      {label}
    </span>
  </div>
);

interface SidebarProps {
  projectId?: string;
}

export function Sidebar({ projectId }: SidebarProps) {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const handleLogout = useLogout();
  const {
    currentProject: projectMember,
    isLoading: isProjectLoading,
    errorMessage: projectErrorMessage,
  } = useProjectStore();
  const { isCollapsed, toggle } = useSidebarStore();

  const isAdmin = projectMember?.projectRole === 'ADMIN';
  const displayName = projectMember?.name || user?.name || 'User';

  const getRoleLabel = (role?: string) => {
    switch (role) {
      case 'ADMIN':
        return 'Project Admin';
      case 'MANAGER':
        return 'Project Manager';
      case 'MEMBER':
        return 'Project Member';
      default:
        return 'No Role';
    }
  };

  const displayRole = isProjectLoading
    ? 'Loading...'
    : projectMember
      ? getRoleLabel(projectMember.projectRole)
      : projectErrorMessage || 'Access Denied';

  return (
    <>
      <aside
        className={cn(
          'relative z-20 flex h-screen shrink-0 flex-col border-r border-[#1f2937] bg-[rgba(17,24,39,0.8)] pt-6 shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)] backdrop-blur-[12px] transition-all duration-300 ease-in-out',
          isCollapsed ? 'w-[70px] px-2' : 'w-[260px]',
        )}
      >
        {/* Collapse Toggle Button */}
        <button
          onClick={toggle}
          className="absolute top-[28px] -right-[12px] z-30 flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-[#1f2937] bg-[#0b1424] text-slate-400 shadow-lg transition-all duration-200 hover:bg-blue-400 hover:text-[#003a6b] active:scale-95"
          title={isCollapsed ? '사이드바 펼치기' : '사이드바 접기'}
        >
          {isCollapsed ? (
            <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <ChevronLeft className="h-3.5 w-3.5" />
          )}
        </button>

        {/* Brand Section */}
        <div
          className={cn(
            'group mb-8 flex cursor-pointer items-center transition-all duration-200 active:scale-[0.98]',
            isCollapsed ? 'justify-center px-0' : 'gap-2 px-6',
          )}
          onClick={() => navigate('/')}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded">
            <img src={theseusLogo} alt="Theseus Logo" className="h-full w-full object-cover" />
          </div>
          {!isCollapsed && (
            <div className="flex flex-col">
              <h1
                className="font-['Space_Grotesk'] text-xl leading-tight font-bold tracking-[-1px] text-blue-400"
                style={{ textShadow: '0px 0px 10px rgba(96,165,250,0.4)' }}
              >
                Theseus
              </h1>
              <span className="font-['Space_Grotesk'] text-[10px] font-normal tracking-[1px] text-slate-500 uppercase">
                AI LAB SYSTEM
              </span>
            </div>
          )}
        </div>

        <SessionList projectId={projectId} isCollapsed={isCollapsed}>
          {/* Nav Tabs */}
          <nav className="mb-8 flex flex-col gap-1">
            <NavLink
              to={`/projects/${projectId}/tools`}
              className={({ isActive }) =>
                cn(
                  'flex items-center border-l-4 transition-all duration-200',
                  isCollapsed ? 'w-full justify-center px-0 py-3' : 'gap-3 px-6 py-3',
                  isActive
                    ? 'border-blue-400 bg-[#1e293b] text-blue-400'
                    : 'border-transparent text-slate-400 hover:bg-white/5 hover:text-slate-300',
                )
              }
              title={isCollapsed ? '도구 목록' : undefined}
            >
              <Wrench className={cn('h-4 w-4', !isCollapsed && 'ml-0.5')} />
              {!isCollapsed && (
                <span className="text-sm font-medium tracking-[0.35px]">도구 목록</span>
              )}
            </NavLink>
          </nav>
        </SessionList>

        {/* Footer Section */}
        <div
          className={cn(
            'mt-auto flex flex-col gap-4 border-t border-[rgba(31,41,55,0.5)] pt-4 pb-6',
            isCollapsed ? 'px-2' : 'px-6',
          )}
        >
          {isAdmin && (
            <NavLink
              to={`/projects/${projectId}/settings`}
              className={({ isActive }) =>
                cn(
                  'flex items-center transition-colors',
                  isCollapsed ? 'justify-center py-2' : 'gap-3 py-2',
                  isActive ? 'text-blue-400' : 'text-slate-400 hover:text-slate-300',
                )
              }
              title={isCollapsed ? '관리자 설정' : undefined}
            >
              <Settings className="h-4 w-4" />
              {!isCollapsed && (
                <span className="text-sm font-medium tracking-[0.35px]">관리자 설정</span>
              )}
            </NavLink>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <div
                className={cn(
                  'flex cursor-pointer items-center rounded border border-transparent bg-white/5 transition-all duration-200',
                  isCollapsed ? 'justify-center p-2' : 'gap-3 p-3',
                )}
                title={isCollapsed ? displayName : undefined}
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full border border-blue-400/20 bg-slate-800">
                  <UserCircle className="h-6 w-6 text-slate-400" />
                </div>
                {!isCollapsed && (
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-xs font-bold tracking-[0.35px] text-slate-100">
                      {displayName}
                    </span>
                    <span className="truncate font-['Space_Grotesk'] text-[10px] tracking-[0.35px] text-slate-500">
                      {displayRole}
                    </span>
                  </div>
                )}
              </div>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              side="top"
              align="start"
              sideOffset={12}
              className="w-[220px] border-slate-800 bg-[#0b1424] p-2 text-slate-200 shadow-2xl backdrop-blur-xl"
            >
              <DropdownMenuLabel className="px-3 py-3">
                <div className="flex flex-col gap-2">
                  <span className="text-[10px] font-bold tracking-wider text-slate-500 uppercase">
                    User Profile
                  </span>
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full border border-blue-400/20 bg-blue-400/10">
                      <UserCircle className="h-6 w-6 text-blue-400" />
                    </div>
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate text-sm font-bold text-slate-100">
                        {displayName}
                      </span>
                      <span className="truncate font-['Space_Grotesk'] text-[10px] tracking-tight text-slate-400">
                        {projectMember?.employeeNumber || 'ID: ' + user?.id}
                      </span>
                    </div>
                  </div>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-slate-800/50" />

              <div className="px-1 py-2">
                <div className="flex flex-col gap-2.5 px-2 py-1">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-[10px] text-slate-400">
                      <Key className="h-3.5 w-3.5 text-blue-400" />
                      <span className="font-medium">Access Level</span>
                    </div>
                    <span className="font-['Space_Grotesk'] text-[10px] font-bold text-slate-100">
                      Lv.{projectMember?.accessLevel || 0}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-[10px] text-slate-400">
                      <User className="h-3.5 w-3.5 text-blue-400" />
                      <span className="font-medium">Project Role</span>
                    </div>
                    <span className="rounded-full border border-blue-400/30 bg-blue-400/20 px-1.5 py-0.5 text-[9px] font-bold text-slate-100">
                      {projectMember?.projectRole || 'MEMBER'}
                    </span>
                  </div>
                </div>
              </div>

              <DropdownMenuSeparator className="bg-slate-800/50" />

              <div className="px-3 py-2">
                <span className="mb-2 block text-[9px] font-bold tracking-widest text-slate-500 uppercase">
                  Tool Permissions
                </span>
                <div className="grid grid-cols-2 gap-2">
                  <PermissionItem label="Use" active={projectMember?.canUseTool} />
                  <PermissionItem label="Create" active={projectMember?.canCreateTool} />
                  <PermissionItem label="Update" active={projectMember?.canUpdateTool} />
                  <PermissionItem label="Delete" active={projectMember?.canDeleteTool} />
                </div>
              </div>

              <DropdownMenuSeparator className="bg-slate-800/50" />
              <DropdownMenuItem
                onClick={() => void handleLogout()}
                className="group/item flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2.5 text-red-400 transition-colors hover:text-red-300 focus:bg-red-400/10 focus:text-red-300"
              >
                <LogOut className="h-4 w-4 transition-transform group-hover/item:-translate-x-0.5" />
                <span className="text-xs font-bold tracking-wider uppercase">Logout</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>
    </>
  );
}
