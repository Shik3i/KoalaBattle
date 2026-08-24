import assert from 'node:assert/strict';
import test from 'node:test';

import { apiToken, authHeaders, setApiToken, withWebsocketToken } from './auth-token.ts';

function withStorage(run: () => void) {
  const store = new Map<string, string>();
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key)
  };
  try {
    run();
  } finally {
    delete (globalThis as { localStorage?: unknown }).localStorage;
  }
}

test('no stored token means no Authorization header and an untouched socket URL', () => {
  withStorage(() => {
    assert.equal(apiToken(), '');
    assert.deepEqual(authHeaders(), {});
    assert.equal(
      withWebsocketToken('ws://localhost:8001/api/matches/abc/stream'),
      'ws://localhost:8001/api/matches/abc/stream'
    );
  });
});

test('a stored token reaches both the fetch header and the websocket query', () => {
  withStorage(() => {
    setApiToken('  s3cret-token  ');
    assert.equal(apiToken(), 's3cret-token', 'surrounding whitespace is not part of the token');
    assert.deepEqual(authHeaders(), { Authorization: 'Bearer s3cret-token' });
    assert.equal(
      withWebsocketToken('ws://localhost:8001/api/matches/abc/stream'),
      'ws://localhost:8001/api/matches/abc/stream?token=s3cret-token'
    );
  });
});

test('a websocket URL that already has a query keeps it', () => {
  withStorage(() => {
    setApiToken('abc');
    assert.equal(
      withWebsocketToken('ws://host/api/admin/stream?scope=all'),
      'ws://host/api/admin/stream?scope=all&token=abc'
    );
  });
});

test('tokens needing escaping are encoded rather than breaking the query', () => {
  withStorage(() => {
    setApiToken('a b&c=d');
    assert.equal(withWebsocketToken('ws://host/s'), 'ws://host/s?token=a%20b%26c%3Dd');
  });
});

test('clearing the token removes it everywhere', () => {
  withStorage(() => {
    setApiToken('temp');
    setApiToken('   ');
    assert.equal(apiToken(), '');
    assert.deepEqual(authHeaders(), {});
    assert.equal(withWebsocketToken('ws://host/s'), 'ws://host/s');
  });
});

test('a browser without localStorage degrades instead of throwing', () => {
  // Server-side rendering and private-mode browsers both hit this path.
  assert.equal(apiToken(), '');
  assert.deepEqual(authHeaders(), {});
  assert.doesNotThrow(() => setApiToken('ignored'));
});
