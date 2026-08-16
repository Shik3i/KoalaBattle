import assert from 'node:assert/strict';
import test from 'node:test';

import type { BattleEvent, BattleState, MatchArchive } from '../types.ts';
import { createPresentationState, reduceEvents, reducePresentation } from './reducer.ts';

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
    event(9, 'battle_finished', {
      result: { winner: 'p1', winner_name: 'KoalaP1InternalIdentifier' }
    })
  ];
  const state = reduceEvents(createPresentationState(match), events);
  assert.equal(state.format, 'gen9randombattle');
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

test('move visuals use authoritative type/category with deterministic fallback', () => {
  const initial = createPresentationState(match);
  const physical = reducePresentation(initial, event(1, 'move_used', {
    actor: 'p1a: Pikachu', move: 'Volt Tackle', move_type: 'electric', category: 'physical'
  }));
  const repeated = reducePresentation(initial, event(1, 'move_used', {
    actor: 'p1a: Pikachu', move: 'Volt Tackle', move_type: 'electric', category: 'physical'
  }));
  const fallback = reducePresentation(initial, event(2, 'move_used', {
    actor: 'p2a: Missingno', move: 'Unknown Future Move', move_type: 'cosmic'
  }));
  assert.equal(physical.currentMoveProfile?.type, 'electric');
  assert.equal(physical.currentMoveProfile?.archetype, 'physical');
  assert.equal(physical.currentMoveProfile?.seed, repeated.currentMoveProfile?.seed);
  assert.equal(fallback.currentMoveProfile?.type, 'normal');
  assert.equal(fallback.currentMoveProfile?.archetype, 'special');
});

test('damage, healing, effectiveness and field feedback follow visible events', () => {
  const active = {
    id: 'pikachu', name: 'Pikachu', species: 'pikachu', hp_fraction: 1, status: null,
    types: ['electric'], moves: [], active: true, fainted: false
  };
  const withBattle = reducePresentation(createPresentationState(match), event(1, 'state_snapshot', {
    state: {
      ...battle,
      player: { ...battle.player, active, team: [active] },
      opponent: { ...battle.opponent, active: { ...active, id: 'eevee', name: 'Eevee', species: 'eevee' }, team: [] }
    }
  }));
  const damaged = reducePresentation(withBattle, event(2, 'damage', { target: 'p2a: Eevee', hp: '64/100' }));
  assert.equal(damaged.battle?.opponent.active?.hp_fraction, 0.64);
  assert.equal(damaged.effectValue, -36);
  assert.equal(reducePresentation(damaged, event(3, 'super_effective', { target: 'p2a: Eevee' })).effect, 'super-effective');
  assert.equal(reducePresentation(damaged, event(4, 'terrain_started', { field: 'electricterrain' })).effect, 'terrain');
});

test('forward-looking snapshots cannot reveal HP or switches before their events', () => {
  const pikachu = {
    id: 'p1: Pikachu', name: 'Pikachu', species: 'pikachu', hp_fraction: 1, status: null,
    types: ['electric'], moves: [], active: true, fainted: false, current_hp: 100, max_hp: 100
  };
  const eevee = {
    id: 'p2: Eevee', name: 'Eevee', species: 'eevee', hp_fraction: 1, status: null,
    types: ['normal'], moves: [], active: true, fainted: false, current_hp: 100, max_hp: 100
  };
  const snorlax = {
    ...eevee, id: 'p2: Snorlax', name: 'Snorlax', species: 'snorlax', active: false
  };
  const initialBattle = {
    ...battle,
    turn: 5,
    player: { ...battle.player, active: pikachu, team: [pikachu] },
    opponent: { ...battle.opponent, active: eevee, team: [eevee, snorlax] }
  };
  const futureSnapshot = {
    ...initialBattle,
    turn: 6,
    opponent: {
      ...initialBattle.opponent,
      active: { ...snorlax, active: true },
      team: [{ ...eevee, active: false, hp_fraction: 0, fainted: true }, { ...snorlax, active: true }]
    }
  };
  const beforeEvents = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: initialBattle }),
    event(2, 'state_snapshot', { state: futureSnapshot })
  ]);
  assert.equal(beforeEvents.battle?.turn, 5);
  assert.equal(beforeEvents.battle?.opponent.active?.name, 'Eevee');
  assert.equal(beforeEvents.battle?.opponent.active?.hp_fraction, 1);

  const afterEvents = reduceEvents(beforeEvents, [
    event(3, 'damage', { target: 'p2a: Eevee', hp: '0 fnt' }),
    event(4, 'pokemon_fainted', { target: 'p2a: Eevee' }),
    event(5, 'pokemon_switched', { actor: 'p2a: Snorlax', hp: '100/100' }),
    event(6, 'turn_started', { turn: 6 })
  ]);
  assert.equal(afterEvents.battle?.turn, 6);
  assert.equal(afterEvents.battle?.opponent.active?.name, 'Snorlax');
  assert.equal(afterEvents.battle?.opponent.active?.hp_fraction, 1);
});

test('maps internal Showdown winner usernames back to participant display names', () => {
  const state = reducePresentation(
    createPresentationState(match),
    event(1, 'battle_finished', { winner_name: 'KoalaP1InternalIdentifier' })
  );
  assert.equal(state.winner, 'p1');
  assert.equal(state.winnerName, 'Alpha');
});
