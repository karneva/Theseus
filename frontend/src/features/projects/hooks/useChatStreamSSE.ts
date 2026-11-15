import { API_BASE_URL } from '@/api/config';
import { createId } from '@/lib/id';
import { useCallback, useRef } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { toast } from 'sonner';
import { useAuthStore } from '@/store/useAuthStore';
import { useChatSessionStore } from '../stores/useChatSessionStore';
import type { ToolPlanMode } from '../types/chat';

interface ChatStreamEvent {
  message?: string;
  content?: string;
  tool_name?: string;
  toolName?: string;
  tool_use_id?: string;
  toolUseId?: string;
  tool_input?: Record<string, unknown>;
  toolInput?: Record<string, unknown>;
  output?: string;
  status?: string;
  is_error?: boolean;
  isError?: boolean;
  total_tokens?: number;
  model_name?: string;
}

function getToolName(data: ChatStreamEvent): string | null {
  return data.tool_name || data.toolName || null;
}

function getToolUseId(data: ChatStreamEvent): string | null {
  return data.tool_use_id || data.toolUseId || null;
}

function getToolInput(data: ChatStreamEvent): Record<string, unknown> {
  return data.tool_input || data.toolInput || {};
}

function isToolError(data: ChatStreamEvent): boolean {
  return data.is_error === true || data.isError === true;
}

/**
 * ASK/AGENT 모드 채팅 스트림(POST .../messages/stream)을 SSE로 받는 훅.
 *
 * 호출 전제: 호출부(ChatArea)가 사용자 메시지와 빈 ASSISTANT placeholder를 추가하고
 * `isGenerating=true`로 바꾼 뒤 `connectChatStream`을 부른다. 새 연결을 열면 이전 연결은 먼저 끊는다.
 *
 * 이벤트 순서(서버 기준):
 * 1. `connected` - 스트림 수립. progressInfo만 갱신한다.
 * 2. `chunk`* - 답변 조각. 마지막 ASSISTANT 메시지 뒤에 이어 붙인다.
 * 3. 도구 호출(AGENT)마다
 *    - 시작: `status` | `tool_start` | `tool_execution_started` -> TOOL_EXECUTION_STARTED 알림 upsert
 *    - 종료: `tool_result` | `tool_complete` | `tool_execution_completed`
 *      -> is_error에 따라 COMPLETED/FAILED로 같은 알림을 교체(매칭 규칙은 upsertToolExecutionNotice 참고)
 * 4. 끝: `completed`(정상) 또는 `error`(서버 오류. SYSTEM_NOTICE 메시지와 토스트를 남기고 연결 종료)
 *
 * 상태 전이: 시작 시 isGenerating=true(호출부) -> `completed`/`error`/전송 오류(onerror)에서
 * isGenerating=false, progressInfo=null, abortController=null. onerror는 예외를 다시 던져
 * fetch-event-source의 자동 재연결을 막는다(같은 프롬프트가 중복 실행되지 않게).
 */
export function useChatStreamSSE() {
  const abortRef = useRef<AbortController | null>(null);

  const disconnectChatStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  const connectChatStream = useCallback(
    (
      projectId: string,
      sessionId: string,
      mode: Extract<ToolPlanMode, 'ASK' | 'AGENT'>,
      prompt: string,
      remoteWorkspaceId?: number,
    ) => {
      disconnectChatStream();

      const controller = new AbortController();
      abortRef.current = controller;
      useChatSessionStore.getState().setAbortController(controller);

      const baseUrl = API_BASE_URL;
      const token = useAuthStore.getState().accessToken;

      void fetchEventSource(
        `${baseUrl}/api/v1/projects/${projectId}/sessions/${sessionId}/messages/stream`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ mode, prompt, remoteWorkspaceId }),
          signal: controller.signal,
          openWhenHidden: true,

          onopen(response) {
            if (!response.ok) {
              return Promise.reject(new Error(`Chat stream failed with status ${response.status}`));
            }
            return Promise.resolve();
          },

          onmessage(ev) {
            if (!ev.data) return;

            try {
              const data = JSON.parse(ev.data) as ChatStreamEvent;
              const eventType = (ev.event || '').toLowerCase();
              const store = useChatSessionStore.getState();
              const toolName = getToolName(data);
              const toolUseId = getToolUseId(data);
              const toolInput = getToolInput(data);
              const toolError = isToolError(data);

              switch (eventType) {
                case 'connected':
                  store.setProgressInfo({
                    step: `${mode} connected`,
                    message: data.message || '',
                    percent: 0,
                  });
                  break;

                case 'chunk':
                  if (data.content) {
                    store.updateLastMessageContent(data.content);
                  }
                  break;

                case 'status':
                case 'tool_start':
                case 'tool_execution_started':
                  if (toolName) {
                    store.upsertToolExecutionNotice({
                      noticeType: 'TOOL_EXECUTION_STARTED',
                      toolName,
                      toolUseId,
                      toolInput,
                      status: data.status || 'started',
                      metadata: {
                        message: data.message || `Executing tool: ${toolName}`,
                        step: `Tool Running: ${toolName}`,
                      },
                    });
                  }
                  store.setProgressInfo({
                    step: toolName ? `Tool Running: ${toolName}` : data.message || 'Agent working',
                    message: data.message || '',
                    percent: 0,
                  });
                  break;

                case 'tool_result':
                case 'tool_complete':
                case 'tool_execution_completed':
                  if (toolName) {
                    store.upsertToolExecutionNotice({
                      noticeType: toolError ? 'TOOL_EXECUTION_FAILED' : 'TOOL_EXECUTION_COMPLETED',
                      toolName,
                      toolUseId,
                      toolInput,
                      output: data.output || '',
                      isError: toolError,
                      status: data.status || (toolError ? 'failed' : 'completed'),
                    });
                  }
                  store.setProgressInfo({
                    step: toolName
                      ? `${toolError ? 'Tool Failed' : 'Tool Completed'}: ${toolName}`
                      : toolError
                        ? 'Tool failed'
                        : 'Tool completed',
                    message: data.output || '',
                    percent: 0,
                  });
                  break;

                case 'completed':
                  store.setIsGenerating(false);
                  store.setProgressInfo(null);
                  store.setAbortController(null);
                  abortRef.current = null;
                  break;

                case 'error': {
                  const errorMessage = data.message || 'Chat stream failed.';
                  store.setIsGenerating(false);
                  store.setProgressInfo(null);
                  store.setAbortController(null);
                  store.addMessage({
                    messageId: createId(),
                    senderType: 'SYSTEM_NOTICE',
                    messageType: 'SYSTEM_NOTICE',
                    contentType: 'TEXT',
                    content: errorMessage,
                    createdAt: new Date().toISOString(),
                  });
                  toast.error(errorMessage);
                  disconnectChatStream();
                  break;
                }

                default:
                  console.warn('[ChatStream] Unknown event type:', eventType, data);
              }
            } catch (error) {
              console.warn('[ChatStream] Failed to handle event:', ev.data, error);
            }
          },

          onerror(error) {
            const store = useChatSessionStore.getState();
            store.setIsGenerating(false);
            store.setProgressInfo(null);
            store.setAbortController(null);
            abortRef.current = null;
            toast.error('Chat stream connection failed.');
            throw error;
          },
        },
      ).catch((error) => {
        if (controller.signal.aborted) return;
        console.error('[ChatStream] Connection failed:', error);
      });
    },
    [disconnectChatStream],
  );

  return { connectChatStream, disconnectChatStream };
}
