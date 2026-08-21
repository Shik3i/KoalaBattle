<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { challengeStatusLabel } from '$lib/challenge';
  import type { ChallengeRunSummary } from '$lib/types';

  let runs: ChallengeRunSummary[] = [];
  let historyLoading = true;
  let historyError = '';

  onMount(() => void loadHistory());

  async function loadHistory() {
    historyLoading = true;
    try {
      runs = await api<ChallengeRunSummary[]>('/api/challenges');
      historyError = '';
    } catch (caught) {
      historyError = caught instanceof Error ? caught.message : String(caught);
    } finally {
      historyLoading = false;
    }
  }

  function currentProgress(run: ChallengeRunSummary) {
    if (run.status === 'completed') return 'Champion cleared';
    if (run.status === 'cancelled') return 'Run ended';
    if (run.status === 'drafting') return 'Continue the draft';
    if (run.status === 'training' || run.status === 'team_review') return 'Finish the roster';
    return `Stage ${Math.min(run.current_stage_index + 1, run.stage_count)} of ${run.stage_count}`;
  }
</script>

<div class="page-head challenge-head">
  <div>
    <span class="eyebrow">Draft · train · battle · progress</span>
    <h1>Challenges</h1>
    <p>Build one roster from disappearing offers, tune automatic recommended EVs, then clear a recorded campaign at fair, equal stage levels.</p>
  </div>
  <a class="button" href="/challenges/new"><i class="ph ph-plus" aria-hidden="true"></i>New Challenge</a>
</div>

<section class="mode-intro panel" aria-labelledby="challenge-intro-title">
  <div class="intro-copy">
    <span class="eyebrow">Kanto Gym Gauntlet</span>
    <h2 id="challenge-intro-title">Your draft. Your team. Thirteen real battles.</h2>
    <p>Draft six Pokémon from Generation + Type offers, allocate training, finish legal sets, then face the Gym Leaders, Elite Four, and Champion.</p>
  </div>
  <div class="intro-facts">
    <span><i class="ph ph-cards-three" aria-hidden="true"></i><strong>Fresh offers</strong><small>Every shown Pokémon leaves the pool after its round.</small></span>
    <span><i class="ph ph-barbell" aria-hidden="true"></i><strong>Ready to train</strong><small>Recommended legal EVs are applied automatically.</small></span>
    <span><i class="ph ph-scales" aria-hidden="true"></i><strong>Equal levels</strong><small>Both teams use the exact stage level.</small></span>
    <span><i class="ph ph-record" aria-hidden="true"></i><strong>Recorded matches</strong><small>Play yourself or use AI; every stage gets a replay.</small></span>
  </div>
  <details>
    <summary>How a Challenge works</summary>
    <ol>
      <li>Choose who drafts and who battles. These choices are independent.</li>
      <li>Choose one Pokémon from each deterministic offer. All shown options are consumed.</li>
      <li>Keep or tune each Pokémon's recommended EVs, choose legal abilities, and complete Showdown sets.</li>
      <li>Play every stage through the normal KoalaBattle match engine.</li>
    </ol>
  </details>
</section>

<section class="history" aria-labelledby="history-title">
  <header><div><span class="eyebrow">Durable run history</span><h2 id="history-title">Your Challenges</h2></div>{#if runs.length}<span>{runs.length} saved {runs.length === 1 ? 'run' : 'runs'}</span>{/if}</header>
  {#if historyLoading}
    <p class="lede" role="status">Loading Challenge history…</p>
  {:else if historyError}
    <section class="empty panel" role="alert"><h3>History could not be loaded</h3><p>{historyError}</p><button class="button secondary" on:click={loadHistory}>Retry</button></section>
  {:else if !runs.length}
    <section class="empty panel"><i class="ph ph-map-trifold" aria-hidden="true"></i><h3>No Challenges yet</h3><p>Create a Kanto run. Your draft, consumed offers, stage matches, results, and replays will stay here.</p><a class="button" href="/challenges/new">Start the Kanto Gauntlet</a></section>
  {:else}
    <div class="run-list">
      {#each runs as run}
        <a class="panel" href={`/challenges/${run.id}`}>
          <div class="run-name"><span class="eyebrow">{run.definition_name}</span><h3>{run.name}</h3><small>Updated {new Date(run.updated_at).toLocaleString()}</small></div>
          <div class="progress"><strong>{run.stages_cleared}/{run.stage_count}</strong><span>stages cleared</span></div>
          <div class="run-state"><span class={`status-pill ${run.status}`}>{challengeStatusLabel(run.status)}</span><small>{currentProgress(run)}</small></div>
          <i class="ph ph-caret-right" aria-hidden="true"></i>
        </a>
      {/each}
    </div>
  {/if}
</section>

<style>
  .challenge-head{margin-bottom:1rem}.challenge-head>div{max-width:720px}.challenge-head p,.panel p,.empty p{color:var(--muted);line-height:1.55}.mode-intro{display:grid;grid-template-columns:1.05fr 1.6fr;gap:1.25rem;padding:1.4rem;border-color:color-mix(in srgb,var(--accent) 35%,var(--border));background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 7%,var(--panel)),var(--panel))}.intro-copy h2{margin:.3rem 0;font-size:1.55rem}.intro-copy p{margin-bottom:0}.intro-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem}.intro-facts>span{display:grid;grid-template-columns:auto 1fr;gap:.12rem .55rem;padding:.7rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.intro-facts i{grid-row:1/3;align-self:center;color:var(--accent);font-size:1.25rem}.intro-facts strong{font-size:.78rem}.intro-facts small{color:var(--muted);font:.62rem/1.35 var(--mono)}.mode-intro>details{grid-column:1/-1}.mode-intro ol{margin:.7rem 0 0;padding-left:1.2rem;color:var(--muted);font-size:.78rem;line-height:1.65}.history{margin-top:1.5rem}.history>header{display:flex;align-items:end;justify-content:space-between;margin-bottom:.65rem}.history h2{margin:.25rem 0}.history>header>span{color:var(--muted);font:.65rem var(--mono)}.run-list{display:grid;gap:.65rem}.run-list>a{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(180px,auto) auto;align-items:center;gap:1.4rem;padding:1rem 1.2rem;box-shadow:none;transition:transform .16s ease,border-color .16s ease}.run-list>a:hover,.run-list>a:focus-visible{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}.run-name h3{margin:.25rem 0}.run-name small,.run-state small{display:block;color:var(--muted);font:.58rem var(--mono)}.progress{display:grid;text-align:right}.progress strong{font-size:1.2rem}.progress span{color:var(--muted);font:.58rem var(--mono)}.run-state{display:grid;justify-items:start;gap:.25rem}.empty{display:grid;place-items:center;padding:3rem;text-align:center}.empty>.ph{color:var(--accent);font-size:2rem}@media(max-width:850px){.page-head{align-items:stretch;flex-direction:column}.mode-intro{grid-template-columns:1fr}.intro-facts{grid-template-columns:1fr 1fr}.run-list>a{grid-template-columns:1fr auto}.run-list>a>.ph{display:none}.run-state{grid-column:1/-1}.progress{text-align:right}}@media(max-width:560px){.intro-facts,.run-list>a{grid-template-columns:1fr}.progress{text-align:left}.history>header{align-items:flex-start;flex-direction:column}}
</style>
