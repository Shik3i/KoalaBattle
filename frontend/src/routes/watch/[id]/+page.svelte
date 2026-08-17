<script lang="ts">
  /**
   * Battle-only view. Deliberately contains no application navigation, no control form and
   * no page scroll: it fills the viewport, updates live, reconnects on its own, and is the
   * URL you point OBS at or keep open on a second tab while you work in the control view.
   */
  import { onMount } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import ProductionConsole from '$lib/production/ProductionConsole.svelte';
  import { getPresentationMatch, getStylePresets, wsBase } from '$lib/api';
  import { configFromQuery } from '$lib/presentation/config';
  import { styleToRendererConfig } from '$lib/production/style';
  import { connectLiveSocket } from '$lib/presentation/live-socket';
  import { PresentationTimeline } from '$lib/presentation/timeline';
  import {
    defaultRendererConfig,
    type AgentPresentationStatus,
    type RendererConfig,
    type TimelineSnapshot
  } from '$lib/presentation/types';
  import type { AgentRequest, BattleEvent, MatchArchive, Side } from '$lib/types';

  export let data: { id: string };
  let timeline: PresentationTimeline | null = null;
  let snapshot: TimelineSnapshot | null = null;
  let config: RendererConfig = defaultRendererConfig({ layout: 'overlay-landscape' });
  let stopSocket: (() => void) | null = null;
  let agentStatus: Partial<Record<Side, AgentPresentationStatus>> = {};
  let connection: 'connecting' | 'live' | 'reconnecting' = 'connecting';

  interface StreamMessage {
    kind: string; match?: MatchArchive; event?: BattleEvent; request?: AgentRequest; error?: string;
  }

  onMount(() => {
    const query = new URLSearchParams(location.search);
    config = configFromQuery(query);
    // One style system drives every production surface. `?style=` applies a saved or
    // built-in ProductionStyle here too; settings this DOM renderer cannot express are
    // left alone rather than approximated with a parallel theme system.
    void applyStyle(query.get('style'));
    void connect();
    return () => { stopSocket?.(); timeline?.destroy(); };
  });

  async function applyStyle(styleId: string | null) {
    if (!styleId) return;
    const presets = await getStylePresets().catch(() => []);
    const preset = presets.find((item) => item.id === styleId);
    if (preset) config = styleToRendererConfig(preset.style, config);
  }

  async function connect() {
    await refresh();
    stopSocket = connectLiveSocket({
      url: `${wsBase()}/api/matches/${data.id}/stream`,
      onConnected: refresh,
      onStatus: (status) => (connection = status === 'connected' ? 'live' : 'reconnecting'),
      onMessage: (raw) => handleMessage(JSON.parse(raw) as StreamMessage)
    });
  }

  async function refresh() {
    const archive = await getPresentationMatch(data.id);
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
    if (message.kind === 'battle_event' && message.event) timeline?.append(message.event);
    if (message.kind === 'agent_waiting' && message.request) {
      agentStatus = { ...agentStatus, [message.request.side]: 'thinking' };
    }
    if (message.kind === 'agent_submitted') agentStatus = { ...agentStatus, p1: 'executing', p2: 'executing' };
    if (message.kind === 'match_completed') agentStatus = { p1: 'finished', p2: 'finished' };
  }
</script>

<svelte:head><title>KoalaBattle · Battle view</title></svelte:head>

<div class="battle-view">
  <BattleRenderer presentation={snapshot?.state || null} {config} overlay {agentStatus} />
  <!-- Keeps narration audio available on the viewer tab; no battle controls are exposed. -->
  <ProductionConsole matchId={data.id} compact overlay />
  {#if connection !== 'live'}
    <p class="connection" role="status">{connection === 'connecting' ? 'Connecting…' : 'Reconnecting…'}</p>
  {/if}
</div>

<style>
  /* Fills the viewport exactly; the battle must never require scrolling. */
  .battle-view{position:fixed;inset:0;overflow:hidden;background:#050a08}
  .connection{position:absolute;right:1rem;bottom:1rem;margin:0;padding:.42rem .7rem;border:1px solid rgba(255,255,255,.16);border-radius:999px;background:rgba(6,14,10,.82);color:#ffd26a;font:.65rem var(--mono)}
</style>
