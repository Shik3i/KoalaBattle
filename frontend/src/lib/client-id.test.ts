import assert from 'node:assert/strict';
import test from 'node:test';

import { createClientId } from './client-id.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function withCrypto<T>(replacement: unknown, run: () => T): T {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  Object.defineProperty(globalThis, 'crypto', { value: replacement, configurable: true });
  try {
    return run();
  } finally {
    if (original) Object.defineProperty(globalThis, 'crypto', original);
    else delete (globalThis as { crypto?: unknown }).crypto;
  }
}

test('uses randomUUID where the page is a secure context', () => {
  const id = withCrypto({ randomUUID: () => '11111111-2222-4333-8444-555555555555' }, createClientId);
  assert.equal(id, '11111111-2222-4333-8444-555555555555');
});

test('still produces a UUID when only randomUUID is missing', () => {
  // Plain HTTP on a LAN address: `crypto` exists, `crypto.randomUUID` does not.
  const id = withCrypto(
    {
      getRandomValues: (array: Uint8Array) => {
        for (let index = 0; index < array.length; index += 1) array[index] = index * 7;
        return array;
      }
    },
    createClientId
  );
  assert.match(id, UUID);
});

test('falls back to a plain identifier when no crypto exists at all', () => {
  const id = withCrypto(undefined, createClientId);
  assert.match(id, /^client-/);
  assert.ok(id.length > 10);
});
