import type { PokemonState, ProductionCue, ProductionStyle, Side } from '../types.ts';
import type { BattlePresentationState, PokemonType } from '../presentation/types.ts';
import type { ProductionFrameState } from './frame-state.ts';
import { MARK_LABELS, accentFor, assetUrl, brandingFor, formatDisplayName } from './style.ts';

export const AUTHORITATIVE_IMPACT_PROGRESS = 0.72;

/**
 * Whether a Pokemon should be drawn knocked out.
 *
 * This must not depend on the faint cue being active: that cue lasts under a second, while
 * the knocked-out Pokemon stays on the field until its replacement is sent out. Driving the
 * pose from the cue alone made the sprite spring back up moments after the KO.
 */
export function isKnockedOut(side: ProductionSceneSide): boolean {
  const active = side.active;
  if (!active) return false;
  return Boolean(active.fainted) || active.hp_fraction <= 0;
}

export interface ProductionSceneSide {
  side: Side;
  displayName: string;
  providerLabel: string;
  active: PokemonState | null;
  previousHpFraction: number | null;
  team: PokemonState[];
  sideConditions: string[];
  spriteUrl: string | null;
  near: boolean;
  /** Resolved presentation identity. Never affects which agent actually played. */
  accent: string;
  logoUrl: string | null;
  markLabel: string;
  slot: string;
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
  moveId: string | null;
  type: PokemonType;
  category: 'physical' | 'special' | 'status' | null;
  condition: string | null;
  archetype: ProductionEffectArchetype;
  /** True only while an authoritative move_used/move_missed cue is on screen. */
  attack: boolean;
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
  /** Human-readable format label, e.g. `Gen 1 · OU`. Machine ids stay internal. */
  formatLabel: string;
  style: ProductionStyle;
  title: string | null;
  vertical: boolean;
  p1: ProductionSceneSide;
  p2: ProductionSceneSide;
  weather: string[];
  fields: string[];
  effect: ProductionSceneEffect;
  commentary: string | null;
  commentarySide: Side | null;
  /** Time since the commentary cue began, so entrance motion stays deterministic. */
  commentaryElapsedMs: number;
  caption: string | null;
  captionSide: Side | null;
  director: ProductionCue | null;
  winnerName: string | null;
  finished: boolean;
}

export function createProductionScene(
  frame: ProductionFrameState,
  vertical: boolean,
  assetApiBase: string,
  style: ProductionStyle,
  title: string | null = null
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
    const previousBattle = frame.priorPresentation?.battle;
    const previousState = previousBattle
      ? previousBattle.player.side === side
        ? previousBattle.player
        : previousBattle.opponent.side === side
          ? previousBattle.opponent
          : null
      : null;
    const previousActive = previousState?.active || null;
    const branding = brandingFor(style, side);
    return {
      side,
      displayName: branding.display_name || presentation.players[side].displayName,
      providerLabel: presentation.players[side].providerLabel,
      accent: accentFor(style, side),
      logoUrl: assetUrl(assetApiBase, branding.logo_asset_id),
      markLabel:
        branding.short_name ||
        MARK_LABELS[branding.logo_mark || ''] ||
        (branding.display_name || presentation.players[side].displayName).slice(0, 8).toUpperCase(),
      slot: side.toUpperCase(),
      active,
      previousHpFraction:
        active && previousActive && active.id === previousActive.id
          ? previousActive.hp_fraction
          : null,
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
  const attackCue = visualKind === 'move_used' || visualKind === 'move_missed';
  return {
    version: '2.0',
    timeMs: frame.timeMs,
    turn: battle?.turn || frame.visual?.turn || 0,
    format: presentation.format,
    formatLabel: formatDisplayName(presentation.format, style.show_generation),
    style,
    title: title || style.title,
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
      moveId: attackCue ? normalizeMoveId(presentation.currentMove) : null,
      type: profile?.type || 'normal',
      category: profile?.archetype || null,
      condition: eventCondition(frame),
      archetype: effectArchetype(frame, profile?.archetype, profile?.type),
      attack: attackCue && Boolean(actor && profile),
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
    commentaryElapsedMs: frame.commentary ? Math.max(0, frame.timeMs - frame.commentary.start_ms) : 0,
    caption: activeCaptionText(frame.caption, frame.timeMs),
    captionSide: frame.caption?.side || null,
    director: frame.director,
    winnerName: presentation.winnerName,
    finished: presentation.finished
  };
}

export interface DirectorCard {
  kind: 'intro' | 'result';
  progress: number;
  opacity: number;
  eyebrow: string | null;
  headline: string;
  subtitle: string | null;
  badge: string | null;
  showLogos: boolean;
}

export type DamageTone = 'damage' | 'heal' | 'crit' | 'effective' | 'resist' | 'immune' | 'miss';

export interface DamageCallout {
  text: string;
  tone: DamageTone;
  progress: number;
}

/**
 * The short numeric/verbal callout for the current hit, honouring the style's toggles.
 *
 * Damage feedback is the one overlay a viewer reads on every exchange, so which callouts
 * appear is a style decision — but the number itself always comes from the recorded HP
 * change, never from an estimate.
 */
export function damageCallout(scene: ProductionScene): DamageCallout | null {
  const damage = scene.style.damage;
  const effect = scene.effect;
  if (effect.impactProgress <= 0 || effect.impactProgress >= 1) return null;
  const value = effect.value;
  const progress = effect.impactProgress;
  switch (effect.kind) {
    case 'damage':
      return damage.show_damage && value ? { text: `${Math.abs(value)}%`, tone: 'damage', progress } : null;
    case 'healing':
      return damage.show_healing && value ? { text: `+${Math.abs(value)}%`, tone: 'heal', progress } : null;
    case 'critical_hit':
      return damage.show_critical ? { text: 'CRITICAL', tone: 'crit', progress } : null;
    case 'super_effective':
      return damage.show_effectiveness ? { text: 'SUPER EFFECTIVE', tone: 'effective', progress } : null;
    case 'resisted':
      return damage.show_effectiveness ? { text: 'RESISTED', tone: 'resist', progress } : null;
    case 'immune':
      return damage.show_immune ? { text: 'IMMUNE', tone: 'immune', progress } : null;
    case 'move_missed':
      return damage.show_miss ? { text: 'MISS', tone: 'miss', progress } : null;
    default:
      return null;
  }
}

const INTRO_KINDS = new Set(['match-intro', 'team-reveal']);
const RESULT_KINDS = new Set(['result', 'outro', 'champion']);

/**
 * What the full-screen intro/result card should say, or null when none is showing.
 *
 * Kept out of the compositor so the decision is unit-testable: the result banner failing
 * to appear is a content bug, not a drawing bug, and asserting it needs no canvas.
 */
export function directorCard(scene: ProductionScene): DirectorCard | null {
  const cue = scene.director;
  if (!cue) return null;
  const intro = INTRO_KINDS.has(cue.kind);
  const result = RESULT_KINDS.has(cue.kind);
  if (!intro && !result) return null;
  const style = scene.style;
  if (intro && !style.intro.enabled) return null;
  if (result && !style.result.enabled) return null;
  const progress = clamp((scene.timeMs - cue.start_ms) / Math.max(1, cue.duration_ms));
  const opacity = Math.min(1, progress * 7, (1 - progress) * 7);
  if (opacity <= 0) return null;
  const series = style.series;
  const names = [scene.p1.displayName, scene.p2.displayName];
  if (intro) {
    const meta: string[] = [];
    if (style.intro.show_format && style.show_format) meta.push(scene.formatLabel);
    if (style.intro.show_game_number && series.game_number) meta.push(`GAME ${series.game_number}`);
    if (style.intro.show_game_number && series.best_of) meta.push(`BEST OF ${series.best_of}`);
    if (style.intro.show_series_score && series.score_p1 !== null && series.score_p2 !== null) {
      meta.push(`SERIES ${series.score_p1}–${series.score_p2}`);
    }
    const round = [series.tournament_name, series.round_name].filter(Boolean).join(' · ');
    return {
      kind: 'intro',
      progress,
      opacity,
      eyebrow:
        (style.intro.show_tournament_round && round) ||
        (style.show_koala_branding ? 'KOALABATTLE // MAIN EVENT' : null),
      headline: style.intro.show_player_names ? names.join('  VS  ') : 'VS',
      subtitle: meta.join('   ·   ') || null,
      badge: style.intro.show_player_names ? 'VS' : null,
      showLogos: style.intro.show_player_logos
    };
  }
  const meta: string[] = [];
  if (style.result.show_format && style.show_format) meta.push(scene.formatLabel);
  if (style.result.show_series && series.score_p1 !== null && series.score_p2 !== null) {
    meta.push(`SERIES ${series.score_p1}–${series.score_p2}`);
  }
  if (style.result.show_final_score) meta.push(`TURN ${scene.turn}`);
  return {
    kind: 'result',
    progress,
    opacity,
    eyebrow: style.show_koala_branding ? 'KOALABATTLE // FINAL' : null,
    headline: style.result.show_winner
      ? scene.winnerName
        ? `${scene.winnerName} WINS`
        : 'DRAW'
      : 'MATCH COMPLETE',
    subtitle: meta.join('   ·   ') || null,
    badge: scene.winnerName ? 'K.O.' : null,
    showLogos: style.result.show_logos
  };
}

function isVisibleBattleEffect(kind: string): boolean {
  return /^(move_|damage$|healing$|critical_hit$|status_|super_effective$|resisted$|immune$|weather_|terrain_|side_condition_|pokemon_switched$|pokemon_fainted$|battle_finished$)/.test(kind);
}

function eventCondition(frame: ProductionFrameState): string | null {
  const value = frame.event?.payload.status ?? frame.event?.payload.condition;
  return typeof value === 'string' ? value.toLowerCase() : null;
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
  if (category === 'special') return 'beam';
  if (type === 'electric' || type === 'psychic' || type === 'dragon') return 'beam';
  if (type === 'ground' || type === 'flying' || type === 'ice') return 'pulse';
  return 'projectile';
}

function normalizeMoveId(value: string | null): string | null {
  if (!value) return null;
  const normalized = value.toLowerCase().replace(/[^a-z0-9]/g, '');
  return normalized || null;
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
