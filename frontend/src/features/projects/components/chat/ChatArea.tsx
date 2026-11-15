import { useEffect, useMemo, useRef, useState } from 'react';
import { createId } from '@/lib/id';
import type { KeyboardEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Lock } from 'lucide-react';
import { toast } from 'sonner';
import { chatApi } from '../../api/chat';
import { useChatStreamSSE } from '../../hooks/useChatStreamSSE';
import { useRemoteWorkspaces } from '../../hooks/useRemoteWorkspaces';
import { useToolGenerationSSE } from '../../hooks/useToolGenerationSSE';
import { useChatSessionStore } from '../../stores/useChatSessionStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { ToolPlanMode } from '../../types/chat';
import type { ChatMessage, ToolPlanMode as ToolPlanModeType } from '../../types/chat';
import {
  dedupeToolExecutionMessages,
  groupToolExecutionMessages,
} from '../../utils/toolExecutionMessages';
import { ChatComposer } from './ChatComposer';
import { ChatProgressPanel } from './ChatProgressPanel';
import { MessageItem } from './MessageItem';

export function ChatArea() {
  const { projectId, sessionId } = useParams<{ projectId: string; sessionId: string }>();
  const navigate = useNavigate();
  const { currentProject } = useProjectStore();
  const {
    messages,
    mode,
    addMessage,
    isGenerating,
    setIsGenerating,
    isBuilding,
    progressInfo,
    title,
    isClosed,
    selectedRemoteWorkspaceId,
    setCurrentRunId,
    setDraftPhase,
    setPlanStatus,
    setCurrentPlan,
  } = useChatSessionStore();

  const [input, setInput] = useState('');
  const remoteWorkspaces = useRemoteWorkspaces(projectId);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottom = useRef(true);

  const { connectSSE } = useToolGenerationSSE();
  const { connectChatStream } = useChatStreamSSE();
  const processingLogText = (
    messages[messages.length - 1]?.content ||
    progressInfo?.message ||
    'Initializing stream...'
  ).replace(/blockId:\s*[\w-]+\s*/gi, '');
  const showProcessingPanel =
    (isGenerating || isBuilding) && (isBuilding || mode === ToolPlanMode.PLAN);
  const processingPanelTitle = isBuilding
    ? 'Tool Building'
    : progressInfo?.step || `${mode} Processing`;
  const visibleMessages = useMemo(
    () => groupToolExecutionMessages(dedupeToolExecutionMessages(messages)),
    [messages],
  );

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    // 하단에서 100px 이내면 바닥에 있는 것으로 간주
    const atBottom = scrollHeight - scrollTop - clientHeight < 100;
    isAtBottom.current = atBottom;
  };

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior });
  };

  useEffect(() => {
    if (isAtBottom.current) {
      scrollToBottom(isGenerating ? 'auto' : 'smooth');
    }
  }, [messages, isGenerating, progressInfo]);

  const appendUserMessage = (content: string) => {
    addMessage({
      messageId: createId(),
      senderType: 'USER',
      messageType: mode === ToolPlanMode.PLAN ? 'TOOL_PLAN_REQUEST' : 'CHAT',
      contentType: 'TEXT',
      content,
      createdAt: new Date().toISOString(),
    });
  };

  const appendAssistantPlaceholder = (
    messageType: ChatMessage['messageType'] = 'TOOL_PLAN_RESPONSE',
  ) => {
    addMessage({
      messageId: createId(),
      senderType: 'ASSISTANT',
      messageType,
      contentType: 'MARKDOWN',
      content: '',
      createdAt: new Date().toISOString(),
    });
  };

  const sendChatStreamMessage = (
    userMessage: string,
    streamMode: Extract<ToolPlanModeType, 'ASK' | 'AGENT'>,
  ) => {
    appendUserMessage(userMessage);
    appendAssistantPlaceholder('CHAT');
    setIsGenerating(true);
    setDraftPhase(null);
    setPlanStatus(null);
    setCurrentPlan(null);
    connectChatStream(
      projectId!,
      sessionId!,
      streamMode,
      userMessage,
      selectedRemoteWorkspaceId ?? undefined,
    );
  };

  const sendPlanMessage = async (userMessage: string) => {
    appendUserMessage(userMessage);
    appendAssistantPlaceholder();
    setIsGenerating(true);
    setDraftPhase('PLAN');
    setPlanStatus('REQUESTED');
    setCurrentPlan(null);

    const result = await chatApi.generateToolPlan(projectId!, sessionId!, {
      userMessage,
      mode: ToolPlanMode.PLAN,
      remoteWorkspaceId: selectedRemoteWorkspaceId ?? undefined,
    });

    setCurrentRunId(result.runId);
    setPlanStatus(result.status);
    connectSSE(result.sseUrl, 'PLAN', result.runId);
  };

  const handleSend = async () => {
    if (!input.trim() || isGenerating || !projectId || !sessionId) return;

    const userMessage = input.trim();
    setInput('');
    isAtBottom.current = true;

    try {
      if (mode === ToolPlanMode.ASK || mode === ToolPlanMode.AGENT) {
        sendChatStreamMessage(userMessage, mode);
        return;
      }

      await sendPlanMessage(userMessage);
    } catch (err) {
      console.error('Chat request failed:', err);
      setIsGenerating(false);
      toast.error('요청 처리에 실패했습니다.');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:40px_40px] opacity-20" />

      <div className="z-20 flex h-14 items-center justify-between border-b border-slate-800 bg-[#0b0e14]/60 px-6 backdrop-blur">
        <div className="flex items-center gap-1">
          <span className="text-base font-bold tracking-wider text-blue-400 uppercase">
            {currentProject?.projectName || 'Loading...'}
          </span>
          <span className="mx-1.5 text-slate-600">/</span>
          <span className="text-sm font-medium text-slate-400">{title || '대화 세션'}</span>
          {isClosed && (
            <div className="ml-3 flex items-center gap-1.5 rounded border border-red-500/20 bg-red-500/10 px-2 py-0.5 text-[10px] font-bold tracking-wider text-red-400 uppercase">
              <Lock size={10} />
              Closed
            </div>
          )}
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent z-10 flex-1 overflow-y-auto p-8"
      >
        {messages.length > 0 ? (
          <div className="space-y-6">
            {visibleMessages.map((msg, idx) => {
              const isLast = idx === visibleMessages.length - 1;

              // 최신 생성 중인 어시스턴트 메시지는 말풍선 리스트에서 숨김 (별도 로그 UI로 표시)
              const isLastAssistant = msg.senderType === 'ASSISTANT' && isLast;
              if (isLastAssistant && (isGenerating || isBuilding) && mode === ToolPlanMode.PLAN)
                return null;

              const isLoadingDots =
                msg.senderType === 'ASSISTANT' && isLast && isGenerating && !msg.content;

              return (
                <MessageItem
                  key={msg.messageId}
                  msg={msg}
                  isLast={isLast}
                  isGenerating={isGenerating}
                  isLoadingDots={isLoadingDots}
                />
              );
            })}

            {/* 별도의 생성 로그 UI (말풍선과 별개) */}
            {showProcessingPanel && (
              <ChatProgressPanel
                title={processingPanelTitle}
                message={progressInfo?.message}
                log={processingLogText}
              />
            )}
            <div ref={messagesEndRef} />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-slate-500">
            모드를 선택하고 대화를 시작하세요.
          </div>
        )}
      </div>

      <ChatComposer
        input={input}
        remoteWorkspaces={remoteWorkspaces}
        onInputChange={setInput}
        onSubmit={handleSend}
        onKeyDown={handleKeyDown}
        onNewSession={() => navigate(`/projects/${projectId}`, { replace: true })}
      />
    </div>
  );
}
