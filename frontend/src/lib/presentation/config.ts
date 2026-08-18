import type { Side } from '../types.ts';
import {
  defaultRendererConfig,
  HUD_SCALE_RANGE,
  type CommentaryMode,
  type EffectQuality,
  type PresentationPreset,
  type RendererConfig,
  type RendererLayout,
  type RendererTheme
} from './types.ts';

const STORAGE_KEY = 'koalabattle-renderer-config-v1';
const layouts: RendererLayout[] = ['standard-landscape', 'standard-vertical', 'overlay-landscape'];
const themes: RendererTheme[] = ['pokemon-route', 'pokemon-stadium', 'koala-dark', 'koala-light'];
const presets: PresentationPreset[] = ['live', 'video', 'fast', 'instant'];
const commentaryModes: CommentaryMode[] = ['latest', 'last-3', 'full', 'hidden'];
const effectQualities: EffectQuality[] = ['off', 'low', 'standard', 'high'];

export function loadRendererConfig(): RendererConfig {
  if (typeof localStorage === 'undefined') return defaultRendererConfig();
  try {
    return sanitizeRendererConfig(JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'));
  } catch {
    return defaultRendererConfig();
  }
}

export function saveRendererConfig(config: RendererConfig): void {
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

export function sanitizeRendererConfig(value: unknown): RendererConfig {
  const candidate = typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
  const speed = candidate.playbackSpeed;
  const defaults = defaultRendererConfig();
  return defaultRendererConfig({
    layout: includes(layouts, candidate.layout) ? candidate.layout : defaults.layout,
    theme: includes(themes, candidate.theme) ? candidate.theme : defaults.theme,
    preset: includes(presets, candidate.preset) ? candidate.preset : defaults.preset,
    commentaryMode: includes(commentaryModes, candidate.commentaryMode)
      ? candidate.commentaryMode
      : defaults.commentaryMode,
    playbackSpeed:
      speed === 0.5 || speed === 1 || speed === 2 || speed === 4 || speed === 'instant'
        ? speed
        : defaults.playbackSpeed,
    showBattleLog: booleanOrDefault(candidate.showBattleLog, defaults.showBattleLog),
    showTurn: booleanOrDefault(candidate.showTurn, defaults.showTurn),
    showAgentState: booleanOrDefault(candidate.showAgentState, defaults.showAgentState),
    transparentBackground: booleanOrDefault(
      candidate.transparentBackground,
      defaults.transparentBackground
    ),
    animatedSprites: booleanOrDefault(candidate.animatedSprites, defaults.animatedSprites),
    effects: includes(effectQualities, candidate.effects) ? candidate.effects : defaults.effects,
    reducedMotion: booleanOrDefault(candidate.reducedMotion, defaults.reducedMotion),
    showDamageNumbers: booleanOrDefault(candidate.showDamageNumbers, defaults.showDamageNumbers),
    nearSide:
      candidate.nearSide === 'p2' ? 'p2' : candidate.nearSide === 'p1' ? 'p1' : defaults.nearSide,
    showTeamRoster: booleanOrDefault(candidate.showTeamRoster, defaults.showTeamRoster),
    hudScale: clampScale(candidate.hudScale, defaults.hudScale)
  });
}

function clampScale(value: unknown, fallback: number): number {
  const scale = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(scale)) return fallback;
  return Math.min(HUD_SCALE_RANGE.max, Math.max(HUD_SCALE_RANGE.min, Math.round(scale * 100) / 100));
}

export function configFromQuery(search: URLSearchParams): RendererConfig {
  const base = loadRendererConfig();
  const transparent = search.get('transparent');
  const reducedMotion = search.get('reducedMotion');
  const damageNumbers = search.get('damageNumbers');
  return sanitizeRendererConfig({
    ...base,
    layout: search.get('layout') || base.layout,
    theme: search.get('theme') || base.theme,
    preset: search.get('preset') || base.preset,
    commentaryMode: search.get('commentary') || base.commentaryMode,
    effects: search.get('effects') || base.effects,
    nearSide: (search.get('near') as Side | null) || base.nearSide,
    transparentBackground:
      transparent === null ? base.transparentBackground : transparent === '1' || transparent === 'true',
    showBattleLog: search.get('log') === null ? base.showBattleLog : search.get('log') !== '0',
    reducedMotion:
      reducedMotion === null ? base.reducedMotion : reducedMotion === '1' || reducedMotion === 'true',
    showDamageNumbers:
      damageNumbers === null ? base.showDamageNumbers : damageNumbers !== '0' && damageNumbers !== 'false',
    showTeamRoster: search.get('roster') === null ? base.showTeamRoster : search.get('roster') !== '0',
    hudScale: search.get('hudScale') === null ? base.hudScale : Number(search.get('hudScale'))
  });
}

function booleanOrDefault(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function includes<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === 'string' && values.includes(value as T);
}
