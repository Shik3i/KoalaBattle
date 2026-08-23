<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { challengeErrorMessage, challengeStatusLabel, difficultyLabel, standardChallengeDefinition, standardChallengePayload } from '$lib/challenge';
  import type { ChallengeDefinitionSummary, ChallengeRunSummary, ChallengeRunView } from '$lib/types';

  let runs: ChallengeRunSummary[] = [];
  let definitions: ChallengeDefinitionSummary[] = [];
  let historyLoading = true;
  let historyError = '';
  let quickStarting = false;
  let quickStartError = '';

  onMount(() => void loadHistory());

  async function loadHistory() {
    historyLoading = true;
    try {
      const [savedRuns, availableDefinitions] = await Promise.all([
        api<ChallengeRunSummary[]>('/api/challenges'),
        api<ChallengeDefinitionSummary[]>('/api/challenges/definitions')
      ]);
      runs = savedRuns;
      definitions = availableDefinitions;
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

  async function quickStart() {
    if (quickStarting) return;
    quickStarting = true;
    quickStartError = '';
    try {
      const seed = Math.floor(Date.now() / 1000);
      const selected = standardChallengeDefinition(definitions, seed);
      if (!selected) throw new Error('No Draft campaign route is available.');
      const view = await api<ChallengeRunView>('/api/challenges', {
        method: 'POST',
        body: JSON.stringify(
          standardChallengePayload(seed, `${selected.region} Draft Gauntlet`, selected.id)
        )
      });
      if (view.run.current_offer) {
        sessionStorage.setItem(`draft-first-roll:${view.run.id}`, view.run.current_offer.fingerprint);
      }
      await goto(`/challenges/${view.run.id}`);
    } catch (caught) {
      quickStartError = challengeErrorMessage(caught instanceof Error ? caught.message : String(caught));
      quickStarting = false;
    }
  }
</script>

<div class="page-head challenge-head">
  <div>
    <span class="eyebrow">Draft · train · battle · progress</span>
    <h1>Draft</h1>
    <p>Build one roster from disappearing offers, tune automatic recommended EVs, then clear a recorded campaign at fair, equal stage levels.</p>
  </div>
  <div class="challenge-actions">
    <button class="button quick-start" type="button" disabled={quickStarting || historyLoading} aria-label="Quick Start: Fast Auto, Normal difficulty, Fast Watch, base forms only, original teams" on:click={quickStart}>
      <i class={`ph ${quickStarting || historyLoading ? 'ph-spinner-gap spinner' : 'ph-lightning'}`} aria-hidden="true"></i>
      <span><strong>{quickStarting ? 'Starting Draft…' : historyLoading ? 'Loading routes…' : 'Quick Start'}</strong><small>Fast Auto · Normal · Fast Watch</small><small>Base forms · Original teams</small></span>
    </button>
    <a class="button secondary" href="/challenges/new"><i class="ph ph-sliders-horizontal" aria-hidden="true"></i>Customize</a>
  </div>
</div>

{#if quickStartError}<p class="quick-start-error" role="alert">{quickStartError}</p>{/if}

<section class="mode-intro panel" aria-labelledby="challenge-intro-title">
  <div class="intro-copy">
    <span class="eyebrow">Regional Gym Gauntlets</span>
    <h2 id="challenge-intro-title">Your draft. Your team. A real story route.</h2>
    <p>Quick Start chooses a regional route for you. Custom Draft lets you choose a region or run every generation with one shared roster.</p>
  </div>
  <div class="intro-facts">
    <span><i class="ph ph-cards-three" aria-hidden="true"></i><strong>Fresh offers</strong><small>Every shown Pokémon leaves the pool after its round.</small></span>
    <span><i class="ph ph-barbell" aria-hidden="true"></i><strong>Ready to train</strong><small>Recommended legal EVs are applied automatically.</small></span>
    <span><i class="ph ph-scales" aria-hidden="true"></i><strong>Four difficulties</strong><small>Your team always follows the campaign's level curve. Hard, Expert and Nightmare only raise the opponent +5, +10 or +15 levels above it.</small></span>
    <span><i class="ph ph-record" aria-hidden="true"></i><strong>Recorded matches</strong><small>Play yourself or use AI; every stage gets a replay.</small></span>
  </div>
  <details>
    <summary>How Draft works</summary>
    <ol>
      <li>Choose who battles: yourself, Fast Auto, or an LLM agent.</li>
      <li>Choose one Pokémon from each deterministic offer. Quick Start removes evolved forms but keeps single-stage Pokémon; Custom Draft can allow every form.</li>
      <li>Keep or tune each Pokémon's recommended EVs, choose legal abilities, and complete Showdown sets.</li>
      <li>Play every stage through the normal KoalaBattle match engine — your team levels and evolves as you climb.</li>
    </ol>
  </details>
</section>

{#if definitions.length}<section class="campaign-library" aria-labelledby="campaign-library-title"><header><div><span class="eyebrow">Real story routes</span><h2 id="campaign-library-title">Choose your region</h2></div><span>{definitions.length} routes</span></header><div class="campaign-grid">{#each definitions as definition}<a class="panel campaign-card" href={`/challenges/new?definition=${definition.id}`}><div class="campaign-card-head"><span class="generation-mark">{definition.campaign_kind === 'multi-generation' ? 'I–IX' : `GEN ${definition.generation}`}</span><i class={`ph ${definition.campaign_kind === 'multi-generation' ? 'ph-arrows-clockwise' : 'ph-map-trifold'}`} aria-hidden="true"></i></div><h3>{definition.name}</h3><p>{definition.stage_count_label || `${definition.stage_count} stages`} · {definition.campaign_kind === 'multi-generation' ? 'one shared draft' : definition.region}</p><small>{definition.specialties.slice(0, 4).join(' · ')}</small></a>{/each}</div></section>{/if}

<section class="history" aria-labelledby="history-title">
  <header><div><span class="eyebrow">Durable run history</span><h2 id="history-title">Your Draft runs</h2></div>{#if runs.length}<span>{runs.length} saved {runs.length === 1 ? 'run' : 'runs'}</span>{/if}</header>
  {#if historyLoading}
    <p class="lede" role="status">Loading Draft history…</p>
  {:else if historyError}
    <section class="empty panel" role="alert"><h3>History could not be loaded</h3><p>{historyError}</p><button class="button secondary" on:click={loadHistory}>Retry</button></section>
  {:else if !runs.length}
    <section class="empty panel"><i class="ph ph-map-trifold" aria-hidden="true"></i><h3>No Draft runs yet</h3><p>Start a regional run. Your draft, consumed offers, stage matches, results, and replays will stay here.</p><a class="button" href="/challenges/new">Start a Draft Gauntlet</a></section>
  {:else}
    <div class="run-list">
      {#each runs as run}
        <a class="panel" href={`/challenges/${run.id}`}>
          <div class="run-name"><span class="eyebrow">{run.definition_name}</span><h3>{run.name}</h3><small>Updated {new Date(run.updated_at).toLocaleString()}</small></div>
          <div class="progress"><strong>{run.stages_cleared}/{run.stage_count}</strong><span>stages cleared</span></div>
          <div class="run-state"><span class={`status-pill ${run.status}`}>{challengeStatusLabel(run.status)}</span><small>{currentProgress(run)} · {difficultyLabel(run.difficulty)}</small></div>
          <i class="ph ph-caret-right" aria-hidden="true"></i>
        </a>
      {/each}
    </div>
  {/if}
</section>

<style>
  .challenge-head{margin-bottom:1rem}.challenge-head>div:first-child{max-width:720px}.challenge-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:.5rem}.quick-start{min-width:13.5rem}.quick-start>span{display:grid;justify-items:start;line-height:1.15}.quick-start strong{font-size:.78rem}.quick-start small{font:500 .53rem/1.25 var(--mono);opacity:.75}.quick-start-error{margin:-.45rem 0 1rem;padding:.65rem .8rem;border:1px solid color-mix(in srgb,var(--danger) 55%,var(--border));border-radius:.6rem;background:color-mix(in srgb,var(--danger) 8%,var(--panel));color:var(--danger);font-size:.75rem}.spinner{animation:spin .8s linear infinite}.challenge-head p,.panel p,.empty p{color:var(--muted);line-height:1.55}.mode-intro{display:grid;grid-template-columns:1.05fr 1.6fr;gap:1.25rem;padding:1.4rem;border-color:color-mix(in srgb,var(--accent) 35%,var(--border));background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 7%,var(--panel)),var(--panel))}.intro-copy h2{margin:.3rem 0;font-size:1.55rem}.intro-copy p{margin-bottom:0}.intro-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem}.intro-facts>span{display:grid;grid-template-columns:auto 1fr;gap:.12rem .55rem;padding:.7rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.intro-facts i{grid-row:1/3;align-self:center;color:var(--accent);font-size:1.25rem}.intro-facts strong{font-size:.78rem}.intro-facts small{color:var(--muted);font:.62rem/1.35 var(--mono)}.mode-intro>details{grid-column:1/-1}.mode-intro ol{margin:.7rem 0 0;padding-left:1.2rem;color:var(--muted);font-size:.78rem;line-height:1.65}.campaign-library{margin-top:1.5rem}.campaign-library>header{display:flex;align-items:end;justify-content:space-between;margin-bottom:.65rem}.campaign-library h2{margin:.25rem 0}.campaign-library>header>span{color:var(--muted);font:.65rem var(--mono)}.campaign-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.65rem}.campaign-card{display:grid;gap:.25rem;padding:1rem;box-shadow:none;transition:transform .16s ease,border-color .16s ease}.campaign-card:hover,.campaign-card:focus-visible{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}.campaign-card-head{display:flex;align-items:center;justify-content:space-between;color:var(--accent)}.campaign-card-head i{font-size:1.2rem}.generation-mark{font:700 .58rem var(--mono);letter-spacing:.08em}.campaign-card h3{margin:.35rem 0 0;font-size:1rem}.campaign-card p{margin:0;font:.62rem var(--mono)}.campaign-card small{color:var(--muted);font-size:.62rem}.history{margin-top:1.5rem}.history>header{display:flex;align-items:end;justify-content:space-between;margin-bottom:.65rem}.history h2{margin:.25rem 0}.history>header>span{color:var(--muted);font:.65rem var(--mono)}.run-list{display:grid;gap:.65rem}.run-list>a{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(180px,auto) auto;align-items:center;gap:1.4rem;padding:1rem 1.2rem;box-shadow:none;transition:transform .16s ease,border-color .16s ease}.run-list>a:hover,.run-list>a:focus-visible{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}.run-name h3{margin:.25rem 0}.run-name small,.run-state small{display:block;color:var(--muted);font:.58rem var(--mono)}.progress{display:grid;text-align:right}.progress strong{font-size:1.2rem}.progress span{color:var(--muted);font:.58rem var(--mono)}.run-state{display:grid;justify-items:start;gap:.25rem}.empty{display:grid;place-items:center;padding:3rem;text-align:center}.empty>.ph{color:var(--accent);font-size:2rem}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:950px){.campaign-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:850px){.page-head{align-items:stretch;flex-direction:column}.challenge-actions{justify-content:flex-start}.mode-intro{grid-template-columns:1fr}.intro-facts{grid-template-columns:1fr 1fr}.run-list>a{grid-template-columns:1fr auto}.run-list>a>.ph{display:none}.run-state{grid-column:1/-1}.progress{text-align:right}}@media(max-width:560px){.challenge-actions>*{flex:1}.intro-facts,.campaign-grid,.run-list>a{grid-template-columns:1fr}.progress{text-align:left}.history>header,.campaign-library>header{align-items:flex-start;flex-direction:column}}@media(prefers-reduced-motion:reduce){.spinner{animation:none}}
</style>
