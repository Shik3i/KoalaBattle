import type { ProductionCue, ProductionTimeline } from '../types.ts';
import { ProductionScheduler } from './scheduler.ts';

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
  private activeMusic: HTMLAudioElement | null = null;
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
    this.caption = null;
    this.director = null;
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
    if (cue.track === 'sfx') this.playSfx(cue.kind);
    if (cue.track === 'music' && typeof cue.payload.media_url === 'string') {
      this.activeMusic?.pause();
      this.activeMusic = new Audio(`${this.mediaBase}${cue.payload.media_url}`);
      this.activeMusic.loop = Boolean(cue.payload.loop);
      this.activeMusic.volume = this.musicVolume();
      void this.activeMusic.play().catch(() => undefined);
    }
  }

  private playSfx(kind: string): void {
    if (!this.context) return;
    const oscillator = this.context.createOscillator();
    const gain = this.context.createGain();
    const frequencies: Record<string, number> = { impact: 120, critical: 720, heal: 520, miss: 180, result: 660 };
    oscillator.frequency.value = frequencies[kind] || 260;
    oscillator.type = kind === 'impact' ? 'square' : 'sine';
    gain.gain.setValueAtTime(this.volume('sfx') * 0.08, this.context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, this.context.currentTime + 0.12);
    oscillator.connect(gain).connect(this.context.destination);
    oscillator.start();
    oscillator.stop(this.context.currentTime + 0.12);
  }

  private activeCue(track: 'captions' | 'director'): ProductionCue | null {
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
