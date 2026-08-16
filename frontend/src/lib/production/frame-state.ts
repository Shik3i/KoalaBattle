import { createPresentationState, reducePresentation } from '../presentation/reducer.ts';
import type { BattlePresentationState } from '../presentation/types.ts';
import type { BattleEvent, MatchArchive, ProductionCue, ProductionTimeline } from '../types.ts';

export interface ProductionFrameState {
  timeMs: number;
  presentation: BattlePresentationState;
  priorPresentation: BattlePresentationState | null;
  commentary: ProductionCue | null;
  caption: ProductionCue | null;
  director: ProductionCue | null;
  visual: ProductionCue | null;
  event: BattleEvent | null;
  visualElapsedMs: number;
  visualProgress: number;
}

interface VisualSnapshot {
  cue: ProductionCue;
  event: BattleEvent;
  presentation: BattlePresentationState;
  priorPresentation: BattlePresentationState;
}

export interface ProductionFrameRenderer {
  renderAt(requestedTimeMs: number): ProductionFrameState;
}

export function createProductionFrameRenderer(
  match: MatchArchive,
  production: ProductionTimeline
): ProductionFrameRenderer {
  const durationMs = production.duration_ms || Math.max(
    0,
    ...production.cues.map((cue) => cue.start_ms + cue.duration_ms)
  );
  const eventBySequence = new Map(match.events.map((event) => [event.sequence, event]));
  const visualCues = production.cues
    .filter((cue) => cue.track === 'visual' && cue.event_sequence !== null)
    .sort((left, right) => left.start_ms - right.start_ms || left.id.localeCompare(right.id));
  const trackCues = new Map<ProductionCue['track'], ProductionCue[]>();
  for (const cue of production.cues) {
    const cues = trackCues.get(cue.track) || [];
    cues.push(cue);
    trackCues.set(cue.track, cues);
  }
  for (const cues of trackCues.values()) {
    cues.sort((left, right) => left.start_ms - right.start_ms || left.id.localeCompare(right.id));
  }

  let state = createPresentationState(match);
  const snapshots: VisualSnapshot[] = [];
  for (const cue of visualCues) {
    const event = eventBySequence.get(cue.event_sequence as number);
    if (!event) continue;
    const priorPresentation = state;
    state = reducePresentation(state, event);
    snapshots.push({ cue, event, presentation: state, priorPresentation });
  }
  const initial = createPresentationState(match);

  return {
    renderAt(requestedTimeMs: number): ProductionFrameState {
      const timeMs = Math.max(0, Math.min(durationMs, Math.trunc(requestedTimeMs)));
      const snapshot = latestSnapshot(snapshots, timeMs);
      const visual = snapshot?.cue || null;
      const commentary = active(trackCues.get('commentary') || [], timeMs);
      const caption = active(trackCues.get('captions') || [], timeMs);
      const director = activeOrLatest(trackCues.get('director') || [], timeMs);
      const visualElapsedMs = visual ? Math.max(0, timeMs - visual.start_ms) : 0;
      return {
        timeMs,
        presentation: snapshot?.presentation || initial,
        priorPresentation: snapshot?.priorPresentation || null,
        commentary,
        caption,
        director,
        visual,
        event: snapshot?.event || null,
        visualElapsedMs,
        visualProgress: visual
          ? Math.min(1, visualElapsedMs / Math.max(1, visual.duration_ms))
          : 0
      };
    }
  };
}

export function renderAt(
  match: MatchArchive,
  production: ProductionTimeline,
  requestedTimeMs: number
): ProductionFrameState {
  return createProductionFrameRenderer(match, production).renderAt(requestedTimeMs);
}

function latestSnapshot(snapshots: VisualSnapshot[], timeMs: number): VisualSnapshot | null {
  let low = 0;
  let high = snapshots.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (snapshots[middle].cue.start_ms <= timeMs) low = middle + 1;
    else high = middle;
  }
  return low === 0 ? null : snapshots[low - 1];
}

function active(cues: ProductionCue[], timeMs: number): ProductionCue | null {
  const latest = latestCue(cues, timeMs);
  return latest && latest.start_ms + latest.duration_ms > timeMs ? latest : null;
}

function activeOrLatest(cues: ProductionCue[], timeMs: number): ProductionCue | null {
  return active(cues, timeMs) || latestCue(cues, timeMs);
}

function latestCue(cues: ProductionCue[], timeMs: number): ProductionCue | null {
  let low = 0;
  let high = cues.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (cues[middle].start_ms <= timeMs) low = middle + 1;
    else high = middle;
  }
  return low === 0 ? null : cues[low - 1];
}
