<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';
  import {
    createProduction,
    directProduction,
    getProductions,
    getProductionSetup,
    prepareProduction,
    previewVoice,
    updateProduction
  } from '../api';
  import { apiBase } from '../api';
  import { createClientId } from '../client-id';
  import type { NarratorMode, NarratorProfile, NarratorSettings, ProductionProfile, ProductionTimeline, VoicePool, VoicePreset } from '../types';
  import CaptionOverlay from './CaptionOverlay.svelte';
  import ExportDashboard from './ExportDashboard.svelte';
  import { ProductionAudioEngine, type MixerSettings, type ProductionPlaybackState } from './audio-engine';

  export let matchId: string;
  export let compact = false;
  export let overlay = false;
  export let followLive = false;

  let profiles: ProductionProfile[] = [];
  let productions: ProductionTimeline[] = [];
  let voices: VoicePreset[] = [];
  let narratorProfiles: NarratorProfile[] = [];
  let voicePools: VoicePool[] = [];
  let selectedProfile = 'live-stream';
  let selectedP1 = 'edge-neural-p1';
  let selectedP2 = 'edge-neural-p2';
  let selectedNarrator = 'edge-neural-narrator';
  let selectedNarratorProfile = 'stadium-broadcast-v1';
  let narratorEnabled = false;
  let narratorMode: NarratorMode = 'highlights';
  let voiceSelectionMode: 'explicit' | 'random' | 'balanced-random' = 'explicit';
  let selectedVoicePool = '';
  let voiceSelectionSeed: number | null = null;
  let production: ProductionTimeline | null = null;
  let engine: ProductionAudioEngine | null = null;
  let playback: ProductionPlaybackState | null = null;
  let error = '';
  let busy = false;
  let refreshTimer: ReturnType<typeof setInterval> | null = null;
  const dispatch = createEventDispatcher<{ playback: ProductionPlaybackState }>();
  $: mixer = playback?.settings || { master: 1, voice: 1, narrator: 1, sfx: 0.65, music: 0.35 };
  const clientId = createClientId();

  onMount(() => {
    engine = new ProductionAudioEngine(apiBase());
    const unsubscribe = engine.subscribe((state) => {
      playback = state;
      dispatch('playback', state);
    });
    void load();
    if (compact && followLive) refreshTimer = setInterval(() => void refreshLiveProduction(), 1500);
    return () => {
      unsubscribe();
      engine?.destroy();
      if (refreshTimer) clearInterval(refreshTimer);
    };
  });

  async function load() {
    try {
      const [setup, existing] = await Promise.all([getProductionSetup(), getProductions(matchId)]);
      profiles = setup.profiles;
      voices = setup.voices.filter((voice) => voice.enabled);
      narratorProfiles = setup.narratorProfiles;
      voicePools = setup.voicePools;
      productions = existing;
      if (existing[0]) select(existing[0]);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function refreshLiveProduction() {
    try {
      const existing = await getProductions(matchId);
      productions = existing;
      const current = production && existing.find((item) => item.id === production?.id);
      if (current) {
        production = current;
        engine?.update(current);
      } else if (!production && existing[0]) {
        select(existing[0]);
      }
    } catch {
      // The battle socket owns connection status; a transient production poll must not
      // cover the battle renderer with a second error state.
    }
  }

  function select(value: ProductionTimeline) {
    production = value;
    selectedProfile = value.profile.id;
    selectedP1 = value.voice_assignments.p1 || selectedP1;
    selectedP2 = value.voice_assignments.p2 || selectedP2;
    selectedNarrator = value.voice_assignments.narrator || selectedNarrator;
    selectedNarratorProfile = value.narrator?.profile_id || selectedNarratorProfile;
    narratorEnabled = value.narrator?.enabled || false;
    narratorMode = value.narrator?.mode || 'highlights';
    voiceSelectionMode = value.voice_selection_mode || 'explicit';
    selectedVoicePool = value.voice_pool_id || '';
    voiceSelectionSeed = value.voice_selection_seed;
    engine?.load(value);
    if (compact) {
      if (followLive) engine?.seek(value.duration_ms);
      engine?.play();
    }
  }

  async function create() {
    busy = true;
    error = '';
    try {
      const value = await createProduction(matchId, selectedProfile, {
        p1: selectedP1,
        p2: selectedP2,
        ...(narratorEnabled ? { narrator: selectedNarrator } : {})
      }, {
        narrator: narratorSettings(),
        voicePoolId: selectedVoicePool || null,
        voiceSelectionMode,
        voiceSelectionSeed
      });
      productions = [value, ...productions];
      select(value);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      busy = false;
    }
  }

  function narratorSettings(): NarratorSettings {
    return {
      enabled: narratorEnabled,
      profile_id: selectedNarratorProfile,
      mode: narratorEnabled ? narratorMode : 'off',
      voice_preset_id: selectedNarrator,
      cooldown_ms: 2800,
      max_lines_per_turn: 1,
      max_lines_per_match: 24,
      minimum_priority: 45,
      repeat_window_ms: 12000,
      overlap_policy: 'duck',
      captions_enabled: true,
      include_pokemon_names: true,
      include_move_names: true,
      language: 'en-US'
    };
  }

  async function saveNarrator() {
    if (!production) return;
    busy = true;
    error = '';
    try {
      const value = await updateProduction(production.id, { narrator: narratorSettings() });
      productions = productions.map((item) => (item.id === value.id ? value : item));
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

  const commandIcon = (command: string) => ({
    'show-intro': 'ph-play-circle', 'show-team-reveal': 'ph-users-three', start: 'ph-play',
    pause: 'ph-pause', resume: 'ph-play', 'show-result': 'ph-check-circle',
    'show-champion': 'ph-trophy', end: 'ph-x'
  })[command] || 'ph-sparkle';
</script>

<!-- Captions accompany narration. Without playback running they would show a cue from a
     different point in the match, so they stay hidden until audio is enabled. -->
{#if production && playback?.enabled}
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
  <!--
    Stream surfaces show only the one affordance browsers require: a click to unlock audio.
    Once audio is running the pill disappears so nothing overlays the battle in OBS.
  -->
  {#if production && !playback?.enabled}
    <div class:overlay class="compact-audio">
      <button on:click={() => engine?.enable()}>Enable audio</button>
    </div>
  {/if}
{:else}
  <section class="production panel" aria-label="Production audio and director">
    <div class="production-head">
      <div><span class="eyebrow">Production timeline</span><h2>Audio, captions & director</h2></div>
      {#if production}<span class={`status-pill ${production.status}`}>{production.status}</span>{/if}
    </div>
    <div class="setup-row">
      <label>Profile<select bind:value={selectedProfile}>{#each profiles as profile}<option value={profile.id}>{profile.display_name}</option>{/each}</select></label>
      <label>Player 1 voice<select bind:value={selectedP1}>{#each voices as voice}<option value={voice.id}>{voice.display_name}{voice.delivery_profile ? ` · ${voice.delivery_profile}` : ''}</option>{/each}</select></label>
      <button on:click={() => preview(selectedP1)}><i class="ph ph-waveform" aria-hidden="true"></i>Preview P1</button>
      <label>Player 2 voice<select bind:value={selectedP2}>{#each voices as voice}<option value={voice.id}>{voice.display_name}{voice.delivery_profile ? ` · ${voice.delivery_profile}` : ''}</option>{/each}</select></label>
      <button on:click={() => preview(selectedP2)}><i class="ph ph-waveform" aria-hidden="true"></i>Preview P2</button>
      <label>Voice pool<select bind:value={selectedVoicePool}><option value="">Explicit voices</option>{#each voicePools.filter((pool) => pool.enabled) as pool}<option value={pool.id}>{pool.display_name}</option>{/each}</select></label>
      <label>Pool selection<select bind:value={voiceSelectionMode} disabled={!selectedVoicePool}><option value="explicit">Explicit</option><option value="random">Random</option><option value="balanced-random">Balanced random</option></select></label>
      <label>Seed<input type="number" bind:value={voiceSelectionSeed} placeholder="deterministic" disabled={!selectedVoicePool} /></label>
      <label class="narrator-toggle"><input type="checkbox" bind:checked={narratorEnabled} /> Narrator</label>
      <label>Narrator profile<select bind:value={selectedNarratorProfile} disabled={!narratorEnabled}>{#each narratorProfiles as profile}<option value={profile.id}>{profile.display_name}</option>{/each}</select></label>
      <label>Narrator mode<select bind:value={narratorMode} disabled={!narratorEnabled}><option value="highlights">Highlights</option><option value="broadcast">Broadcast</option><option value="full">Full</option></select></label>
      <label>Narrator voice<select bind:value={selectedNarrator} disabled={!narratorEnabled}>{#each voices.filter((voice) => voice.id.includes('narrator')) as voice}<option value={voice.id}>{voice.display_name}</option>{/each}</select></label>
      <button on:click={() => preview(selectedNarrator)} disabled={!narratorEnabled}><i class="ph ph-waveform" aria-hidden="true"></i>Preview Narrator</button>
      <button on:click={create} disabled={busy}><i class="ph ph-plus" aria-hidden="true"></i>Create separate production</button>
      {#if production}<button on:click={saveNarrator} disabled={busy}><i class="ph ph-megaphone" aria-hidden="true"></i>Save narrator</button>{/if}
      {#if production}<button on:click={prepare} disabled={busy || production.status === 'preparing'}><i class="ph ph-sparkle" aria-hidden="true"></i>Prepare speech audio</button>{/if}
      <button class="enable" on:click={() => engine?.enable()} disabled={playback?.enabled}><i class={`ph ${playback?.enabled ? 'ph-check' : 'ph-waveform'}`} aria-hidden="true"></i>{playback?.enabled ? 'Audio enabled' : 'Enable audio'}</button>
    </div>
    {#if production && playback}
      <div class="transport-row">
        <button on:click={() => { engine?.restart(); engine?.play(); }}><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>Restart</button>
        <button on:click={() => playback?.playing ? engine?.pause() : engine?.play()}><i class={`ph ${playback.playing ? 'ph-pause' : 'ph-play'}`} aria-hidden="true"></i>{playback.playing ? 'Pause production' : 'Play production'}</button>
        <input aria-label="Production position" type="range" min="0" max={Math.max(1, playback.durationMs)} value={playback.elapsedMs} on:input={(event) => engine?.seek(Number(event.currentTarget.value))} />
        <output>{(playback.elapsedMs / 1000).toFixed(1)}s / {(playback.durationMs / 1000).toFixed(1)}s</output>
      </div>
      <div class="mixer">
        {#each ['master', 'voice', 'narrator', 'sfx', 'music'] as track}
          <label>{track}<input type="range" min="0" max="1" step="0.05" value={mixer[track as keyof MixerSettings]} on:input={(event) => engine?.setVolume(track as keyof MixerSettings, Number(event.currentTarget.value))} /></label>
        {/each}
      </div>
      <div class="director">
        <strong>Director: {production.director_state}</strong>
        {#each ['show-intro', 'show-team-reveal', 'start', 'pause', 'resume', 'show-result', 'show-champion', 'end'] as command}
          <button on:click={() => direct(command)}><i class={`ph ${commandIcon(command)}`} aria-hidden="true"></i>{command}</button>
        {/each}
      </div>
      <details>
        <summary>Timeline inspector · {production.cues.length} cues · revision {production.revision}</summary>
        <div class="cue-list">
          {#each production.cues as cue}
            <button on:click={() => engine?.seek(cue.start_ms)}><span>{(cue.start_ms / 1000).toFixed(2)}s</span><strong>{cue.track}</strong><span>{cue.kind}</span><span>{cue.speaker || cue.side || '—'}</span></button>
          {/each}
        </div>
      </details>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </section>
{/if}

<style>
  .setup-row button,.transport-row button,.director button,.compact-audio button{display:inline-flex;align-items:center;justify-content:center;gap:.38rem;min-height:40px;padding:.55rem .72rem;border:1px solid var(--border);border-radius:.58rem;background:var(--panel-strong);color:var(--text);font-size:.76rem;font-weight:700;cursor:pointer;transition:transform .16s ease,border-color .16s ease,background .16s ease,box-shadow .16s ease}.setup-row button:hover:not(:disabled),.transport-row button:hover:not(:disabled),.director button:hover:not(:disabled){transform:translateY(-1px);border-color:color-mix(in srgb,var(--accent) 42%,var(--border));background:var(--surface);box-shadow:var(--shadow-sm)}.setup-row button:active:not(:disabled),.transport-row button:active:not(:disabled),.director button:active:not(:disabled){transform:scale(.985)}.setup-row button:disabled,.transport-row button:disabled,.director button:disabled{opacity:.5;cursor:not-allowed}.setup-row button .ph,.transport-row button .ph,.director button .ph{color:var(--accent);font-size:1rem}.enable{border-color:var(--accent)!important}
  .production{position:relative;display:grid;gap:1rem;margin-top:1rem;padding:1rem}.production-head,.setup-row,.transport-row,.director{display:flex;align-items:center;justify-content:space-between;gap:.7rem;flex-wrap:wrap}.production-head h2{margin:.2rem 0 0}.setup-row label{min-width:160px}.setup-row select,.setup-row button,.transport-row button,.director button{min-height:40px}.narrator-toggle{display:inline-flex!important;align-items:center;gap:.4rem;min-width:auto!important;padding:.6rem .7rem;border:1px solid var(--border);border-radius:.58rem}.enable{border-color:var(--accent)!important}.transport-row input{flex:1;min-width:180px}.transport-row output{font:.7rem var(--mono)}.mixer{display:grid;grid-template-columns:repeat(5,1fr);gap:.8rem}.mixer label{display:grid;gap:.35rem;text-transform:capitalize}.mixer input{padding:0}.director{justify-content:flex-start}.director strong{margin-right:auto}.cue-list{display:grid;max-height:320px;overflow:auto;margin-top:.7rem}.cue-list button{display:grid;grid-template-columns:70px 100px 1fr 60px;gap:.6rem;text-align:left;border:0;border-bottom:1px solid var(--border);border-radius:0;background:transparent;color:var(--text);font:.68rem var(--mono)}.compact-audio{position:fixed;z-index:40;left:1rem;bottom:1rem;display:flex;align-items:center;gap:.6rem;padding:.45rem .6rem;border:1px solid rgba(255,255,255,.18);border-radius:.55rem;background:rgba(8,16,11,.86);color:white;font:.65rem var(--mono)}.compact-audio button{min-height:34px}.compact-audio.overlay{right:auto;bottom:calc(10.5% + .7rem);left:1rem;top:auto}@media(max-width:700px){.mixer{grid-template-columns:repeat(2,1fr)}.cue-list button{grid-template-columns:60px 80px 1fr}.cue-list button span:last-child{display:none}}
</style>
