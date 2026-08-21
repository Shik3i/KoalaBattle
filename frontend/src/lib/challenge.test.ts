import assert from 'node:assert/strict';
import test from 'node:test';

import {
  challengeErrorMessage,
  challengeStatusLabel,
  draftChoiceIndexForKey,
  emptyEvSpread,
  evAllocationTotal,
  evSpreadTotal,
  formatDuration,
  legalEvValue
} from './challenge.ts';

test('empty EV spreads are independent zeroed records', () => {
  const first = emptyEvSpread();
  const second = emptyEvSpread();
  first.hp = 252;

  assert.equal(second.hp, 0);
  assert.equal(evSpreadTotal(second), 0);
});

test('spread totals include all six stats', () => {
  assert.equal(
    evSpreadTotal({ hp: 4, atk: 252, def: 0, spa: 0, spd: 0, spe: 252 }),
    508
  );
});

test('allocation totals enforce the shared campaign budget calculation', () => {
  assert.equal(
    evAllocationTotal({
      pikachu: { hp: 0, atk: 252, def: 0, spa: 0, spd: 4, spe: 252 },
      blastoise: { hp: 252, atk: 0, def: 0, spa: 252, spd: 4, spe: 0 }
    }),
    1016
  );
});

test('EV editing cannot exceed stat, Pokemon, or global limits', () => {
  const allocations = {
    pikachu: { hp: 252, atk: 0, def: 0, spa: 0, spd: 0, spe: 252 },
    blastoise: { hp: 252, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 }
  };
  const limits = { global: 760, pokemon: 510, stat: 252 };

  assert.equal(legalEvValue(allocations, 'pikachu', 'spd', 252, limits), 4);
  assert.equal(legalEvValue(allocations, 'blastoise', 'def', 999, limits), 4);
  assert.equal(legalEvValue(allocations, 'blastoise', 'hp', -20, limits), 0);
});

test('Challenge errors turn stale state and AI failures into recovery guidance', () => {
  assert.match(challengeErrorMessage('stale challenge revision: current 7'), /latest saved state/);
  assert.match(challengeErrorMessage('agent draft provider timed out'), /take over manually/);
  assert.match(challengeErrorMessage('Showdown rejected the team: bad move'), /Fix the listed/);
  assert.match(challengeErrorMessage('draft pricing verification failed: hash mismatch'), /Re-import/);
});

test('draft shortcuts accept only visible one-based choice keys', () => {
  assert.equal(draftChoiceIndexForKey('1'), 0);
  assert.equal(draftChoiceIndexForKey('8'), 7);
  assert.equal(draftChoiceIndexForKey('0'), null);
  assert.equal(draftChoiceIndexForKey('9'), null);
});

test('status and duration labels are user-facing', () => {
  assert.equal(challengeStatusLabel('team_review'), 'Team review');
  assert.equal(formatDuration(0), '0s');
  assert.equal(formatDuration(3670), '1h 1m');
});
