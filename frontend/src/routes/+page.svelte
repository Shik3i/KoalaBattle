<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { challengeStatusLabel } from '$lib/challenge';
  import type { ChallengeDefinitionSummary, ChallengeRunSummary, MatchSummary } from '$lib/types';

  let matches: MatchSummary[] = [];
  let runs: ChallengeRunSummary[] = [];
  let definitions: ChallengeDefinitionSummary[] = [];
  let routeIndex = 0;
  let routeRolling = false;
  let routeTimer: ReturnType<typeof setInterval> | null = null;
  let routeAnimationTimer: ReturnType<typeof setTimeout> | null = null;
  const ACTIVE_RUN_STATUSES = new Set([
    'drafting', 'preparing', 'training', 'team_review', 'ready', 'battle_queued', 'battling', 'stage_result', 'mega_selection'
  ]);

  $: regionalRoutes = definitions
    .filter((definition) => definition.campaign_kind === 'regional')
    .sort((left, right) => left.generation - right.generation || left.id.localeCompare(right.id));
  $: activeRoute = regionalRoutes.length ? regionalRoutes[routeIndex % regionalRoutes.length] : null;

  onMount(() => {
    void Promise.all([
      api<MatchSummary[]>('/api/matches?limit=3').catch(() => []),
      api<ChallengeRunSummary[]>('/api/challenges').catch(() => []),
      api<ChallengeDefinitionSummary[]>('/api/challenges/definitions').catch(() => [])
    ]).then(([savedMatches, savedRuns, availableDefinitions]) => {
      matches = savedMatches;
      runs = savedRuns;
      definitions = availableDefinitions;
    });

    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      routeTimer = setInterval(() => {
        if (regionalRoutes.length < 2) return;
        routeRolling = true;
        if (routeAnimationTimer) clearTimeout(routeAnimationTimer);
        routeAnimationTimer = setTimeout(() => {
          routeIndex = (routeIndex + 1) % regionalRoutes.length;
          routeRolling = false;
        }, 220);
      }, 2800);
    }

    return () => {
      if (routeTimer) clearInterval(routeTimer);
      if (routeAnimationTimer) clearTimeout(routeAnimationTimer);
    };
  });

  $: activeRun = runs.find((run) => ACTIVE_RUN_STATUSES.has(run.status)) || null;
</script>

<section class="hero">
  <span class="eyebrow">A self-hosted Pokémon battle suite</span>
  <h1>Draft a team. Climb <span class="route-roll" class:rolling={routeRolling} aria-live="polite" aria-atomic="true">{#if activeRoute}<span>{activeRoute.region}</span><small>Gen {activeRoute.generation}</small>{:else}<span>the regions</span>{/if}</span>. Watch it happen.</h1>
  <p class="lede">Pick six Pokémon, level and evolve them stage by stage, and fight through authentic regional Gym, Elite Four and Champion routes — every battle a real Pokémon Showdown match, recorded and replayable.</p>
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
  <article><span><i class="ph ph-map-trifold" aria-hidden="true"></i></span><h2>Draft a regional Gauntlet</h2><p>Six picks from rotating Generation + Type offers, then climb a real regional story route in one continuous run.</p></article>
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
  .route-roll{display:inline-flex;align-items:baseline;gap:.35em;min-width:7.2ch;color:var(--accent);white-space:nowrap;will-change:transform,opacity}.route-roll small{font:600 .38em var(--mono);letter-spacing:.08em;color:var(--muted);text-transform:uppercase}.route-roll.rolling{animation:route-roll-in .42s ease both}@keyframes route-roll-in{0%{transform:translateY(.35em);opacity:.15}65%{transform:translateY(-.06em);opacity:1}100%{transform:translateY(0);opacity:1}}
  .principles { display:grid; grid-template-columns:repeat(3,1fr); border-block:1px solid var(--border); }
  .principles article { padding:2rem; border-right:1px solid var(--border); } .principles article:last-child { border:0; }
  .principles h2 { margin:.7rem 0 .5rem; font-size:1.1rem; } .principles p { margin:0; color:var(--muted); line-height:1.6; }
  .recent { display:grid; grid-template-columns:1fr 2fr; gap:2rem; margin-top:3rem; } .recent h2 { margin:.4rem 0; }
  .recent > a { display:flex; align-items:center; justify-content:space-between; padding:1rem 0; border-bottom:1px solid var(--border); } .recent i { color:var(--muted); font-weight:400; }
  .recent strong small{display:block;margin-top:.15rem;color:var(--muted);font:.68rem var(--mono);font-weight:500}
  @media(max-width:720px){ .principles,.recent{grid-template-columns:1fr}.principles article{border-right:0;border-bottom:1px solid var(--border)} }
  @media(prefers-reduced-motion:reduce){.route-roll.rolling{animation:none}}
</style>
