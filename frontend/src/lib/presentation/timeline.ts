import type { BattleEvent } from '../types.ts';
import { createPresentationState, reduceEvents, reducePresentation } from './reducer.ts';
import type {
  BattlePresentationState,
  PlaybackSpeed,
  PresentationMatch,
  PresentationPreset,
  TimelineSnapshot
} from './types.ts';

export interface TimelineClock {
  set(callback: () => void, delayMs: number): unknown;
  clear(handle: unknown): void;
}

const browserClock: TimelineClock = {
  set: (callback, delayMs) => setTimeout(callback, delayMs),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>)
};

const INTRO_READABILITY_HOLD_MS = 2_000;
const RESULT_READABILITY_HOLD_MS = 2_000;

const EVENT_DURATIONS: Record<string, number> = {
  move_used: 800,
  move_missed: 620,
  damage: 650,
  healing: 650,
  critical_hit: 700,
  status_applied: 620,
  status_removed: 520,
  ability_activated: 520,
  item_activated: 520,
  item_consumed: 520,
  effect_activated: 460,
  stat_changed: 500,
  stat_reset: 460,
  pokemon_switched: 900,
  pokemon_fainted: 1100,
  agent_decision: 40,
  agent_progress: 20,
  turn_started: 160,
  state_snapshot: 20,
  battle_finished: 240
};

const MIN_VISIBLE_DURATIONS: Record<string, number> = {
  move_used: 420,
  move_missed: 340,
  damage: 320,
  healing: 320,
  critical_hit: 300,
  status_applied: 280,
  status_removed: 240,
  ability_activated: 260,
  item_activated: 260,
  item_consumed: 260,
  effect_activated: 240,
  stat_changed: 240,
  stat_reset: 220,
  pokemon_switched: 500,
  pokemon_fainted: 650
};

const PRESET_MULTIPLIERS: Record<PresentationPreset, number> = {
  live: 1,
  video: 1.35,
  fast: 0.35,
  instant: 0
};

export class PresentationTimeline {
  private readonly match: PresentationMatch;
  private readonly clock: TimelineClock;
  private readonly follow: boolean;
  private events: BattleEvent[];
  private state: BattlePresentationState;
  private index = 0;
  private playing = false;
  private speed: PlaybackSpeed = 1;
  private preset: PresentationPreset = 'live';
  private timer: unknown = null;
  private introHoldComplete = false;
  private resultHoldComplete = false;
  private readonly listeners = new Set<(snapshot: TimelineSnapshot) => void>();

  constructor(
    match: PresentationMatch,
    events: readonly BattleEvent[] = [],
    clock: TimelineClock = browserClock,
    follow = false
  ) {
    this.match = match;
    this.clock = clock;
    this.follow = follow;
    // Token previews are a live-stream affordance. Keep them out of replay/video timing so
    // a long model response does not turn into dozens of artificial historical frames.
    this.events = follow ? [...events] : events.filter((event) => event.event_type !== 'agent_progress');
    this.state = createPresentationState(match);
  }

  subscribe(listener: (snapshot: TimelineSnapshot) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  snapshot(): TimelineSnapshot {
    return {
      state: this.state,
      index: this.index,
      eventCount: this.events.length,
      playing: this.playing,
      speed: this.speed,
      currentTurn: this.state.battle?.turn ?? this.events[Math.max(0, this.index - 1)]?.turn ?? 0
    };
  }

  replace(events: readonly BattleEvent[], index = 0): void {
    this.pause();
    this.events = this.follow
      ? [...events]
      : events.filter((event) => event.event_type !== 'agent_progress');
    this.seek(index);
  }

  append(event: BattleEvent): void {
    if (this.events.some((item) => item.sequence === event.sequence)) return;
    const wasAtEnd = this.index === this.events.length;
    this.events.push(event);
    this.events.sort((a, b) => a.sequence - b.sequence);
    // Showdown may append final agent lifecycle records after battle_finished. Consume those
    // immediately without reopening or invalidating the result hold; otherwise eventCount
    // moves ahead of index and the Draft return waits forever.
    if (wasAtEnd && this.state.finished) {
      while (this.index < this.events.length) {
        this.state = reducePresentation(this.state, this.events[this.index]);
        this.index += 1;
      }
      this.emit();
      return;
    }
    this.emit();
    if (this.playing && this.timer === null) this.schedule();
  }

  play(): void {
    if (!this.follow && this.index >= this.events.length) this.restart();
    this.playing = true;
    this.emit();
    this.schedule();
  }

  pause(): void {
    this.playing = false;
    this.clearTimer();
    this.emit();
  }

  toggle(): void {
    if (this.playing) this.pause();
    else this.play();
  }

  restart(): void {
    this.clearTimer();
    this.playing = false;
    this.index = 0;
    this.state = createPresentationState(this.match);
    this.introHoldComplete = false;
    this.resultHoldComplete = false;
    this.emit();
  }

  seek(index: number): void {
    this.clearTimer();
    this.index = Math.max(0, Math.min(Math.trunc(index), this.events.length));
    this.state = reduceEvents(createPresentationState(this.match), this.events, this.index);
    this.introHoldComplete = this.index > 0;
    this.resultHoldComplete = this.index >= this.events.length && this.state.finished;
    this.emit();
  }

  nextEvent(): void {
    if (this.index >= this.events.length) {
      if (!this.follow) this.playing = false;
      this.emit();
      return;
    }
    this.state = reducePresentation(this.state, this.events[this.index]);
    this.index += 1;
    this.emit();
  }

  previousEvent(): void {
    this.seek(this.index - 1);
  }

  nextTurn(): void {
    if (this.index >= this.events.length) return;
    const turn = this.events[this.index].turn;
    let target = this.index + 1;
    while (target < this.events.length && this.events[target].turn <= turn) target += 1;
    this.seek(target);
  }

  previousTurn(): void {
    if (this.index === 0) return;
    const currentTurn = this.events[Math.max(0, this.index - 1)].turn;
    let targetTurn = -1;
    for (let cursor = this.index - 1; cursor >= 0; cursor -= 1) {
      if (this.events[cursor].turn < currentTurn) {
        targetTurn = this.events[cursor].turn;
        break;
      }
    }
    if (targetTurn < 0) {
      this.seek(0);
      return;
    }
    let target = 0;
    while (target < this.events.length && this.events[target].turn < targetTurn) target += 1;
    this.seek(target);
  }

  setSpeed(speed: PlaybackSpeed): void {
    this.speed = speed;
    this.clearTimer();
    this.emit();
    if (this.playing) this.schedule();
  }

  setPreset(preset: PresentationPreset): void {
    this.preset = preset;
    this.clearTimer();
    this.emit();
    if (this.playing) this.schedule();
  }

  destroy(): void {
    this.pause();
    this.listeners.clear();
  }

  private schedule(): void {
    if (!this.playing || this.timer !== null) return;
    if (this.index === 0 && this.events.length > 0 && !this.introHoldComplete) {
      this.introHoldComplete = true;
      this.timer = this.clock.set(() => {
        this.timer = null;
        this.schedule();
      }, INTRO_READABILITY_HOLD_MS);
      return;
    }
    if (this.index >= this.events.length) {
      if (this.state.finished) {
        if (!this.resultHoldComplete) {
          this.resultHoldComplete = true;
          this.timer = this.clock.set(() => {
            this.timer = null;
            this.playing = false;
            this.emit();
          }, RESULT_READABILITY_HOLD_MS);
          return;
        }
        // A completed archive initialized at its end has already satisfied the hold. Follow
        // mode must still settle instead of remaining "playing" with no timer forever.
        this.playing = false;
        this.emit();
        return;
      }
      if (!this.follow) {
        this.playing = false;
        this.emit();
      }
      return;
    }
    const delay = this.duration(this.events[this.index]);
    if (delay === 0) {
      while (this.index < this.events.length && this.playing) this.nextEvent();
      if (!this.follow) this.playing = false;
      this.emit();
      return;
    }
    this.timer = this.clock.set(() => {
      this.timer = null;
      this.nextEvent();
      this.schedule();
    }, delay);
  }

  private duration(event: BattleEvent): number {
    if (this.speed === 'instant' || this.preset === 'instant') return 0;
    const base = EVENT_DURATIONS[event.event_type] ?? 120;
    const backlog = this.follow ? this.events.length - this.index : 0;
    const catchUp = backlog > 96 ? 16 : backlog > 48 ? 8 : backlog > 24 ? 4 : backlog > 12 ? 2 : 1;
    const scaled = Math.round((base * PRESET_MULTIPLIERS[this.preset]) / this.speed / catchUp);
    return Math.max(MIN_VISIBLE_DURATIONS[event.event_type] ?? 16, scaled);
  }

  private clearTimer(): void {
    if (this.timer === null) return;
    this.clock.clear(this.timer);
    this.timer = null;
  }

  private emit(): void {
    const snapshot = this.snapshot();
    for (const listener of this.listeners) listener(snapshot);
  }
}
