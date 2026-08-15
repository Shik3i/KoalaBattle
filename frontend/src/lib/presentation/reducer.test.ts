import assert from 'node:assert/strict';
import test from 'node:test';

import type { BattleEvent, BattleState, MatchArchive } from '../types.ts';
import { createPresentationState, reduceEvents } from './reducer.ts';

const match = {
  id: 'match-1',
  winner: null,
  config: {
    format: 'gen9randombattle',
    generation: 9,
    players: [
      { side: 'p1', display_name: 'Alpha', agent_type: 'manual' },
      { side: 'p2', display_name: 'Beta', agent_type: 'random' }
    ]
  }
} satisfies Pick<MatchArchive, 'id' | 'winner' | 'config'>;

const battle = {
  match_id: 'match-1',
  turn: 2,
  perspective: 'p1',
  player: { side: 'p1', display_name: 'Alpha', active: null, team: [] },
  opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] },
  weather: [],
  fields: [],
  last_action: null,
  public_history: [],
  result: null
} satisfies BattleState;

const event = (sequence: number, event_type: string, payload: Record<string, unknown>): BattleEvent => ({
  id: sequence,
  match_id: 'match-1',
  sequence,
  turn: 2,
  event_type,
  logical_offset_ms: sequence * 10,
  payload
});

test('presentation reducer restores switch, combat, status, commentary, and winner state', () => {
  const events = [
    event(1, 'state_snapshot', { state: battle }),
    event(2, 'pokemon_switched', { actor: 'p1a: Pikachu' }),
    event(3, 'move_used', { actor: 'p1a: Pikachu', target: 'p2a: Eevee', move: 'Thunderbolt' }),
    event(4, 'damage', { target: 'p2a: Eevee', hp: '20/100' }),
    event(5, 'healing', { target: 'p2a: Eevee', hp: '40/100' }),
    event(6, 'status_applied', { target: 'p2a: Eevee', status: 'par' }),
    event(7, 'pokemon_fainted', { target: 'p2a: Eevee' }),
    event(8, 'agent_decision', {
      side: 'p1',
      action: 'move:1',
      action_name: 'Thunderbolt',
      commentary: 'Public plan.'
    }),
    event(9, 'battle_finished', { winner_name: 'Alpha' })
  ];
  const state = reduceEvents(createPresentationState(match), events);
  assert.equal(state.battle?.turn, 2);
  assert.equal(state.currentMove, 'Thunderbolt');
  assert.equal(state.players.p1.commentary[0].commentary, 'Public plan.');
  assert.equal(state.players.p2.motion, 'idle');
  assert.equal(state.finished, true);
  assert.equal(state.winnerName, 'Alpha');
  assert.equal(state.effect, 'victory');
  assert.ok(state.log.some((entry) => entry.text === 'Eevee fainted.'));
  assert.ok(state.log.every((entry) => !entry.text.includes('|')));
});

test('old Phase 1 actor strings remain sufficient for side mapping', () => {
  const state = reduceEvents(createPresentationState(match), [
    event(1, 'move_used', { actor: 'p2a: Mismagius', move: 'Shadow Ball' }),
    event(2, 'critical_hit', { target: 'p1a: Pikachu' })
  ]);
  assert.equal(state.players.p1.motion, 'taking-damage');
  assert.equal(state.effectSide, 'p1');
  assert.equal(state.effect, 'critical-hit');
});

test('completed archive metadata does not spoil replay frame zero', () => {
  const initial = createPresentationState({ ...match, winner: 'p1' });
  assert.equal(initial.winner, null);
  assert.equal(initial.finished, false);
  assert.equal(initial.players.p1.agentStatus, 'waiting');
});
