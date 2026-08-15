import type { ProductionCue, ProductionTimeline } from '../types.ts';

export class ProductionScheduler {
  private timeline: ProductionTimeline | null = null;
  private cursorMs = 0;
  private emitted = new Set<string>();

  load(timeline: ProductionTimeline): void {
    this.timeline = timeline;
    this.seek(0);
  }

  seek(milliseconds: number): void {
    this.cursorMs = Math.max(0, Math.trunc(milliseconds));
    this.emitted = new Set(
      (this.timeline?.cues || [])
        .filter((cue) => cue.start_ms <= this.cursorMs)
        .map((cue) => cue.id)
    );
  }

  advance(milliseconds: number): ProductionCue[] {
    this.cursorMs = Math.max(0, this.cursorMs + Math.max(0, milliseconds));
    const due = (this.timeline?.cues || []).filter(
      (cue) => cue.start_ms <= this.cursorMs && !this.emitted.has(cue.id)
    );
    due.forEach((cue) => this.emitted.add(cue.id));
    return due;
  }

  time(): number {
    return this.cursorMs;
  }

  duration(): number {
    return Math.max(0, ...(this.timeline?.cues || []).map((cue) => cue.start_ms + cue.duration_ms));
  }

  timeForEvent(sequence: number): number {
    const start = this.timeline?.cues.find((cue) => cue.event_sequence === sequence)?.start_ms || 0;
    return Math.max(0, start - 1);
  }
}
