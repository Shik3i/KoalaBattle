import type { ProductionTimeline } from '../types.ts';

export type PreviewMarkId =
  | 'intro'
  | 'neutral'
  | 'commentary'
  | 'attack'
  | 'damage'
  | 'switch'
  | 'victory';

export interface PreviewMark {
  id: PreviewMarkId;
  label: string;
  timeMs: number;
}

const VISUAL_MARKS: { id: PreviewMarkId; label: string; kinds: string[] }[] = [
  { id: 'attack', label: 'Attack', kinds: ['move_used'] },
  { id: 'damage', label: 'Damage', kinds: ['damage', 'critical_hit', 'super_effective'] },
  { id: 'switch', label: 'Switch', kinds: ['pokemon_switched'] }
];

/**
 * Jump points for judging a theme without scrubbing the whole match.
 *
 * A shortcut only appears when the production actually contains that moment. Fabricating
 * an "attack" preview for a match that has none would mean inventing battle events, which
 * this system never does.
 */
export function previewMarks(production: ProductionTimeline): PreviewMark[] {
  const marks: PreviewMark[] = [];
  const cue = (predicate: (kind: string, track: string) => boolean) =>
    production.cues.find((item) => predicate(item.kind, item.track));

  const intro = cue((kind, track) => track === 'director' && kind === 'match-intro');
  if (intro) marks.push({ id: 'intro', label: 'Intro', timeMs: intro.start_ms + Math.round(intro.duration_ms / 2) });

  const firstVisual = production.cues.find((item) => item.track === 'visual');
  if (firstVisual) {
    // A beat just after the first event, before any callout, shows the resting composition.
    marks.push({ id: 'neutral', label: 'Neutral', timeMs: firstVisual.start_ms + firstVisual.duration_ms + 1 });
  }

  const commentary = cue((_, track) => track === 'commentary');
  if (commentary) {
    marks.push({
      id: 'commentary',
      label: 'Commentary',
      timeMs: commentary.start_ms + Math.min(600, Math.round(commentary.duration_ms / 2))
    });
  }

  for (const entry of VISUAL_MARKS) {
    const found = production.cues.find(
      (item) => item.track === 'visual' && entry.kinds.includes(item.kind)
    );
    if (found) {
      marks.push({
        id: entry.id,
        label: entry.label,
        // Land inside the impact window rather than on the cue start, where nothing shows yet.
        timeMs: found.start_ms + Math.round(found.duration_ms * 0.82)
      });
    }
  }

  const result = cue((kind, track) => track === 'director' && kind === 'result');
  if (result) {
    marks.push({ id: 'victory', label: 'Victory', timeMs: result.start_ms + Math.round(result.duration_ms / 2) });
  }
  return marks.filter((mark) => mark.timeMs >= 0 && mark.timeMs <= Math.max(1, production.duration_ms));
}
