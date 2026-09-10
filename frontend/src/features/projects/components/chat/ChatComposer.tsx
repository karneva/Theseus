import type { KeyboardEventHandler } from 'react';
import { Lock } from 'lucide-react';
import { useChatSessionStore } from '../../stores/useChatSessionStore';
import { ToolPlanMode } from '../../types/chat';
import type { ToolPlanMode as ToolPlanModeType } from '../../types/chat';
import type { RemoteWorkspaceResponse } from '../../types/project';

const MODE_OPTIONS: Array<{ value: ToolPlanModeType; label: string; description: string }> = [
  { value: ToolPlanMode.ASK, label: 'ASK', description: '일반 대화' },
  { value: ToolPlanMode.PLAN, label: 'PLAN', description: '도구 명세' },
  { value: ToolPlanMode.AGENT, label: 'AGENT', description: '실행 준비' },
];

interface ChatComposerProps {
  input: string;
  remoteWorkspaces: RemoteWorkspaceResponse[];
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>;
  onNewSession: () => void;
}

export function ChatComposer({
  input,
  remoteWorkspaces,
  onInputChange,
  onSubmit,
  onKeyDown,
  onNewSession,
}: ChatComposerProps) {
  const {
    mode,
    setMode,
    isGenerating,
    isClosed,
    selectedRemoteWorkspaceId,
    setSelectedRemoteWorkspaceId,
  } = useChatSessionStore();
  const selectedRemoteWorkspace = remoteWorkspaces.find(
    (workspace) => workspace.remoteWorkspaceId === selectedRemoteWorkspaceId,
  );

  return (
    <div className="px-8 pb-8 pt-4 bg-gradient-to-t from-[#051424] via-[#051424]/90 to-transparent z-10">
      <div className="mb-3 flex gap-2">
        {MODE_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={isGenerating || isClosed}
            onClick={() => setMode(option.value)}
            className={`px-3 py-2 rounded border text-xs font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              mode === option.value
                ? 'bg-blue-400 border-blue-400 text-slate-950'
                : 'bg-[#0d1c2d] border-slate-700 text-slate-400 hover:text-blue-200 hover:border-blue-400/50'
            }`}
            title={option.description}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="mb-3 max-w-xs">
        <select
          value={selectedRemoteWorkspaceId ?? ''}
          onChange={(event) => {
            const value = event.target.value;
            setSelectedRemoteWorkspaceId(value ? Number(value) : null);
          }}
          disabled={isGenerating || isClosed}
          className="w-full rounded border border-slate-700 bg-[#0d1c2d] px-3 py-2 text-xs font-medium text-slate-300 outline-none transition-colors focus:border-blue-400/60 disabled:opacity-40"
        >
          <option value="">Remote Workspace 없음</option>
          {remoteWorkspaces.map((workspace) => (
            <option key={workspace.remoteWorkspaceId} value={workspace.remoteWorkspaceId}>
              {workspace.name} ({workspace.host})
            </option>
          ))}
        </select>
        {selectedRemoteWorkspace && (
          <p className="mt-2 text-xs text-slate-400">
            {mode === ToolPlanMode.AGENT
              ? selectedRemoteWorkspace.allowWriteExecution
                ? 'AGENT can use this Remote Workspace for write/command tasks.'
                : 'This Remote Workspace is read-only for AGENT.'
              : 'ASK/PLAN use the selected Remote Workspace as read-only context.'}
          </p>
        )}
      </div>

      {isClosed ? (
        <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-6 flex flex-col items-center justify-center gap-4 shadow-xl backdrop-blur-sm">
          <div className="flex items-center gap-2 text-red-400 font-medium">
            <Lock size={18} className="animate-pulse" />
            <span className="text-sm tracking-tight">
              이 세션은 종료되었습니다. 기록만 확인할 수 있습니다.
            </span>
          </div>
          <button
            onClick={onNewSession}
            className="bg-blue-400 hover:bg-blue-500 text-slate-900 px-8 py-2.5 rounded font-bold transition-all hover:scale-[1.02] active:scale-[0.98] uppercase tracking-widest text-[11px] shadow-[0_0_20px_rgba(96,165,250,0.3)]"
          >
            새 대화 시작하기
          </button>
        </div>
      ) : (
        <div
          className={`bg-[#0d1c2d] border ${isGenerating ? 'border-slate-600' : 'border-slate-700/50'} rounded-lg p-3 flex items-end shadow-lg shadow-blue-500/5 transition-colors`}
        >
          <textarea
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={isGenerating}
            className="flex-1 bg-transparent border-none outline-none resize-none px-3 py-2 text-sm text-slate-300 placeholder-slate-500 min-h-[40px] max-h-[200px] disabled:opacity-50"
            rows={1}
            placeholder={
              isGenerating
                ? 'AI가 작업 중입니다...'
                : mode === ToolPlanMode.ASK
                  ? '일반 질문을 입력하세요. (Enter 전송, Shift+Enter 줄바꿈)'
                  : mode === ToolPlanMode.AGENT
                    ? 'Agent에게 승인된 Tool 사용 작업을 지시하세요. (Enter 전송, Shift+Enter 줄바꿈)'
                    : 'Tool PLAN 요청 또는 피드백을 입력하세요. (Enter 전송, Shift+Enter 줄바꿈)'
            }
          />
          <button
            onClick={onSubmit}
            disabled={isGenerating || !input.trim()}
            className="bg-blue-400 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-slate-900 px-6 py-2 rounded text-xs font-bold transition-colors ml-4 uppercase tracking-wider"
          >
            {isGenerating ? '처리중' : '보내기'}
          </button>
        </div>
      )}
    </div>
  );
}
