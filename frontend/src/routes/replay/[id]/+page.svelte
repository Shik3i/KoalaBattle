<script lang="ts">
  import { onMount } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import ProductionConsole from '$lib/production/ProductionConsole.svelte';
  import { goto } from '$app/navigation';
  import {
    createProduction,
    deleteProduction,
    duplicateProduction,
    getPresentationMatch,
    getProductions,
    getStylePresets
  } from '$lib/api';
  import { loadRendererConfig, saveRendererConfig } from '$lib/presentation/config';
  import { PresentationTimeline } from '$lib/presentation/timeline';
  import {
    defaultRendererConfig,
    type CommentaryMode,
    type EffectQuality,
    type PlaybackSpeed,
    type RendererConfig,
    type RendererLayout,
    type RendererTheme,
    type TimelineSnapshot
  } from '$lib/presentation/types';
  import { formatDisplayName, generationOf } from '$lib/production/style';
  import type { MatchArchive, ProductionTimeline, StylePreset } from '$lib/types';

  export let data: { id: string };

  let match: MatchArchive | null = null;
  let timeline: PresentationTimeline | null = null;
  let snapshot: TimelineSnapshot | null = null;
  let config: RendererConfig = defaultRendererConfig({ preset: 'video' });
  let error = '';
  let productionConsole: ProductionConsole | null = null;
  let productions: ProductionTimeline[] = [];
  let stylePresets: StylePreset[] = [];
  let newStyleId = 'koala-broadcast';
  let newProfileId = 'youtube';
  let creating = false;

  /**
   * A suggestion, never a rule: early generations look better retro and vertical exports
   * want the vertical preset, but the picker stays fully open.
   */
  $: if (match) {
    newStyleId =
      newProfileId === 'shorts'
        ? 'vertical'
        : generationOf(match.config.format) <= 2
          ? 'retro'
          : 'koala-broadcast';
  }

  async function loadProductions() {
    [productions, stylePresets] = await Promise.all([
      getProductions(data.id),
      getStylePresets().catch(() => [])
    ]);
  }

  async function createVideo() {
    creating = true;
    error = '';
    try {
      const production = await createProduction(data.id, newProfileId, {}, { styleId: newStyleId });
      await goto(`/studio/${production.id}`);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      creating = false;
    }
  }

  async function duplicateFor(id: string) {
    const copy = await duplicateProduction(id, { title: 'Copy' });
    await loadProductions();
    await goto(`/studio/${copy.id}`);
  }

  async function removeProduction(id: string) {
    if (!confirm('Delete this production? The recorded match itself is not affected.')) return;
    await deleteProduction(id);
    await loadProductions();
  }

  onMount(() => {
    config = { ...loadRendererConfig(), preset: 'video' };
    void load();
    return () => timeline?.destroy();
  });

  async function load() {
    try {
      match = await getPresentationMatch(data.id);
      timeline = new PresentationTimeline(match, match.events);
      timeline.subscribe((value) => {
        snapshot = value;
        const event = value.index > 0 ? match?.events[value.index - 1] : null;
        if (event) productionConsole?.seekEvent(event.sequence);
        else productionConsole?.restart();
      });
      timeline.setPreset(config.preset);
      timeline.setSpeed(config.playbackSpeed);
      await loadProductions();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  function updateConfig(patch: Partial<RendererConfig>) {
    config = { ...config, ...patch };
    saveRendererConfig(config);
    if (patch.playbackSpeed !== undefined) timeline?.setSpeed(config.playbackSpeed);
    if (patch.preset !== undefined) timeline?.setPreset(config.preset);
    if (config.playbackSpeed !== 1 || config.preset === 'instant') productionConsole?.pause();
  }

  function togglePlayback() {
    const willPlay = !snapshot?.playing;
    timeline?.toggle();
    if (willPlay && config.playbackSpeed === 1 && config.preset !== 'instant') productionConsole?.play();
    else productionConsole?.pause();
  }

  function restartPlayback() {
    timeline?.restart();
    productionConsole?.restart();
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

<section class="studio-entry panel" aria-label="Video productions">
  <div class="studio-entry-head">
    <div>
      <h2>Video Studio</h2>
      <p>Render this recorded match again with any presentation. The battle itself never changes.</p>
    </div>
    <div class="create">
      <label>Format
        <select bind:value={newProfileId}>
          <option value="youtube">Landscape 1920×1080</option>
          <option value="shorts">Vertical 1080×1920</option>
          <option value="silent">Silent landscape</option>
          <option value="live-stream">Live stream</option>
        </select>
      </label>
      <label>Style
        <select bind:value={newStyleId}>
          {#each stylePresets as preset (preset.id)}<option value={preset.id}>{preset.display_name}</option>{/each}
        </select>
      </label>
      <button class="primary" on:click={createVideo} disabled={creating}>{creating ? 'Creating…' : 'Create Video'}</button>
    </div>
  </div>
  {#if productions.length}
    <ul class="productions">
      {#each productions as item (item.id)}
        <li>
          <div>
            <strong>{item.title || item.style.display_name}</strong>
            <small>{item.profile.aspect_ratio === '9:16' ? '1080×1920' : '1920×1080'} · {item.profile.display_name} · {item.status}{match ? ` · ${formatDisplayName(match.config.format)}` : ''}</small>
          </div>
          <div class="production-actions">
            <a class="button compact" href={`/studio/${item.id}`}>Edit</a>
            <button on:click={() => duplicateFor(item.id)}>Duplicate</button>
            <button class="danger" on:click={() => removeProduction(item.id)}>Delete</button>
          </div>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="empty">No productions yet. Create one to open the Video Studio.</p>
  {/if}
</section>

<ProductionConsole bind:this={productionConsole} matchId={data.id} />

{#if snapshot}
  <section class="transport panel" aria-label="Replay controls">
    <div class="transport-buttons">
      <div><button on:click={restartPlayback}>Restart</button><button on:click={() => timeline?.previousTurn()} disabled={snapshot.index === 0}>Previous turn</button></div>
      <div><button on:click={() => timeline?.previousEvent()} disabled={snapshot.index === 0}>Previous event</button><button class="play" on:click={togglePlayback}>{snapshot.playing ? 'Pause' : 'Play'}</button><button on:click={() => timeline?.nextEvent()} disabled={snapshot.index >= snapshot.eventCount}>Next event</button></div>
      <div><button on:click={() => timeline?.nextTurn()} disabled={snapshot.index >= snapshot.eventCount}>Next turn</button></div>
    </div>
    <label class="timeline">Timeline <input type="range" min="0" max={snapshot.eventCount} value={snapshot.index} on:input={(event) => timeline?.seek(Number(event.currentTarget.value))} /><output>{Math.round((snapshot.index / Math.max(1, snapshot.eventCount)) * 100)}%</output></label>
    <div class="render-settings">
      <label>Speed<select value={config.playbackSpeed} on:change={(event) => updateConfig({ playbackSpeed: speedFrom(event.currentTarget.value) })}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option><option value="instant">Instant</option></select></label>
      <label>Layout<select value={config.layout} on:change={(event) => updateConfig({ layout: event.currentTarget.value as RendererLayout })}><option value="standard-landscape">Landscape 16:9</option><option value="standard-vertical">Vertical 9:16</option><option value="overlay-landscape">Overlay landscape</option></select></label>
      <label>Theme<select value={config.theme} on:change={(event) => updateConfig({ theme: event.currentTarget.value as RendererTheme })}><option value="koala-dark">Koala Dark</option><option value="koala-light">Koala Light</option></select></label>
      <label>Commentary<select value={config.commentaryMode} on:change={(event) => updateConfig({ commentaryMode: event.currentTarget.value as CommentaryMode })}><option value="latest">Latest</option><option value="last-3">Last 3</option><option value="full">Full history</option><option value="hidden">Hidden</option></select></label>
      <label>Effects<select value={config.effects} on:change={(event) => updateConfig({ effects: event.currentTarget.value as EffectQuality })}><option value="off">Off</option><option value="low">Low</option><option value="standard">Standard</option><option value="high">High</option></select></label>
    </div>
  </section>
{/if}

{#if error}<p class="error">{error}</p>{/if}

<style>
  .studio-entry{margin-top:1rem;padding:1rem;display:grid;gap:.9rem}
  .studio-entry-head{display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap}
  .studio-entry h2{margin:0;font-size:1.1rem}
  .studio-entry p{margin:.25rem 0 0;color:var(--muted);font-size:.8rem}
  .create{display:flex;gap:.5rem;align-items:end;flex-wrap:wrap}
  .create label{display:grid;gap:.2rem;font-size:.72rem;color:var(--muted)}
  .create select{min-height:40px;padding:.45rem .5rem;border:1px solid var(--border);border-radius:.5rem;background:var(--panel-strong);color:var(--text)}
  .create .primary{min-height:40px;padding:.5rem 1rem;border:1px solid var(--accent);border-radius:.5rem;background:var(--accent);color:var(--accent-ink);font-weight:800;cursor:pointer}
  .productions{list-style:none;margin:0;padding:0;display:grid;gap:.45rem}
  .productions li{display:flex;justify-content:space-between;align-items:center;gap:.75rem;padding:.6rem .75rem;border:1px solid var(--border);border-radius:.55rem;flex-wrap:wrap}
  .productions small{display:block;color:var(--muted);font:.68rem var(--mono)}
  .production-actions{display:flex;gap:.4rem}
  .production-actions button,.production-actions .button{min-height:36px;padding:.4rem .7rem;border:1px solid var(--border);border-radius:.5rem;background:var(--panel-strong);color:var(--text);cursor:pointer;font-size:.78rem}
  .production-actions .danger{border-color:#a8464f;color:#ffb0b6}
  .empty{color:var(--muted);font-size:.82rem;margin:0}
  .replay-head{display:flex;justify-content:space-between;align-items:end;gap:1rem;margin-bottom:1.5rem}.replay-head h1{margin:.3rem 0 0;font-size:clamp(1.7rem,4vw,3rem)}.replay-head>span{color:var(--muted);font:.72rem var(--mono);white-space:nowrap}.transport{display:grid;gap:1rem;margin-top:1rem;padding:1rem;box-shadow:none}.transport-buttons{display:grid;grid-template-columns:1fr auto 1fr;gap:.7rem}.transport-buttons>div{display:flex;gap:.4rem}.transport-buttons>div:last-child{justify-content:flex-end}.transport button{min-height:40px;padding:.55rem .8rem;border:1px solid var(--border);border-radius:.55rem;background:var(--panel-strong);color:var(--text);cursor:pointer}.transport button:disabled{opacity:.4;cursor:not-allowed}.transport .play{min-width:88px;border-color:var(--accent);background:var(--accent);color:var(--accent-ink);font-weight:800}.timeline{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.8rem}.timeline input{min-height:20px;padding:0;accent-color:var(--accent)}.timeline output{min-width:3.5rem;text-align:right;font:.7rem var(--mono)}.render-settings{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:.7rem;padding-top:1rem;border-top:1px solid var(--border)}.render-settings select{min-height:40px;padding:.5rem}.error{margin-top:1rem}@media(max-width:850px){.transport-buttons{grid-template-columns:1fr}.transport-buttons>div,.transport-buttons>div:last-child{justify-content:center}.render-settings{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.replay-head{align-items:start;flex-direction:column}.transport-buttons>div{display:grid;grid-template-columns:1fr 1fr}.transport-buttons>div:nth-child(2){grid-template-columns:1fr}.render-settings{grid-template-columns:1fr}}
</style>
