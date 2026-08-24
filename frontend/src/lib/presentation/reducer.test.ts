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
  assert.equal(state.currentMove, null);
  assert.equal(state.currentMoveProfile, null);
  assert.equal(state.currentMoveSide, null);
  assert.equal(state.currentMovePhase, 'resolved');
  assert.deepEqual(state.impacts, { p1: null, p2: null });
  assert.equal(state.players.p1.commentary[0].commentary, 'Public plan.');
  assert.equal(state.players.p2.motion, 'idle');
  assert.equal(state.finished, true);
  assert.equal(state.winnerName, 'Alpha');
  assert.equal(state.effect, 'victory');
  assert.ok(state.log.some((entry) => entry.text === 'Eevee fainted.'));
  assert.ok(state.log.some((entry) => entry.text === 'Alpha wins.'));
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

test('switches clear the previous move before the replacement enters', () => {
  const attacking = reducePresentation(createPresentationState(match), event(1, 'move_used', {
    actor: 'p1a: Pikachu', move: 'Thunderbolt'
  }));
  const switched = reducePresentation(attacking, event(2, 'pokemon_switched', {
    actor: 'p1a: Raichu', hp: '100/100'
  }));
  assert.equal(switched.currentMove, null);
  assert.equal(switched.currentMoveProfile, null);
  assert.equal(switched.currentMovePhase, 'resolved');
  assert.equal(switched.players.p1.motion, 'switching-in');
});

test('switches expose one strict outgoing-to-incoming transition and clear it on the next event', () => {
  const pikachu = {
    id: 'p1: Pikachu', name: 'Pikachu', species: 'pikachu', hp_fraction: 1, status: null,
    types: ['electric'], moves: [], active: true, fainted: false
  };
  const raichu = { ...pikachu, id: 'p1: Raichu', name: 'Raichu', species: 'raichu', active: false };
  const seeded = reducePresentation(createPresentationState(match), event(1, 'state_snapshot', {
    state: { ...battle, player: { ...battle.player, active: pikachu, team: [pikachu, raichu] } }
  }));
  const switched = reducePresentation(seeded, event(2, 'pokemon_switched', {
    actor: 'p1a: Raichu', hp: '100/100', forced: true
  }));
  assert.equal(switched.switchTransitions.p1?.outgoing?.name, 'Pikachu');
  assert.equal(switched.switchTransitions.p1?.incoming.name, 'Raichu');
  assert.equal(switched.switchTransitions.p1?.forced, true);
  assert.equal(switched.battle?.player.active?.name, 'Raichu');

  const settled = reducePresentation(switched, event(3, 'agent_state', { side: 'p1', state: 'thinking' }));
  assert.equal(settled.switchTransitions.p1, null);
  assert.equal(settled.battle?.player.active?.name, 'Raichu');
});

test('campaign presentation uses the P1 slot instead of the Draft run name', () => {
  const campaignMatch = {
    ...match,
    config: {
      ...match.config,
      campaign: {
        definition_name: 'Kanto Gym Gauntlet',
        stage_id: 'brock',
        stage_index: 0,
        stage_count: 8,
        stage_name: 'Brock',
        stage_title: 'Rock Gym Leader',
        specialty: 'Rock',
        trainer_asset_id: null,
        visual_accent: '#b08a68',
        difficulty: 'normal' as const,
        player_level: 5,
        opponent_level: 5
      }
    }
  };

  const state = createPresentationState(campaignMatch);

  assert.equal(state.players.p1.displayName, 'P1');
  assert.equal(state.players.p2.displayName, 'Beta');
});

test('a fainted active Pokemon remains fainted after lifecycle noise and is never a switch-out ghost', () => {
  const pikachu = {
    id: 'p1: Pikachu', name: 'Pikachu', species: 'pikachu', hp_fraction: 0.2, status: null,
    types: ['electric'], moves: [], active: true, fainted: false
  };
  const raichu = { ...pikachu, id: 'p1: Raichu', name: 'Raichu', species: 'raichu', active: false, hp_fraction: 1 };
  const seeded = reducePresentation(createPresentationState(match), event(1, 'state_snapshot', {
    state: { ...battle, player: { ...battle.player, active: pikachu, team: [pikachu, raichu] } }
  }));
  const fainted = reducePresentation(seeded, event(2, 'pokemon_fainted', { target: 'p1a: Pikachu' }));
  assert.equal(fainted.players.p1.motion, 'fainting');
  assert.equal(fainted.battle?.player.active?.fainted, true);

  const waiting = reducePresentation(fainted, event(3, 'agent_state', { side: 'p1', state: 'thinking' }));
  assert.equal(waiting.players.p1.motion, 'idle');
  assert.equal(waiting.battle?.player.active?.fainted, true);
  const switched = reducePresentation(waiting, event(4, 'pokemon_switched', { actor: 'p1a: Raichu', hp: '100/100' }));
  assert.equal(switched.switchTransitions.p1?.outgoing, null);
  assert.equal(switched.switchTransitions.p1?.incoming.name, 'Raichu');
});

test('the canonical action feed groups one move with target, damage, effectiveness, crit and status', () => {
  const pikachu = {
    id: 'p1: Pikachu', name: 'Pikachu', species: 'pikachu', hp_fraction: 1, status: null,
    types: ['electric'], moves: [], active: true, fainted: false
  };
  const eevee = { ...pikachu, id: 'p2: Eevee', name: 'Eevee', species: 'eevee', types: ['normal'] };
  const state = reduceEvents(createPresentationState(match), [
    turnEvent(1, 'state_snapshot', {
      state: {
        ...battle,
        player: { ...battle.player, active: pikachu, team: [pikachu] },
        opponent: { ...battle.opponent, active: eevee, team: [eevee] }
      }
    }, 1),
    turnEvent(2, 'move_used', { actor: 'p1a: Pikachu', target: 'p2a: Eevee', move: 'Thunderbolt' }, 1),
    turnEvent(3, 'super_effective', { target: 'p2a: Eevee' }, 1),
    turnEvent(4, 'damage', { target: 'p2a: Eevee', hp: '31/100' }, 1),
    turnEvent(5, 'critical_hit', { target: 'p2a: Eevee' }, 1),
    turnEvent(6, 'status_applied', { target: 'p2a: Eevee', status: 'par' }, 1),
    turnEvent(7, 'pokemon_fainted', { target: 'p2a: Eevee' }, 1)
  ]);
  assert.equal(state.actionFeed.length, 2);
  assert.equal(state.actionFeed[0].headline, 'Pikachu used Thunderbolt');
  assert.deepEqual(state.actionFeed[0].detailParts, [
    'Critical hit!', 'Super effective!', 'Eevee -69% HP', 'Eevee was paralyzed'
  ]);
  assert.equal(state.actionFeed[0].emphasis, 'critical');
  assert.equal(state.actionFeed[1].headline, 'Eevee fainted');
});

test('ability, item, stat and residual events stay semantic, including old replay protocol lines', () => {
  const state = reduceEvents(createPresentationState(match), [
    turnEvent(1, 'ability_activated', { target: 'p1a: Gengar', ability: 'Cursed Body' }, 3),
    turnEvent(2, 'item_consumed', { target: 'p2a: Snorlax', item: 'Sitrus Berry' }, 3),
    turnEvent(3, 'stat_changed', { target: 'p2a: Snorlax', stat: 'def', amount: -2 }, 3),
    turnEvent(4, 'damage', { target: 'p1a: Gengar', hp: '75/100', source: 'brn' }, 3),
    turnEvent(5, 'showdown_message', {
      command: '-activate', raw: '|-activate|p1a: Gengar|ability: Levitate'
    }, 3)
  ]);
  assert.deepEqual(state.actionFeed.map((entry) => entry.kind), ['ability', 'item', 'stat', 'residual', 'ability']);
  assert.equal(state.actionFeed[0].detailParts[0], 'Cursed Body');
  assert.equal(state.actionFeed[2].detailParts[0], 'Defense fell harshly');
  assert.deepEqual(state.actionFeed[3].detailParts, ['Burn', 'took damage']);
  assert.equal(state.actionFeed[4].detailParts[0], 'Levitate');
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
  assert.deepEqual(beforeEvents.battle?.opponent.team.map((member) => member.name), ['Eevee', 'Snorlax']);

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

test('a switch event can reveal an opponent that was absent from prior snapshots', () => {
  const initial = reducePresentation(createPresentationState(match), event(1, 'state_snapshot', {
    state: {
      ...battle,
      player: { ...battle.player, active: null, team: [] },
      opponent: { ...battle.opponent, active: null, team: [] }
    }
  }));
  const switched = reducePresentation(initial, event(2, 'pokemon_switched', {
    actor: 'p2a: Gholdengo', hp: '100/100'
  }));
  assert.equal(switched.battle?.opponent.active?.species, 'gholdengo');
  assert.equal(switched.battle?.opponent.team[0]?.name, 'Gholdengo');
});

test('maps internal Showdown winner usernames back to participant display names', () => {
  const state = reducePresentation(
    createPresentationState(match),
    event(1, 'battle_finished', { winner_name: 'KoalaP1InternalIdentifier' })
  );
  assert.equal(state.winner, 'p1');
  assert.equal(state.winnerName, 'Alpha');
});

const turnEvent = (
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
  turn: number
): BattleEvent => ({ ...event(sequence, eventType, payload), turn });

test('public commentary belongs to one action and clears when the turn resolves', () => {
  const decided = reduceEvents(createPresentationState(match), [
    turnEvent(1, 'agent_state', { side: 'p1', state: 'thinking' }, 1),
    turnEvent(2, 'agent_decision', {
      side: 'p1', action: 'move:1', action_name: 'Thunderbolt', commentary: 'Turn 1 plan.'
    }, 1)
  ]);
  assert.equal(decided.players.p1.commentaryPhase, 'decided');
  assert.equal(decided.players.p1.currentCommentary?.commentary, 'Turn 1 plan.');

  const executing = reducePresentation(
    decided,
    turnEvent(3, 'move_used', { actor: 'p1a: Pikachu', move: 'Thunderbolt' }, 1)
  );
  assert.equal(executing.players.p1.commentaryPhase, 'executing');
  assert.equal(executing.currentMovePhase, 'executing');

  // Turn 2 begins: the previous action's commentary must not read as the next plan.
  const resolved = reducePresentation(executing, turnEvent(4, 'turn_started', { turn: 2 }, 2));
  assert.equal(resolved.players.p1.commentaryPhase, 'resolved');
  assert.equal(resolved.players.p1.currentCommentary, null);
  assert.equal(resolved.currentMovePhase, 'resolved');
  // The headline action is cleared, not just marked resolved: left standing it kept announcing
  // a move from a previous turn over the middle of the arena for the rest of the match.
  assert.equal(resolved.currentMove, null);
  assert.equal(resolved.currentMoveSide, null);
  assert.equal(resolved.currentMoveProfile, null);
  // History is preserved for the decision log.
  assert.equal(resolved.players.p1.commentary.length, 1);

  const thinkingAgain = reducePresentation(
    resolved,
    turnEvent(5, 'agent_state', { side: 'p1', state: 'thinking' }, 2)
  );
  assert.equal(thinkingAgain.players.p1.commentaryPhase, 'thinking');
  assert.equal(thinkingAgain.players.p1.currentCommentary, null);
});

test('hp changes are attributed to the target and cleared on the next turn', () => {
  const active = {
    id: 'pikachu', name: 'Pikachu', species: 'pikachu', hp_fraction: 1, status: null,
    types: ['electric'], moves: [], active: true, fainted: false
  };
  const seeded = reducePresentation(createPresentationState(match), turnEvent(1, 'state_snapshot', {
    state: {
      ...battle,
      player: { ...battle.player, active, team: [active] },
      opponent: {
        ...battle.opponent,
        active: { ...active, id: 'eevee', name: 'Eevee', species: 'eevee' },
        team: []
      }
    }
  }, 1));
  const damaged = reducePresentation(seeded, turnEvent(2, 'damage', { target: 'p2a: Eevee', hp: '79/100' }, 1));
  assert.equal(damaged.impacts.p2?.value, -21);
  assert.equal(damaged.impacts.p2?.kind, 'damage');
  assert.equal(damaged.impacts.p1, null);
  assert.ok(damaged.log.some((entry) => entry.text === 'Eevee lost 21% HP.'));

  // A following effect event must not wipe the number before it can be read.
  const stillVisible = reducePresentation(damaged, turnEvent(3, 'super_effective', { target: 'p2a: Eevee' }, 1));
  assert.equal(stillVisible.impacts.p2?.value, -21);

  const healed = reducePresentation(stillVisible, turnEvent(4, 'healing', { target: 'p2a: Eevee', hp: '91/100' }, 1));
  assert.equal(healed.impacts.p2?.value, 12);
  assert.equal(healed.impacts.p2?.kind, 'healing');
  assert.ok(healed.log.some((entry) => entry.text === 'Eevee recovered 12% HP.'));

  const nextTurn = reducePresentation(healed, turnEvent(5, 'turn_started', { turn: 2 }, 2));
  assert.equal(nextTurn.impacts.p2, null);
});

test('a miss or a protected hit never invents damage', () => {
  const missed = reduceEvents(createPresentationState(match), [
    turnEvent(1, 'move_used', { actor: 'p1a: Pikachu', move: 'Focus Blast' }, 1),
    turnEvent(2, 'move_missed', { actor: 'p1a: Pikachu' }, 1)
  ]);
  assert.equal(missed.impacts.p1, null);
  assert.equal(missed.impacts.p2, null);
  assert.equal(missed.effect, 'miss');
  assert.ok(missed.log.every((entry) => !entry.text.includes('% HP')));
});

test('repeated authoritative lines are not duplicated in the spectator feed', () => {
  const state = reduceEvents(createPresentationState(match), [
    turnEvent(1, 'move_used', { actor: 'p1a: Pikachu', move: 'Thunderbolt' }, 1),
    turnEvent(2, 'move_used', { actor: 'p1a: Pikachu', move: 'Thunderbolt' }, 1)
  ]);
  const lines = state.log.filter((entry) => entry.text === 'Pikachu used Thunderbolt.');
  assert.equal(lines.length, 1);
});

test('Doubles keeps both field slots active and targets damage at the correct partner', () => {
  const pikachu = {
    id: 'p1a: Pikachu', name: 'Pikachu', species: 'Pikachu', hp_fraction: 1,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const raichu = {
    id: 'p1b: Raichu', name: 'Raichu', species: 'Raichu', hp_fraction: 1,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const eevee = {
    id: 'p2a: Eevee', name: 'Eevee', species: 'Eevee', hp_fraction: 1,
    status: null, types: ['Normal'], active: true, fainted: false
  };
  const snorlax = {
    id: 'p2b: Snorlax', name: 'Snorlax', species: 'Snorlax', hp_fraction: 1,
    status: null, types: ['Normal'], active: true, fainted: false
  };
  const doubles = {
    ...battle,
    player: {
      side: 'p1', display_name: 'Alpha', active: pikachu,
      active_slots: [pikachu, raichu], team: [pikachu, raichu]
    },
    opponent: {
      side: 'p2', display_name: 'Beta', active: eevee,
      active_slots: [eevee, snorlax], team: [eevee, snorlax]
    }
  } satisfies BattleState;

  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: doubles }),
    event(2, 'damage', { target: 'p2b: Snorlax', hp: '25/100' })
  ]);

  assert.equal(state.battle?.opponent.active_slots?.length, 2);
  assert.equal(state.battle?.opponent.active_slots?.[0].hp_fraction, 1);
  assert.equal(state.battle?.opponent.active_slots?.[1].hp_fraction, 0.25);
  assert.equal(state.battle?.opponent.team.find((pokemon) => pokemon.name === 'Snorlax')?.hp_fraction, 0.25);
});

test('Doubles credits damage and knockouts to the specific slot that attacked, not slot 0', () => {
  const pikachu = {
    id: 'p1a: Pikachu', name: 'Pikachu', species: 'Pikachu', hp_fraction: 1,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const raichu = {
    id: 'p1b: Raichu', name: 'Raichu', species: 'Raichu', hp_fraction: 1,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const eevee = {
    id: 'p2a: Eevee', name: 'Eevee', species: 'Eevee', hp_fraction: 1,
    status: null, types: ['Normal'], active: true, fainted: false
  };
  const snorlax = {
    id: 'p2b: Snorlax', name: 'Snorlax', species: 'Snorlax', hp_fraction: 1,
    status: null, types: ['Normal'], active: true, fainted: false
  };
  const doubles = {
    ...battle,
    player: {
      side: 'p1', display_name: 'Alpha', active: pikachu,
      active_slots: [pikachu, raichu], team: [pikachu, raichu]
    },
    opponent: {
      side: 'p2', display_name: 'Beta', active: eevee,
      active_slots: [eevee, snorlax], team: [eevee, snorlax]
    }
  } satisfies BattleState;

  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: doubles }),
    // Raichu is field slot "b", not the side's slot 0 (Pikachu) — the recap must
    // still credit the actual mover, not whichever mon happens to sit in slot 0.
    event(2, 'move_used', { actor: 'p1b: Raichu', target: 'p2a: Eevee', move: 'Thunderbolt' }),
    event(3, 'damage', { target: 'p2a: Eevee', hp: '0 fnt' }),
    event(4, 'pokemon_fainted', { target: 'p2a: Eevee' })
  ]);

  const raichuRecap = state.recap.find((entry) => entry.species === 'Raichu');
  const pikachuRecap = state.recap.find((entry) => entry.species === 'Pikachu');
  assert.ok(raichuRecap, 'Raichu should appear in the recap as the attacker');
  assert.equal(raichuRecap.damageDealt, 100);
  assert.equal(raichuRecap.knockouts, 1);
  assert.equal(pikachuRecap?.damageDealt ?? 0, 0);
  assert.equal(pikachuRecap?.knockouts ?? 0, 0);
});

test('the recap credits move damage to the attacker and never to hazards or status', () => {
  const arena = {
    ...battle,
    player: {
      side: 'p1',
      display_name: 'Alpha',
      active: { id: 'p1a', name: 'Pikachu', species: 'Pikachu', hp_fraction: 1, status: null, types: ['Electric'], active: true, fainted: false },
      team: []
    },
    opponent: {
      side: 'p2',
      display_name: 'Beta',
      active: { id: 'p2a', name: 'Eevee', species: 'Eevee', hp_fraction: 1, status: null, types: ['Normal'], active: true, fainted: false },
      team: []
    }
  } satisfies BattleState;

  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: arena }),
    event(2, 'move_used', { actor: 'p1a: Pikachu', target: 'p2a: Eevee', move: 'Thunderbolt' }),
    event(3, 'damage', { target: 'p2a: Eevee', hp: '40/100' }),
    // Turn boundary clears the executing move, so the next chip has no attacker.
    event(4, 'turn_started', { turn: 3 }),
    event(5, 'damage', { target: 'p2a: Eevee', hp: '30/100' }),
    event(6, 'move_used', { actor: 'p1a: Pikachu', target: 'p2a: Eevee', move: 'Thunderbolt' }),
    event(7, 'damage', { target: 'p2a: Eevee', hp: '0 fnt' }),
    event(8, 'pokemon_fainted', { target: 'p2a: Eevee' })
  ]);

  const pikachu = state.recap.find((entry) => entry.species === 'Pikachu');
  const eevee = state.recap.find((entry) => entry.species === 'Eevee');
  assert.ok(pikachu && eevee);
  // 60 from the first Thunderbolt + 30 from the finishing hit. The 10 chip is uncredited.
  assert.equal(pikachu.damageDealt, 90);
  assert.equal(pikachu.knockouts, 1);
  assert.equal(pikachu.fainted, false);
  // The victim still records everything it took, including the uncredited chip.
  assert.equal(eevee.damageTaken, 100);
  assert.equal(eevee.knockouts, 0);
  assert.equal(eevee.fainted, true);
});

test('a Pokemon that only switches in still appears in the recap', () => {
  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: battle }),
    event(2, 'pokemon_switched', { actor: 'p1a: Snorlax' })
  ]);

  const entry = state.recap.find((item) => item.name === 'Snorlax');
  assert.ok(entry, 'the entering Pokemon is registered even with no damage');
  assert.equal(entry.side, 'p1');
  assert.equal(entry.entered, true);
  assert.equal(entry.damageDealt, 0);
  assert.equal(entry.knockouts, 0);
  assert.equal(entry.fainted, false);
});

test('the recap keeps duplicate opponent species as separate Pokemon', () => {
  const first = {
    id: 'p2: Gengar', name: 'Gengar', species: 'gengar', hp_fraction: 1, status: null,
    types: ['ghost', 'poison'], moves: [], active: true, fainted: false
  };
  const second = { ...first, id: 'p2: Gengar 2', active: false };
  const seeded = reducePresentation(createPresentationState(match), event(1, 'state_snapshot', {
    state: {
      ...battle,
      opponent: { ...battle.opponent, active: first, team: [first, second] }
    }
  }));
  const firstEntered = reducePresentation(seeded, event(2, 'pokemon_switched', {
    actor: 'p2a: Gengar', hp: '100/100'
  }));
  const switched = reducePresentation(firstEntered, event(3, 'pokemon_switched', {
    actor: 'p2a: Gengar 2', hp: '100/100'
  }));

  assert.deepEqual(
    switched.recap.filter((entry) => entry.side === 'p2').map((entry) => entry.id),
    ['p2: Gengar', 'p2: Gengar 2']
  );
});

test('a real HP reading is never downgraded by a later percentage-only snapshot', () => {
  // Both engine players stream snapshots: each reports its own side in real HP points
  // and the other side as a percentage. Taking whichever arrived last made one bar
  // flip between "0 / 34" and "2 / 100" mid-battle, which is what a viewer sees as
  // "my Pokemon always has 100 HP but the opponent does not".
  const exact = {
    id: 'p1a: Wattrel', name: 'Wattrel', species: 'Wattrel', hp_fraction: 1,
    current_hp: 34, max_hp: 34, hp_is_exact: true,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const asPercent = { ...exact, current_hp: 100, max_hp: 100, hp_is_exact: false };
  const opponent = {
    id: 'p2a: Staryu', name: 'Staryu', species: 'Staryu', hp_fraction: 1,
    current_hp: 100, max_hp: 100, hp_is_exact: false,
    status: null, types: ['Water'], active: true, fainted: false
  };

  const fromOwnSide = {
    ...battle,
    player: { side: 'p1', display_name: 'Alpha', active: exact, team: [exact] },
    opponent: { side: 'p2', display_name: 'Beta', active: opponent, team: [opponent] }
  } satisfies BattleState;
  const fromOtherSide = {
    ...battle,
    player: { side: 'p1', display_name: 'Alpha', active: asPercent, team: [asPercent] },
    opponent: { side: 'p2', display_name: 'Beta', active: opponent, team: [opponent] }
  } satisfies BattleState;

  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: fromOwnSide }),
    event(2, 'state_snapshot', { state: fromOtherSide })
  ]);

  assert.equal(state.battle?.player.active?.max_hp, 34, 'the real 34 HP bar must survive');
  assert.equal(state.battle?.player.active?.hp_is_exact, true);
  assert.equal(state.battle?.player.team[0].max_hp, 34, 'and on the bench entry too');
});

test('a percentage-only reading is upgraded once real HP points arrive', () => {
  const asPercent = {
    id: 'p1a: Wattrel', name: 'Wattrel', species: 'Wattrel', hp_fraction: 1,
    current_hp: 100, max_hp: 100, hp_is_exact: false,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const exact = { ...asPercent, current_hp: 34, max_hp: 34, hp_is_exact: true };
  const side = (active: typeof asPercent) => ({
    ...battle,
    player: { side: 'p1', display_name: 'Alpha', active, team: [active] },
    opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] }
  }) satisfies BattleState;

  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: side(asPercent) }),
    event(2, 'state_snapshot', { state: side(exact) })
  ]);

  assert.equal(state.battle?.player.active?.max_hp, 34);
  assert.equal(state.battle?.player.active?.hp_is_exact, true);
});

test('legacy archives without the flag still resolve a 100-point bar as the percentage', () => {
  // Matches recorded before `hp_is_exact` existed carry no flag, so both readings look
  // exact. A percentage always arrives as x/100, so the differing non-100 bar is real.
  const asPercent = {
    id: 'p1a: Wattrel', name: 'Wattrel', species: 'Wattrel', hp_fraction: 1,
    current_hp: 100, max_hp: 100,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const real = { ...asPercent, current_hp: 34, max_hp: 34 };
  const side = (active: typeof asPercent) => ({
    ...battle,
    player: { side: 'p1', display_name: 'Alpha', active, team: [active] },
    opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] }
  }) satisfies BattleState;

  const percentFirst = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: side(asPercent) }),
    event(2, 'state_snapshot', { state: side(real) })
  ]);
  assert.equal(percentFirst.battle?.player.active?.max_hp, 34);

  // And the other arrival order reaches the same conclusion.
  const realFirst = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: side(real) }),
    event(2, 'state_snapshot', { state: side(asPercent) })
  ]);
  assert.equal(realFirst.battle?.player.active?.max_hp, 34);
});

test('real HP revealed while a Pokemon is benched reaches its active plate too', () => {
  // The active Pokemon is tracked separately from the team, so a snapshot that reveals
  // a benched mon's real HP used to leave the arena plate on the percentage it entered
  // with — the "10 / 100" a viewer sees next to an opponent's honest "0 / 37".
  const benchPercent = {
    id: 'p1: Zygarde', name: 'Zygarde', species: 'Zygarde', hp_fraction: 0.25,
    current_hp: 100, max_hp: 100, hp_is_exact: false,
    status: null, types: ['Dragon'], active: false, fainted: false
  };
  const other = {
    id: 'p1: Chi-Yu', name: 'Chi-Yu', species: 'Chi-Yu', hp_fraction: 1,
    current_hp: 41, max_hp: 41, hp_is_exact: true,
    status: null, types: ['Fire'], active: true, fainted: false
  };
  const benchExact = { ...benchPercent, current_hp: 10, max_hp: 41, hp_is_exact: true };

  const state = reduceEvents(createPresentationState(match), [
    // Zygarde arrives as a percentage from the other player's perspective...
    event(1, 'state_snapshot', { state: {
      ...battle,
      player: { side: 'p1', display_name: 'Alpha', active: other, team: [other, benchPercent] },
      opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] }
    } satisfies BattleState }),
    // ...becomes active, still carrying that percentage...
    event(2, 'pokemon_switched', { actor: 'p1a: Zygarde', hp: '10/41' }),
    // ...and only afterwards does its own side reveal the real 41 HP bar.
    event(3, 'state_snapshot', { state: {
      ...battle,
      player: { side: 'p1', display_name: 'Alpha', active: other, team: [other, benchExact] },
      opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] }
    } satisfies BattleState })
  ]);

  assert.equal(state.battle?.player.active?.name, 'Zygarde');
  assert.equal(state.battle?.player.active?.max_hp, 41, 'the arena plate must show the real bar');
  assert.equal(state.battle?.player.active?.hp_is_exact, true);
});

test('the action feed narrates weather without leaking protocol identifiers', () => {
  const arena = {
    ...battle,
    player: { side: 'p1', display_name: 'Alpha', active: {
      id: 'p1a: Ninetales', name: 'Ninetales', species: 'Ninetales', hp_fraction: 1,
      status: null, types: ['Fire'], active: true, fainted: false }, team: [] },
    opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] }
  } satisfies BattleState;

  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: arena }),
    // An ability bringing weather in names the Pokemon and the ability.
    event(2, 'weather_changed', {
      weather: 'SunnyDay', source: 'ability: Drought', source_actor: 'p1a: Ninetales',
      raw: '|-weather|SunnyDay|[from] ability: Drought|[of] p1a: Ninetales'
    }),
    // The per-turn residual tick must not add a line of its own.
    event(3, 'weather_changed', { weather: 'SunnyDay', upkeep: true, raw: '|-weather|SunnyDay|[upkeep]' }),
    // `none` is Showdown's "weather ended", not an actor called none.
    event(4, 'weather_changed', { weather: 'none', raw: '|-weather|none' })
  ]);

  const headlines = state.actionFeed.map((entry) => entry.headline);
  assert.deepEqual(headlines, [
    "Ninetales's Drought whipped up Sunny Day",
    'The weather cleared'
  ]);
  assert.ok(!headlines.some((line) => /none|SunnyDay/.test(line)));
});

test('a replacement after a faint is not narrated as the fainted Pokemon switching out', () => {
  const pikachu = {
    id: 'p1a: Pikachu', name: 'Pikachu', species: 'Pikachu', hp_fraction: 0.1,
    status: null, types: ['Electric'], active: true, fainted: false
  };
  const state = reduceEvents(createPresentationState(match), [
    event(1, 'state_snapshot', { state: {
      ...battle,
      player: { side: 'p1', display_name: 'Alpha', active: pikachu, team: [pikachu] },
      opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] }
    } satisfies BattleState }),
    event(2, 'pokemon_fainted', { target: 'p1a: Pikachu' }),
    event(3, 'pokemon_switched', { actor: 'p1a: Raichu', hp: '100/100', forced: true })
  ]);

  const headlines = state.actionFeed.map((entry) => entry.headline);
  assert.deepEqual(headlines, ['Pikachu fainted', 'Raichu entered the battle']);
  assert.ok(
    !headlines.some((line) => /Pikachu (switched out|was forced out)/.test(line)),
    'a fainted Pokemon never walks off the field'
  );
});
