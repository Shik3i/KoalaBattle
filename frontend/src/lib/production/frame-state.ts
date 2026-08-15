import { createPresentationState, reduceEvents } from '../presentation/reducer.ts';
import type { BattlePresentationState } from '../presentation/types.ts';
import type { MatchArchive, ProductionCue, ProductionTimeline } from '../types.ts';

export interface ProductionFrameState {
  timeMs: number;
  presentation: BattlePresentationState;
  caption: ProductionCue | null;
  director: ProductionCue | null;
  visual: ProductionCue | null;
  visualElapsedMs: number;
  visualProgress: number;
}

export function renderAt(
  match: MatchArchive,
  production: ProductionTimeline,
  requestedTimeMs: number
): ProductionFrameState {
  const timeMs = Math.max(0, Math.min(production.duration_ms, Math.trunc(requestedTimeMs)));
  const startedVisuals = production.cues.filter(
    (cue) => cue.track === 'visual' && cue.start_ms <= timeMs && cue.event_sequence !== null
  );
  const visibleSequences = new Set(startedVisuals.map((cue) => cue.event_sequence));
  const visibleEvents = match.events.filter((event) => visibleSequences.has(event.sequence));
  const presentation = reduceEvents(createPresentationState(match), visibleEvents);
  const visual = activeOrLatest(production.cues, 'visual', timeMs);
  const caption = active(production.cues, 'captions', timeMs);
  const director = activeOrLatest(production.cues, 'director', timeMs);
  const visualElapsedMs = visual ? Math.max(0, timeMs - visual.start_ms) : 0;
  return {
    timeMs,
    presentation,
    caption,
    director,
    visual,
    visualElapsedMs,
    visualProgress: visual ? Math.min(1, visualElapsedMs / Math.max(1, visual.duration_ms)) : 0
  };
}

function active(cues: ProductionCue[], track: ProductionCue['track'], timeMs: number) {
  return (
    cues.find(
      (cue) =>
        cue.track === track && cue.start_ms <= timeMs && cue.start_ms + cue.duration_ms > timeMs
    ) || null
  );
}

function activeOrLatest(cues: ProductionCue[], track: ProductionCue['track'], timeMs: number) {
  const matches = cues.filter((cue) => cue.track === track && cue.start_ms <= timeMs);
  return active(cues, track, timeMs) || matches.at(-1) || null;
}
