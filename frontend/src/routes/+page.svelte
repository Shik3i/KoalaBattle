<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { MatchSummary } from '$lib/types';
  let matches: MatchSummary[] = [];
  onMount(async () => { matches = await api<MatchSummary[]>('/api/matches?limit=3').catch(() => []); });
</script>

<section class="hero">
  <span class="eyebrow">Battle production, locally controlled</span>
  <h1>Direct every match. See the whole tournament.</h1>
  <p class="lede">Run isolated Gen 9 Random Battles concurrently, mix API, Manual Web Chat, Fake, and Random agents, then schedule persistent Single Elimination or Round Robin tournaments.</p>
  <div class="actions"><a class="button" href="/admin">Open director →</a><a class="button secondary" href="/tournaments/new">Create tournament</a><a class="button secondary" href="/new">Create match</a></div>
</section>
<section class="principles">
  <article><span>01</span><h2>Sessions isolated</h2><p>Every match owns its engine, agents, waiters, lifecycle, stream, and OBS URL.</p></article>
  <article><span>02</span><h2>Scheduling durable</h2><p>Global and tournament concurrency limits keep queued work bounded.</p></article>
  <article><span>03</span><h2>History independent</h2><p>Recorded events replay without Showdown, providers, or an active runtime.</p></article>
</section>
{#if matches.length}
  <section class="recent"><div><span class="eyebrow">Recent archive</span><h2>Continue where you left off</h2></div>{#each matches as match}<a href={`/replay/${match.id}`}><strong>{match.config.players[0].display_name} <i>vs</i> {match.config.players[1].display_name}</strong><span class={`status-pill ${match.status}`}>{match.status}</span></a>{/each}</section>
{/if}

<style>
  .hero { padding:clamp(1rem,7vw,6rem) 0 5rem; }
  .principles { display:grid; grid-template-columns:repeat(3,1fr); border-block:1px solid var(--border); }
  .principles article { padding:2rem; border-right:1px solid var(--border); } .principles article:last-child { border:0; }
  .principles span { color:var(--accent); font:.7rem var(--mono); } .principles h2 { margin:.7rem 0 .5rem; font-size:1.1rem; } .principles p { margin:0; color:var(--muted); line-height:1.6; }
  .recent { display:grid; grid-template-columns:1fr 2fr; gap:2rem; margin-top:5rem; } .recent h2 { margin:.4rem 0; }
  .recent > a { display:flex; align-items:center; justify-content:space-between; padding:1rem 0; border-bottom:1px solid var(--border); } .recent i { color:var(--muted); font-weight:400; }
  @media(max-width:720px){ .principles,.recent{grid-template-columns:1fr}.principles article{border-right:0;border-bottom:1px solid var(--border)} }
</style>
