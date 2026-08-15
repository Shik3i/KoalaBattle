import type { BattleEvent, BattleState, MatchArchive, Side } from '../types.ts';

export const RENDERER_VERSION = '2.0.0';
export const RENDERER_CONFIG_VERSION = '1.0';

export type RendererLayout =
  | 'standard-landscape'
  | 'standard-vertical'
  | 'overlay-landscape';
export type RendererTheme = 'koala-dark' | 'koala-light';
export type PresentationPreset = 'live' | 'video' | 'fast' | 'instant';
export type PlaybackSpeed = 0.5 | 1 | 2 | 4 | 'instant';
export type CommentaryMode = 'latest' | 'last-3' | 'full' | 'hidden';
export type AgentPresentationStatus =
  | 'waiting'
  | 'thinking'
  | 'decided'
  | 'executing'
  | 'finished';
export type PokemonMotion =
  | 'idle'
  | 'attacking'
  | 'taking-damage'
  | 'switching-in'
  | 'switching-out'
  | 'fainting'
  | 'status-flash';
export type BattleEffect =
  | 'none'
  | 'impact'
  | 'critical-hit'
  | 'miss'
  | 'healing'
  | 'status'
  | 'faint'
  | 'victory';

export interface RendererConfig {
  version: typeof RENDERER_CONFIG_VERSION;
  layout: RendererLayout;
  theme: RendererTheme;
  preset: PresentationPreset;
  playbackSpeed: PlaybackSpeed;
  commentaryMode: CommentaryMode;
  showBattleLog: boolean;
  showTurn: boolean;
  showAgentState: boolean;
  transparentBackground: boolean;
  animatedSprites: boolean;
  nearSide: Side;
}

export interface CommentaryPresentationState {
  sequence: number;
  turn: number;
  side: Side;
  action: string;
  actionName: string;
  commentary: string;
  latencyMs: number | null;
}

export interface PlayerPresentationState {
  side: Side;
  displayName: string;
  providerLabel: string;
  agentStatus: AgentPresentationStatus;
  motion: PokemonMotion;
  commentary: CommentaryPresentationState[];
}

export interface SpectatorLogEntry {
  sequence: number;
  turn: number;
  kind: BattleEvent['event_type'];
  text: string;
  emphasis: 'normal' | 'positive' | 'negative' | 'critical';
}

export interface BattlePresentationState {
  version: typeof RENDERER_VERSION;
  matchId: string;
  format: string;
  eventIndex: number;
  eventSequence: number;
  battle: BattleState | null;
  players: Record<Side, PlayerPresentationState>;
  currentMove: string | null;
  effect: BattleEffect;
  effectSide: Side | null;
  log: SpectatorLogEntry[];
  winner: Side | null;
  winnerName: string | null;
  finished: boolean;
}

export interface TimelineSnapshot {
  state: BattlePresentationState;
  index: number;
  eventCount: number;
  playing: boolean;
  speed: PlaybackSpeed;
  currentTurn: number;
}

export const defaultRendererConfig = (
  overrides: Partial<RendererConfig> = {}
): RendererConfig => ({
  version: RENDERER_CONFIG_VERSION,
  layout: 'standard-landscape',
  theme: 'koala-dark',
  preset: 'live',
  playbackSpeed: 1,
  commentaryMode: 'latest',
  showBattleLog: true,
  showTurn: true,
  showAgentState: true,
  transparentBackground: false,
  animatedSprites: true,
  nearSide: 'p1',
  ...overrides
});

export type PresentationMatch = Pick<MatchArchive, 'id' | 'config' | 'winner'>;
