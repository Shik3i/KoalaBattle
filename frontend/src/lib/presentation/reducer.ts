import type { BattleEvent, BattleState, Side } from '../types.ts';
import {
  RENDERER_VERSION,
  type ActionPhase,
  type BattleEffect,
  type BattlePresentationState,
  type CommentaryPhase,
  type ContextMetricsPresentation,
  type ImpactPresentationState,
  type MoveVisualArchetype,
  type MoveVisualProfile,
  type PokemonType,
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
      commentary: [],
      currentCommentary: null,
      commentaryPhase: 'waiting',
      streamPreview: null,
      contextMetrics: null
    };
  };
  return {
    version: RENDERER_VERSION,
    matchId: match.id,
    format: match.config.format,
    eventIndex: 0,
    eventSequence: 0,
    battle: null,
    players: { p1: player('p1'), p2: player('p2') },
    currentMove: null,
    currentMoveProfile: null,
    currentMoveSide: null,
    currentMovePhase: 'resolved',
    effect: 'none',
    effectSide: null,
    effectValue: null,
    impacts: { p1: null, p2: null },
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
  let currentMoveProfile = state.currentMoveProfile;
  let currentMoveSide = state.currentMoveSide;
  let currentMovePhase: ActionPhase = state.currentMovePhase;
  let impacts = state.impacts;
  let effectValue: number | null = null;
  let winner = state.winner;
  let winnerName = state.winnerName;
  let finished = state.finished;
  let players = state.players;

  switch (event.event_type) {
    case 'state_snapshot': {
      battle = mergeBattleSnapshot(battle, payload.state as unknown as BattleState);
      if (battle.result) {
        winner = battle.result.winner;
        winnerName = winner ? players[winner].displayName : battle.result.winner_name;
        finished = true;
        players = finishPlayers(players);
      }
      break;
    }
    case 'move_used':
      currentMove = stringValue(payload.move);
      currentMoveProfile = moveVisualProfile(state, side, currentMove, payload);
      currentMoveSide = side;
      currentMovePhase = 'executing';
      players = setMotion(players, side, 'attacking');
      players = setStatus(players, side, 'executing');
      players = setCommentaryPhase(players, side, 'executing');
      break;
    case 'damage':
      effect = 'impact';
      effectValue = hpDelta(state, targetSide, payload.hp);
      battle = updateBattleActive(battle, targetSide, { hp: payload.hp });
      players = setMotion(players, targetSide, 'taking-damage');
      impacts = withImpact(impacts, targetSide, effectValue, event.sequence, 'damage');
      break;
    case 'healing':
      effect = 'healing';
      effectValue = hpDelta(state, targetSide, payload.hp);
      battle = updateBattleActive(battle, targetSide, { hp: payload.hp });
      players = setMotion(players, targetSide, 'status-flash');
      impacts = withImpact(impacts, targetSide, effectValue, event.sequence, 'healing');
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
      battle = updateBattleActive(battle, targetSide, {
        status: event.event_type === 'status_applied' ? stringValue(payload.status) : null
      });
      players = setMotion(players, targetSide, 'status-flash');
      break;
    case 'super_effective':
      effect = 'super-effective';
      players = setMotion(players, targetSide, 'taking-damage');
      break;
    case 'resisted':
      effect = 'resisted';
      break;
    case 'immune':
      effect = 'immune';
      break;
    case 'weather_changed':
      effect = 'weather';
      break;
    case 'terrain_started':
    case 'terrain_ended':
      effect = 'terrain';
      break;
    case 'side_condition_started':
    case 'side_condition_ended':
      effect = 'barrier';
      break;
    case 'showdown_message': {
      const legacy = legacyProtocolEffect(stringValue(payload.command));
      if (legacy) effect = legacy;
      break;
    }
    case 'pokemon_switched':
      battle = switchBattleActive(battle, side, payload);
      // A switch is its own beat. Do not let the previous move remain in the executing
      // phase while the replacement enters the arena; that rendered as an attack on switch.
      currentMove = null;
      currentMoveProfile = null;
      currentMoveSide = null;
      currentMovePhase = 'resolved';
      players = setMotion(players, side, 'switching-in');
      players = setCommentaryPhase(players, side, 'executing');
      break;
    case 'turn_started':
      if (battle) battle = { ...battle, turn: numberValue(payload.turn) ?? event.turn };
      // The previous turn has resolved: retire its commentary, headline action and HP
      // flashes so none of them can be mistaken for the reasoning behind the next move.
      // The headline is cleared outright rather than only marked resolved — left standing it
      // sat over the arena for the rest of the match announcing a move from a turn ago.
      players = resolveCommentary(players);
      currentMove = null;
      currentMoveProfile = null;
      currentMoveSide = null;
      currentMovePhase = 'resolved';
      impacts = { p1: null, p2: null };
      break;
    case 'pokemon_fainted':
      effect = 'faint';
      battle = updateBattleActive(battle, targetSide, { hp: '0 fnt', fainted: true });
      players = setMotion(players, targetSide, 'fainting');
      break;
    case 'agent_state':
    case 'agent_progress': {
      if (!side) break;
      const lifecycle = stringValue(payload.state);
      if (lifecycle === 'thinking' || lifecycle === 'waiting' || lifecycle === 'retrying') {
        // A new decision has started, so the previous turn's commentary is no longer current.
        players = {
          ...players,
          [side]: {
            ...players[side],
            commentaryPhase: 'thinking',
            currentCommentary: null,
            streamPreview: stringValue(payload.progress) || null,
            contextMetrics: contextMetricsValue(payload.context_metrics) || players[side].contextMetrics
          }
        };
      }
      break;
    }
    case 'agent_decision': {
      if (!side) break;
      const entry = {
        sequence: event.sequence,
        turn: event.turn,
        side,
        action: stringValue(payload.action),
        actionName: stringValue(payload.action_name),
        commentary: stringValue(payload.public_text) || stringValue(payload.commentary),
        banter: stringValue(payload.banter) || null,
        latencyMs: numberValue(payload.latency_ms)
      };
      players = {
        ...players,
        [side]: {
          ...players[side],
          agentStatus: 'decided',
          commentaryPhase: 'decided',
          currentCommentary: entry,
          streamPreview: null,
          commentary: [...players[side].commentary, entry]
        }
      };
      break;
    }
    case 'battle_finished':
      effect = 'victory';
      if (typeof payload.result === 'object' && payload.result !== null) {
        const result = payload.result as Record<string, unknown>;
        const resultWinner = result.winner === 'p1' || result.winner === 'p2' ? result.winner : null;
        winner = resultWinner || winner;
        winnerName = resultWinner
          ? players[resultWinner].displayName
          : stringValue(result.winner_name) || winnerName;
      } else {
        const rawWinnerName = stringValue(payload.winner_name);
        const internalSide = internalWinnerSide(rawWinnerName);
        winner = internalSide || winner;
        winnerName = internalSide ? players[internalSide].displayName : rawWinnerName || winnerName;
      }
      finished = true;
      players = finishPlayers(players);
      break;
  }

  const entry = spectatorEntry(event, battle, effectValue);
  return {
    ...state,
    battle,
    players,
    currentMove,
    currentMoveProfile,
    currentMoveSide,
    currentMovePhase,
    effect,
    effectSide,
    effectValue,
    impacts,
    log: appendLogEntry(state.log, entry),
    winner,
    winnerName,
    finished
  };
}

function withImpact(
  impacts: BattlePresentationState['impacts'],
  side: Side | null,
  value: number | null,
  sequence: number,
  kind: ImpactPresentationState['kind']
): BattlePresentationState['impacts'] {
  if (!side || value === null || value === 0) return impacts;
  return { ...impacts, [side]: { side, value, sequence, kind } };
}

function setCommentaryPhase(
  players: BattlePresentationState['players'],
  side: Side | null,
  phase: CommentaryPhase
) {
  if (!side) return players;
  // Only an action that already has commentary can move into executing.
  if (phase === 'executing' && !players[side].currentCommentary) return players;
  return { ...players, [side]: { ...players[side], commentaryPhase: phase } };
}

function resolveCommentary(players: BattlePresentationState['players']) {
  const retire = (player: PlayerPresentationState): PlayerPresentationState =>
    player.currentCommentary
      ? { ...player, commentaryPhase: 'resolved', currentCommentary: null }
      : player;
  return { p1: retire(players.p1), p2: retire(players.p2) };
}

/** Drop consecutive duplicates so a repeated authoritative event never reads as two hits. */
function appendLogEntry(log: SpectatorLogEntry[], entry: SpectatorLogEntry | null) {
  if (!entry) return log;
  const previous = log[log.length - 1];
  if (previous && previous.text === entry.text && previous.turn === entry.turn) return log;
  return [...log, entry];
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
    effectSide: null,
    effectValue: null
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

function contextMetricsValue(value: unknown): ContextMetricsPresentation | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Record<string, unknown>;
  const renderedCharacters = numberValue(candidate.rendered_characters);
  const estimatedTokens = numberValue(candidate.estimated_tokens);
  return renderedCharacters !== null && estimatedTokens !== null
    ? { renderedCharacters, estimatedTokens }
    : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

const POKEMON_TYPES = new Set<PokemonType>([
  'normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison', 'ground',
  'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy'
]);

function moveVisualProfile(
  state: BattlePresentationState,
  side: Side | null,
  moveName: string,
  payload: Record<string, unknown>
): MoveVisualProfile {
  const battleSide = side && state.battle
    ? state.battle.player.side === side
      ? state.battle.player
      : state.battle.opponent.side === side
        ? state.battle.opponent
        : null
    : null;
  const knownMove = battleSide?.active?.moves?.find(
    (move) => move.name.toLocaleLowerCase() === moveName.toLocaleLowerCase()
  );
  const rawType = (stringValue(payload.move_type) || knownMove?.type || 'normal').toLowerCase();
  const type = POKEMON_TYPES.has(rawType as PokemonType) ? rawType as PokemonType : 'normal';
  const rawCategory = stringValue(payload.category) || knownMove?.category || '';
  const archetype: MoveVisualArchetype = rawCategory === 'physical' || rawCategory === 'special'
    || rawCategory === 'status'
    ? rawCategory
    : knownMove?.power === 0 || knownMove?.power === null
      ? 'status'
      : 'special';
  return { type, archetype, moveName: moveName || 'Unknown move', seed: stableSeed(moveName) };
}

function stableSeed(value: string): number {
  let seed = 2166136261;
  for (const character of value) {
    seed ^= character.charCodeAt(0);
    seed = Math.imul(seed, 16777619);
  }
  return seed >>> 0;
}

function internalWinnerSide(value: string): Side | null {
  const match = value.match(/^KoalaP([12])/i);
  return match?.[1] === '1' ? 'p1' : match?.[1] === '2' ? 'p2' : null;
}

function hpDelta(
  state: BattlePresentationState,
  side: Side | null,
  hp: unknown
): number | null {
  if (!side || typeof hp !== 'string' || !state.battle) return null;
  const battleSide = state.battle.player.side === side ? state.battle.player : state.battle.opponent;
  const previous = battleSide.active?.hp_fraction;
  const match = hp.match(/([0-9.]+)\s*\/\s*([0-9.]+)/);
  const next = match ? Number(match[1]) / Math.max(1, Number(match[2])) : hp.includes('fnt') ? 0 : null;
  return previous === undefined || next === null ? null : Math.round((next - previous) * 100);
}

function legacyProtocolEffect(command: string): BattleEffect | null {
  const effects: Record<string, BattleEffect> = {
    '-supereffective': 'super-effective',
    '-resisted': 'resisted',
    '-immune': 'immune',
    '-weather': 'weather',
    '-fieldstart': 'terrain',
    '-fieldend': 'terrain',
    '-sidestart': 'barrier',
    '-sideend': 'barrier'
  };
  return effects[command] || null;
}

function updateBattleActive(
  battle: BattlePresentationState['battle'],
  side: Side | null,
  update: { hp?: unknown; status?: string | null; fainted?: boolean }
): BattlePresentationState['battle'] {
  if (!battle || !side) return battle;
  const key = battle.player.side === side ? 'player' : battle.opponent.side === side ? 'opponent' : null;
  if (!key || !battle[key].active) return battle;
  const active = battle[key].active;
  let hpFraction = active.hp_fraction;
  if (typeof update.hp === 'string') {
    const match = update.hp.match(/([0-9.]+)\s*\/\s*([0-9.]+)/);
    if (match) hpFraction = Math.max(0, Math.min(1, Number(match[1]) / Math.max(1, Number(match[2]))));
    else if (update.hp.includes('fnt')) hpFraction = 0;
  }
  const nextActive = {
    ...active,
    hp_fraction: hpFraction,
    status: update.status !== undefined ? update.status : active.status,
    fainted: update.fainted ?? active.fainted
  };
  const team = battle[key].team.map((member) => member.id === active.id ? nextActive : member);
  return { ...battle, [key]: { ...battle[key], active: nextActive, team } };
}

function mergeBattleSnapshot(
  current: BattlePresentationState['battle'],
  incoming: BattleState
): BattleState {
  if (!current) return incoming;
  const currentBySide = new Map([
    [current.player.side, current.player],
    [current.opponent.side, current.opponent]
  ]);
  const mergeSide = (nextSide: BattleState['player']) => {
    const previousSide = currentBySide.get(nextSide.side);
    const previousActive = previousSide?.active;
    const nextActive = nextSide.active;
    if (!previousSide) return nextSide;
    const sameActive = Boolean(previousActive && nextActive && (
      previousActive.id === nextActive.id
      || previousActive.name.toLocaleLowerCase() === nextActive.name.toLocaleLowerCase()
    ));
    // State snapshots are recorded before the normalized event stream catches up. Keep the
    // active switch and HP changes event-driven, but never discard team members revealed by a
    // snapshot from the opposite player's perspective.
    const active = sameActive && previousActive && nextActive
      ? {
          ...nextActive,
          current_hp: previousActive.current_hp,
          max_hp: previousActive.max_hp,
          hp_fraction: previousActive.hp_fraction,
          status: previousActive.status,
          fainted: previousActive.fainted,
          active: previousActive.active
        }
      : previousActive || null;
    const team = mergeTeam(previousSide.team, nextSide.team);
    if (active && !team.some((member) => member.id === active.id)) team.push(active);
    return { ...nextSide, active, team };
  };
  return {
    ...incoming,
    turn: current.turn,
    last_action: current.last_action,
    result: current.result,
    player: mergeSide(incoming.player),
    opponent: mergeSide(incoming.opponent)
  };
}

function mergeTeam(previous: BattleState['player']['team'], incoming: BattleState['player']['team']) {
  const merged = previous.map((member) => member);
  for (const member of incoming) {
    const index = merged.findIndex((candidate) => candidate.id === member.id);
    if (index < 0) {
      merged.push(member);
      continue;
    }
    const existing = merged[index];
    merged[index] = {
      ...member,
      // Keep event-driven combat facts when a future snapshot reports the same Pokémon.
      current_hp: existing.current_hp,
      max_hp: existing.max_hp,
      hp_fraction: existing.hp_fraction,
      status: existing.status,
      active: existing.active,
      fainted: existing.fainted
    };
  }
  return merged;
}

function switchBattleActive(
  battle: BattlePresentationState['battle'],
  side: Side | null,
  payload: Record<string, unknown>
): BattlePresentationState['battle'] {
  if (!battle || !side) return battle;
  const key = battle.player.side === side ? 'player' : battle.opponent.side === side ? 'opponent' : null;
  if (!key) return battle;
  const battleSide = battle[key];
  const name = actorName(payload.actor).toLocaleLowerCase();
  let selected = battleSide.team.find((member) =>
    member.name.toLocaleLowerCase() === name || member.id.toLocaleLowerCase().endsWith(`: ${name}`)
  );
  if (!selected) {
    const species = name.replace(/[^a-z0-9]/g, '') || 'unknown';
    selected = {
      id: `${side}: ${actorName(payload.actor)}`,
      name: actorName(payload.actor),
      species,
      hp_fraction: 1,
      current_hp: null,
      max_hp: null,
      status: null,
      types: [],
      moves: [],
      active: false,
      fainted: false
    };
  }
  const hp = stringValue(payload.hp);
  const match = hp.match(/([0-9.]+)\s*\/\s*([0-9.]+)/);
  const hpFraction = match
    ? Math.max(0, Math.min(1, Number(match[1]) / Math.max(1, Number(match[2]))))
    : hp.includes('fnt') ? 0 : selected.hp_fraction;
  const active = {
    ...selected,
    active: true,
    hp_fraction: hpFraction,
    fainted: hp.includes('fnt')
  };
  const team = [...battleSide.team, ...(battleSide.team.some((member) => member.id === selected?.id) ? [] : [selected])].map((member) => ({
    ...member,
    active: member.id === active.id,
    ...(member.id === active.id ? active : {})
  }));
  return { ...battle, [key]: { ...battleSide, active, team } };
}

function actorName(value: unknown): string {
  return stringValue(value).replace(/^p[12]a:\s*/, '') || 'Pokémon';
}

function spectatorEntry(
  event: BattleEvent,
  battle: BattleState | null,
  hpDeltaPercent: number | null
): SpectatorLogEntry | null {
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
      // Report the authoritative delta, not a generic "took damage" line.
      text = hpDeltaPercent
        ? `${actorName(payload.target)} lost ${Math.abs(hpDeltaPercent)}% HP.`
        : `${actorName(payload.target)} took damage.`;
      emphasis = 'negative';
      break;
    case 'healing':
      text = hpDeltaPercent
        ? `${actorName(payload.target)} recovered ${Math.abs(hpDeltaPercent)}% HP.`
        : `${actorName(payload.target)} recovered health.`;
      emphasis = 'positive';
      break;
    case 'critical_hit':
      text = 'A critical hit!';
      emphasis = 'critical';
      break;
    case 'super_effective':
      text = 'It is super effective!';
      emphasis = 'critical';
      break;
    case 'resisted':
      text = 'It is not very effective.';
      break;
    case 'immune':
      text = 'The attack had no effect.';
      emphasis = 'negative';
      break;
    case 'weather_changed':
      text = `${stringValue(payload.weather) || 'Weather'} changed the arena.`;
      break;
    case 'terrain_started':
    case 'terrain_ended':
      text = `${stringValue(payload.field) || 'Terrain'} changed.`;
      break;
    case 'side_condition_started':
    case 'side_condition_ended':
      text = `${stringValue(payload.condition) || 'A field barrier'} changed.`;
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
