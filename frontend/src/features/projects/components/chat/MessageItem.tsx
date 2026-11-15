import { useState } from 'react';
import {
  Copy,
  Check,
  CheckCircle,
  Play,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { MarkdownViewer } from '@/components/ui/MarkdownViewer';
import type { ChatMessage, ToolExecutionNotice, ToolExecutionNoticeGroup } from '../../types/chat';

/**
 * SYSTEM_NOTICE 등 JSON 본문 메시지가 가질 수 있는 필드. 메시지 종류마다 일부만 채워진다
 * (도구 실행 알림/그룹, PLAN 수정 요청, 도구 승인 요청, 도구 생성 완료).
 */
interface StructuredMessagePayload {
  noticeType?: string;
  notices?: unknown;
  feedbackItems?: Array<{ comment: string }>;
  toolApprovalId?: number;
  status?: string;
  fileName?: string;
}

interface MessageItemProps {
  msg: ChatMessage;
  isLast: boolean;
  isGenerating: boolean;
  isLoadingDots: boolean;
}

function getToolExecutionState(notice: ToolExecutionNotice): 'started' | 'completed' | 'failed' {
  if (notice.noticeType === 'TOOL_EXECUTION_FAILED' || notice.isError === true) return 'failed';
  if (notice.noticeType === 'TOOL_EXECUTION_COMPLETED') return 'completed';
  return 'started';
}

function ToolExecutionStatusIcon({ state }: { state: 'started' | 'completed' | 'failed' }) {
  return (
    <div
      className={`shrink-0 rounded-md p-1.5 ${
        state === 'started'
          ? 'border border-blue-500/20 bg-blue-500/10 text-blue-400'
          : state === 'completed'
            ? 'border border-green-500/20 bg-green-500/10 text-green-400'
            : 'border border-red-500/20 bg-red-500/10 text-red-400'
      }`}
    >
      {state === 'started' && <Play className="h-3.5 w-3.5 animate-pulse" />}
      {state === 'completed' && <CheckCircle2 className="h-3.5 w-3.5" />}
      {state === 'failed' && <AlertTriangle className="h-3.5 w-3.5" />}
    </div>
  );
}

function ToolExecutionNoticeView({
  notice,
  compact = false,
}: {
  notice: ToolExecutionNotice;
  compact?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const executionState = getToolExecutionState(notice);
  const isStarted = executionState === 'started';
  const isFailed = executionState === 'failed';
  const isCompleted = executionState === 'completed';
  const errorOutput = notice.error || notice.output;
  const statusMessage =
    typeof notice.metadata?.message === 'string'
      ? notice.metadata.message
      : isStarted
        ? `Executing tool: ${notice.toolName}`
        : null;

  return (
    <div className="flex w-full flex-col gap-2 font-sans text-slate-300">
      <div
        className={`flex items-center justify-between gap-3 rounded-lg border border-slate-800/80 bg-slate-900/60 shadow-[inset_0_1px_2px_rgba(255,255,255,0.05)] ${compact ? 'p-2' : 'p-3'}`}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <ToolExecutionStatusIcon state={executionState} />
          <div className="flex min-w-0 flex-col">
            <span className="font-['Space_Grotesk'] text-[10px] font-bold tracking-widest text-slate-500 uppercase">
              {isStarted
                ? 'Tool Execution Started'
                : isCompleted
                  ? 'Tool Execution Completed'
                  : 'Tool Execution Failed'}
            </span>
            <span className="truncate text-xs font-bold text-slate-200">
              도구 호출:{' '}
              <code className="rounded border border-blue-800/30 bg-blue-950/40 px-1 py-0.5 font-mono text-[11px] text-blue-400">
                {notice.toolName}
              </code>
            </span>
          </div>
        </div>

        {(notice.toolInput || notice.output || notice.error) && (
          <button
            onClick={() => setIsOpen(!isOpen)}
            className="flex shrink-0 cursor-pointer items-center gap-1 rounded border border-slate-700/50 bg-slate-800/60 px-2 py-1 text-[10px] font-bold tracking-wider text-slate-400 uppercase transition-all hover:bg-slate-700/60 hover:text-slate-200 active:scale-95"
          >
            <span>{isOpen ? 'Close' : 'Details'}</span>
            {isOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
        )}
      </div>

      {isOpen && (
        <div className="animate-fade-in flex max-w-full flex-col gap-2.5 overflow-hidden rounded-lg border border-slate-800/80 bg-[#0c1322] p-3 font-mono text-[11px] leading-relaxed shadow-[inset_0_2px_4px_rgba(0,0,0,0.4)]">
          {statusMessage && (
            <div className="flex max-w-full flex-col gap-1">
              <span className="text-[9px] font-bold tracking-wider text-slate-500 uppercase">
                Execution Status
              </span>
              <pre className="overflow-x-auto rounded border border-slate-900/60 bg-slate-950/40 p-2 break-all whitespace-pre-wrap text-blue-300">
                {statusMessage}
              </pre>
            </div>
          )}

          {notice.toolInput && (
            <div className="flex max-w-full flex-col gap-1">
              <span className="text-[9px] font-bold tracking-wider text-slate-500 uppercase">
                Input Arguments
              </span>
              <pre className="overflow-x-auto rounded border border-slate-900/60 bg-slate-950/40 p-2 break-all whitespace-pre-wrap text-blue-300">
                {JSON.stringify(notice.toolInput, null, 2)}
              </pre>
            </div>
          )}

          {isCompleted && notice.output && (
            <div className="flex max-w-full flex-col gap-1">
              <span className="text-[9px] font-bold tracking-wider text-slate-500 uppercase">
                Execution Output
              </span>
              <pre className="max-h-[250px] overflow-x-auto overflow-y-auto rounded border border-slate-900/60 bg-slate-950/40 p-2 break-all whitespace-pre-wrap text-slate-400">
                {notice.output}
              </pre>
            </div>
          )}

          {isFailed && errorOutput && (
            <div className="flex max-w-full flex-col gap-1">
              <span className="text-[9px] font-bold tracking-wider text-red-400/80 uppercase">
                Error Output
              </span>
              <pre className="overflow-x-auto rounded border border-red-950/20 bg-red-950/10 p-2 break-all whitespace-pre-wrap text-red-300">
                {errorOutput}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolExecutionGroupView({ group }: { group: ToolExecutionNoticeGroup }) {
  const [isOpen, setIsOpen] = useState(false);
  const failedCount = group.notices.filter(
    (notice) => getToolExecutionState(notice) === 'failed',
  ).length;
  const runningCount = group.notices.filter(
    (notice) => getToolExecutionState(notice) === 'started',
  ).length;
  const completedCount = group.notices.filter(
    (notice) => getToolExecutionState(notice) === 'completed',
  ).length;
  const groupState = failedCount > 0 ? 'failed' : runningCount > 0 ? 'started' : 'completed';
  const summaryParts = [
    runningCount > 0 ? `${runningCount} running` : null,
    completedCount > 0 ? `${completedCount} completed` : null,
    failedCount > 0 ? `${failedCount} failed` : null,
  ].filter(Boolean);

  return (
    <div className="flex w-full flex-col gap-2 font-sans text-slate-300">
      <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-800/80 bg-slate-900/60 p-3 shadow-[inset_0_1px_2px_rgba(255,255,255,0.05)]">
        <div className="flex min-w-0 items-center gap-2.5">
          <ToolExecutionStatusIcon state={groupState} />
          <div className="flex min-w-0 flex-col">
            <span className="font-['Space_Grotesk'] text-[10px] font-bold tracking-widest text-slate-500 uppercase">
              Tool Executions
            </span>
            <span className="truncate text-xs font-bold text-slate-200">
              도구 실행 {group.notices.length}개 · {summaryParts.join(' · ')}
            </span>
          </div>
        </div>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex shrink-0 cursor-pointer items-center gap-1 rounded border border-slate-700/50 bg-slate-800/60 px-2 py-1 text-[10px] font-bold tracking-wider text-slate-400 uppercase transition-all hover:bg-slate-700/60 hover:text-slate-200 active:scale-95"
        >
          <span>{isOpen ? 'Close' : 'Details'}</span>
          {isOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      </div>

      {isOpen && (
        <div className="flex flex-col gap-2 rounded-lg border border-slate-800/80 bg-[#0c1322] p-2">
          {group.notices.map((notice, index) => (
            <ToolExecutionNoticeView
              key={`${notice.toolUseId || notice.toolName}-${index}`}
              notice={notice}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function MessageItem({ msg, isLoadingDots }: MessageItemProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
  };

  const isToolNotice = (() => {
    if (msg.content.trim().startsWith('{')) {
      try {
        const parsed = JSON.parse(msg.content) as StructuredMessagePayload;
        return Boolean(parsed.noticeType?.startsWith('TOOL_EXECUTION_'));
      } catch {
        return false;
      }
    }
    return false;
  })();

  const isMessageLoading = msg.senderType === 'ASSISTANT' && !msg.content.trim();

  const renderContent = () => {
    if (msg.senderType === 'ASSISTANT') {
      if (isMessageLoading) {
        return (
          <div className="flex items-center gap-1.5 px-1 py-2">
            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400/60" />
            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400/60 [animation-delay:0.2s]" />
            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400/60 [animation-delay:0.4s]" />
          </div>
        );
      }
      return <MarkdownViewer content={msg.content} />;
    }

    if (msg.content.trim().startsWith('{')) {
      try {
        const parsed = JSON.parse(msg.content) as StructuredMessagePayload;

        if (parsed.noticeType === 'TOOL_EXECUTION_GROUP' && Array.isArray(parsed.notices)) {
          return <ToolExecutionGroupView group={parsed as unknown as ToolExecutionNoticeGroup} />;
        }

        if (parsed.noticeType?.startsWith('TOOL_EXECUTION_')) {
          const notice = parsed as unknown as ToolExecutionNotice;
          return <ToolExecutionNoticeView notice={notice} />;
        }

        if (parsed.feedbackItems && Array.isArray(parsed.feedbackItems)) {
          return (
            <div className="space-y-1">
              <div className="mb-1 text-xs font-bold tracking-tight text-blue-300 uppercase">
                PLAN 수정 요청
              </div>
              {parsed.feedbackItems.map((item, i) => (
                <div key={i} className="flex gap-2 text-[14px]">
                  <span className="mt-1 text-blue-400/60">•</span>
                  <span>{item.comment}</span>
                </div>
              ))}
            </div>
          );
        }

        if (parsed.toolApprovalId) {
          return (
            <div className="flex flex-col gap-1.5">
              <div className="text-xs font-bold tracking-tight text-blue-300 uppercase">
                도구 생성 요청
              </div>
              <div className="flex items-center gap-2 text-[14px] text-slate-300">
                <CheckCircle className="h-3.5 w-3.5 text-blue-400" />
                <span>도구 생성을 요청했습니다</span>
              </div>
            </div>
          );
        }

        if (parsed.status === 'BUILT') {
          return (
            <div className="flex flex-col gap-1.5">
              <div className="text-xs font-bold tracking-tight text-green-400 uppercase">
                도구 생성 완료
              </div>
              <div className="flex items-center gap-2 text-[14px] text-slate-300">
                <CheckCircle className="h-3.5 w-3.5 text-green-500" />
                <span>
                  도구(<code>{parsed.fileName}</code>)가 성공적으로 생성되었습니다.
                </span>
              </div>
            </div>
          );
        }
      } catch {
        // JSON 파싱 실패 시 일반 텍스트로 렌더링
      }
    }

    return (
      <div className="text-[15px] leading-relaxed break-words whitespace-pre-wrap">
        {msg.content}
      </div>
    );
  };

  const showCopyButton =
    msg.content &&
    !isLoadingDots &&
    !isMessageLoading &&
    (msg.senderType === 'USER' || msg.senderType === 'ASSISTANT');

  return (
    <div className={`flex ${msg.senderType === 'USER' ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`group relative max-w-[75%] ${isLoadingDots || isMessageLoading ? 'px-4 py-2' : 'p-4'} overflow-x-auto rounded-lg ${
          msg.senderType === 'USER'
            ? 'bg-slate-700 text-slate-100 shadow-md'
            : isToolNotice
              ? 'w-full border border-slate-800/60 bg-slate-900/30 text-slate-300 shadow-lg'
              : msg.senderType === 'SYSTEM_NOTICE' || msg.senderType === 'SYSTEM'
                ? 'mx-auto border border-slate-700 bg-slate-800/50 text-center text-xs text-slate-400 italic'
                : `border-l-2 border-[#a4c9ff] bg-[#1c2b3c] text-[#d4e4fa] ${isLoadingDots || isMessageLoading ? 'w-fit' : 'w-full'}`
        }`}
      >
        {showCopyButton && (
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 rounded bg-slate-800/50 p-1.5 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-slate-700 hover:text-slate-100"
            title="복사하기"
          >
            {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
          </button>
        )}

        {renderContent()}
      </div>
    </div>
  );
}
