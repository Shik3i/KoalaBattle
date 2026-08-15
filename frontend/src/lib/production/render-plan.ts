import type { ProductionCue, ProductionTimeline } from '../types.ts';

export type RenderReason = 'initial' | 'animated' | 'cue-boundary' | 'static-hold';

export interface RenderPlanFrame {
  index: number;
  logicalTimeMs: number;
  render: boolean;
  animated: boolean;
  reason: RenderReason;
}

export interface RenderPlan {
  version: '1.0';
  startMs: number;
  endMs: number;
  fps: number;
  outputFrames: number;
  plannedUniqueRenders: number;
  plannedStaticHeldFrames: number;
  plannedAnimatedFrames: number;
  frames: RenderPlanFrame[];
}

const CONTINUOUS_VISUALS = new Set([
  'move_used', 'move_missed', 'damage', 'healing', 'critical_hit', 'status_applied',
  'status_removed', 'super_effective', 'resisted', 'immune', 'weather_changed',
  'terrain_started', 'terrain_ended', 'side_condition_started', 'side_condition_ended',
  'pokemon_switched', 'pokemon_fainted', 'battle_finished'
]);

export function createRenderPlan(
  production: ProductionTimeline,
  startMs: number,
  endMs: number,
  fps: number
): RenderPlan {
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    throw new Error('render plan requires a non-empty finite time range');
  }
  if (!Number.isInteger(fps) || fps <= 0 || fps > 60) {
    throw new Error('render plan fps must be an integer between 1 and 60');
  }
  const outputFrames = Math.ceil((endMs - startMs) * fps / 1000);
  const relevant = production.cues.filter(
    (cue) => cue.start_ms < endMs && cue.start_ms + cue.duration_ms > startMs
  );
  const boundaries = new Set<number>([0]);
  for (const cue of relevant) {
    addBoundary(boundaries, cue.start_ms, startMs, fps, outputFrames);
    addBoundary(boundaries, cue.start_ms + cue.duration_ms, startMs, fps, outputFrames);
    if (cue.track === 'captions') {
      addBoundary(boundaries, cue.start_ms + Math.min(180, cue.duration_ms / 3), startMs, fps, outputFrames);
      addBoundary(boundaries, cue.start_ms + Math.max(0, cue.duration_ms - 180), startMs, fps, outputFrames);
    }
  }
  const frames: RenderPlanFrame[] = [];
  let unique = 0;
  let animatedFrames = 0;
  for (let index = 0; index < outputFrames; index += 1) {
    const logicalTimeMs = startMs + index * 1000 / fps;
    const animated = relevant.some((cue) => cueAnimatedAt(cue, logicalTimeMs));
    const boundary = boundaries.has(index);
    const render = index === 0 || animated || boundary;
    if (render) unique += 1;
    if (animated) animatedFrames += 1;
    frames.push({
      index,
      logicalTimeMs,
      render,
      animated,
      reason: index === 0 ? 'initial' : animated ? 'animated' : boundary ? 'cue-boundary' : 'static-hold'
    });
  }
  return {
    version: '1.0',
    startMs,
    endMs,
    fps,
    outputFrames,
    plannedUniqueRenders: unique,
    plannedStaticHeldFrames: outputFrames - unique,
    plannedAnimatedFrames: animatedFrames,
    frames
  };
}

function cueAnimatedAt(cue: ProductionCue, timeMs: number): boolean {
  const elapsed = timeMs - cue.start_ms;
  if (elapsed < 0 || elapsed >= cue.duration_ms) return false;
  if (cue.track === 'visual') return CONTINUOUS_VISUALS.has(cue.kind);
  if (cue.track === 'captions') return elapsed < 180 || elapsed >= cue.duration_ms - 180;
  if (cue.track === 'director') return cue.kind === 'match-intro' || cue.kind === 'result';
  return false;
}

function addBoundary(
  boundaries: Set<number>,
  timeMs: number,
  startMs: number,
  fps: number,
  outputFrames: number
) {
  const frame = Math.ceil((timeMs - startMs) * fps / 1000);
  if (frame >= 0 && frame < outputFrames) boundaries.add(frame);
}
