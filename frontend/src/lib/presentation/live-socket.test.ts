import assert from 'node:assert/strict';
import test from 'node:test';

import { connectLiveSocket, type LiveSocket, type LiveSocketRuntime } from './live-socket.ts';

class FakeSocket implements LiveSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  close() { this.closed = true; }
}

class FakeRuntime implements LiveSocketRuntime {
  sockets: FakeSocket[] = [];
  timers: Array<{ callback: () => void; delay: number; cleared: boolean }> = [];
  create(): LiveSocket {
    const socket = new FakeSocket();
    this.sockets.push(socket);
    return socket;
  }
  set(callback: () => void, delay: number): unknown {
    const timer = { callback, delay, cleared: false };
    this.timers.push(timer);
    return timer;
  }
  clear(handle: unknown) { (handle as { cleared: boolean }).cleared = true; }
}

test('reconnects with bounded backoff and refreshes state after every connection', async () => {
  const runtime = new FakeRuntime();
  const states: string[] = [];
  let refreshes = 0;
  const stop = connectLiveSocket({
    url: 'ws://example.test/live',
    onMessage: (data) => states.push(data),
    onConnected: () => { refreshes += 1; },
    onStatus: (status) => states.push(status)
  }, runtime);

  runtime.sockets[0].onopen?.();
  runtime.sockets[0].onmessage?.({ data: 'event-1' });
  runtime.sockets[0].onclose?.();
  assert.equal(runtime.timers[0].delay, 500);
  runtime.timers[0].callback();
  runtime.sockets[1].onopen?.();
  await Promise.resolve();

  assert.equal(refreshes, 2);
  assert.deepEqual(states, ['connected', 'event-1', 'reconnecting', 'connected']);
  stop();
  assert.equal(runtime.sockets[1].closed, true);
});

test('deduplicates error and close reconnect scheduling and cleans up', () => {
  const runtime = new FakeRuntime();
  const stop = connectLiveSocket({ url: 'ws://example.test/live', onMessage: () => undefined }, runtime);
  runtime.sockets[0].onerror?.();
  runtime.sockets[0].onclose?.();
  assert.equal(runtime.timers.length, 1);
  stop();
  assert.equal(runtime.timers[0].cleared, true);
});

test('ignores a delayed close from a superseded socket', () => {
  const runtime = new FakeRuntime();
  const stop = connectLiveSocket({ url: 'ws://example.test/live', onMessage: () => undefined }, runtime);
  const first = runtime.sockets[0];
  first.onclose?.();
  runtime.timers[0].callback();
  runtime.sockets[1].onopen?.();
  first.onclose?.();
  assert.equal(runtime.timers.length, 1);
  stop();
});
