import { describe, expect, it } from 'vitest';
import { message, noticeMessage } from '@/test/fixtures';
import type { ToolExecutionNotice } from '../types/chat';
import {
  dedupeToolExecutionMessages,
  groupToolExecutionMessages,
  isTerminalToolNotice,
  parseToolExecutionNotice,
} from './toolExecutionMessages';

const started = (toolName: string, toolUseId?: string): ToolExecutionNotice => ({
  noticeType: 'TOOL_EXECUTION_STARTED',
  toolName,
  toolUseId,
});
const completed = (toolName: string, toolUseId?: string): ToolExecutionNotice => ({
  noticeType: 'TOOL_EXECUTION_COMPLETED',
  toolName,
  toolUseId,
  output: 'ok',
});

describe('parseToolExecutionNotice', () => {
  it('TOOL_EXECUTION_* JSON만 알림으로 인식한다', () => {
    expect(parseToolExecutionNotice(JSON.stringify(started('grep')))).toMatchObject({
      toolName: 'grep',
    });
    expect(parseToolExecutionNotice('plain text')).toBeNull();
    expect(parseToolExecutionNotice('{broken')).toBeNull();
    expect(parseToolExecutionNotice('{"noticeType":"OTHER","toolName":"x"}')).toBeNull();
    expect(parseToolExecutionNotice('{"noticeType":"TOOL_EXECUTION_STARTED"}')).toBeNull();
  });

  it('STARTED이면서 오류가 아닌 알림만 진행 중으로 본다', () => {
    expect(isTerminalToolNotice(started('a'))).toBe(false);
    expect(isTerminalToolNotice({ ...started('a'), isError: true })).toBe(true);
    expect(isTerminalToolNotice(completed('a'))).toBe(true);
  });
});

describe('dedupeToolExecutionMessages', () => {
  it('같은 toolUseId의 STARTED를 종료 알림으로 교체한다', () => {
    const user = message({ senderType: 'USER', content: 'hi' });
    const start = noticeMessage(started('grep', 'u1'), 'n1');
    const done = noticeMessage(completed('grep', 'u1'), 'n2');

    const result = dedupeToolExecutionMessages([user, start, done]);

    expect(result.map((m) => m.messageId)).toEqual([user.messageId, 'n2']);
  });

  it('toolUseId가 없는 종료 알림은 같은 이름의 가장 최근 진행 중 알림을 대체한다', () => {
    const first = noticeMessage(started('grep'), 'a');
    const firstDone = noticeMessage(completed('grep'), 'b');
    const second = noticeMessage(started('grep'), 'c');
    const secondDone = noticeMessage(completed('grep'), 'd');

    const result = dedupeToolExecutionMessages([first, firstDone, second, secondDone]);

    expect(result.map((m) => m.messageId)).toEqual(['b', 'd']);
  });

  it('이미 끝난 알림은 늦게 온 STARTED로 되돌리지 않는다', () => {
    const done = noticeMessage(completed('grep', 'u1'), 'done');
    const lateStart = noticeMessage(started('grep', 'u1'), 'late');

    expect(dedupeToolExecutionMessages([done, lateStart]).map((m) => m.messageId)).toEqual([
      'done',
    ]);
  });
});

describe('groupToolExecutionMessages', () => {
  it('연속된 도구 알림 2개 이상을 그룹 메시지 하나로 묶는다', () => {
    const user = message({ senderType: 'USER', content: 'q' });
    const n1 = noticeMessage(completed('grep', 'u1'), 'n1');
    const n2 = noticeMessage(completed('read', 'u2'), 'n2');
    const answer = message({ content: 'answer' });
    const n3 = noticeMessage(completed('ls', 'u3'), 'n3');

    const result = groupToolExecutionMessages([user, n1, n2, answer, n3]);

    expect(result).toHaveLength(4);
    expect(result[1]).toMatchObject({
      messageId: 'tool-execution-group-n1-n2',
      senderType: 'SYSTEM_NOTICE',
      contentType: 'JSON',
    });
    const group = JSON.parse(result[1].content) as { noticeType: string; notices: unknown[] };
    expect(group.noticeType).toBe('TOOL_EXECUTION_GROUP');
    expect(group.notices).toHaveLength(2);
    // 하나뿐인 알림은 묶지 않고 그대로 둔다.
    expect(result[3]).toBe(n3);
  });
});
