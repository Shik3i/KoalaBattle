<script lang="ts">
  import { onMount } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import { getPresentationMatch, wsBase } from '$lib/api';
  import { loadRendererConfig } from '$lib/presentation/config';
  import { PresentationTimeline } from '$lib/presentation/timeline';
  import { defaultRendererConfig, type RendererConfig, type TimelineSnapshot } from '$lib/presentation/types';
  import type { BattleEvent, MatchArchive } from '$lib/types';
  export let data: { id: string };
  let match: MatchArchive | null = null;
  let timeline: PresentationTimeline | null = null;
  let snapshot: TimelineSnapshot | null = null;
  let config: RendererConfig = defaultRendererConfig();
  let socket: WebSocket | null = null;
  let error = '';
  onMount(() => { config = loadRendererConfig(); void connect(); return () => { socket?.close(); timeline?.destroy(); }; });
  async function connect() {
    try {
      match = await getPresentationMatch(data.id);
      timeline = new PresentationTimeline(match, match.events, undefined, true);
      timeline.subscribe((value) => (snapshot = value)); timeline.seek(match.events.length); timeline.play();
      socket = new WebSocket(`${wsBase()}/api/matches/${data.id}/stream`);
      socket.onmessage = ({ data: raw }) => {
        const message = JSON.parse(raw) as { kind: string; event?: BattleEvent; match?: MatchArchive };
        if (message.kind === 'battle_event' && message.event) timeline?.append(message.event);
        if (message.kind === 'snapshot' && message.match && match) match = { ...match, status: message.match.status };
        if (message.kind === 'match_completed' && match) match.status = 'completed';
      };
      socket.onerror = () => (error = 'Live spectator updates disconnected.');
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
</script>

<div class="watch-head"><div><span class="eyebrow">Read-only spectator</span><h1>{match?.config.name || (match ? `${match.config.players[0].display_name} vs ${match.config.players[1].display_name}` : 'Loading match…')}</h1></div>{#if match}<span class={`status-pill ${match.status}`}>{match.status}</span>{/if}</div>
<BattleRenderer presentation={snapshot?.state || null} {config} />
{#if match}<div class="watch-links"><span>No control data or provider secrets are available on this route.</span><a href={`/overlay/${match.id}`}>OBS view</a>{#if match.status === 'completed'}<a href={`/replay/${match.id}`}>Replay</a>{/if}</div>{/if}
{#if error}<p class="error">{error}</p>{/if}
<style>.watch-head,.watch-links{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:1rem}.watch-head h1{margin:.2rem 0;font-size:clamp(1.6rem,4vw,3rem)}.watch-links{margin-top:1rem;color:var(--muted);font-size:.72rem}.watch-links a{color:var(--accent);font-weight:700}@media(max-width:620px){.watch-head,.watch-links{align-items:flex-start;flex-direction:column}}</style>
