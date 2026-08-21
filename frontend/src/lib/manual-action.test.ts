import assert from 'node:assert/strict';
import test from 'node:test';
import { actionIndexForKey, actionPreview, isForcedSwitch, shortcutFor } from './manual-action.ts';
import type { BattleAction } from './types.ts';

const move = (patch: Partial<BattleAction>): BattleAction => ({
  id: 'move:1', type: 'move', name: 'Test move', slot: 1, terastallize: false, ...patch
});

test('manual previews describe known power and priority without inventing damage', () => {
  assert.deepEqual(actionPreview(move({ power: 100, priority: 1 })), {
    impact: 'Heavy hit · 100 BP', tempo: 'Acts early · priority +1'
  });
  assert.equal(actionPreview(move({ power: null })).impact, 'Status / utility');
});

test('manual shortcuts only map the visible one through nine keys', () => {
  assert.equal(shortcutFor(0), '1');
  assert.equal(shortcutFor(9), null);
  assert.equal(actionIndexForKey('7'), 6);
  assert.equal(actionIndexForKey('0'), null);
});

test('forced switch state is derived only from the authoritative legal actions', () => {
  const switching = { id: 'switch:2', type: 'switch', name: 'Bench', slot: 2, terastallize: false } as BattleAction;
  assert.equal(isForcedSwitch({ legal_actions: [switching] }), true);
  assert.equal(isForcedSwitch({ legal_actions: [switching, move({})] }), false);
  assert.equal(isForcedSwitch({ legal_actions: [] }), false);
});
