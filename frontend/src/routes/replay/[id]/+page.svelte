<script lang="ts">
  import { onMount } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import { getPresentationMatch } from '$lib/api';
  import { loadRendererConfig, saveRendererConfig } from '$lib/presentation/config';
  import { PresentationTimeline } from '$lib/presentation/timeline';
  import {
    defaultRendererConfig,
    type CommentaryMode,
    type PlaybackSpeed,
    type RendererConfig,
    type RendererLayout,
    type RendererTheme,
    type TimelineSnapshot
  } from '$lib/presentation/types';
  import type { MatchArchive } from '$lib/types';

  export let data: { id: string };

  let match: MatchArchive | null = null;
  let timeline: PresentationTimeline | null = null;
  let snapshot: TimelineSnapshot | null = null;
  let config: RendererConfig = defaultRendererConfig({ preset: 'video' });
  let error = '';

  onMount(() => {
    config = { ...loadRendererConfig(), preset: 'video' };
    void load();
    return () => timeline?.destroy();
  });

  async function load() {
    try {
      match = await getPresentationMatch(data.id);
      timeline = new PresentationTimeline(match, match.events);
      timeline.subscribe((value) => (snapshot = value));
      timeline.setPreset(config.preset);
      timeline.setSpeed(config.playbackSpeed);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  function updateConfig(patch: Partial<RendererConfig>) {
    config = { ...config, ...patch };
    saveRendererConfig(config);
    if (patch.playbackSpeed !== undefined) timeline?.setSpeed(config.playbackSpeed);
    if (patch.preset !== undefined) timeline?.setPreset(config.preset);
  }

  function speedFrom(value: string): PlaybackSpeed {
    return value === 'instant' ? 'instant' : (Number(value) as PlaybackSpeed);
  }
</script>

<div class="replay-head">
  <div><span class="eyebrow">Deterministic production replay</span><h1>{match ? `${match.config.players[0].display_name} vs ${match.config.players[1].display_name}` : 'Loading replay…'}</h1></div>
  {#if snapshot}<span>TURN {snapshot.currentTurn} · EVENT {snapshot.index}/{snapshot.eventCount}</span>{/if}
</div>

<BattleRenderer presentation={snapshot?.state || null} {config} />

{#if snapshot}
  <section class="transport panel" aria-label="Replay controls">
    <div class="transport-buttons">
      <button on:click={() => timeline?.restart()} aria-label="Restart replay">↺</button>
      <button on:click={() => timeline?.previousTurn()} disabled={snapshot.index === 0}>Previous turn</button>
      <button on:click={() => timeline?.previousEvent()} disabled={snapshot.index === 0}>Previous event</button>
      <button class="play" on:click={() => timeline?.toggle()}>{snapshot.playing ? 'Pause' : 'Play'}</button>
      <button on:click={() => timeline?.nextEvent()} disabled={snapshot.index >= snapshot.eventCount}>Next event</button>
      <button on:click={() => timeline?.nextTurn()} disabled={snapshot.index >= snapshot.eventCount}>Next turn</button>
    </div>
    <label class="timeline">Timeline <input type="range" min="0" max={snapshot.eventCount} value={snapshot.index} on:input={(event) => timeline?.seek(Number(event.currentTarget.value))} /><output>{Math.round((snapshot.index / Math.max(1, snapshot.eventCount)) * 100)}%</output></label>
    <div class="render-settings">
      <label>Speed<select value={config.playbackSpeed} on:change={(event) => updateConfig({ playbackSpeed: speedFrom(event.currentTarget.value) })}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option><option value="instant">Instant</option></select></label>
      <label>Layout<select value={config.layout} on:change={(event) => updateConfig({ layout: event.currentTarget.value as RendererLayout })}><option value="standard-landscape">Landscape 16:9</option><option value="standard-vertical">Vertical 9:16</option><option value="overlay-landscape">Overlay landscape</option></select></label>
      <label>Theme<select value={config.theme} on:change={(event) => updateConfig({ theme: event.currentTarget.value as RendererTheme })}><option value="koala-dark">Koala Dark</option><option value="koala-light">Koala Light</option></select></label>
      <label>Commentary<select value={config.commentaryMode} on:change={(event) => updateConfig({ commentaryMode: event.currentTarget.value as CommentaryMode })}><option value="latest">Latest</option><option value="last-3">Last 3</option><option value="full">Full history</option><option value="hidden">Hidden</option></select></label>
    </div>
  </section>
{/if}

{#if error}<p class="error">{error}</p>{/if}

<style>
  .replay-head{display:flex;justify-content:space-between;align-items:end;gap:1rem;margin-bottom:1.5rem}.replay-head h1{margin:.3rem 0 0;font-size:clamp(1.7rem,4vw,3rem)}.replay-head>span{color:var(--muted);font:.72rem var(--mono);white-space:nowrap}.transport{display:grid;gap:1rem;margin-top:1rem;padding:1rem;box-shadow:none}.transport-buttons{display:flex;flex-wrap:wrap;gap:.5rem}.transport button{min-height:40px;padding:.55rem .8rem;border:1px solid var(--border);border-radius:.55rem;background:var(--panel-strong);color:var(--text);cursor:pointer}.transport button:disabled{opacity:.4;cursor:not-allowed}.transport .play{min-width:88px;border-color:var(--accent);background:var(--accent);color:var(--accent-ink);font-weight:800}.timeline{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.8rem}.timeline input{min-height:20px;padding:0}.timeline output{min-width:3.5rem;text-align:right;font:.7rem var(--mono)}.render-settings{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:.7rem}.render-settings select{min-height:40px;padding:.5rem}.error{margin-top:1rem}@media(max-width:850px){.render-settings{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.replay-head{align-items:start;flex-direction:column}.transport-buttons{display:grid;grid-template-columns:repeat(2,1fr)}.transport-buttons button:first-child,.transport-buttons .play{grid-column:1/-1}.render-settings{grid-template-columns:1fr}}
</style>
