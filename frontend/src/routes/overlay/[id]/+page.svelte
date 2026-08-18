<script lang="ts">
  import { onMount } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import ProductionConsole from '$lib/production/ProductionConsole.svelte';
  import { getPresentationMatch, getStylePresets, wsBase } from '$lib/api';
  import { configFromQuery, sanitizeRendererConfig } from '$lib/presentation/config';
  import { styleToRendererConfig } from '$lib/production/style';
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
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  let error = '';
  let agentStatus: Partial<Record<Side, AgentPresentationStatus>> = {};

  interface StreamMessage {
    kind: string;
    match?: MatchArchive;
    event?: BattleEvent;
    request?: AgentRequest;
    error?: string;
    config?: Partial<RendererConfig>;
  }

  onMount(() => {
    const query = new URLSearchParams(location.search);
    config = configFromQuery(query);
    // One style system drives every production surface. `?style=` applies a saved or
    // built-in ProductionStyle here too; settings this DOM renderer cannot express are
    // left alone rather than approximated with a parallel theme system.
    void applyStyle(query.get('style'));
    void initialize();
    return () => {
      stopped = true;
      socket?.close();
      timeline?.destroy();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  });

  async function applyStyle(styleId: string | null) {
    if (!styleId) return;
    const presets = await getStylePresets().catch(() => []);
    const preset = presets.find((item) => item.id === styleId);
    if (preset) config = styleToRendererConfig(preset.style, config);
  }

  async function initialize() {
    try {
      const match = await getPresentationMatch(data.id);
      timeline?.destroy();
      timeline = new PresentationTimeline(match, match.events, undefined, true);
      timeline.subscribe((value) => (snapshot = value));
      timeline.setPreset(config.preset);
      timeline.setSpeed(config.playbackSpeed);
      timeline.seek(match.events.length);
      timeline.play();
      connectSocket();
      error = '';
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
      scheduleReconnect();
    }
  }

  function connectSocket() {
    socket?.close();
    socket = new WebSocket(`${wsBase()}/api/matches/${data.id}/stream`);
    socket.onmessage = ({ data: raw }) => handleMessage(JSON.parse(raw) as StreamMessage);
    socket.onopen = () => (error = '');
    socket.onerror = () => (error = 'Overlay reconnecting…');
    socket.onclose = () => scheduleReconnect();
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      void initialize();
    }, 1500);
  }

  function handleMessage(message: StreamMessage) {
    if (message.kind === 'snapshot' && message.match && message.match.events.length > (snapshot?.eventCount || 0)) {
      timeline?.replace(message.match.events, message.match.events.length);
      timeline?.play();
    }
    if (message.kind === 'battle_event' && message.event) timeline?.append(message.event);
    if (message.kind === 'agent_waiting' && message.request) {
      agentStatus = { ...agentStatus, [message.request.side]: 'thinking' };
    }
    if (message.kind === 'manual_response_accepted') {
      agentStatus = { ...agentStatus, p1: 'executing', p2: 'executing' };
    }
    if (message.kind === 'match_completed') agentStatus = { p1: 'finished', p2: 'finished' };
    if (message.kind === 'match_failed') error = message.error || 'Battle failed.';
    // The control tab tunes settings live; this is the same OBS source it's describing when it
    // says the preview and the source share settings, so it has to actually hear the update.
    if (message.kind === 'renderer_config' && message.config) {
      config = sanitizeRendererConfig({ ...config, ...message.config });
    }
  }
</script>

<svelte:head><title>KoalaBattle OBS Overlay</title></svelte:head>
<BattleRenderer presentation={snapshot?.state || null} {config} overlay {agentStatus} />
<ProductionConsole matchId={data.id} compact overlay />
{#if error}<div class="connection-state" role="status">{error}</div>{/if}

<style>.connection-state{position:fixed;z-index:30;right:1rem;bottom:1rem;padding:.5rem .7rem;border:1px solid rgba(255,255,255,.2);border-radius:999px;background:rgba(8,16,11,.8);color:#ffd26a;font:.65rem var(--mono)}</style>
