import assert from 'node:assert/strict';
import test from 'node:test';
import { ProductionScheduler } from './scheduler.ts';
import type { ProductionTimeline } from '../types.ts';

const timeline = {
  cues: [
    { id: 'a', start_ms: 100, duration_ms: 20, event_sequence: 1 },
    { id: 'b', start_ms: 200, duration_ms: 20, event_sequence: 2 }
  ]
} as ProductionTimeline;

test('scheduler emits each cue once and clears stale work on seek', () => {
  const scheduler = new ProductionScheduler();
  scheduler.load(timeline);
  assert.deepEqual(scheduler.advance(100).map((cue) => cue.id), ['a']);
  assert.deepEqual(scheduler.advance(100).map((cue) => cue.id), ['b']);
  assert.deepEqual(scheduler.advance(100), []);
  scheduler.seek(50);
  assert.deepEqual(scheduler.advance(50).map((cue) => cue.id), ['a']);
  scheduler.seek(200);
  assert.deepEqual(scheduler.advance(10), []);
});
