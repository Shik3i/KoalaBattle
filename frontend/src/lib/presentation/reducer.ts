import type { BattleEvent, BattleState, Side } from '../types.ts';
import {
  RENDERER_VERSION,
  type BattleEffect,
  type BattlePresentationState,
  type PlayerPresentationState,
  type PresentationMatch,
  type SpectatorLogEntry
} from './types.ts';

const SIDES: Side[] = ['p1', 'p2'];

export function createPresentationState(match: PresentationMatch): BattlePresentationState {
  const player = (side: Side): PlayerPresentationState => {
    const config = match.config.players.find((item) => item.side === side);
    const provider = [config?.provider, config?.model].filter(Boolean).join(' · ');
    return {
      side,
      displayName: config?.display_name || side.toUpperCase(),
      providerLabel: provider || (config?.agent_type === 'manual' ? 'Manual agent' : 'Random agent'),
      agentStatus: 'waiting',
      motion: 'idle',
      commentary: []
    };
  };
  return {
    version: RENDERER_VERSION,
    matchId: match.id,
    eventIndex: 0,
    eventSequence: 0,
    battle: null,
    players: { p1: player('p1'), p2: player('p2') },
    currentMove: null,
    effect: 'none',
    effectSide: null,
    log: [],
    winner: null,
    winnerName: null,
    finished: false
  };
}

export function reducePresentation(
  current: BattlePresentationState,
  event: BattleEvent
): BattlePresentationState {
  const state = resetTransient(current, event);
  const side = eventSide(event);
  const targetSide = eventTargetSide(event);
  const payload = event.payload;
  let effect: BattleEffect = 'none';
  let effectSide: Side | null = targetSide;
  let battle = state.battle;
  let currentMove = state.currentMove;
  let winner = state.winner;
  let winnerName = state.winnerName;
  let finished = state.finished;
  let players = state.players;

  switch (event.event_type) {
    case 'state_snapshot': {
      battle = payload.state as unknown as BattleState;
      if (battle.result) {
        winner = battle.result.winner;
        winnerName = battle.result.winner_name;
        finished = true;
        players = finishPlayers(players);
      }
      break;
    }
    case 'move_used':
      currentMove = stringValue(payload.move);
      players = setMotion(players, side, 'attacking');
      players = setStatus(players, side, 'executing');
      break;
    case 'damage':
      effect = 'impact';
      players = setMotion(players, targetSide, 'taking-damage');
      break;
    case 'healing':
      effect = 'healing';
      players = setMotion(players, targetSide, 'status-flash');
      break;
    case 'critical_hit':
      effect = 'critical-hit';
      players = setMotion(players, targetSide, 'taking-damage');
      break;
    case 'move_missed':
      effect = 'miss';
      effectSide = side;
      break;
    case 'status_applied':
    case 'status_removed':
      effect = 'status';
      players = setMotion(players, targetSide, 'status-flash');
      break;
    case 'pokemon_switched':
      players = setMotion(players, side, 'switching-in');
      break;
    case 'pokemon_fainted':
      effect = 'faint';
      players = setMotion(players, targetSide, 'fainting');
      break;
    case 'agent_decision': {
      if (!side) break;
      const commentary = stringValue(payload.commentary);
      players = {
        ...players,
        [side]: {
          ...players[side],
          agentStatus: 'decided',
          commentary: [
            ...players[side].commentary,
            {
              sequence: event.sequence,
              turn: event.turn,
              side,
              action: stringValue(payload.action),
              actionName: stringValue(payload.action_name),
              commentary,
              latencyMs: numberValue(payload.latency_ms)
            }
          ]
        }
      };
      break;
    }
    case 'battle_finished':
      effect = 'victory';
      if (typeof payload.result === 'object' && payload.result !== null) {
        const result = payload.result as Record<string, unknown>;
        winner = result.winner === 'p1' || result.winner === 'p2' ? result.winner : winner;
        winnerName = stringValue(result.winner_name) || winnerName;
      } else {
        winnerName = stringValue(payload.winner_name) || winnerName;
      }
      finished = true;
      players = finishPlayers(players);
      break;
  }

  const entry = spectatorEntry(event, battle);
  return {
    ...state,
    battle,
    players,
    currentMove,
    effect,
    effectSide,
    log: entry ? [...state.log, entry] : state.log,
    winner,
    winnerName,
    finished
  };
}

export function reduceEvents(
  initial: BattlePresentationState,
  events: readonly BattleEvent[],
  end = events.length
): BattlePresentationState {
  let state = initial;
  for (let index = 0; index < Math.min(end, events.length); index += 1) {
    state = reducePresentation(state, events[index]);
  }
  return state;
}

export function withAgentStatus(
  state: BattlePresentationState,
  side: Side,
  agentStatus: PlayerPresentationState['agentStatus']
): BattlePresentationState {
  return {
    ...state,
    players: { ...state.players, [side]: { ...state.players[side], agentStatus } }
  };
}

function resetTransient(
  state: BattlePresentationState,
  event: BattleEvent
): BattlePresentationState {
  const players = { ...state.players };
  for (const side of SIDES) players[side] = { ...players[side], motion: 'idle' };
  return {
    ...state,
    eventIndex: state.eventIndex + 1,
    eventSequence: event.sequence,
    players,
    effect: 'none',
    effectSide: null
  };
}

function setMotion(
  players: BattlePresentationState['players'],
  side: Side | null,
  motion: PlayerPresentationState['motion']
) {
  return side ? { ...players, [side]: { ...players[side], motion } } : players;
}

function setStatus(
  players: BattlePresentationState['players'],
  side: Side | null,
  agentStatus: PlayerPresentationState['agentStatus']
) {
  return side ? { ...players, [side]: { ...players[side], agentStatus } } : players;
}

function finishPlayers(players: BattlePresentationState['players']) {
  return {
    p1: { ...players.p1, agentStatus: 'finished' as const },
    p2: { ...players.p2, agentStatus: 'finished' as const }
  };
}

function eventSide(event: BattleEvent): Side | null {
  return sideFromText(stringValue(event.payload.side) || stringValue(event.payload.actor));
}

function eventTargetSide(event: BattleEvent): Side | null {
  return sideFromText(stringValue(event.payload.target));
}

function sideFromText(value: string): Side | null {
  const match = value.match(/(?:^|\|)(p[12])(?:a|:|$)/);
  return match?.[1] === 'p1' || match?.[1] === 'p2' ? match[1] : null;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function actorName(value: unknown): string {
  return stringValue(value).replace(/^p[12]a:\s*/, '') || 'Pokémon';
}

function spectatorEntry(event: BattleEvent, battle: BattleState | null): SpectatorLogEntry | null {
  const payload = event.payload;
  let text = '';
  let emphasis: SpectatorLogEntry['emphasis'] = 'normal';
  switch (event.event_type) {
    case 'turn_started':
      text = `Turn ${numberValue(payload.turn) ?? event.turn}`;
      break;
    case 'move_used':
      text = `${actorName(payload.actor)} used ${stringValue(payload.move) || 'a move'}.`;
      break;
    case 'move_missed':
      text = `${actorName(payload.actor)} missed.`;
      emphasis = 'negative';
      break;
    case 'damage':
      text = `${actorName(payload.target)} took damage.`;
      emphasis = 'negative';
      break;
    case 'healing':
      text = `${actorName(payload.target)} recovered health.`;
      emphasis = 'positive';
      break;
    case 'critical_hit':
      text = 'A critical hit!';
      emphasis = 'critical';
      break;
    case 'status_applied':
      text = `${actorName(payload.target)} is now ${stringValue(payload.status) || 'affected'}.`;
      break;
    case 'status_removed':
      text = `${actorName(payload.target)} recovered from ${stringValue(payload.status) || 'status'}.`;
      emphasis = 'positive';
      break;
    case 'pokemon_switched':
      text = `${actorName(payload.actor)} entered the arena.`;
      break;
    case 'pokemon_fainted':
      text = `${actorName(payload.target)} fainted.`;
      emphasis = 'negative';
      break;
    case 'battle_finished':
      text = `${stringValue(payload.winner_name) || battle?.result?.winner_name || 'Battle'} wins.`;
      emphasis = 'critical';
      break;
    default:
      return null;
  }
  return { sequence: event.sequence, turn: event.turn, kind: event.event_type, text, emphasis };
}
