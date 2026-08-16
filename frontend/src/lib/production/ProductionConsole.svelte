<script lang="ts">
  import { onMount } from 'svelte';
  import {
    createProduction,
    directProduction,
    getProductions,
    getProductionSetup,
    prepareProduction,
    previewVoice
  } from '../api';
  import { apiBase } from '../api';
  import type { ProductionProfile, ProductionTimeline, VoicePreset } from '../types';
  import CaptionOverlay from './CaptionOverlay.svelte';
  import ExportDashboard from './ExportDashboard.svelte';
  import { ProductionAudioEngine, type MixerSettings, type ProductionPlaybackState } from './audio-engine';

  export let matchId: string;
  export let compact = false;
  export let overlay = false;

  let profiles: ProductionProfile[] = [];
  let productions: ProductionTimeline[] = [];
  let voices: VoicePreset[] = [];
  let selectedProfile = 'live-stream';
  let selectedP1 = 'edge-neural-p1';
  let selectedP2 = 'edge-neural-p2';
  let production: ProductionTimeline | null = null;
  let engine: ProductionAudioEngine | null = null;
  let playback: ProductionPlaybackState | null = null;
  let error = '';
  let busy = false;
  $: mixer = playback?.settings || { master: 1, voice: 1, sfx: 0.65, music: 0.35 };
  const clientId = typeof crypto !== 'undefined' ? crypto.randomUUID() : 'production-client';

  onMount(() => {
    engine = new ProductionAudioEngine(apiBase());
    const unsubscribe = engine.subscribe((state) => (playback = state));
    void load();
    return () => {
      unsubscribe();
      engine?.destroy();
    };
  });

  async function load() {
    try {
      const [setup, existing] = await Promise.all([getProductionSetup(), getProductions(matchId)]);
      profiles = setup.profiles;
      voices = setup.voices.filter((voice) => voice.enabled);
      productions = existing;
      if (existing[0]) select(existing[0]);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  function select(value: ProductionTimeline) {
    production = value;
    selectedProfile = value.profile.id;
    selectedP1 = value.voice_assignments.p1 || selectedP1;
    selectedP2 = value.voice_assignments.p2 || selectedP2;
    engine?.load(value);
    if (compact) engine?.play();
  }

  async function create() {
    busy = true;
    error = '';
    try {
      const value = await createProduction(matchId, selectedProfile, { p1: selectedP1, p2: selectedP2 });
      productions = [value, ...productions];
      select(value);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      busy = false;
    }
  }

  async function prepare() {
    if (!production) return;
    busy = true;
    try {
      const value = await prepareProduction(production.id, false);
      productions = productions.map((item) => (item.id === value.id ? value : item));
      select(value);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      busy = false;
    }
  }

  async function direct(command: string) {
    if (!production) return;
    try {
      const value = await directProduction(production.id, command, clientId);
      production = value;
      productions = productions.map((item) => (item.id === value.id ? value : item));
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function preview(presetId: string) {
    if (!playback?.enabled) {
      error = 'Enable audio before playing a voice preview.';
      return;
    }
    try {
      const artifact = await previewVoice(presetId);
      engine?.preview(artifact.media_url);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  export function seekEvent(sequence: number) {
    engine?.seekEvent(sequence);
  }
  export function play() {
    engine?.play();
  }
  export function pause() {
    engine?.pause();
  }
  export function restart() {
    engine?.restart();
  }
</script>

{#if production && playback}
  <CaptionOverlay
    cue={playback.caption}
    elapsedMs={playback.elapsedMs}
    vertical={production.profile.aspect_ratio === '9:16'}
  />
{/if}

{#if !compact}
  <ExportDashboard {matchId} {productions} selectedProduction={production} />
{/if}

{#if compact}
  <div class:overlay class="compact-audio">
    {#if production}
      <button on:click={() => engine?.enable()} disabled={playback?.enabled}>
        {playback?.enabled ? 'Audio enabled' : 'Enable audio'}
      </button>
      <span>{production.status} · {production.profile.display_name}</span>
    {:else}
      <span>No production timeline</span>
    {/if}
  </div>
{:else}
  <section class="production panel" aria-label="Production audio and director">
    <div class="production-head">
      <div><span class="eyebrow">Production timeline</span><h2>Audio, captions & director</h2></div>
      {#if production}<span class={`status-pill ${production.status}`}>{production.status}</span>{/if}
    </div>
    <div class="setup-row">
      <label>Profile<select bind:value={selectedProfile}>{#each profiles as profile}<option value={profile.id}>{profile.display_name}</option>{/each}</select></label>
      <label>Player 1 voice<select bind:value={selectedP1}>{#each voices as voice}<option value={voice.id}>{voice.display_name}</option>{/each}</select></label>
      <button on:click={() => preview(selectedP1)}>Preview P1</button>
      <label>Player 2 voice<select bind:value={selectedP2}>{#each voices as voice}<option value={voice.id}>{voice.display_name}</option>{/each}</select></label>
      <button on:click={() => preview(selectedP2)}>Preview P2</button>
      <button on:click={create} disabled={busy}>Create separate production</button>
      {#if production}<button on:click={prepare} disabled={busy || production.status === 'preparing'}>Prepare free neural speech</button>{/if}
      <button class="enable" on:click={() => engine?.enable()} disabled={playback?.enabled}>{playback?.enabled ? 'Audio enabled' : 'Enable audio'}</button>
    </div>
    {#if production && playback}
      <div class="transport-row">
        <button on:click={() => { engine?.restart(); engine?.play(); }}>Restart</button>
        <button on:click={() => playback?.playing ? engine?.pause() : engine?.play()}>{playback.playing ? 'Pause production' : 'Play production'}</button>
        <input aria-label="Production position" type="range" min="0" max={Math.max(1, playback.durationMs)} value={playback.elapsedMs} on:input={(event) => engine?.seek(Number(event.currentTarget.value))} />
        <output>{(playback.elapsedMs / 1000).toFixed(1)}s / {(playback.durationMs / 1000).toFixed(1)}s</output>
      </div>
      <div class="mixer">
        {#each ['master', 'voice', 'sfx', 'music'] as track}
          <label>{track}<input type="range" min="0" max="1" step="0.05" value={mixer[track as keyof MixerSettings]} on:input={(event) => engine?.setVolume(track as keyof MixerSettings, Number(event.currentTarget.value))} /></label>
        {/each}
      </div>
      <div class="director">
        <strong>Director: {production.director_state}</strong>
        {#each ['show-intro', 'show-team-reveal', 'start', 'pause', 'resume', 'show-result', 'show-champion', 'end'] as command}
          <button on:click={() => direct(command)}>{command}</button>
        {/each}
      </div>
      <details>
        <summary>Timeline inspector · {production.cues.length} cues · revision {production.revision}</summary>
        <div class="cue-list">
          {#each production.cues as cue}
            <button on:click={() => engine?.seek(cue.start_ms)}><span>{(cue.start_ms / 1000).toFixed(2)}s</span><strong>{cue.track}</strong><span>{cue.kind}</span><span>{cue.side || '—'}</span></button>
          {/each}
        </div>
      </details>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </section>
{/if}

<style>
  .production{position:relative;display:grid;gap:1rem;margin-top:1rem;padding:1rem}.production-head,.setup-row,.transport-row,.director{display:flex;align-items:center;justify-content:space-between;gap:.7rem;flex-wrap:wrap}.production-head h2{margin:.2rem 0 0}.setup-row label{min-width:160px}.setup-row select,.setup-row button,.transport-row button,.director button{min-height:40px}.enable{border-color:var(--accent)!important}.transport-row input{flex:1;min-width:180px}.transport-row output{font:.7rem var(--mono)}.mixer{display:grid;grid-template-columns:repeat(4,1fr);gap:.8rem}.mixer label{display:grid;gap:.35rem;text-transform:capitalize}.mixer input{padding:0}.director{justify-content:flex-start}.director strong{margin-right:auto}.cue-list{display:grid;max-height:320px;overflow:auto;margin-top:.7rem}.cue-list button{display:grid;grid-template-columns:70px 100px 1fr 30px;gap:.6rem;text-align:left;border:0;border-bottom:1px solid var(--border);border-radius:0;background:transparent;color:var(--text);font:.68rem var(--mono)}.compact-audio{position:fixed;z-index:40;left:1rem;bottom:1rem;display:flex;align-items:center;gap:.6rem;padding:.45rem .6rem;border:1px solid rgba(255,255,255,.18);border-radius:.55rem;background:rgba(8,16,11,.86);color:white;font:.65rem var(--mono)}.compact-audio button{min-height:34px}.compact-audio.overlay{bottom:1rem}@media(max-width:700px){.mixer{grid-template-columns:repeat(2,1fr)}.cue-list button{grid-template-columns:60px 80px 1fr}.cue-list button span:last-child{display:none}}
</style>
