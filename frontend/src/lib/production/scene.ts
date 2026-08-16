import type { PokemonState, ProductionCue, Side } from '../types.ts';
import type { BattlePresentationState, PokemonType } from '../presentation/types.ts';
import type { ProductionFrameState } from './frame-state.ts';

export const AUTHORITATIVE_IMPACT_PROGRESS = 0.72;

export interface ProductionSceneSide {
  side: Side;
  displayName: string;
  providerLabel: string;
  active: PokemonState | null;
  team: PokemonState[];
  sideConditions: string[];
  spriteUrl: string | null;
  near: boolean;
}

export type ProductionEffectArchetype =
  | 'contact'
  | 'projectile'
  | 'beam'
  | 'pulse'
  | 'status'
  | 'buff'
  | 'debuff'
  | 'heal'
  | 'barrier'
  | 'hazard'
  | 'field';

export interface ProductionSceneEffect {
  kind: string;
  moveName: string | null;
  type: PokemonType;
  archetype: ProductionEffectArchetype;
  progress: number;
  impactProgress: number;
  seed: number;
  actor: Side | null;
  target: Side | null;
  value: number | null;
}

export interface ProductionScene {
  version: '2.0';
  timeMs: number;
  turn: number;
  format: string;
  vertical: boolean;
  p1: ProductionSceneSide;
  p2: ProductionSceneSide;
  weather: string[];
  fields: string[];
  effect: ProductionSceneEffect;
  commentary: string | null;
  commentarySide: Side | null;
  caption: string | null;
  captionSide: Side | null;
  director: ProductionCue | null;
  winnerName: string | null;
  finished: boolean;
}

export function createProductionScene(
  frame: ProductionFrameState,
  vertical: boolean,
  assetApiBase: string
): ProductionScene {
  const presentation = authoritativePresentation(frame);
  const battle = presentation.battle;
  const sideState = (side: Side) => {
    if (!battle) return null;
    return battle.player.side === side ? battle.player : battle.opponent.side === side ? battle.opponent : null;
  };
  const makeSide = (side: Side, near: boolean): ProductionSceneSide => {
    const state = sideState(side);
    const active = state?.active || null;
    return {
      side,
      displayName: presentation.players[side].displayName,
      providerLabel: presentation.players[side].providerLabel,
      active,
      team: state?.team || [],
      sideConditions: state?.side_conditions || [],
      spriteUrl: active
        ? `${assetApiBase}/api/assets/pokemon/${encodeURIComponent(active.species)}?perspective=${near ? 'back' : 'front'}&animated=false`
        : null,
      near
    };
  };
  const actor = eventSide(frame.event?.payload.side) || eventSide(frame.event?.payload.actor);
  const target = eventSide(frame.event?.payload.target) || (actor ? opposite(actor) : presentation.effectSide);
  const profile = presentation.currentMoveProfile;
  const visualKind = frame.visual?.kind || presentation.effect;
  const visibleEffect = isVisibleBattleEffect(visualKind);
  return {
    version: '2.0',
    timeMs: frame.timeMs,
    turn: battle?.turn || frame.visual?.turn || 0,
    format: presentation.format,
    vertical,
    p1: makeSide('p1', true),
    p2: makeSide('p2', false),
    weather: battle?.weather || [],
    fields: battle?.fields || [],
    effect: {
      kind: visualKind,
      moveName: visibleEffect && /move|damage|heal|critical|effective|resisted|immune/.test(visualKind)
        ? presentation.currentMove
        : null,
      type: profile?.type || 'normal',
      archetype: effectArchetype(frame, profile?.archetype, profile?.type),
      progress: visibleEffect ? frame.visualProgress : 0,
      impactProgress: visibleEffect
        ? clamp((frame.visualProgress - AUTHORITATIVE_IMPACT_PROGRESS) / (1 - AUTHORITATIVE_IMPACT_PROGRESS))
        : 0,
      seed: profile?.seed ?? stableSeed(`${frame.visual?.id || 'idle'}:${frame.event?.sequence || 0}`),
      actor,
      target,
      value: presentation.effectValue
    },
    commentary: cueText(frame.commentary),
    commentarySide: frame.commentary?.side || null,
    caption: activeCaptionText(frame.caption, frame.timeMs),
    captionSide: frame.caption?.side || null,
    director: frame.director,
    winnerName: presentation.winnerName,
    finished: presentation.finished
  };
}

function isVisibleBattleEffect(kind: string): boolean {
  return /^(move_|damage$|healing$|critical_hit$|status_|super_effective$|resisted$|immune$|weather_|terrain_|side_condition_|pokemon_switched$|pokemon_fainted$|battle_finished$)/.test(kind);
}

function cueText(cue: ProductionCue | null): string | null {
  return cue && typeof cue.payload.text === 'string' ? cue.payload.text : null;
}

function authoritativePresentation(frame: ProductionFrameState): BattlePresentationState {
  if (!frame.priorPresentation || frame.visualProgress >= AUTHORITATIVE_IMPACT_PROGRESS) {
    return frame.presentation;
  }
  const delayed = new Set(['damage', 'healing', 'status_applied', 'status_removed', 'pokemon_fainted']);
  if (!frame.visual || !delayed.has(frame.visual.kind)) return frame.presentation;
  return {
    ...frame.priorPresentation,
    currentMove: frame.presentation.currentMove,
    currentMoveProfile: frame.presentation.currentMoveProfile,
    effect: frame.presentation.effect,
    effectSide: frame.presentation.effectSide,
    effectValue: frame.presentation.effectValue
  };
}

function activeCaptionText(cue: ProductionCue | null, timeMs: number): string | null {
  if (!cue) return null;
  const segments = Array.isArray(cue.payload.segments) ? cue.payload.segments : [];
  const elapsed = timeMs - cue.start_ms;
  const segment = segments.find((value) => {
    if (!value || typeof value !== 'object') return false;
    const item = value as Record<string, unknown>;
    return Number(item.start_ms) <= elapsed && Number(item.end_ms) > elapsed;
  }) as Record<string, unknown> | undefined;
  if (typeof segment?.text === 'string') return segment.text;
  return typeof cue.payload.text === 'string' ? cue.payload.text : null;
}

function eventSide(value: unknown): Side | null {
  if (typeof value !== 'string') return null;
  const match = value.match(/(?:^|\|)(p[12])(?:a|:|$)/);
  return match?.[1] === 'p1' || match?.[1] === 'p2' ? match[1] : null;
}

function effectArchetype(
  frame: ProductionFrameState,
  category?: 'physical' | 'special' | 'status',
  type?: PokemonType
): ProductionEffectArchetype {
  const kind = frame.visual?.kind || '';
  const condition = String(frame.event?.payload.condition || '').toLowerCase();
  if (kind === 'healing') return 'heal';
  if (kind.includes('side_condition')) {
    return /(spike|rock|web)/.test(condition) ? 'hazard' : 'barrier';
  }
  if (kind.includes('weather') || kind.includes('terrain')) return 'field';
  if (kind.includes('unboost') || kind.includes('debuff')) return 'debuff';
  if (kind.includes('boost') || kind.includes('buff')) return 'buff';
  if (kind.includes('status') || category === 'status') return 'status';
  if (category === 'physical' || kind === 'damage' || kind === 'critical_hit') return 'contact';
  if (type === 'electric' || type === 'psychic' || type === 'dragon') return 'beam';
  if (type === 'ground' || type === 'flying' || type === 'ice') return 'pulse';
  return 'projectile';
}

function opposite(side: Side): Side { return side === 'p1' ? 'p2' : 'p1'; }
function clamp(value: number): number { return Math.max(0, Math.min(1, value)); }

function stableSeed(value: string): number {
  let seed = 2166136261;
  for (const character of value) {
    seed ^= character.charCodeAt(0);
    seed = Math.imul(seed, 16777619);
  }
  return seed >>> 0;
}
