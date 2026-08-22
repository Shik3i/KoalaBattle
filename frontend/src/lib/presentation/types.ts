import type { BattleEvent, BattleState, MatchArchive, PokemonState, Side } from '../types.ts';

export const RENDERER_VERSION = '2.1.0';
export const RENDERER_CONFIG_VERSION = '2.0';

export type RendererLayout =
  | 'standard-landscape'
  | 'standard-vertical'
  | 'overlay-landscape';
export type RendererTheme = 'pokemon-route' | 'pokemon-stadium' | 'koala-dark' | 'koala-light';
export type PresentationPreset = 'live' | 'video' | 'fast' | 'instant';
export type PlaybackSpeed = 0.5 | 1 | 2 | 4 | 'instant';
export type CommentaryMode = 'latest' | 'last-3' | 'full' | 'hidden';
export type AgentPresentationStatus =
  | 'waiting'
  | 'thinking'
  | 'decided'
  | 'executing'
  | 'finished';

/**
 * Lifecycle of one player's public commentary. The primary panel only ever shows the
 * commentary for the action currently being decided or executed; once the turn resolves it
 * clears, and the text survives in `commentary` history and in the decision log.
 */
export type CommentaryPhase = 'waiting' | 'thinking' | 'decided' | 'executing' | 'resolved';

/** Whether the headline action is still playing out or has already been resolved. */
export type ActionPhase = 'executing' | 'resolved';
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
  | 'super-effective'
  | 'resisted'
  | 'immune'
  | 'weather'
  | 'terrain'
  | 'barrier'
  | 'faint'
  | 'victory';

export type PokemonType =
  | 'normal' | 'fire' | 'water' | 'electric' | 'grass' | 'ice'
  | 'fighting' | 'poison' | 'ground' | 'flying' | 'psychic' | 'bug'
  | 'rock' | 'ghost' | 'dragon' | 'dark' | 'steel' | 'fairy';
export type MoveVisualArchetype = 'physical' | 'special' | 'status';
export type EffectQuality = 'off' | 'low' | 'standard' | 'high';
export type MoveEffectSkin = 'broadcast' | 'retro' | 'procedural';

export interface MoveVisualProfile {
  type: PokemonType;
  archetype: MoveVisualArchetype;
  moveName: string;
  seed: number;
}

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
  effects: EffectQuality;
  moveEffectSkin: MoveEffectSkin;
  reducedMotion: boolean;
  showDamageNumbers: boolean;
  nearSide: Side;
  /** The six-slot squad row under each player's name. */
  showTeamRoster: boolean;
  /** Multiplies every HUD text and bar size, for capture at other distances. */
  hudScale: number;
}

export interface CommentaryPresentationState {
  sequence: number;
  turn: number;
  side: Side;
  action: string;
  actionName: string;
  commentary: string;
  banter?: string | null;
  latencyMs: number | null;
}

export interface ContextMetricsPresentation {
  renderedCharacters: number;
  estimatedTokens: number;
}

export interface PlayerPresentationState {
  side: Side;
  displayName: string;
  providerLabel: string;
  agentStatus: AgentPresentationStatus;
  motion: PokemonMotion;
  /** Full history, kept for the decision log and the control UI. */
  commentary: CommentaryPresentationState[];
  /** Only the commentary that belongs to the action in flight; null once it resolves. */
  currentCommentary: CommentaryPresentationState | null;
  commentaryPhase: CommentaryPhase;
  /** Safe public commentary preview from providers that support token streaming. */
  streamPreview: string | null;
  /** Prompt size only; never the private battle prompt itself. */
  contextMetrics: ContextMetricsPresentation | null;
}

/** Transient HP change shown next to the Pokemon it happened to. */
export interface ImpactPresentationState {
  side: Side;
  /** Signed percentage points of maximum HP. Negative for damage, positive for healing. */
  value: number;
  sequence: number;
  kind: 'damage' | 'healing';
}

export interface SpectatorLogEntry {
  sequence: number;
  turn: number;
  kind: BattleEvent['event_type'];
  text: string;
  emphasis: 'normal' | 'positive' | 'negative' | 'critical';
}

export interface ActionFeedEntry {
  sequence: number;
  updatedSequence: number;
  turn: number;
  kind: 'move' | 'switch' | 'faint' | 'status' | 'ability' | 'item' | 'stat' | 'field' | 'residual' | 'result';
  headline: string;
  detailParts: string[];
  emphasis: 'normal' | 'positive' | 'negative' | 'critical' | 'field';
  actorSide: Side | null;
  targetSide: Side | null;
}

/** One authoritative switch event rendered as a strict outgoing-then-incoming sequence. */
export interface SwitchTransitionPresentationState {
  sequence: number;
  side: Side;
  forced: boolean;
  outgoing: PokemonState | null;
  incoming: PokemonState;
}

/**
 * Per-Pokemon contribution accumulated while the battle plays, so the end card can show a
 * real recap instead of only a winner name. Damage is in percentage points of the target's
 * maximum HP, which is the only cross-Pokemon comparable unit the protocol gives us.
 */
export interface RecapEntry {
  side: Side;
  species: string;
  name: string;
  damageDealt: number;
  damageTaken: number;
  knockouts: number;
  fainted: boolean;
  entered: boolean;
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
  currentMoveProfile: MoveVisualProfile | null;
  currentMoveSide: Side | null;
  currentMovePhase: ActionPhase;
  effect: BattleEffect;
  effectSide: Side | null;
  effectValue: number | null;
  /** Latest HP change per side, cleared when the turn resolves. */
  impacts: Record<Side, ImpactPresentationState | null>;
  /** Canonical spectator messages; every replay seek rebuilds this from event zero. */
  actionFeed: ActionFeedEntry[];
  /** Transient only for the currently displayed event; never resurrects a fainted sprite. */
  switchTransitions: Record<Side, SwitchTransitionPresentationState | null>;
  log: SpectatorLogEntry[];
  winner: Side | null;
  winnerName: string | null;
  finished: boolean;
  /** Ordered by team slot within each side; only Pokemon that entered the battle count. */
  recap: RecapEntry[];
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
  theme: 'pokemon-route',
  preset: 'live',
  playbackSpeed: 1,
  commentaryMode: 'latest',
  showBattleLog: true,
  showTurn: true,
  showAgentState: true,
  transparentBackground: false,
  animatedSprites: true,
  effects: 'standard',
  moveEffectSkin: 'broadcast',
  reducedMotion: false,
  showDamageNumbers: true,
  nearSide: 'p1',
  showTeamRoster: true,
  hudScale: 1,
  ...overrides
});

/** The renderer clamps this; the UI and the query parser share the same bounds. */
export const HUD_SCALE_RANGE = { min: 0.8, max: 1.6, step: 0.05 } as const;

export type PresentationMatch = Pick<MatchArchive, 'id' | 'config' | 'winner'>;
