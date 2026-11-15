import { beforeEach, describe, expect, it } from 'vitest';
import { message } from '@/test/fixtures';
import type { ToolExecutionNotice } from '../types/chat';
import { useChatSessionStore } from './useChatSessionStore';

const initialState = useChatSessionStore.getState();

function initWith(messages = [message({ senderType: 'USER', content: 'q' })]) {
  useChatSessionStore.getState().initSession({
    messages,
    plan: null,
    phase: null,
    toolId: null,
    toolResult: null,
    title: 'session',
    isClosed: false,
  });
}

const notice = (overrides: Partial<ToolExecutionNotice> = {}): ToolExecutionNotice => ({
  noticeType: 'TOOL_EXECUTION_STARTED',
  toolName: 'grep',
  toolUseId: 'u1',
  ...overrides,
});

describe('useChatSessionStore', () => {
  beforeEach(() => {
    useChatSessionStore.setState(initialState, true);
  });

  describe('initSession', () => {
    it('진행 중이던 스트림을 끊고 임시 UI 상태를 초기화한다', () => {
      const controller = new AbortController();
      useChatSessionStore.setState({
        abortController: controller,
        isGenerating: true,
        commentMode: true,
        draftComments: { b1: 'x' },
      });

      initWith();

      const state = useChatSessionStore.getState();
      expect(controller.signal.aborted).toBe(true);
      expect(state).toMatchObject({
        abortController: null,
        isGenerating: false,
        commentMode: false,
        draftComments: {},
        activeTab: 'plan',
        planStatus: null,
      });
    });

    it('생성된 도구가 있으면 결과 탭을 연다', () => {
      useChatSessionStore.getState().initSession({
        messages: [],
        plan: null,
        phase: 'BUILT',
        toolId: '9',
        toolResult: { toolId: 9 },
        title: 't',
        isClosed: false,
      });

      expect(useChatSessionStore.getState()).toMatchObject({
        activeTab: 'result',
        planStatus: 'BUILT',
        isBuilding: false,
      });
    });
  });

  describe('updateLastMessageContent', () => {
    it('마지막 ASSISTANT 메시지에 chunk를 이어 붙인다', () => {
      initWith([message({ senderType: 'USER' }), message({ content: 'Hel' })]);

      useChatSessionStore.getState().updateLastMessageContent('lo');

      const { messages } = useChatSessionStore.getState();
      expect(messages).toHaveLength(2);
      expect(messages[1].content).toBe('Hello');
    });

    it('마지막이 사용자 메시지면 새 ASSISTANT 메시지를 만든다', () => {
      initWith();

      useChatSessionStore.getState().updateLastMessageContent('first');

      const { messages } = useChatSessionStore.getState();
      expect(messages).toHaveLength(2);
      expect(messages[1]).toMatchObject({ senderType: 'ASSISTANT', content: 'first' });
    });
  });

  describe('upsertToolExecutionNotice', () => {
    it('새 알림은 스트리밍 중인 빈 ASSISTANT placeholder 앞에 끼워 넣는다', () => {
      const placeholder = message({ content: '' });
      initWith([message({ senderType: 'USER' }), placeholder]);

      useChatSessionStore.getState().upsertToolExecutionNotice(notice());

      const { messages } = useChatSessionStore.getState();
      expect(messages.map((m) => m.senderType)).toEqual(['USER', 'SYSTEM_NOTICE', 'ASSISTANT']);
      expect(messages[2]).toBe(placeholder);
    });

    it('같은 toolUseId의 알림은 새로 추가하지 않고 교체한다', () => {
      initWith();
      const store = useChatSessionStore.getState();

      store.upsertToolExecutionNotice(notice());
      store.upsertToolExecutionNotice(notice({ noticeType: 'TOOL_EXECUTION_COMPLETED' }));

      const notices = useChatSessionStore
        .getState()
        .messages.filter((m) => m.senderType === 'SYSTEM_NOTICE');
      expect(notices).toHaveLength(1);
      expect(JSON.parse(notices[0].content)).toMatchObject({
        noticeType: 'TOOL_EXECUTION_COMPLETED',
      });
    });

    it('toolUseId 없는 종료 알림은 같은 이름의 진행 중 알림만 교체한다', () => {
      initWith();
      const store = useChatSessionStore.getState();

      store.upsertToolExecutionNotice(notice({ toolUseId: null }));
      store.upsertToolExecutionNotice(
        notice({ toolUseId: null, noticeType: 'TOOL_EXECUTION_COMPLETED' }),
      );
      // 이미 끝난 알림은 건너뛰므로 두 번째 호출은 새 알림이 된다.
      store.upsertToolExecutionNotice(notice({ toolUseId: null }));

      const notices = useChatSessionStore
        .getState()
        .messages.filter((m) => m.senderType === 'SYSTEM_NOTICE')
        .map((m) => (JSON.parse(m.content) as ToolExecutionNotice).noticeType);
      expect(notices).toEqual(['TOOL_EXECUTION_COMPLETED', 'TOOL_EXECUTION_STARTED']);
    });
  });

  describe('completeAssistantPlaceholder', () => {
    it('비어 있는 PLAN 응답 placeholder를 받은 메시지로 채우되 messageId는 유지한다', () => {
      const placeholder = message({ messageType: 'TOOL_PLAN_RESPONSE', content: '' });
      initWith([message({ senderType: 'USER' }), placeholder]);

      useChatSessionStore
        .getState()
        .completeAssistantPlaceholder(
          message({ messageId: 'server-1', content: 'general answer' }),
        );

      const { messages } = useChatSessionStore.getState();
      expect(messages).toHaveLength(2);
      expect(messages[1]).toMatchObject({
        messageId: placeholder.messageId,
        content: 'general answer',
      });
    });
  });
});
