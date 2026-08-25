<script lang="ts">
  import { onMount } from 'svelte';
  import Skeleton from '$lib/Skeleton.svelte';
  import { api } from '$lib/api';
  import { challengeStatusLabel } from '$lib/challenge';
  import type { ChallengeDefinitionSummary, ChallengeRunSummary, MatchSummary } from '$lib/types';

  let matches: MatchSummary[] = [];
  let runs: ChallengeRunSummary[] = [];
  let definitions: ChallengeDefinitionSummary[] = [];
  let loading = true;
  let loadError = '';
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

  async function load() {
    loading = true;
    loadError = '';
    try {
      // The landing page shows four recent runs plus the newest active one. Fetching
      // the full default page of 100 made the whole history the home page's problem.
      const [savedMatches, savedRuns, availableDefinitions] = await Promise.all([
        api<MatchSummary[]>('/api/matches?limit=3'),
        api<ChallengeRunSummary[]>('/api/challenges?limit=12'),
        api<ChallengeDefinitionSummary[]>('/api/challenges/definitions')
      ]);
      matches = savedMatches;
      runs = savedRuns;
      definitions = availableDefinitions;
    } catch (caught) {
      // These calls used to swallow their own failure and resolve to []. With the API
      // down the page then rendered as a tidy, permanently empty archive rather than
      // saying anything was wrong.
      loadError = caught instanceof Error ? caught.message : String(caught);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();

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
  $: lastRun = runs.find((run) => !ACTIVE_RUN_STATUSES.has(run.status)) || null;
  $: featuredRun = activeRun || lastRun;
  $: featuredProgress = featuredRun && featuredRun.stage_count
    ? Math.round((featuredRun.stages_cleared / featuredRun.stage_count) * 100)
    : 0;
</script>

<!--
  The hero is two columns on desktop. It used to be a single narrow measure pinned left,
  which left the entire right half of a 1440px viewport empty — the page opened on more
  background than content. The second column is the reader's own state, built from data
  this page already fetches, so it costs no extra request.
-->
<section class="hero">
  <div class="hero-copy">
    <span class="eyebrow">A self-hosted Pokémon battle suite</span>
    <!-- The rotating region ends the headline. It has to reserve the width of the
         longest region name so the sentence does not reshape every few seconds, and any
         reserved width that the current name does not use shows up as blank space — which
         is only invisible at the end of a line. It sat mid-sentence before, where that
         slack read as a broken gap before "Watch it happen"; that clause moved into the
         lede. The full stop belongs to the span for the same reason: a generation badge
         used to sit between word and stop, which read as a typo. -->
    <h1>Draft a team.<br />Climb <span class="route-roll" class:rolling={routeRolling} aria-live="polite" aria-atomic="true">{activeRoute ? activeRoute.region : 'every region'}.</span></h1>
    <p class="lede">Watch it happen: pick six Pokémon, level and evolve them stage by stage, and fight through authentic regional Gym, Elite Four and Champion routes — every battle a real Pokémon Showdown match, recorded and replayable.</p>
    <div class="actions">
      {#if activeRun}
        <a class="button" href={`/challenges/${activeRun.id}`}><i class="ph ph-map-trifold" aria-hidden="true"></i>Continue your run</a>
      {:else}
        <a class="button" href="/challenges/new"><i class="ph ph-map-trifold" aria-hidden="true"></i>Start Draft</a>
      {/if}
      <a class="button secondary" href="/new"><i class="ph ph-sword" aria-hidden="true"></i>Start a battle</a>
    </div>
  </div>

  <aside class="hero-side" aria-label="Your current state">
    {#if loading}
      <Skeleton rows={1} variant="card" label="Loading your run…" />
    {:else if loadError}
      <div class="side-card panel side-error" role="alert">
        <i class="ph ph-plugs" aria-hidden="true"></i>
        <strong>The API is not answering</strong>
        <p>{loadError}</p>
        <button class="button secondary compact" type="button" on:click={load}><i class="ph ph-arrow-clockwise" aria-hidden="true"></i>Try again</button>
      </div>
    {:else if featuredRun}
      <a class="side-card panel side-run" href={`/challenges/${featuredRun.id}`}>
        <span class="eyebrow">{activeRun ? 'Run in progress' : 'Last run'}</span>
        <strong>{featuredRun.name}</strong>
        <small>{featuredRun.definition_name}</small>
        <div class="side-progress" role="img" aria-label={`${featuredRun.stages_cleared} of ${featuredRun.stage_count} stages cleared`}>
          <div style={`width:${featuredProgress}%`}></div>
        </div>
        <div class="side-meta">
          <span><b>{featuredRun.stages_cleared}/{featuredRun.stage_count}</b> stages</span>
          <span class={`status-pill ${featuredRun.status}`}>{challengeStatusLabel(featuredRun.status)}</span>
        </div>
      </a>
    {:else}
      <div class="side-card panel side-empty">
        <i class="ph ph-map-trifold" aria-hidden="true"></i>
        <strong>No run yet</strong>
        <p>{regionalRoutes.length || 'Ten'} regional routes are ready to draft against.</p>
        <a class="button compact" href="/challenges/new">Draft your first team</a>
      </div>
    {/if}
  </aside>
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
  .principles article>span{display:flex;align-items:center;gap:.4rem}.principles article>span .ph{font-size:1.35rem;color:var(--accent)}
  .hero { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr); align-items:center; gap:clamp(1.5rem,4vw,3.5rem); padding:clamp(1rem,5vw,4.5rem) 0 4.5rem; }
  .hero-copy h1{max-width:20ch;text-wrap:balance}
  .route-roll{display:inline-block;min-width:6.5ch;color:var(--accent);white-space:nowrap;will-change:transform,opacity}.route-roll.rolling{animation:route-roll-in .42s ease both}@keyframes route-roll-in{0%{transform:translateY(.35em);opacity:.15}65%{transform:translateY(-.06em);opacity:1}100%{transform:translateY(0);opacity:1}}
  .side-card{display:grid;gap:.5rem;padding:1.4rem;text-align:left}
  .side-card strong{font-size:1.05rem;line-height:1.25}
  .side-card small,.side-card p{margin:0;color:var(--muted);font-size:var(--meta-strong);line-height:1.5}
  .side-card>.ph{font-size:1.9rem;color:var(--accent)}
  .side-run{transition:transform .2s cubic-bezier(.2,.8,.2,1),border-color .2s ease}
  .side-run:hover,.side-run:focus-visible{transform:translateY(-3px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}
  .side-progress{height:.4rem;margin-top:.35rem;overflow:hidden;border-radius:999px;background:var(--surface)}
  .side-progress>div{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--accent),var(--accent-strong));transition:width .5s cubic-bezier(.2,.8,.2,1)}
  .side-meta{display:flex;align-items:center;justify-content:space-between;gap:.6rem;margin-top:.2rem;color:var(--muted);font:var(--meta) var(--mono)}
  .side-meta b{color:var(--text);font-size:1rem}
  .side-error{border-color:color-mix(in srgb,var(--danger) 45%,var(--border))}.side-error>.ph{color:var(--danger)}.side-error p{overflow-wrap:anywhere;font-size:var(--meta)}
  .side-error .button,.side-empty .button{justify-self:start;margin-top:.35rem}
  .principles { display:grid; grid-template-columns:repeat(3,1fr); border-block:1px solid var(--border); }
  .principles article { padding:2rem; border-right:1px solid var(--border); } .principles article:last-child { border:0; }
  .principles h2 { margin:.7rem 0 .5rem; font-size:1.1rem; } .principles p { margin:0; color:var(--muted); line-height:1.6; }
  .recent { display:grid; grid-template-columns:1fr 2fr; gap:2rem; margin-top:3rem; } .recent h2 { margin:.4rem 0; }
  .recent > a { display:flex; align-items:center; justify-content:space-between; padding:1rem 0; border-bottom:1px solid var(--border); } .recent i { color:var(--muted); font-weight:400; }
  .recent strong small{display:block;margin-top:.15rem;color:var(--muted);font:0.72rem var(--mono);font-weight:500}
  @media(max-width:940px){ .hero{grid-template-columns:1fr;gap:2rem;padding-bottom:3rem}.hero-copy h1{max-width:24ch} }
  @media(max-width:720px){ .principles,.recent{grid-template-columns:1fr}.principles article{border-right:0;border-bottom:1px solid var(--border)} }
  @media(prefers-reduced-motion:reduce){.route-roll.rolling{animation:none}}
</style>
