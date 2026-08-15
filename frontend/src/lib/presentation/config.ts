import type { Side } from '../types.ts';
import {
  defaultRendererConfig,
  type CommentaryMode,
  type PresentationPreset,
  type RendererConfig,
  type RendererLayout,
  type RendererTheme
} from './types.ts';

const STORAGE_KEY = 'koalabattle-renderer-config-v1';
const layouts: RendererLayout[] = ['standard-landscape', 'standard-vertical', 'overlay-landscape'];
const themes: RendererTheme[] = ['koala-dark', 'koala-light'];
const presets: PresentationPreset[] = ['live', 'video', 'fast', 'instant'];
const commentaryModes: CommentaryMode[] = ['latest', 'last-3', 'full', 'hidden'];

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
    nearSide:
      candidate.nearSide === 'p2' ? 'p2' : candidate.nearSide === 'p1' ? 'p1' : defaults.nearSide
  });
}

export function configFromQuery(search: URLSearchParams): RendererConfig {
  const base = loadRendererConfig();
  const transparent = search.get('transparent');
  return sanitizeRendererConfig({
    ...base,
    layout: search.get('layout') || base.layout,
    theme: search.get('theme') || base.theme,
    preset: search.get('preset') || base.preset,
    commentaryMode: search.get('commentary') || base.commentaryMode,
    nearSide: (search.get('near') as Side | null) || base.nearSide,
    transparentBackground:
      transparent === null ? base.transparentBackground : transparent === '1' || transparent === 'true',
    showBattleLog: search.get('log') === null ? base.showBattleLog : search.get('log') !== '0'
  });
}

function booleanOrDefault(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function includes<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === 'string' && values.includes(value as T);
}
