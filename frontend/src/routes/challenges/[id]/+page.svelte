<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api, copyText } from '$lib/api';
  import {
    challengeErrorMessage,
    challengeStatusLabel,
    draftChoiceIndexForKey,
    emptyEvSpread,
    evAllocationTotal,
    evSpreadTotal,
    formatDuration,
    legalEvValue,
    type EvStat
  } from '$lib/challenge';
  import type { ChallengeRunView, EvSpread, PricingStatus } from '$lib/types';

  export let data: { id: string };
  const statEntries: Array<[EvStat, string]> = [['hp','HP'],['atk','Atk'],['def','Def'],['spa','SpA'],['spd','SpD'],['spe','Spe']];
  const presets: Array<[string, EvSpread]> = [
    ['Fast physical', { hp: 0, atk: 252, def: 0, spa: 0, spd: 4, spe: 252 }],
    ['Fast special', { hp: 0, atk: 0, def: 0, spa: 252, spd: 4, spe: 252 }],
    ['Physical bulk', { hp: 252, atk: 0, def: 252, spa: 0, spd: 4, spe: 0 }]
  ];

  let view: ChallengeRunView | null = null;
  let pricing: PricingStatus | null = null;
  let allocations: Record<string, EvSpread> = {};
  let teamText = '';
  let loading = '';
  let initialLoading = true;
  let error = '';
  let technicalError = '';
  let copied = false;
  let agentFailed = false;
  let trainingNotice = '';
  let timer: ReturnType<typeof setInterval> | null = null;
  let initializedRun = '';
  let scaffoldRun = '';

  $: run = view?.run;
  $: evUsed = evAllocationTotal(allocations);
  $: evRemaining = Math.max(0, (run?.definition.training_rules.global_ev_budget || 0) - evUsed);
  $: latestResult = run?.stage_results.length ? run.stage_results[run.stage_results.length - 1] : null;
  $: latestStage = latestResult ? view?.stages[latestResult.stage_index] : null;
  $: if (run?.status === 'team_review' && view?.team_export_scaffold && scaffoldRun !== run.id && !teamText) {
    scaffoldRun = run.id;
    teamText = view.team_export_scaffold;
  }

  onMount(() => {
    void refresh();
    void api<PricingStatus>('/api/challenge-prices/status').then((result) => (pricing = result)).catch(() => null);
    timer = setInterval(() => { if (view?.run.active_match_id) void refresh(false); }, 3000);
    window.addEventListener('keydown', handleDraftShortcut);
    return () => {
      if (timer) clearInterval(timer);
      window.removeEventListener('keydown', handleDraftShortcut);
    };
  });

  function handleDraftShortcut(event: KeyboardEvent) {
    const target = event.target as HTMLElement | null;
    if (target?.matches('input, textarea, select, button') || target?.isContentEditable) return;
    if (event.metaKey || event.ctrlKey || event.altKey || loading || run?.status !== 'drafting' || run.draft_controller.kind !== 'human') return;
    const index = draftChoiceIndexForKey(event.key);
    const option = index == null ? null : run.current_offer?.options[index];
    if (!option) return;
    event.preventDefault();
    void pick(option.entry_id);
  }

  function setView(nextView: ChallengeRunView) {
    const nextRun = nextView.run;
    const nextAllocations = nextRun.id === initializedRun ? { ...allocations } : {};
    for (const pick of nextRun.picks) {
      const entryId = pick.candidate.entry_id;
      if (!(entryId in nextAllocations)) {
        nextAllocations[entryId] = nextRun.ev_allocations[entryId] || emptyEvSpread();
      }
    }
    allocations = nextAllocations;
    initializedRun = nextRun.id;
    view = nextView;
  }

  async function refresh(showLoading = true) {
    if (showLoading && !view) initialLoading = true;
    try {
      setView(await api<ChallengeRunView>(`/api/challenges/${data.id}`));
      error = ''; technicalError = '';
    } catch (caught) {
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
    } finally {
      initialLoading = false;
    }
  }

  async function mutate(path: string, body: Record<string, unknown>, label: string) {
    if (!run || loading) return false;
    loading = label; error = ''; technicalError = '';
    try {
      setView(await api<ChallengeRunView>(`/api/challenges/${run.id}${path}`, { method: 'POST', body: JSON.stringify(body) }));
      agentFailed = false;
      return true;
    } catch (caught) {
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
      if (technicalError.toLowerCase().includes('stale') || technicalError.toLowerCase().includes('not waiting')) await refresh(false);
      if (label === 'agent') agentFailed = true;
      return false;
    } finally {
      loading = '';
    }
  }

  async function pick(entryId: string) {
    if (!run?.current_offer) return;
    await mutate('/draft/pick', { entry_id: entryId, offer_fingerprint: run.current_offer.fingerprint, expected_revision: run.revision }, `pick:${entryId}`);
  }
  async function reroll() {
    if (!run?.current_offer || !confirm(`Use one reroll? ${run.rerolls_remaining - 1} will remain.`)) return;
    await mutate('/draft/reroll', { offer_fingerprint: run.current_offer.fingerprint, expected_revision: run.revision }, 'reroll');
  }
  async function agentDraft() { if (run) await mutate('/draft/agent', { expected_revision: run.revision }, 'agent'); }
  async function takeOverDraft() { if (run && await mutate('/draft/takeover', { expected_revision: run.revision }, 'takeover')) agentFailed = false; }
  async function saveTraining() { if (run) await mutate('/training', { allocations, expected_revision: run.revision }, 'training'); }
  async function finalizeTeam() {
    if (!run || !confirm('Validate and lock this exact roster for the campaign? Drafted species and Training Camp EVs cannot be changed after this step.')) return;
    await mutate('/team', { team_text: teamText, expected_revision: run.revision }, 'team');
  }
  async function launch() {
    if (!run || loading) return;
    loading = 'launch'; error = ''; technicalError = '';
    try {
      const result = await api<{ run: ChallengeRunView; match: { id: string } }>(`/api/challenges/${run.id}/launch`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision }) });
      setView(result.run);
      await goto(`/battle/${result.match.id}`);
    } catch (caught) {
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
      loading = '';
      if (technicalError.toLowerCase().includes('stale')) await refresh(false);
    }
  }
  async function cancelRun() {
    if (!run || !confirm('Cancel this entire Challenge run? Any active stage match will also be cancelled. Saved history and replays are retained.')) return;
    await mutate('/cancel', { expected_revision: run.revision }, 'cancel');
  }

  function setEv(entryId: string, stat: EvStat, requested: number) {
    if (!run) return;
    const value = legalEvValue(allocations, entryId, stat, requested, {
      global: run.definition.training_rules.global_ev_budget,
      pokemon: run.definition.training_rules.per_pokemon_max,
      stat: run.definition.training_rules.per_stat_max
    });
    allocations = { ...allocations, [entryId]: { ...(allocations[entryId] || emptyEvSpread()), [stat]: value } };
    trainingNotice = value !== Math.max(0, Math.floor(Number(requested) || 0)) ? `Adjusted to ${value}; that is the largest legal value within the remaining budget.` : '';
  }
  function resetPokemon(entryId: string) { allocations = { ...allocations, [entryId]: emptyEvSpread() }; trainingNotice = 'Pokémon training reset.'; }
  function resetAll() { if (confirm('Reset every EV allocation to zero?')) { allocations = Object.fromEntries(run?.picks.map((pick) => [pick.candidate.entry_id, emptyEvSpread()]) || []); trainingNotice = 'All Training Camp allocations reset.'; } }
  function applyPreset(entryId: string, preset: EvSpread) {
    if (!run) return;
    let next = { ...allocations, [entryId]: emptyEvSpread() };
    for (const [stat] of statEntries) {
      const value = legalEvValue(next, entryId, stat, preset[stat], { global: run.definition.training_rules.global_ev_budget, pokemon: run.definition.training_rules.per_pokemon_max, stat: run.definition.training_rules.per_stat_max });
      next = { ...next, [entryId]: { ...next[entryId], [stat]: value } };
    }
    allocations = next;
    trainingNotice = evSpreadTotal(next[entryId]) === evSpreadTotal(preset) ? 'Legal preset applied.' : 'Preset used the remaining legal budget; some values were reduced.';
  }
  function stageResult(stageId: string) { return [...(run?.stage_results || [])].reverse().find((item) => item.stage_id === stageId); }
  async function copyScaffold() { if (!view?.team_export_scaffold) return; copied = await copyText(view.team_export_scaffold); }
  function restoreScaffold() { if (view?.team_export_scaffold && confirm('Replace the editor with the saved roster and EV scaffold?')) teamText = view.team_export_scaffold; }

  function primaryLabel(current: ChallengeRunView['run']) {
    if (current.status === 'drafting') return current.draft_controller.kind === 'agent' ? 'Continue AI draft' : 'Continue draft';
    if (current.status === 'training') return 'Open Training Camp';
    if (current.status === 'team_review') return 'Complete team review';
    if (current.status === 'ready') return `Fight ${view?.current_stage?.name || 'first stage'}`;
    if (current.status === 'stage_result') return latestResult?.status === 'won' ? `Continue to ${view?.current_stage?.name}` : `Retry ${view?.current_stage?.name}`;
    if (current.active_match_id) return 'Resume battle';
    if (current.status === 'completed') return 'View finale';
    if (current.status === 'cancelled') return 'Start a new Challenge';
    return 'Review run';
  }
  function primaryHref(current: ChallengeRunView['run']) {
    if (current.active_match_id) return `/battle/${current.active_match_id}`;
    if (current.status === 'drafting') return '#draft';
    if (current.status === 'training') return '#training';
    if (current.status === 'team_review') return '#team-review';
    if (current.status === 'ready' || current.status === 'stage_result') return '#current-stage';
    if (current.status === 'completed') return '#summary';
    if (current.status === 'cancelled') return '/challenges/new';
    return '#campaign';
  }
  function outcomeTitle(status: ChallengeRunView['run']['stage_results'][number]['status']) {
    return status === 'won' ? 'Victory' : status === 'lost' ? 'Defeat' : status === 'draw' ? 'Draw' : status === 'failed' ? 'Technical failure' : status === 'interrupted' ? 'Battle interrupted' : 'Battle cancelled';
  }
  function outcomeDetail(status: ChallengeRunView['run']['stage_results'][number]['status']) {
    if (status === 'won') return 'The next stage is unlocked. V1 progression does not add a separate reward currency.';
    if (status === 'lost') return 'This was a genuine battle loss. The same stage remains available for a retry.';
    if (status === 'draw') return 'No winner was recorded. The stage remains available for a clean retry.';
    return 'This did not count as a loss. The same stage remains available after the technical issue is resolved.';
  }
</script>

{#if initialLoading}<p class="lede" role="status">Loading saved Challenge state…</p>{:else if !view}<section class="panel load-error" role="alert"><h1>Challenge could not be loaded</h1><p>{error}</p>{#if technicalError && technicalError !== error}<details><summary>Technical details</summary><code>{technicalError}</code></details>{/if}<button class="button secondary" on:click={() => refresh()}>Retry</button><a class="button ghost" href="/challenges">Back to Challenges</a></section>{:else if run}
<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/challenges">Challenges</a><i class="ph ph-caret-right" aria-hidden="true"></i><span>{run.name}</span></nav>
<div class="page-head"><div><span class="eyebrow">{run.definition.name}</span><h1>{run.name}</h1><p>{run.definition.description}</p></div><div class="head-actions"><span class={`status-pill ${run.status}`}>{challengeStatusLabel(run.status)}</span>{#if !['completed','cancelled'].includes(run.status)}<button class="button danger compact" disabled={Boolean(loading)} on:click={cancelRun}>Cancel run</button>{/if}</div></div>

<section class="continue-card panel" aria-labelledby="continue-title"><div><span class="eyebrow">Continue where you left off</span><h2 id="continue-title">{primaryLabel(run)}</h2><p>{run.active_match_id ? 'The stage match is already linked and running. Your pending Human turn is restored on the battle screen.' : `Saved revision ${run.revision} · updated ${new Date(run.updated_at).toLocaleString()}`}</p></div><a class="button" href={primaryHref(run)}>{primaryLabel(run)}<i class="ph ph-arrow-right" aria-hidden="true"></i></a></section>

{#if pricing && (!pricing.ready || pricing.catalog_hash !== run.pricing.catalog_hash)}<section class="snapshot-warning panel"><i class="ph ph-shield-check" aria-hidden="true"></i><div><strong>This run remains safe on its saved pricing snapshot</strong><p>{!pricing.ready ? 'Local pricing is currently unavailable for new Challenges.' : 'A different pricing catalog is now installed.'} This run still uses <code>{run.pricing.board_name}</code> · <code>{run.pricing.catalog_hash.slice(0, 12)}</code>; it will never be silently substituted.</p></div></section>{/if}

{#if latestResult && (run.status === 'stage_result' || run.status === 'completed')}
  <section class:success={latestResult.status === 'won'} class:technical={['failed','cancelled','interrupted'].includes(latestResult.status)} class="result-card panel"><div class="result-icon"><i class={`ph ${latestResult.status === 'won' ? 'ph-trophy' : latestResult.status === 'lost' ? 'ph-x-circle' : 'ph-warning'}`} aria-hidden="true"></i></div><div><span class="eyebrow">Latest stage result</span><h2>{outcomeTitle(latestResult.status)} · {latestStage?.name}</h2><p>{outcomeDetail(latestResult.status)}</p><span class="result-meta">{latestResult.turns} turns · {formatDuration(latestResult.duration_seconds)}{latestResult.estimated_cost ? ` · $${latestResult.estimated_cost.toFixed(4)}` : ''}</span></div><div class="result-actions"><a class="button secondary" href={`/replay/${latestResult.match_id}`}>View replay</a>{#if run.status !== 'completed'}<a class="button" href="#current-stage">{latestResult.status === 'won' ? `Continue to ${view.current_stage?.name}` : `Retry ${latestStage?.name}`}</a>{/if}</div></section>
{/if}

<section id="campaign" class="campaign panel">
  <header><div><span class="eyebrow">Campaign route</span><h2>{view.statistics.stages_cleared} of {view.stages.length} stages cleared</h2></div><div class="campaign-stats"><span><strong>{view.statistics.wins}-{view.statistics.losses}-{view.statistics.draws}</strong>record</span><span><strong>{view.statistics.total_battles}</strong>battles</span><span><strong>{view.statistics.total_turns}</strong>turns</span><span><strong>{view.statistics.credits_spent}</strong>credits spent</span></div></header>
  <ol aria-label="Kanto campaign progression">{#each view.stages as stage, index}{@const result = stageResult(stage.id)}<li class:current={index === run.current_stage_index && run.status !== 'completed'} class:won={result?.status === 'won'} class:failed={result && result.status !== 'won'} aria-current={index === run.current_stage_index && run.status !== 'completed' ? 'step' : undefined}><span>{result?.status === 'won' ? '✓' : index + 1}</span><div><strong>{stage.name}</strong><small>{stage.title} · Lv. {stage.level}</small></div>{#if result}<a href={`/replay/${result.match_id}`} aria-label={`${stage.name} ${outcomeTitle(result.status)} replay`}>{outcomeTitle(result.status)} · {result.turns} turns</a>{:else if index > run.current_stage_index}<small class="locked">Upcoming</small>{/if}</li>{/each}</ol>
</section>

{#if run.stage_results.length}
  <section id="battle-history" class="battle-history panel" aria-labelledby="battle-history-title">
    <header><div><span class="eyebrow">Battle history</span><h2 id="battle-history-title">Every campaign attempt</h2></div><span>{run.stage_results.length} recorded {run.stage_results.length === 1 ? 'battle' : 'battles'}</span></header>
    <ol>{#each run.stage_results as result, index}<li><div><span class={`status-pill ${result.status === 'won' ? 'completed' : result.status === 'lost' ? 'failed' : result.status}`}>{outcomeTitle(result.status)}</span><strong>{view.stages[result.stage_index]?.name || result.stage_id}</strong><small>Battle {index + 1} · {result.turns} turns · {formatDuration(result.duration_seconds)}</small></div><a class="button secondary compact" href={`/replay/${result.match_id}`}>View replay</a></li>{/each}</ol>
  </section>
{/if}

{#if run.status === 'drafting' && run.current_offer}
  <section id="draft" class="draft panel" aria-labelledby="draft-title">
    <header><div><span class="eyebrow">Draft · Round {run.current_offer.round} of {run.definition.draft_rules.roster_size}</span><h2 id="draft-title">Generation {run.current_offer.generation} · {run.current_offer.type}</h2><p>Choose one exact imported price. Every visible option keeps the remaining roster mathematically completable.</p></div><div class="wallet"><strong>{run.credits_remaining}</strong><span>Draft Credits</span><b>{run.rerolls_remaining} rerolls left</b></div></header>
    <div class="draft-guidance"><span><i class="ph ph-users-three" aria-hidden="true"></i><b>{run.definition.draft_rules.roster_size - run.picks.length}</b> picks remaining</span><span><i class="ph ph-calculator" aria-hidden="true"></i><b>{view.minimum_completion_cost}</b> minimum credits needed</span><span><i class="ph ph-database" aria-hidden="true"></i><b>{run.pricing.board_name}</b> pricing source</span></div>
    {#if run.current_offer.options.length === 1}<p class="pool-note" role="status"><i class="ph ph-info" aria-hidden="true"></i>The legal pool is exhausted for this round, so one budget-safe matching choice remains. The offer is still deterministic.</p>{/if}
    <div class="offer-grid">{#each run.current_offer.options as option, index}<button disabled={Boolean(loading)} aria-label={`Draft ${option.species} for ${option.points} credits`} aria-keyshortcuts={index < 9 ? String(index + 1) : undefined} on:click={() => pick(option.entry_id)}><span>#{option.national_dex_number} · Gen {option.introduction_generation}</span><h3>{option.species}</h3><p>{option.types.join(' / ')}</p>{#if option.base_stat_total}<small>Base stat total {option.base_stat_total}</small>{/if}<strong>{option.points}<small>credits</small></strong>{#if loading === `pick:${option.entry_id}`}<em role="status">Locking pick…</em>{/if}</button>{/each}</div>
    <footer>{#if run.draft_controller.kind === 'human'}<button class="button secondary" disabled={!run.rerolls_remaining || Boolean(loading)} title={!run.rerolls_remaining ? 'No rerolls remain' : 'Consumes one scarce reroll'} on:click={reroll}><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>{loading === 'reroll' ? 'Generating saved reroll…' : `Reroll offer · ${run.rerolls_remaining} left`}</button>{:else if run.draft_controller.kind === 'agent'}<div class="agent-actions"><button class="button" disabled={Boolean(loading)} on:click={agentDraft}><i class="ph ph-robot" aria-hidden="true"></i>{loading === 'agent' ? 'AI is choosing…' : agentFailed ? 'Retry AI decision' : 'Ask AI to choose'}</button><button class="button secondary" disabled={Boolean(loading)} on:click={takeOverDraft}>{loading === 'takeover' ? 'Taking over…' : 'Take over manually'}</button></div>{/if}<span class="offer-saved"><i class="ph ph-cloud-check" aria-hidden="true"></i>Offer saved · refresh safe</span></footer>
    {#if loading === 'agent'}<p class="async-note" role="status">Waiting for one strict legal action. This offer will not reroll while the AI responds.</p>{/if}
  </section>
{/if}

{#if run.picks.length}
  <section class="roster panel"><header><div><span class="eyebrow">Drafted roster</span><h2>{run.picks.length} of {run.definition.draft_rules.roster_size} locked</h2></div><strong>{run.credits_remaining} credits left</strong></header><div>{#each run.picks as pick}<article><span>Round {pick.round} · {pick.selected_by === 'human' ? 'Me' : pick.selected_by === 'agent' ? 'AI' : 'Random'}</span><h3>{pick.candidate.species}</h3><p>{pick.candidate.types.join(' / ')}</p><small>{pick.candidate.base_stat_total ? `BST ${pick.candidate.base_stat_total}` : `Gen ${pick.candidate.introduction_generation}`}</small><strong>{pick.candidate.points}</strong></article>{/each}</div></section>
{/if}

{#if ['training','team_review'].includes(run.status)}
  <section id="training" class="training panel" aria-labelledby="training-title"><header><div><span class="eyebrow">Training Camp</span><h2 id="training-title">{evUsed} / {run.definition.training_rules.global_ev_budget} EV used</h2><p><strong>{evRemaining} remaining.</strong> Zero or unused budget is legal; red/blocked values are prevented before submission.</p></div><div class="training-actions"><button class="button ghost compact" on:click={resetAll}>Reset all</button><div class="ev-counter"><strong>{evRemaining}</strong><span>EV remaining</span></div></div></header>
    <div class="ev-cards">{#each run.picks as pick}{@const spread = allocations[pick.candidate.entry_id] || emptyEvSpread()}<article><div class="ev-mon"><div><strong>{pick.candidate.species}</strong><small>{evSpreadTotal(spread)} / {run.definition.training_rules.per_pokemon_max} EV</small></div><button class="link-button" on:click={() => resetPokemon(pick.candidate.entry_id)}>Reset</button></div><div class="preset-row" aria-label={`${pick.candidate.species} EV presets`}>{#each presets as preset}<button on:click={() => applyPreset(pick.candidate.entry_id, preset[1])}>{preset[0]}</button>{/each}</div><div class="stat-grid">{#each statEntries as stat}<label><span>{stat[1]}</span><input type="number" inputmode="numeric" min="0" max={run.definition.training_rules.per_stat_max} value={spread[stat[0]]} aria-label={`${pick.candidate.species} ${stat[1]} EVs`} on:input={(event) => setEv(pick.candidate.entry_id, stat[0], Number(event.currentTarget.value))} /><button title={`Set ${stat[1]} to the largest legal value`} aria-label={`Maximize ${pick.candidate.species} ${stat[1]}`} on:click={() => setEv(pick.candidate.entry_id, stat[0], run?.definition.training_rules.per_stat_max || 252)}>Max</button></label>{/each}</div></article>{/each}</div>
    {#if trainingNotice}<p class="training-notice" role="status">{trainingNotice}</p>{/if}<footer><span>{evUsed === 0 ? 'No EVs allocated. This is legal if intentional.' : evRemaining ? `${evRemaining} EV may remain unused.` : 'The global Training Budget is exactly exhausted.'}</span><button class="button" disabled={Boolean(loading)} on:click={saveTraining}>{loading === 'training' ? 'Saving legal allocation…' : run.status === 'team_review' ? 'Save updated allocation' : 'Save and continue to team review'}</button></footer></section>
{/if}

{#if run.status === 'team_review'}
  <section id="team-review" class="team-review panel"><div><span class="eyebrow">Team review</span><h2>Finish the legal Showdown sets</h2><p>The editor starts with the drafted species and exact Training Camp EVs. Add legal items, abilities, natures, IVs, and moves. No AI builder is running in this V1 flow.</p><div class="team-tools"><button class="button secondary compact" on:click={copyScaffold}><i class={`ph ${copied ? 'ph-check' : 'ph-copy'}`} aria-hidden="true"></i>{copied ? 'Scaffold copied' : 'Copy scaffold'}</button><button class="button ghost compact" on:click={restoreScaffold}>Restore scaffold</button></div><div class="lock-note"><i class="ph ph-lock" aria-hidden="true"></i><span><strong>Validation locks the roster.</strong><small>Drafted species/forms and EVs cannot change after the campaign starts.</small></span></div></div><label>Showdown team export<textarea rows="26" bind:value={teamText} placeholder="Complete the six drafted Pokémon sets…" spellcheck="false"></textarea></label><footer><span>The pinned Showdown validator is authoritative. Exact validator output stays available under technical details if validation fails.</span><button class="button" disabled={!teamText.trim() || Boolean(loading)} on:click={finalizeTeam}>{loading === 'team' ? 'Validating with Showdown…' : 'Validate and lock team'}</button></footer></section>
{/if}

{#if ['ready','stage_result'].includes(run.status) && view.current_stage}
  <section id="current-stage" class="stage panel"><div><span class="eyebrow">Current stage · {run.current_stage_index + 1} of {view.stages.length}</span><h2>{view.current_stage.name}</h2><p>{view.current_stage.title} · {view.current_stage.theme}</p><div class="level-rule"><strong>Level {view.current_stage.level}</strong><span>Your derived match snapshot and the private opponent snapshot receive this exact same level.</span></div>{#if latestResult && latestResult.stage_id === view.current_stage.id && latestResult.status !== 'won'}<p class="retry-note">{outcomeTitle(latestResult.status)} recorded. Retrying creates a new normal match and retains the previous replay.</p>{/if}</div><button class="button launch" disabled={Boolean(loading)} on:click={launch}><i class="ph ph-sword" aria-hidden="true"></i>{loading === 'launch' ? 'Validating teams and creating match…' : run.status === 'stage_result' && latestResult?.status !== 'won' ? `Retry ${view.current_stage.name}` : `Fight ${view.current_stage.name}`}</button></section>
{/if}

{#if run.active_match_id}<section class="active panel"><div><span class="live-dot"></span><div><span class="eyebrow">Stage match in progress</span><h2>{view.current_stage?.name || 'Challenge stage'}</h2><p>Human pending turns and the linked Match archive are reconnect-safe in this browser session.</p></div></div><a class="button" href={`/battle/${run.active_match_id}`}>Resume battle<i class="ph ph-arrow-up-right" aria-hidden="true"></i></a></section>{/if}

{#if run.status === 'cancelled'}<section class="ending panel"><i class="ph ph-flag" aria-hidden="true"></i><span class="eyebrow">Run ended</span><h2>Challenge cancelled</h2><p>The saved draft, results, and existing replays remain available. No active stage can advance this run.</p><div><a class="button" href="/challenges/new">Start a new Challenge</a><a class="button secondary" href="/challenges">Back to history</a></div></section>{/if}

{#if run.status === 'completed'}<section id="summary" class="complete panel"><i class="ph ph-crown" aria-hidden="true"></i><span class="eyebrow">Kanto Gauntlet complete</span><h2>Champion cleared</h2><p>{view.statistics.wins} wins · {view.statistics.total_battles} battles · {view.statistics.total_turns} turns · {formatDuration(view.statistics.duration_seconds)}</p><dl><div><dt>Draft Credits</dt><dd>{view.statistics.credits_spent} spent · {view.statistics.credits_remaining} left</dd></div><div><dt>Training</dt><dd>{view.statistics.ev_used} EV allocated</dd></div><div><dt>Rerolls</dt><dd>{view.statistics.rerolls_used} used</dd></div><div><dt>Controllers</dt><dd>{run.draft_controller_history.length ? 'AI → Me draft' : `${run.draft_controller.kind} draft`} · {run.battle_controller.agent_type} battle</dd></div><div><dt>Estimated API cost</dt><dd>${view.statistics.estimated_cost.toFixed(4)}</dd></div><div><dt>Average decision</dt><dd>{view.statistics.average_decision_latency_ms == null ? 'Not available' : `${Math.round(view.statistics.average_decision_latency_ms)} ms`}</dd></div></dl><div class="final-roster">{#each run.picks as pick}<span>{pick.candidate.species}<small>{pick.candidate.points} credits</small></span>{/each}</div><div class="final-actions"><a class="button" href="/challenges/new">Start new Challenge</a><a class="button secondary" href="#battle-history">View all battles</a></div></section>{/if}

<details class="run-details panel"><summary>Saved run details</summary><dl><div><dt>Seed</dt><dd>{run.seed}</dd></div><div><dt>Definition</dt><dd>{run.definition.id} · v{run.definition.version}</dd></div><div><dt>Format</dt><dd>{run.definition.format}</dd></div>{#if run.definition.source}<div><dt>Opponent source</dt><dd>{run.definition.source.game} · Gen {run.definition.source.generation}</dd></div><div><dt>Source variant</dt><dd>{run.definition.source.variant}</dd></div><div><dt>Compatibility</dt><dd>{run.definition.source.compatibility_note}</dd></div>{/if}<div><dt>Pricing</dt><dd>{run.pricing.board_name} · {run.pricing.context}</dd></div><div><dt>Catalog</dt><dd><code>{run.pricing.catalog_hash}</code></dd></div><div><dt>Imported</dt><dd>{new Date(run.pricing.imported_at).toLocaleString()}</dd></div></dl></details>

{#if error}<section class="error-box" role="alert"><strong>{error}</strong>{#if technicalError && technicalError !== error}<details><summary>Technical details</summary><code>{technicalError}</code></details>{/if}<button class="link-button" on:click={() => { error = ''; technicalError = ''; }}>Dismiss</button></section>{/if}
{/if}

<style>
  .battle-history{margin-bottom:.9rem;padding:1.25rem;box-shadow:none}.battle-history header{display:flex;align-items:end;justify-content:space-between;gap:1rem}.battle-history h2{margin:.25rem 0}.battle-history header>span{color:var(--muted);font:.62rem var(--mono)}.battle-history ol{display:grid;gap:.45rem;margin:.8rem 0 0;padding:0;list-style:none}.battle-history li{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.7rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong)}.battle-history li>div{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:.2rem .55rem}.battle-history li small{grid-column:2;color:var(--muted);font:.58rem var(--mono)}
  .breadcrumbs{display:flex;align-items:center;gap:.35rem;margin-bottom:.8rem;color:var(--muted);font:.65rem var(--mono)}.breadcrumbs a{color:var(--accent)}.page-head p,.panel p{color:var(--muted);line-height:1.5}.head-actions{display:flex;align-items:center;gap:.6rem}.button.danger{border-color:color-mix(in srgb,var(--danger) 45%,var(--border));background:transparent;color:var(--danger)}.continue-card{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.8rem;padding:1.15rem;border-color:color-mix(in srgb,var(--accent) 42%,var(--border));background:linear-gradient(110deg,color-mix(in srgb,var(--accent) 8%,var(--panel)),var(--panel))}.continue-card h2{margin:.2rem 0}.continue-card p{margin:0;font-size:.7rem}.snapshot-warning,.result-card{display:flex;align-items:center;gap:1rem;margin-bottom:.8rem;padding:1rem}.snapshot-warning>i{color:var(--accent);font-size:1.7rem}.snapshot-warning p{margin:.25rem 0}.result-card{border-color:color-mix(in srgb,var(--danger) 42%,var(--border))}.result-card.success{border-color:color-mix(in srgb,var(--accent) 48%,var(--border))}.result-card.technical{border-color:color-mix(in srgb,var(--warning) 48%,var(--border))}.result-icon{display:grid;place-items:center;width:52px;aspect-ratio:1;border-radius:50%;background:color-mix(in srgb,var(--danger) 12%,var(--surface));color:var(--danger);font-size:1.6rem}.result-card.success .result-icon{background:color-mix(in srgb,var(--accent) 12%,var(--surface));color:var(--accent)}.result-card.technical .result-icon{background:color-mix(in srgb,var(--warning) 12%,var(--surface));color:var(--warning)}.result-card>div:nth-child(2){flex:1}.result-card h2{margin:.2rem 0}.result-card p{margin:.2rem 0}.result-meta{color:var(--muted);font:.62rem var(--mono)}.result-actions{display:flex;gap:.5rem}.campaign,.draft,.roster,.training,.team-review,.stage,.active,.complete,.ending{margin-bottom:.9rem;padding:1.25rem;box-shadow:none}.campaign header,.draft header,.roster header,.training header{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem}.campaign h2,.draft h2,.roster h2,.training h2,.team-review h2,.stage h2,.active h2,.complete h2,.ending h2{margin:.25rem 0}.campaign-stats{display:flex;gap:1rem}.campaign-stats span{display:grid;color:var(--muted);font:.6rem var(--mono)}.campaign-stats strong{color:var(--text);font:700 1.1rem var(--display)}.campaign ol{display:grid;grid-template-columns:repeat(13,minmax(108px,1fr));gap:.4rem;overflow-x:auto;margin:1rem 0 0;padding:0 0 .5rem;list-style:none}.campaign li{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:.4rem;min-width:108px;padding:.58rem;border:1px solid var(--border);border-radius:.55rem}.campaign li>span{display:grid;place-items:center;width:24px;aspect-ratio:1;border-radius:50%;background:var(--surface);font:.62rem var(--mono)}.campaign li small{display:block;color:var(--muted);font:.52rem var(--mono)}.campaign li a,.campaign li .locked{grid-column:1/-1;color:var(--muted);font:.55rem var(--mono)}.campaign li.current{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 7%,var(--panel))}.campaign li.won>span{background:var(--accent);color:var(--accent-ink)}.campaign li.failed{border-color:color-mix(in srgb,var(--danger) 40%,var(--border))}.wallet{display:grid;text-align:right}.wallet>strong{color:var(--accent);font-size:2.3rem}.wallet span,.wallet b{color:var(--muted);font:.62rem var(--mono)}.draft-guidance{display:flex;flex-wrap:wrap;gap:.45rem;margin-top:.8rem}.draft-guidance span{display:flex;align-items:center;gap:.35rem;padding:.35rem .5rem;border:1px solid var(--border);border-radius:999px;color:var(--muted);font:.6rem var(--mono)}.draft-guidance i{color:var(--accent)}.draft-guidance b{color:var(--text)}.pool-note,.async-note{display:flex;align-items:center;gap:.45rem;padding:.65rem;border-radius:.55rem;background:color-mix(in srgb,var(--warning) 8%,transparent);font-size:.72rem}.offer-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem;margin-top:1rem}.offer-grid button{position:relative;display:grid;gap:.35rem;min-height:205px;padding:1.1rem;border:1px solid var(--border);border-radius:.75rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer;transition:transform .16s ease,border-color .16s ease}.offer-grid button:hover:not(:disabled),.offer-grid button:focus-visible{transform:translateY(-3px);border-color:var(--accent)}.offer-grid button>span,.offer-grid button p,.offer-grid button>small{color:var(--muted);font:.65rem var(--mono)}.offer-grid h3{margin:.5rem 0 0;font-size:1.25rem}.offer-grid button>strong{align-self:end;color:var(--accent);font-size:2rem}.offer-grid strong small{margin-left:.25rem;font:.6rem var(--mono)}.offer-grid em{position:absolute;inset:0;display:grid;place-items:center;border-radius:inherit;background:color-mix(in srgb,var(--bg) 88%,transparent);color:var(--accent);font-style:normal}.draft footer,.training footer,.team-review footer{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-top:1rem}.agent-actions,.team-tools{display:flex;flex-wrap:wrap;gap:.5rem}.offer-saved{color:var(--muted);font:.6rem var(--mono)}.offer-saved i{color:var(--accent)}.roster>div{display:grid;grid-template-columns:repeat(6,1fr);gap:.5rem;margin-top:1rem}.roster article{position:relative;padding:.8rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong)}.roster article span,.roster article p,.roster article small{color:var(--muted);font:.6rem var(--mono)}.roster article h3{margin:.35rem 0}.roster article>strong{position:absolute;right:.6rem;bottom:.5rem;color:var(--accent);font-size:1.3rem}.training-actions{display:flex;align-items:center;gap:.8rem}.ev-counter{display:grid;text-align:right}.ev-counter strong{color:var(--accent);font-size:1.7rem}.ev-counter span{color:var(--muted);font:.62rem var(--mono)}.ev-cards{display:grid;gap:.55rem;margin-top:1rem}.ev-cards article{display:grid;gap:.65rem;padding:.8rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.ev-mon{display:flex;align-items:center;justify-content:space-between}.ev-mon>div{display:grid}.ev-mon small{color:var(--muted);font:.6rem var(--mono)}.preset-row{display:flex;flex-wrap:wrap;gap:.35rem}.preset-row button,.stat-grid label button{min-height:30px;padding:.3rem .45rem;border:1px solid var(--border);border-radius:.45rem;background:var(--surface);color:var(--muted);font:.58rem var(--mono);cursor:pointer}.preset-row button:hover,.stat-grid label button:hover{border-color:var(--accent);color:var(--accent)}.stat-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:.4rem}.stat-grid label{display:grid;grid-template-columns:1fr auto;gap:.25rem}.stat-grid label span{grid-column:1/-1;color:var(--muted);font:.58rem var(--mono)}.stat-grid input{min-width:0;min-height:34px;padding:.35rem;text-align:center}.training-notice{padding:.55rem;border-radius:.5rem;background:color-mix(in srgb,var(--accent) 7%,transparent);font-size:.68rem}.team-review{display:grid;grid-template-columns:.8fr 1.2fr;gap:1.25rem}.team-review>label{display:grid;gap:.35rem}.team-review textarea{width:100%;font:.7rem/1.5 var(--mono)}.team-review footer{grid-column:1/-1}.team-review footer span{color:var(--muted);font-size:.68rem}.lock-note{display:flex;align-items:center;gap:.55rem;margin-top:1rem;padding:.7rem;border:1px solid var(--border);border-radius:.55rem}.lock-note i{color:var(--warning);font-size:1.2rem}.lock-note span{display:grid}.lock-note small{color:var(--muted);font:.6rem var(--mono)}.stage,.active{display:flex;align-items:center;justify-content:space-between;gap:2rem}.stage>div{max-width:700px}.level-rule{display:flex;align-items:center;gap:.8rem;margin-top:1rem;padding:.75rem;border:1px solid var(--border);border-radius:.6rem}.level-rule strong{color:var(--accent);font-size:1.2rem;white-space:nowrap}.level-rule span{color:var(--muted);font-size:.7rem}.retry-note{padding:.55rem;border-radius:.5rem;background:color-mix(in srgb,var(--warning) 8%,transparent);font-size:.68rem}.launch{min-height:54px}.active>div{display:flex;align-items:center;gap:.8rem}.live-dot{width:12px;aspect-ratio:1;border-radius:50%;background:var(--accent);box-shadow:0 0 0 6px color-mix(in srgb,var(--accent) 14%,transparent);animation:pulse 1.8s infinite}@keyframes pulse{50%{opacity:.45}}.complete,.ending{display:grid;place-items:center;padding:2.5rem;text-align:center}.complete>.ph,.ending>.ph{color:var(--accent);font-size:3rem}.complete dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;width:100%;margin:1rem 0}.complete dl div{display:grid;padding:.65rem;border:1px solid var(--border);border-radius:.55rem}.complete dt{color:var(--muted);font:.58rem var(--mono)}.complete dd{margin:.2rem 0 0;font-weight:700}.final-roster{display:flex;flex-wrap:wrap;justify-content:center;gap:.4rem}.final-roster span{display:grid;padding:.4rem .6rem;border:1px solid var(--border);border-radius:.55rem}.final-roster small{color:var(--muted);font:.55rem var(--mono)}.final-actions,.ending>div{display:flex;gap:.5rem;margin-top:1rem}.run-details{margin-bottom:1rem;padding:1rem;box-shadow:none}.run-details dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}.run-details dt{color:var(--muted);font:.58rem var(--mono)}.run-details dd{overflow-wrap:anywhere;margin:.2rem 0}.error-box{position:sticky;bottom:1rem;z-index:5;display:grid;grid-template-columns:1fr auto;gap:.5rem;margin-top:1rem;padding:.8rem;border:1px solid var(--danger);border-radius:.65rem;background:var(--panel);color:var(--danger);box-shadow:var(--shadow)}.error-box details{grid-column:1/-1;color:var(--muted)}.load-error{display:grid;justify-items:start;gap:.7rem;padding:1.5rem}@media(max-width:900px){.page-head,.campaign header,.draft header,.roster header,.training header,.stage,.active,.result-card{align-items:stretch;flex-direction:column}.campaign-stats{flex-wrap:wrap}.offer-grid{grid-template-columns:repeat(2,1fr)}.roster>div{grid-template-columns:repeat(3,1fr)}.team-review{grid-template-columns:1fr}.team-review footer{grid-column:auto}.wallet,.ev-counter{text-align:left}.result-actions{align-self:stretch}.result-actions>*{flex:1}.stat-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){.continue-card,.snapshot-warning{align-items:stretch;flex-direction:column}.continue-card .button{width:100%}.head-actions{align-items:flex-start;flex-direction:column}.offer-grid,.roster>div,.complete dl,.run-details dl{grid-template-columns:1fr}.draft footer,.training footer,.team-review footer{align-items:stretch;flex-direction:column}.stat-grid{grid-template-columns:repeat(2,1fr)}.final-actions,.ending>div,.result-actions{display:grid;width:100%}.error-box{grid-template-columns:1fr}}
  @media(max-width:600px){.battle-history header,.battle-history li{align-items:stretch;flex-direction:column}.battle-history li .button{width:100%}}
  @media(prefers-reduced-motion:reduce){.live-dot{animation:none}.offer-grid button{transition:none}}
</style>
