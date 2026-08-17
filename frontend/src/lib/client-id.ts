/**
 * A per-tab identifier that also works when the page is not a secure context.
 *
 * `crypto.randomUUID` is only exposed over HTTPS or on localhost. Guarding on `crypto` itself
 * is not enough — the object exists either way and only the method is missing — so serving
 * KoalaBattle from a LAN address over plain HTTP threw during hydration and left the battle
 * view blank. That is exactly how an OBS capture machine reaches the overlay.
 *
 * The value only has to be unique among the clients of one production, never unguessable.
 */
export function createClientId(): string {
  const source = globalThis.crypto;
  if (source && typeof source.randomUUID === 'function') return source.randomUUID();
  if (source && typeof source.getRandomValues === 'function') {
    const bytes = source.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
