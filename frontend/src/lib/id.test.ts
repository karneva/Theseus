import { afterEach, describe, expect, it, vi } from 'vitest';
import { createId } from './id';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('createId', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('crypto.randomUUID가 있으면 그대로 사용한다', () => {
    const randomUUID = vi.fn(() => '11111111-1111-4111-8111-111111111111');
    vi.stubGlobal('crypto', { randomUUID, getRandomValues: vi.fn() });

    expect(createId()).toBe('11111111-1111-4111-8111-111111111111');
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it('비보안 컨텍스트(randomUUID 없음)에서는 getRandomValues로 v4 UUID를 만든다', () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => bytes.fill(0xff));
    vi.stubGlobal('crypto', { getRandomValues });

    const id = createId();

    expect(getRandomValues).toHaveBeenCalledOnce();
    expect(id).toMatch(UUID_V4);
    expect(id).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff');
  });

  it('Web Crypto가 없어도 v4 형식의 서로 다른 ID를 만든다', () => {
    vi.stubGlobal('crypto', undefined);

    const ids = new Set(Array.from({ length: 20 }, () => createId()));

    expect(ids.size).toBe(20);
    for (const id of ids) expect(id).toMatch(UUID_V4);
  });
});
