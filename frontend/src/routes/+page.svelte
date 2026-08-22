<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { challengeStatusLabel } from '$lib/challenge';
  import type { ChallengeRunSummary, MatchSummary } from '$lib/types';

  let matches: MatchSummary[] = [];
  let runs: ChallengeRunSummary[] = [];
  const ACTIVE_RUN_STATUSES = new Set([
    'drafting', 'preparing', 'training', 'team_review', 'ready', 'battle_queued', 'battling', 'stage_result', 'mega_selection'
  ]);

  onMount(async () => {
    [matches, runs] = await Promise.all([
      api<MatchSummary[]>('/api/matches?limit=3').catch(() => []),
      api<ChallengeRunSummary[]>('/api/challenges').catch(() => [])
    ]);
  });

  $: activeRun = runs.find((run) => ACTIVE_RUN_STATUSES.has(run.status)) || null;
</script>

<section class="hero">
  <span class="eyebrow">A self-hosted Pokémon battle suite</span>
  <h1>Draft a team. Climb Kanto. Watch it happen.</h1>
  <p class="lede">Pick six Pokémon, level and evolve them stage by stage, and fight your way from Brock to Champion Blue — every battle a real Pokémon Showdown match, recorded and replayable.</p>
  <div class="actions">
    {#if activeRun}
      <a class="button" href={`/challenges/${activeRun.id}`}><i class="ph ph-map-trifold" aria-hidden="true"></i>Continue your run</a>
    {:else}
      <a class="button" href="/challenges/new"><i class="ph ph-map-trifold" aria-hidden="true"></i>Start Draft</a>
    {/if}
    <a class="button secondary" href="/new"><i class="ph ph-sword" aria-hidden="true"></i>Start a battle</a>
  </div>
</section>
<section class="principles">
  <article><span><i class="ph ph-map-trifold" aria-hidden="true"></i></span><h2>Draft the Kanto Gauntlet</h2><p>Six picks from rotating Generation + Type offers, then Brock through Champion Blue in one continuous run.</p></article>
  <article><span><i class="ph ph-sparkle" aria-hidden="true"></i></span><h2>Level and evolve as you climb</h2><p>Your team follows the campaign's own level curve and evolves between stages — never mid-battle.</p></article>
  <article><span><i class="ph ph-play-circle" aria-hidden="true"></i></span><h2>Every fight is a real battle</h2><p>Pokémon Showdown decides every move, every stat, every outcome. Watch live, at 4× speed, or after the fact.</p></article>
</section>
{#if matches.length}
  <section class="recent"><div><span class="eyebrow">Recent archive</span><h2>Continue where you left off</h2></div>{#each matches as match}<a href={`/replay/${match.id}`}><strong>{match.config.players[0].display_name} <i>vs</i> {match.config.players[1].display_name}</strong><span class={`status-pill ${match.status}`}>{match.status}</span></a>{/each}</section>
{/if}
{#if runs.length}
  <section class="recent"><div><span class="eyebrow">Draft history</span><h2>Your runs</h2></div>{#each runs.slice(0, 4) as run}<a href={`/challenges/${run.id}`}><strong>{run.name}<small>{run.stages_cleared} / {run.stage_count} cleared</small></strong><span class={`status-pill ${run.status}`}>{challengeStatusLabel(run.status)}</span></a>{/each}</section>
{/if}

<style>
  .principles article>span{display:flex;align-items:center;gap:.4rem}.principles article>span .ph{font-size:1.05rem;color:var(--accent)}
  .hero { padding:clamp(1rem,7vw,6rem) 0 5rem; }
  .principles { display:grid; grid-template-columns:repeat(3,1fr); border-block:1px solid var(--border); }
  .principles article { padding:2rem; border-right:1px solid var(--border); } .principles article:last-child { border:0; }
  .principles h2 { margin:.7rem 0 .5rem; font-size:1.1rem; } .principles p { margin:0; color:var(--muted); line-height:1.6; }
  .recent { display:grid; grid-template-columns:1fr 2fr; gap:2rem; margin-top:3rem; } .recent h2 { margin:.4rem 0; }
  .recent > a { display:flex; align-items:center; justify-content:space-between; padding:1rem 0; border-bottom:1px solid var(--border); } .recent i { color:var(--muted); font-weight:400; }
  .recent strong small{display:block;margin-top:.15rem;color:var(--muted);font:.68rem var(--mono);font-weight:500}
  @media(max-width:720px){ .principles,.recent{grid-template-columns:1fr}.principles article{border-right:0;border-bottom:1px solid var(--border)} }
</style>
