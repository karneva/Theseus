import type { ChatMessage, ToolExecutionNotice } from '@/features/projects/types/chat';

let sequence = 0;

export function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  sequence += 1;
  return {
    messageId: `m-${sequence}`,
    senderType: 'ASSISTANT',
    messageType: 'CHAT',
    contentType: 'MARKDOWN',
    content: '',
    createdAt: '2026-01-01T00:00:00.000Z',
    ...overrides,
  };
}

export function noticeMessage(notice: ToolExecutionNotice, id?: string): ChatMessage {
  return message({
    messageId: id ?? `notice-${notice.toolName}-${notice.noticeType}-${sequence + 1}`,
    senderType: 'SYSTEM_NOTICE',
    messageType: 'SYSTEM_NOTICE',
    contentType: 'JSON',
    content: JSON.stringify(notice),
  });
}
