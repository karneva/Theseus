/**
 * 클라이언트 측 임시 ID(낙관적 메시지, 알림 등)를 만든다.
 *
 * `crypto.randomUUID`는 secure context(HTTPS 또는 localhost)에서만 정의되므로,
 * 서버 IP에 HTTP로 먼저 띄운 셀프호스팅 환경에서는 호출 즉시 TypeError가 난다.
 * 그런 환경에서도 채팅 전송이 멈추지 않도록 `crypto.getRandomValues`로
 * RFC 4122 v4 형식의 UUID를 직접 조립하는 fallback을 둔다.
 */
export function createId(): string {
  const cryptoApi = globalThis.crypto as Crypto | undefined;

  if (typeof cryptoApi?.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }

  const bytes = new Uint8Array(16);
  if (typeof cryptoApi?.getRandomValues === 'function') {
    cryptoApi.getRandomValues(bytes);
  } else {
    // Web Crypto가 아예 없는 환경 대비. 화면 내부 키 용도라 암호학적 강도는 필요하지 않다.
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }

  // version(4)과 variant(10xx) 비트를 맞춰 v4 UUID 형식으로 만든다.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
