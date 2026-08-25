<script lang="ts">
  /**
   * Battle-only view. Deliberately contains no application navigation, no control form and
   * no page scroll: it fills the viewport, updates live, reconnects on its own, and is the
   * URL you point OBS at or keep open on a second tab while you work in the control view.
   */
  import { onMount } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import ProductionConsole from '$lib/production/ProductionConsole.svelte';
  import { getPresentationMatch, getStylePresets, wsUrl } from '$lib/api';
  import { configFromQuery, sanitizeRendererConfig } from '$lib/presentation/config';
  import { styleToRendererConfig } from '$lib/production/style';
  import { connectLiveSocket } from '$lib/presentation/live-socket';
  import { fullscreenSupported, isFullscreen, onFullscreenChange, toggleFullscreen } from '$lib/fullscreen';
  import { PresentationTimeline } from '$lib/presentation/timeline';
  import {
    defaultRendererConfig,
    type RendererConfig,
    type TimelineSnapshot
  } from '$lib/presentation/types';
  import type { BattleEvent, MatchArchive } from '$lib/types';
  import type { ProductionPlaybackState } from '$lib/production/audio-engine';

  export let data: { id: string };
  let timeline: PresentationTimeline | null = null;
  let snapshot: TimelineSnapshot | null = null;
  let config: RendererConfig = defaultRendererConfig({ layout: 'overlay-landscape' });
  let stopSocket: (() => void) | null = null;
  let match: MatchArchive | null = null;
  let productionClockActive = false;
  let speaking: ProductionPlaybackState['speaking'] = [];
  let connection: 'connecting' | 'live' | 'reconnecting' = 'connecting';
  let viewElement: HTMLElement | null = null;
  let viewFullscreen = false;
  const canFullscreen = fullscreenSupported();

  interface StreamMessage {
    kind: string; match?: MatchArchive; event?: BattleEvent; error?: string;
    config?: Partial<RendererConfig>;
  }

  onMount(() => {
    const query = new URLSearchParams(location.search);
    config = configFromQuery(query);
    // One style system drives every production surface. `?style=` applies a saved or
    // built-in ProductionStyle here too; settings this DOM renderer cannot express are
    // left alone rather than approximated with a parallel theme system.
    void applyStyle(query.get('style'));
    void connect();
    // "f" toggles; Escape/F11 leave without going through the button.
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key !== 'f' && event.key !== 'F') return;
      event.preventDefault();
      void toggleViewFullscreen();
    };
    window.addEventListener('keydown', onKey);
    const stopFullscreenSync = onFullscreenChange(() => {
      viewFullscreen = isFullscreen(viewElement);
    });
    return () => {
      window.removeEventListener('keydown', onKey);
      stopFullscreenSync();
      stopSocket?.();
      timeline?.destroy();
    };
  });

  async function toggleViewFullscreen() {
    viewFullscreen = await toggleFullscreen(viewElement);
  }

  async function applyStyle(styleId: string | null) {
    if (!styleId) return;
    const presets = await getStylePresets().catch(() => []);
    const preset = presets.find((item) => item.id === styleId);
    if (preset) config = styleToRendererConfig(preset.style, config);
  }

  async function connect() {
    await refresh();
    // onConnected also fires on this very first open, right after the fetch above — only a
    // later, genuine reconnect should trigger a second one.
    let firstConnection = true;
    stopSocket = connectLiveSocket({
      url: wsUrl(`/api/matches/${data.id}/stream`),
      onConnected: () => {
        if (firstConnection) {
          firstConnection = false;
          return;
        }
        return refresh();
      },
      onStatus: (status) => (connection = status === 'connected' ? 'live' : 'reconnecting'),
      onMessage: (raw) => handleMessage(JSON.parse(raw) as StreamMessage)
    });
  }

  async function refresh() {
    const archive = await getPresentationMatch(data.id);
    match = archive;
    timeline?.destroy();
    timeline = new PresentationTimeline(archive, archive.events, undefined, true);
    timeline.subscribe((value) => (snapshot = value));
    timeline.setPreset(config.preset);
    timeline.setSpeed(config.playbackSpeed);
    timeline.seek(archive.events.length);
    timeline.play();
    connection = 'live';
  }

  function handleMessage(message: StreamMessage) {
    if (message.kind === 'battle_event' && message.event) {
      match = match ? { ...match, events: [...match.events, message.event] } : match;
      timeline?.append(message.event);
    }
    // Mirrors the overlay route: the control tab tunes settings live over this same socket.
    if (message.kind === 'renderer_config' && message.config) {
      config = sanitizeRendererConfig({ ...config, ...message.config });
    }
    // The server sends this when its outgoing queue overflowed and had to drop this
    // subscriber's backlog — the stream is now discontinuous. Refetch a fresh snapshot
    // instead of trying to reason about events with a gap in their sequence.
    if (message.kind === 'resync_required') void refresh();
  }

  function syncProductionPlayback(event: CustomEvent<ProductionPlaybackState>) {
    speaking = event.detail.speaking;
    const sequence = event.detail.visual?.event_sequence;
    if (!sequence || !match || !timeline) return;
    const index = match.events.findIndex((item) => item.sequence === sequence);
    if (index < 0) return;
    if (!productionClockActive) {
      productionClockActive = true;
      timeline.pause();
    }
    if (snapshot?.index !== index + 1) timeline.seek(index + 1);
  }
</script>

<svelte:head><title>KoalaBattle · Battle view</title></svelte:head>

<div class="battle-view" bind:this={viewElement}>
  <BattleRenderer presentation={snapshot?.state || null} {config} overlay {speaking} campaign={match?.config.campaign || null} />
  <!-- Keeps narration audio available on the viewer tab; no battle controls are exposed. -->
  <ProductionConsole
    matchId={data.id}
    compact
    overlay
    followLive
    on:playback={syncProductionPlayback}
  />
  {#if canFullscreen}
    <button
      type="button"
      class="fullscreen-toggle"
      on:click={toggleViewFullscreen}
      aria-label={viewFullscreen ? 'Exit fullscreen' : 'Enter fullscreen (F)'}
      title={viewFullscreen ? 'Exit fullscreen (F)' : 'Fullscreen (F)'}
    ><i class={`ph ${viewFullscreen ? 'ph-corners-in' : 'ph-corners-out'}`} aria-hidden="true"></i></button>
  {/if}
  {#if connection !== 'live'}
    <p class="connection" role="status">{connection === 'connecting' ? 'Connecting…' : 'Reconnecting…'}</p>
  {/if}
</div>

<style>
  /* Fills the viewport exactly; the battle must never require scrolling. */
  .battle-view{position:fixed;inset:0;overflow:hidden;background:#050a08}
  /* Sits over the arena, fades back until hovered so it never competes with the
     battle on a capture source. */
  .fullscreen-toggle{position:absolute;z-index:20;right:1rem;top:1rem;display:grid;place-items:center;width:40px;height:40px;border:1px solid rgba(255,255,255,.18);border-radius:.55rem;background:rgba(6,14,10,.7);color:#e9fff4;font-size:1.05rem;cursor:pointer;opacity:.35;transition:opacity .16s ease,background .16s ease}
  .fullscreen-toggle:hover,.fullscreen-toggle:focus-visible{opacity:1;background:rgba(6,14,10,.92)}
  @media(prefers-reduced-motion:reduce){.fullscreen-toggle{transition:none}}
  .connection{position:absolute;right:1rem;bottom:1rem;margin:0;padding:.42rem .7rem;border:1px solid rgba(255,255,255,.16);border-radius:999px;background:rgba(6,14,10,.82);color:#ffd26a;font:0.72rem var(--mono)}
</style>
