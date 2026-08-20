import type { ProductionCue, ProductionTimeline } from '../types.ts';
import { ProductionScheduler } from './scheduler.ts';
import { sfxVariantFor } from './sfx.ts';

export interface MixerSettings {
  master: number;
  voice: number;
  narrator: number;
  sfx: number;
  music: number;
}

export interface ProductionPlaybackState {
  enabled: boolean;
  playing: boolean;
  elapsedMs: number;
  durationMs: number;
  visual: ProductionCue | null;
  caption: ProductionCue | null;
  director: ProductionCue | null;
  settings: MixerSettings;
}

const defaults: MixerSettings = { master: 1, voice: 1, narrator: 1, sfx: 0.65, music: 0.35 };
type VoiceChannel = 'p1' | 'p2' | 'narrator';

export class ProductionAudioEngine {
  private readonly scheduler = new ProductionScheduler();
  private timeline: ProductionTimeline | null = null;
  private context: AudioContext | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private lastTick = 0;
  private enabled = false;
  private playing = false;
  private readonly activeVoices = new Map<VoiceChannel, HTMLAudioElement>();
  private readonly activeSfx = new Set<HTMLAudioElement>();
  private readonly unavailableSfx = new Set<string>();
  private activeMusic: HTMLAudioElement | null = null;
  private visual: ProductionCue | null = null;
  private caption: ProductionCue | null = null;
  private director: ProductionCue | null = null;
  private listeners = new Set<(state: ProductionPlaybackState) => void>();
  private settings: MixerSettings = { ...defaults };

  constructor(private readonly mediaBase: string) {
    if (typeof localStorage !== 'undefined') {
      try {
        this.settings = { ...defaults, ...JSON.parse(localStorage.getItem('koalabattle-mixer-v1') || '{}') };
      } catch {
        this.settings = { ...defaults };
      }
    }
  }

  subscribe(listener: (state: ProductionPlaybackState) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  load(timeline: ProductionTimeline): void {
    this.stopMedia();
    this.timeline = timeline;
    this.scheduler.load(timeline);
    this.visual = this.activeCue('visual');
    this.caption = null;
    this.director = null;
    this.emit();
  }

  /** Refresh a live production without jumping its current playback position. */
  update(timeline: ProductionTimeline): void {
    const elapsedMs = this.scheduler.time();
    const wasPlaying = this.playing;
    this.timeline = timeline;
    this.scheduler.load(timeline);
    // Keep a cue appended exactly at the previous live tail eligible. A normal seek treats
    // cues at the cursor as already emitted; a live timeline refresh must treat that boundary
    // as the next playback moment instead.
    this.scheduler.seek(Math.max(0, elapsedMs - 1));
    for (const cue of this.scheduler.advance(1)) this.handle(cue);
    this.visual = this.activeCue('visual');
    this.caption = this.activeCue('captions');
    this.director = this.activeCue('director');
    this.lastTick = performance.now();
    this.playing = wasPlaying;
    if (wasPlaying && !this.timer) this.timer = setInterval(() => this.tick(), 40);
    this.emit();
  }

  async enable(): Promise<void> {
    this.context ||= new AudioContext();
    await this.context.resume();
    this.enabled = true;
    this.emit();
  }

  play(): void {
    if (!this.timeline) return;
    this.playing = true;
    this.lastTick = performance.now();
    if (!this.timer) this.timer = setInterval(() => this.tick(), 40);
    this.emit();
  }

  pause(): void {
    this.playing = false;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.pauseVoices();
    this.activeMusic?.pause();
    this.emit();
  }

  restart(): void {
    this.seek(0);
  }

  seek(milliseconds: number): void {
    this.stopMedia();
    this.scheduler.seek(milliseconds);
    this.visual = this.activeCue('visual');
    this.caption = this.activeCue('captions');
    this.director = this.activeCue('director');
    this.lastTick = performance.now();
    this.emit();
  }

  seekEvent(sequence: number): void {
    this.seek(this.scheduler.timeForEvent(sequence));
  }

  setVolume(track: keyof MixerSettings, value: number): void {
    this.settings = { ...this.settings, [track]: Math.max(0, Math.min(1, value)) };
    this.updateVoiceVolumes();
    if (this.activeMusic) this.activeMusic.volume = this.musicVolume();
    localStorage.setItem('koalabattle-mixer-v1', JSON.stringify(this.settings));
    this.emit();
  }

  preview(mediaUrl: string): void {
    if (!this.enabled) return;
    this.pauseVoices();
    const audio = new Audio(`${this.mediaBase}${mediaUrl}`);
    audio.volume = this.volume('voice');
    audio.onended = () => {
      audio.src = '';
    };
    void audio.play().catch(() => undefined);
  }

  destroy(): void {
    this.pause();
    this.stopMedia();
    void this.context?.close();
    this.context = null;
    this.listeners.clear();
  }

  private tick(): void {
    if (!this.playing) return;
    const now = performance.now();
    const due = this.scheduler.advance(now - this.lastTick);
    this.lastTick = now;
    for (const cue of due) this.handle(cue);
    this.visual = this.activeCue('visual');
    this.caption = this.activeCue('captions');
    this.director = this.activeCue('director');
    if (this.scheduler.time() >= this.scheduler.duration()) this.pause();
    else this.emit();
  }

  private handle(cue: ProductionCue): void {
    if (!this.enabled) return;
    if (cue.track === 'voice' && typeof cue.payload.media_url === 'string') {
      const channel = cue.speaker || cue.side || 'p1';
      const previous = this.activeVoices.get(channel);
      if (this.timeline?.profile.interruption_policy === 'interrupt') previous?.pause();
      const audio = new Audio(`${this.mediaBase}${cue.payload.media_url}`);
      audio.volume = this.channelVolume(channel);
      audio.onended = () => {
        if (this.activeVoices.get(channel) === audio) this.activeVoices.delete(channel);
        this.updateVoiceVolumes();
        if (this.activeMusic) this.activeMusic.volume = this.musicVolume();
      };
      this.activeVoices.set(channel, audio);
      this.updateVoiceVolumes();
      if (this.activeMusic) this.activeMusic.volume = this.musicVolume();
      void audio.play().catch(() => undefined);
    }
    if (cue.track === 'sfx') this.playSfx(cue.kind, cue.id);
    if (cue.track === 'music' && typeof cue.payload.media_url === 'string') {
      this.activeMusic?.pause();
      this.activeMusic = new Audio(`${this.mediaBase}${cue.payload.media_url}`);
      this.activeMusic.loop = Boolean(cue.payload.loop);
      this.activeMusic.volume = this.musicVolume();
      void this.activeMusic.play().catch(() => undefined);
    }
  }

  private playSfx(kind: string, seed: string): void {
    const variant = sfxVariantFor(kind, seed);
    if (variant) {
      const mediaUrl = `${this.mediaBase.replace(/\/$/, '')}/api/assets/audio/${encodeURIComponent(variant)}`;
      if (!this.unavailableSfx.has(mediaUrl)) {
        const audio = new Audio(mediaUrl);
        audio.volume = this.volume('sfx');
        this.activeSfx.add(audio);
        let fallbackPlayed = false;
        const cleanup = () => {
          this.activeSfx.delete(audio);
          audio.src = '';
        };
        const fallback = () => {
          if (fallbackPlayed) return;
          fallbackPlayed = true;
          this.unavailableSfx.add(mediaUrl);
          cleanup();
          this.playSynthSfx(kind);
        };
        audio.onended = cleanup;
        audio.onerror = fallback;
        void audio.play().catch(fallback);
        return;
      }
    }
    this.playSynthSfx(kind);
  }

  private playSynthSfx(kind: string): void {
    if (!this.context) return;
    const now = this.context.currentTime;
    const volume = this.volume('sfx');
    if (kind === 'result-sting') {
      [392, 494, 587, 784].forEach((frequency, index) => {
        this.playTone(frequency, now + index * 0.09, 0.42, 'triangle', volume * 0.1);
      });
      return;
    }
    const frequencies: Record<string, number> = {
      action: 360,
      impact: 120,
      critical: 720,
      heal: 520,
      miss: 180,
      result: 660,
      switch: 300,
      faint: 92,
      status: 410,
      field: 250
    };
    const types: Record<string, OscillatorType> = {
      impact: 'square',
      faint: 'sawtooth',
      status: 'triangle'
    };
    this.playTone(frequencies[kind] || 260, now, kind === 'faint' ? 0.3 : 0.14, types[kind] || 'sine', volume * 0.08);
  }

  private playTone(
    frequency: number,
    start: number,
    duration: number,
    type: OscillatorType,
    peak: number
  ): void {
    if (!this.context) return;
    const oscillator = this.context.createOscillator();
    const gain = this.context.createGain();
    oscillator.frequency.setValueAtTime(frequency, start);
    oscillator.type = type;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(gain).connect(this.context.destination);
    oscillator.start(start);
    oscillator.stop(start + duration + 0.01);
  }

  private activeCue(track: 'visual' | 'captions' | 'director'): ProductionCue | null {
    const time = this.scheduler.time();
    return [...(this.timeline?.cues || [])]
      .reverse()
      .find((cue) => cue.track === track && cue.start_ms <= time && cue.start_ms + cue.duration_ms > time) || null;
  }

  private volume(track: 'voice' | 'narrator' | 'sfx' | 'music'): number {
    return this.settings.master * this.settings[track];
  }

  private musicVolume(): number {
    const ducking = this.activeVoices.size ? Math.pow(10, (this.timeline?.profile.ducking_db || -12) / 20) : 1;
    return this.volume('music') * ducking;
  }

  private stopMedia(): void {
    this.pauseVoices();
    this.pauseSfx();
    if (this.activeMusic) {
      this.activeMusic.pause();
      this.activeMusic.src = '';
      this.activeMusic = null;
    }
  }

  private pauseVoices(): void {
    for (const audio of this.activeVoices.values()) {
      audio.pause();
      audio.src = '';
    }
    this.activeVoices.clear();
  }

  private pauseSfx(): void {
    for (const audio of this.activeSfx) {
      audio.pause();
      audio.src = '';
    }
    this.activeSfx.clear();
  }

  private channelVolume(channel: VoiceChannel): number {
    if (channel === 'narrator') return this.volume('narrator');
    const ducking = this.activeVoices.has('narrator') ? Math.pow(10, -5 / 20) : 1;
    return this.volume('voice') * ducking;
  }

  private updateVoiceVolumes(): void {
    for (const [channel, audio] of this.activeVoices) audio.volume = this.channelVolume(channel);
  }

  private snapshot(): ProductionPlaybackState {
    return {
      enabled: this.enabled,
      playing: this.playing,
      elapsedMs: this.scheduler.time(),
      durationMs: this.scheduler.duration(),
      visual: this.visual,
      caption: this.caption,
      director: this.director,
      settings: this.settings
    };
  }

  private emit(): void {
    const state = this.snapshot();
    this.listeners.forEach((listener) => listener(state));
  }
}
