import type { ChatMessage, ToolExecutionNotice, ToolExecutionNoticeGroup } from '../types/chat';

export function parseToolExecutionNotice(content: string): ToolExecutionNotice | null {
  const trimmed = content.trim();
  if (!trimmed.startsWith('{')) return null;

  try {
    const parsed = JSON.parse(trimmed) as Partial<ToolExecutionNotice>;
    if (
      typeof parsed.noticeType === 'string' &&
      parsed.noticeType.startsWith('TOOL_EXECUTION_') &&
      typeof parsed.toolName === 'string'
    ) {
      return parsed as ToolExecutionNotice;
    }
  } catch {
    return null;
  }

  return null;
}

export function toolNoticeExactKey(notice: ToolExecutionNotice): string | null {
  return notice.toolUseId ? `id:${notice.toolUseId}` : null;
}

export function toolNoticeNameKey(notice: ToolExecutionNotice): string | null {
  return notice.toolName ? `tool:${notice.toolName}` : null;
}

export function isTerminalToolNotice(notice: ToolExecutionNotice): boolean {
  return notice.noticeType !== 'TOOL_EXECUTION_STARTED' || notice.isError === true;
}

export function dedupeToolExecutionMessages(messages: ChatMessage[]): ChatMessage[] {
  const visible: ChatMessage[] = [];
  const noticeIndexByExactKey = new Map<string, number>();
  const startedIndexesByToolName = new Map<string, number[]>();

  const rememberStarted = (notice: ToolExecutionNotice, visibleIndex: number) => {
    const nameKey = toolNoticeNameKey(notice);
    if (!nameKey) return;
    const indexes = startedIndexesByToolName.get(nameKey) || [];
    indexes.push(visibleIndex);
    startedIndexesByToolName.set(nameKey, indexes);
  };

  const takeLatestStartedIndex = (notice: ToolExecutionNotice): number | null => {
    const nameKey = toolNoticeNameKey(notice);
    if (!nameKey) return null;

    const indexes = startedIndexesByToolName.get(nameKey);
    if (!indexes) return null;

    while (indexes.length > 0) {
      const index = indexes.pop();
      if (index === undefined) break;

      const existingNotice = parseToolExecutionNotice(visible[index]?.content || '');
      if (existingNotice && !isTerminalToolNotice(existingNotice)) {
        return index;
      }
    }

    return null;
  };

  for (const message of messages) {
    const notice = parseToolExecutionNotice(message.content);
    const exactKey = notice ? toolNoticeExactKey(notice) : null;

    if (!notice) {
      visible.push(message);
      continue;
    }

    if (!isTerminalToolNotice(notice)) {
      const existingIndex = exactKey ? noticeIndexByExactKey.get(exactKey) : undefined;
      if (existingIndex !== undefined) {
        const existingNotice = parseToolExecutionNotice(visible[existingIndex].content);
        if (!existingNotice || !isTerminalToolNotice(existingNotice)) {
          visible[existingIndex] = message;
        }
        continue;
      }

      const visibleIndex = visible.length;
      visible.push(message);
      if (exactKey) {
        noticeIndexByExactKey.set(exactKey, visibleIndex);
      }
      rememberStarted(notice, visibleIndex);
      continue;
    }

    const exactMatchIndex = exactKey ? noticeIndexByExactKey.get(exactKey) : undefined;
    const fallbackStartedIndex =
      exactMatchIndex === undefined ? takeLatestStartedIndex(notice) : null;
    const replaceIndex = exactMatchIndex ?? fallbackStartedIndex;

    if (replaceIndex !== undefined && replaceIndex !== null) {
      visible[replaceIndex] = message;
      if (exactKey) {
        noticeIndexByExactKey.set(exactKey, replaceIndex);
      }
      continue;
    }

    const visibleIndex = visible.length;
    visible.push(message);
    if (exactKey) {
      noticeIndexByExactKey.set(exactKey, visibleIndex);
    }
  }

  return visible;
}

function isToolExecutionMessage(message: ChatMessage): boolean {
  return parseToolExecutionNotice(message.content) !== null;
}

export function groupToolExecutionMessages(messages: ChatMessage[]): ChatMessage[] {
  const grouped: ChatMessage[] = [];
  let buffer: ChatMessage[] = [];

  const flushBuffer = () => {
    if (buffer.length === 0) return;

    if (buffer.length === 1) {
      grouped.push(buffer[0]);
      buffer = [];
      return;
    }

    const notices = buffer
      .map((message) => parseToolExecutionNotice(message.content))
      .filter((notice): notice is ToolExecutionNotice => notice !== null);
    const groupPayload: ToolExecutionNoticeGroup = {
      noticeType: 'TOOL_EXECUTION_GROUP',
      notices,
    };
    grouped.push({
      ...buffer[0],
      messageId: `tool-execution-group-${buffer[0].messageId}-${buffer[buffer.length - 1].messageId}`,
      senderType: 'SYSTEM_NOTICE',
      messageType: 'SYSTEM_NOTICE',
      contentType: 'JSON',
      content: JSON.stringify(groupPayload),
    });
    buffer = [];
  };

  for (const message of messages) {
    if (isToolExecutionMessage(message)) {
      buffer.push(message);
      continue;
    }

    flushBuffer();
    grouped.push(message);
  }

  flushBuffer();

  return grouped;
}
