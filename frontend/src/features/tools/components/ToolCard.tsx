import { ArrowRight, Shield } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ToolItem } from '../types';

interface ToolCardProps {
  tool: ToolItem;
  onClick?: () => void;
  canEditAccessLevel?: boolean;
  isUpdatingAccessLevel?: boolean;
  onAccessLevelChange?: (accessLevel: number) => void;
}

const TOOL_ACCESS_LEVELS = [1, 2, 3, 4, 5];

export function ToolCard({
  tool,
  onClick,
  canEditAccessLevel = false,
  isUpdatingAccessLevel = false,
  onAccessLevelChange,
}: ToolCardProps) {
  // 통일된 디자인 테마 적용 (BLUE 기반)
  const colors = { gradient: 'from-blue-500/5 to-blue-500/0' };
  const accessLevel = tool.toolGrade ?? 1;

  return (
    <div
      className="group relative flex h-[184px] cursor-pointer flex-col justify-between overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50 p-5 transition-all duration-300 hover:border-slate-700 hover:shadow-lg"
      onClick={onClick}
    >
      {/* 백그라운드 그라데이션 (Hover 시 더 진해짐) */}
      <div
        className={cn(
          'absolute inset-0 bg-gradient-to-br opacity-50 transition-opacity duration-300 group-hover:opacity-100',
          colors.gradient,
        )}
      />

      <div className="relative z-10 flex h-full flex-col">
        {/* 상단 타이틀 */}
        <div className="mb-2 flex items-start justify-between gap-3">
          <h3 className="line-clamp-1 min-w-0 text-lg font-bold text-slate-200 transition-colors group-hover:text-white">
            {tool.displayName}
          </h3>
          <div
            className="flex shrink-0 items-center gap-1.5 rounded border border-blue-500/20 bg-blue-500/10 px-2 py-1 text-xs font-medium text-blue-200"
            title="Tool access level"
            onClick={(event) => event.stopPropagation()}
          >
            <Shield className="h-3.5 w-3.5" />
            {canEditAccessLevel ? (
              <select
                value={accessLevel}
                disabled={isUpdatingAccessLevel}
                onChange={(event) => onAccessLevelChange?.(Number(event.target.value))}
                className="bg-transparent text-blue-100 outline-none disabled:opacity-50"
                aria-label="Tool access level"
              >
                {TOOL_ACCESS_LEVELS.map((level) => (
                  <option key={level} value={level} className="bg-slate-900 text-slate-100">
                    Lv.{level}
                  </option>
                ))}
              </select>
            ) : (
              <span>Lv.{accessLevel}</span>
            )}
          </div>
        </div>

        {/* 텍스트 영역 */}
        <div className="flex-1">
          <p className="line-clamp-2 text-sm leading-relaxed text-slate-400">
            {tool.displayDescription}
          </p>
        </div>

        {/* 하단 푸터 (상세 정보) */}
        <div className="mt-auto flex items-center justify-between border-t border-slate-800/30 pt-3">
          <span className="text-xs font-medium tracking-wider text-slate-500 uppercase transition-colors group-hover:text-slate-300">
            상세 정보
          </span>
          <ArrowRight className="h-4 w-4 transform text-slate-600 transition-colors group-hover:translate-x-1 group-hover:text-slate-400" />
        </div>
      </div>
    </div>
  );
}
