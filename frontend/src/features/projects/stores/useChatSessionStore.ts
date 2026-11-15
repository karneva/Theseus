import {
  parseToolExecutionNotice,
  toolNoticeExactKey,
  toolNoticeNameKey,
  isTerminalToolNotice,
} from '../utils/toolExecutionMessages';
import { create } from 'zustand';
import { createId } from '@/lib/id';
import type {
  ChatMessage,
  CreatedToolRecovery,
  DraftPhase,
  ProgressInfo,
  StructuredPlan,
  ToolExecutionNotice,
  ToolPlanMode,
} from '../types/chat';

function isEmptyAssistantPlaceholder(message: ChatMessage | undefined): boolean {
  return message?.senderType === 'ASSISTANT' && !message.content.trim();
}

function isAssistantMessage(message: ChatMessage | undefined): boolean {
  return message?.senderType === 'ASSISTANT';
}

/**
 * 도구 실행 알림을 덮어쓸 기존 메시지 위치를 찾는다.
 *
 * 1. toolUseId가 있으면 같은 toolUseId를 가진 가장 최근 알림(정확 매칭)
 * 2. 없으면 같은 toolName이면서 아직 끝나지 않은(STARTED, 오류 아님) 가장 최근 알림
 *    - 일부 이벤트는 종료 시 toolUseId를 주지 않으므로 이름으로 짝을 맞춘다.
 *    - 이미 끝난 알림은 건너뛰어, 같은 도구를 여러 번 호출해도 이전 결과를 덮지 않는다.
 * 3. 둘 다 없으면 -1(새 알림으로 추가)
 */
function findToolNoticeUpsertIndex(messages: ChatMessage[], notice: ToolExecutionNotice): number {
  const exactKey = toolNoticeExactKey(notice);
  const nameKey = toolNoticeNameKey(notice);

  if (exactKey) {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const existingNotice = parseToolExecutionNotice(messages[i].content);
      if (existingNotice && toolNoticeExactKey(existingNotice) === exactKey) {
        return i;
      }
    }
  }

  if (nameKey) {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const existingNotice = parseToolExecutionNotice(messages[i].content);
      if (
        existingNotice &&
        toolNoticeNameKey(existingNotice) === nameKey &&
        !isTerminalToolNotice(existingNotice)
      ) {
        return i;
      }
    }
  }

  return -1;
}

/**
 * 현재 열린 채팅 세션 하나의 화면 상태.
 *
 * - messages: 서버에서 읽은 메시지 + 스트리밍 중 로컬에서 추가한 메시지(사용자 입력, ASSISTANT
 *   placeholder, 도구 실행 알림). 스트림이 끝나면 SSE 훅이 서버 상태로 다시 덮어쓴다(initSession).
 * - draftPhase: ToolPlan 진행 단계. 일반적인 전이는
 *   null -> PLAN(생성 요청) -> REVIEW(초안 도착) -> PENDING(승인 요청) -> APPROVED -> BUILDING -> BUILT
 *   이고, 실패/반려 시 FAILED/REJECTED. ASK/AGENT 대화를 보내면 null로 돌아간다.
 * - isGenerating / isBuilding: PLAN·채팅 스트림 진행 중 / 승인 후 BUILD 진행 중.
 * - abortController: 현재 열린 스트림. initSession이 이전 스트림을 끊는 데 쓴다.
 */
interface ChatSessionState {
  messages: ChatMessage[];
  mode: ToolPlanMode;
  currentPlan: StructuredPlan | null;
  draftPhase: DraftPhase;
  planStatus: string | null;
  currentRunId: string | null;
  currentToolPlanGroupId: string | null;
  currentToolPlanId: string | null;
  currentToolId: string | null;
  createdTool: CreatedToolRecovery | null;
  isGenerating: boolean;
  progressInfo: ProgressInfo | null;
  commentMode: boolean;
  draftComments: Record<string, string>;
  toolResult: Record<string, unknown> | null;
  activeTab: 'plan' | 'result';
  isBuilding: boolean;
  draftVersion: number;
  planVersion: number;
  abortController: AbortController | null;
  selectedRemoteWorkspaceId: number | null;
  title: string;
  isClosed: boolean;

  /** 서버에서 읽은 세션 상세로 상태 전체를 교체한다. 진행 중이던 스트림은 끊고 임시 UI 상태는 초기화한다. */
  initSession: (data: {
    messages: ChatMessage[];
    plan: StructuredPlan | null;
    phase: DraftPhase;
    toolId: string | null;
    toolPlanGroupId?: string | null;
    toolPlanId?: string | null;
    runId?: string | null;
    planStatus?: string | null;
    createdTool?: CreatedToolRecovery | null;
    toolResult: Record<string, unknown> | null;
    title: string;
    isClosed: boolean;
    planVersion?: number;
    draftVersion?: number;
  }) => void;
  setMode: (mode: ToolPlanMode) => void;
  setActiveTab: (tab: 'plan' | 'result') => void;
  setIsBuilding: (isBuilding: boolean) => void;
  /**
   * 도구 실행 알림을 추가하거나 기존 알림을 갱신한다(매칭 규칙은 findToolNoticeUpsertIndex).
   * 새 알림은 스트리밍 중인 ASSISTANT 메시지 바로 앞에 끼워 넣어, 답변 본문이 항상 마지막에 오게 한다.
   */
  upsertToolExecutionNotice: (notice: ToolExecutionNotice) => void;
  addMessage: (msg: ChatMessage) => void;
  completeAssistantPlaceholder: (msg: ChatMessage) => void;
  /** 스트림 chunk를 마지막 ASSISTANT 메시지에 이어 붙인다. 없으면 새 ASSISTANT 메시지를 만든다. */
  updateLastMessageContent: (chunk: string) => void;
  /** 재접속 replay처럼 전체 본문이 올 때 마지막 ASSISTANT 메시지 내용을 교체한다. */
  replaceLastMessageContent: (content: string) => void;
  setCurrentPlan: (plan: StructuredPlan | null) => void;
  setDraftPhase: (phase: DraftPhase) => void;
  setPlanStatus: (status: string | null) => void;
  setIsGenerating: (isGen: boolean) => void;
  setProgressInfo: (info: ProgressInfo | null) => void;
  setCommentMode: (mode: boolean) => void;
  setDraftComment: (blockId: string, comment: string) => void;
  clearDraftComments: () => void;
  setCurrentRunId: (runId: string | null) => void;
  setCurrentToolId: (toolId: string | null) => void;
  setCurrentToolPlanId: (planId: string | null) => void;
  setPlanVersion: (version: number) => void;
  setAbortController: (ctrl: AbortController | null) => void;
  setSelectedRemoteWorkspaceId: (remoteWorkspaceId: number | null) => void;
  updateTitle: (title: string) => void;
  setClosed: (isClosed: boolean) => void;
}

export const useChatSessionStore = create<ChatSessionState>((set, get) => ({
  messages: [],
  mode: 'PLAN',
  currentPlan: null,
  draftPhase: null,
  planStatus: null,
  currentRunId: null,
  currentToolPlanGroupId: null,
  currentToolPlanId: null,
  currentToolId: null,
  createdTool: null,
  isGenerating: false,
  progressInfo: null,
  commentMode: false,
  draftComments: {},
  draftVersion: 0,
  planVersion: 0,
  toolResult: null,
  activeTab: 'plan',
  isBuilding: false,
  abortController: null,
  selectedRemoteWorkspaceId: null,
  title: '',
  isClosed: false,

  initSession: ({
    messages,
    plan,
    phase,
    toolId,
    toolPlanGroupId,
    toolPlanId,
    runId,
    planStatus,
    createdTool,
    toolResult,
    title,
    isClosed,
    planVersion,
    draftVersion,
  }) => {
    // 세션을 서버 기준으로 다시 채울 때, 이전 상태에서 열려 있던 스트림(SSE)이 남아
    // 새 세션의 메시지를 오염시키지 않도록 먼저 끊는다.
    get().abortController?.abort();
    set({
      messages,
      currentPlan: plan,
      draftPhase: phase,
      planStatus: planStatus || phase,
      currentRunId: runId || null,
      currentToolId: toolId,
      currentToolPlanGroupId: toolPlanGroupId || null,
      currentToolPlanId: toolPlanId || null,
      createdTool: createdTool || null,
      toolResult: toolResult || null,
      activeTab: createdTool || toolResult ? 'result' : 'plan',
      isBuilding: phase === 'BUILDING',
      draftVersion: draftVersion || 0,
      planVersion: planVersion || 0,
      title,
      isClosed,
      isGenerating: false,
      progressInfo: null,
      commentMode: false,
      draftComments: {},
      abortController: null,
    });
  },

  setMode: (mode) => set({ mode }),

  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),

  upsertToolExecutionNotice: (notice) =>
    set((state) => {
      const content = JSON.stringify(notice);
      const messages = [...state.messages];
      const existingIndex = findToolNoticeUpsertIndex(messages, notice);

      if (existingIndex >= 0) {
        messages[existingIndex] = {
          ...messages[existingIndex],
          senderType: 'SYSTEM_NOTICE',
          messageType: 'SYSTEM_NOTICE',
          contentType: 'JSON',
          content,
        };
        return { messages };
      }

      const message: ChatMessage = {
        messageId: createId(),
        senderType: 'SYSTEM_NOTICE',
        messageType: 'SYSTEM_NOTICE',
        contentType: 'JSON',
        content,
        createdAt: new Date().toISOString(),
      };
      const insertIndex =
        isEmptyAssistantPlaceholder(messages[messages.length - 1]) ||
        (state.isGenerating && isAssistantMessage(messages[messages.length - 1]))
          ? messages.length - 1
          : messages.length;
      messages.splice(insertIndex, 0, message);

      return { messages };
    }),

  completeAssistantPlaceholder: (msg) =>
    set((state) => {
      const messages = [...state.messages];
      const lastMessage = messages[messages.length - 1];
      if (
        lastMessage?.senderType === 'ASSISTANT' &&
        lastMessage.messageType === 'TOOL_PLAN_RESPONSE' &&
        !lastMessage.content
      ) {
        messages[messages.length - 1] = {
          ...lastMessage,
          ...msg,
          messageId: lastMessage.messageId,
        };
        return { messages };
      }

      return { messages: [...messages, msg] };
    }),

  updateLastMessageContent: (chunk) =>
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        const last = messages[messages.length - 1];
        if (last.senderType === 'ASSISTANT') {
          messages[messages.length - 1] = { ...last, content: last.content + chunk };
          return { messages };
        }
      }

      // 어시스턴트 메시지가 없거나 마지막 메시지가 유저/시스템인 경우 새로 생성
      const newMsg: ChatMessage = {
        messageId: createId(),
        senderType: 'ASSISTANT',
        messageType: 'TOOL_PLAN_RESPONSE',
        contentType: 'MARKDOWN',
        content: chunk,
        createdAt: new Date().toISOString(),
      };
      return { messages: [...messages, newMsg] };
    }),

  replaceLastMessageContent: (content) =>
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        const last = messages[messages.length - 1];
        if (last.senderType === 'ASSISTANT') {
          messages[messages.length - 1] = { ...last, content };
          return { messages };
        }
      }

      const newMsg: ChatMessage = {
        messageId: createId(),
        senderType: 'ASSISTANT',
        messageType: 'TOOL_PLAN_RESPONSE',
        contentType: 'MARKDOWN',
        content,
        createdAt: new Date().toISOString(),
      };
      return { messages: [...messages, newMsg] };
    }),

  setCurrentPlan: (plan) => set({ currentPlan: plan }),
  setDraftPhase: (phase) => set({ draftPhase: phase }),
  setPlanStatus: (status) => set({ planStatus: status }),
  setIsGenerating: (isGen) => set({ isGenerating: isGen }),
  setProgressInfo: (info) => set({ progressInfo: info }),
  setCommentMode: (mode) => set({ commentMode: mode }),
  setDraftComment: (blockId, comment) =>
    set((state) => ({
      draftComments: { ...state.draftComments, [blockId]: comment },
    })),
  clearDraftComments: () => set({ draftComments: {} }),

  setCurrentRunId: (runId) => set({ currentRunId: runId }),
  setCurrentToolId: (toolId) => set({ currentToolId: toolId }),
  setCurrentToolPlanId: (planId) => set({ currentToolPlanId: planId }),
  setPlanVersion: (version) => set({ planVersion: version }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setIsBuilding: (isBuilding) => set({ isBuilding }),
  setAbortController: (ctrl) => set({ abortController: ctrl }),
  setSelectedRemoteWorkspaceId: (remoteWorkspaceId) =>
    set({ selectedRemoteWorkspaceId: remoteWorkspaceId }),

  updateTitle: (title) => set({ title }),
  setClosed: (isClosed) => set({ isClosed }),
}));
