import assert from 'node:assert/strict';
import test from 'node:test';

import type { BattleEvent, MatchArchive } from '../types.ts';
import { PresentationTimeline, type TimelineClock } from './timeline.ts';

const match = {
  id: 'match-1',
  winner: null,
  config: {
    format: 'gen9randombattle',
    generation: 9,
    players: [
      { side: 'p1', display_name: 'Alpha', agent_type: 'random' },
      { side: 'p2', display_name: 'Beta', agent_type: 'random' }
    ]
  }
} satisfies Pick<MatchArchive, 'id' | 'winner' | 'config'>;

const events: BattleEvent[] = [
  { id: 1, match_id: 'match-1', sequence: 1, turn: 1, event_type: 'turn_started', logical_offset_ms: 5, payload: { turn: 1 } },
  { id: 2, match_id: 'match-1', sequence: 2, turn: 1, event_type: 'move_used', logical_offset_ms: 9000, payload: { actor: 'p1a: A', move: 'Move A' } },
  { id: 3, match_id: 'match-1', sequence: 3, turn: 2, event_type: 'turn_started', logical_offset_ms: 12000, payload: { turn: 2 } },
  { id: 4, match_id: 'match-1', sequence: 4, turn: 2, event_type: 'move_used', logical_offset_ms: 50000, payload: { actor: 'p2a: B', move: 'Move B' } }
];

class FakeClock implements TimelineClock {
  tasks: Array<{ callback: () => void; delay: number; active: boolean }> = [];
  set(callback: () => void, delay: number): unknown {
    const task = { callback, delay, active: true };
    this.tasks.push(task);
    return task;
  }
  clear(handle: unknown): void {
    (handle as { active: boolean }).active = false;
  }
  runNext(): void {
    const task = this.tasks.find((item) => item.active);
    assert.ok(task);
    task.active = false;
    task.callback();
  }
}

test('scheduler orders events deterministically and ignores historical wall-clock offsets', () => {
  const clock = new FakeClock();
  const timeline = new PresentationTimeline(match, events, clock);
  timeline.play();
  assert.equal(clock.tasks[0].delay, 240);
  clock.runNext();
  assert.equal(timeline.snapshot().index, 1);
  assert.equal(clock.tasks[1].delay, 520);
  timeline.setSpeed(2);
  assert.equal(clock.tasks.at(-1)?.delay, 260);
});

test('pause, resume, instant, reset, event and turn navigation are stable', () => {
  const clock = new FakeClock();
  const timeline = new PresentationTimeline(match, events, clock);
  timeline.nextEvent();
  assert.equal(timeline.snapshot().index, 1);
  timeline.nextTurn();
  assert.equal(timeline.snapshot().index, 2);
  timeline.previousTurn();
  assert.equal(timeline.snapshot().index, 0);
  timeline.seek(3);
  timeline.previousEvent();
  assert.equal(timeline.snapshot().index, 2);
  timeline.setSpeed('instant');
  timeline.play();
  assert.equal(timeline.snapshot().index, 4);
  assert.equal(timeline.snapshot().playing, false);
  timeline.restart();
  assert.equal(timeline.snapshot().index, 0);
  assert.equal(timeline.snapshot().state.log.length, 0);
  timeline.play();
  timeline.pause();
  assert.equal(timeline.snapshot().playing, false);
});

test('follow mode accepts ordered live events without duplicate sequences', () => {
  const clock = new FakeClock();
  const timeline = new PresentationTimeline(match, [], clock, true);
  timeline.play();
  timeline.append(events[1]);
  timeline.append(events[0]);
  timeline.append(events[0]);
  assert.equal(timeline.snapshot().eventCount, 2);
  clock.runNext();
  assert.equal(timeline.snapshot().state.eventSequence, 1);
});
