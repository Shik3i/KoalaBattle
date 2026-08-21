<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount, tick } from 'svelte';
  import { api, copyText } from '$lib/api';
  import PokemonSprite from '$lib/PokemonSprite.svelte';
  import TrainerPortrait from '$lib/TrainerPortrait.svelte';
  import TypeBadges from '$lib/TypeBadges.svelte';
  import {
    campaignBattleLabel,
    challengeErrorMessage,
    challengeStatusLabel,
    draftChoiceIndexForKey,
    draftRollTransitionMode,
    emptyEvSpread,
    evSpreadTotal,
    formatDuration,
    legalEvValue,
    recommendedEvPresets,
    type EvStat
  } from '$lib/challenge';
  import type { ChallengeRunView, DraftCandidate, EvSpread } from '$lib/types';

  export let data: { id: string };
  const statEntries: Array<[EvStat, string]> = [['hp','HP'],['atk','Atk'],['def','Def'],['spa','SpA'],['spd','SpD'],['spe','Spe']];

  let view: ChallengeRunView | null = null;
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
  let clock = Date.now();
  let initializedRun = '';
  let scaffoldRun = '';
  type RerollKind = 'pokemon' | 'type' | 'generation';
  type ConfirmationAction = 'finalize' | 'cancel' | 'reset-all' | 'restore';
  type Confirmation = {
    action: ConfirmationAction;
    title: string;
    detail: string;
    confirmLabel: string;
    icon: string;
    danger?: boolean;
  };
  let confirmation: Confirmation | null = null;
  let confirmationButton: HTMLButtonElement | null = null;
  let rollReveal: { generation: number; type: string; mode: 'both' | 'type' | 'generation' } | null = null;
  let rollRevealTimer: ReturnType<typeof setTimeout> | null = null;

  $: run = view?.run;
  $: evUsed = Object.values(allocations).reduce((total, spread) => total + evSpreadTotal(spread), 0);
  $: latestResult = run?.stage_results.length ? run.stage_results[run.stage_results.length - 1] : null;
  $: latestStage = latestResult ? view?.stages[latestResult.stage_index] : null;
  $: autoRunAvailable = Boolean(run && !['human','manual'].includes(run.battle_controller.agent_type) && !['human','manual'].includes(run.opponent_controller.agent_type));
  $: autoCountdown = run?.auto_advance_at ? Math.max(0, Math.ceil((new Date(run.auto_advance_at).getTime() - clock) / 1000)) : null;
  $: if (run?.status === 'team_review' && view?.team_export_scaffold && scaffoldRun !== run.id && !teamText) {
    scaffoldRun = run.id;
    teamText = view.team_export_scaffold;
  }

  onMount(() => {
    void refresh();
    timer = setInterval(() => {
      clock = Date.now();
      const current = view?.run;
      if (current?.active_match_id || current?.status === 'preparing' || current?.auto_advance_at) void refresh(false);
      if (current?.auto_advance_at && !current.auto_run_paused && new Date(current.auto_advance_at).getTime() <= clock) void requestAutoAdvance();
    }, 1000);
    window.addEventListener('keydown', handleDraftShortcut);
    return () => {
      if (timer) clearInterval(timer);
      if (rollRevealTimer) clearTimeout(rollRevealTimer);
      window.removeEventListener('keydown', handleDraftShortcut);
    };
  });

  function handleDraftShortcut(event: KeyboardEvent) {
    if (confirmation) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeConfirmation();
      }
      return;
    }
    const target = event.target as HTMLElement | null;
    if (target?.matches('input, textarea, select, button') || target?.isContentEditable) return;
    if (event.metaKey || event.ctrlKey || event.altKey || loading || run?.status !== 'drafting' || run.draft_controller.kind !== 'human') return;
    const index = draftChoiceIndexForKey(event.key);
    const option = index == null ? null : run.current_offer?.options[index];
    if (!option) return;
    event.preventDefault();
    void pick(option.entry_id);
  }

  function baseStat(candidate: DraftCandidate, stat: EvStat): number | null {
    if (!candidate.base_stats) return null;
    return stat === 'def' ? candidate.base_stats.defense : candidate.base_stats[stat];
  }

  function setView(nextView: ChallengeRunView) {
    const nextRun = nextView.run;
    const priorActiveMatch = view?.run.active_match_id;
    const priorFingerprint = view?.run.current_offer?.fingerprint;
    const nextFingerprint = nextRun.current_offer?.fingerprint;
    const firstRoll = !view && nextFingerprint && sessionStorage.getItem(`draft-first-roll:${nextRun.id}`) === nextFingerprint;
    if (firstRoll) sessionStorage.removeItem(`draft-first-roll:${nextRun.id}`);
    if (nextFingerprint && (firstRoll || (priorFingerprint && priorFingerprint !== nextFingerprint))) {
      const outcome = nextRun.draft_history[nextRun.draft_history.length - 1]?.outcome;
      const mode = draftRollTransitionMode(outcome, Boolean(firstRoll));
      if (mode) {
        rollReveal = { generation: nextRun.current_offer!.generation, type: nextRun.current_offer!.type, mode };
        if (rollRevealTimer) clearTimeout(rollRevealTimer);
        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        rollRevealTimer = setTimeout(() => (rollReveal = null), reducedMotion ? 260 : 1320);
      }
    }
    const enteringTraining = view?.run.id === nextRun.id
      && view.run.status === 'drafting'
      && nextRun.status === 'training';
    const nextAllocations = nextRun.id === initializedRun && !enteringTraining
      ? { ...allocations }
      : {};
    for (const pick of nextRun.picks) {
      const entryId = pick.candidate.entry_id;
      if (!(entryId in nextAllocations)) {
        nextAllocations[entryId] = nextRun.ev_allocations[entryId] || emptyEvSpread();
      }
    }
    allocations = nextAllocations;
    initializedRun = nextRun.id;
    view = nextView;
    if (nextRun.active_match_id && nextRun.active_match_id !== priorActiveMatch && nextRun.battle_experience === 'fast-watch') {
      void goto(`/battle/${nextRun.active_match_id}?speed=4`);
    }
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

  async function requestAutoAdvance() {
    if (!run || loading || run.auto_run_paused) return;
    loading = 'auto-advance';
    try {
      const result = await api<{ run: ChallengeRunView; match: { id: string } | null }>(`/api/challenges/${run.id}/auto/advance`, { method: 'POST' });
      setView(result.run);
    } catch (caught) {
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
    } finally { loading = ''; }
  }
  async function pauseAutoRun() { if (run) await mutate('/auto/pause', { expected_revision: run.revision }, 'pause-auto'); }
  async function continueAutoRun() {
    if (!run || loading) return;
    loading = 'continue-auto';
    try {
      const result = await api<{ run: ChallengeRunView; match: { id: string } | null }>(`/api/challenges/${run.id}/auto/continue`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision }) });
      setView(result.run);
    } catch (caught) {
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
    } finally { loading = ''; }
  }

  async function pick(entryId: string) {
    if (!run?.current_offer) return;
    await mutate('/draft/pick', { entry_id: entryId, offer_fingerprint: run.current_offer.fingerprint, expected_revision: run.revision }, `pick:${entryId}`);
  }
  async function requestReroll(kind: RerollKind) {
    if (!run?.current_offer) return;
    await mutate('/draft/reroll', { kind, offer_fingerprint: run.current_offer.fingerprint, expected_revision: run.revision }, `reroll:${kind}`);
  }
  async function agentDraft() { if (run) await mutate('/draft/agent', { expected_revision: run.revision }, 'agent'); }
  async function takeOverDraft() { if (run && await mutate('/draft/takeover', { expected_revision: run.revision }, 'takeover')) agentFailed = false; }
  async function saveTraining() { if (run) await mutate('/training', { allocations, expected_revision: run.revision }, 'training'); }
  async function openAdvancedTeam() { if (run) await mutate('/team/advanced', { expected_revision: run.revision }, 'advanced-team'); }
  async function saveAbility(entryId: string, abilityId: string) {
    if (!run) return;
    const abilities = { ...run.ability_selections, [entryId]: abilityId };
    await mutate('/team/abilities', { abilities, expected_revision: run.revision }, `ability:${entryId}`);
  }
  function requestFinalizeTeam() {
    if (!run) return;
    openConfirmation({
      action: 'finalize',
      title: 'Lock this team?',
      detail: 'Showdown validates the exact sets first. After validation, drafted species, abilities, and recommended EVs stay fixed for the campaign.',
      confirmLabel: 'Validate and lock',
      icon: 'ph-lock-key'
    });
  }
  async function launch() {
    if (!run || loading) return;
    loading = 'launch'; error = ''; technicalError = '';
    try {
      const result = await api<{ run: ChallengeRunView; match: { id: string } }>(`/api/challenges/${run.id}/launch`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision }) });
      setView(result.run);
      if (run.battle_experience === 'fast-watch') await goto(`/battle/${result.match.id}?speed=4`);
      else if (run.battle_experience === 'normal' || run.battle_controller.agent_type === 'human') await goto(`/battle/${result.match.id}`);
      else loading = '';
    } catch (caught) {
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
      loading = '';
      if (technicalError.toLowerCase().includes('stale')) await refresh(false);
    }
  }
  function requestCancelRun() {
    if (!run) return;
    openConfirmation({
      action: 'cancel',
      title: 'Cancel this Draft run?',
      detail: 'The active stage match also ends. Draft history and completed replays remain available for review.',
      confirmLabel: 'Cancel run',
      icon: 'ph-x-circle',
      danger: true
    });
  }

  function setEv(entryId: string, stat: EvStat, requested: number) {
    if (!run) return;
    const value = legalEvValue(allocations, entryId, stat, requested, {
      pokemon: run.definition.training_rules.per_pokemon_max,
      stat: run.definition.training_rules.per_stat_max
    });
    allocations = { ...allocations, [entryId]: { ...(allocations[entryId] || emptyEvSpread()), [stat]: value } };
    trainingNotice = value !== Math.max(0, Math.floor(Number(requested) || 0)) ? `Adjusted to ${value}; that is the largest legal value for this Pokémon.` : '';
  }
  function resetPokemon(entryId: string) { allocations = { ...allocations, [entryId]: emptyEvSpread() }; trainingNotice = 'Pokémon EVs reset.'; }
  function requestResetAll() {
    openConfirmation({
      action: 'reset-all',
      title: 'Reset all EVs?',
      detail: 'Every current EV spread will return to zero. You can apply Recommended again per Pokémon at any time.',
      confirmLabel: 'Reset all EVs',
      icon: 'ph-arrow-counter-clockwise',
      danger: true
    });
  }
  function applyPreset(entryId: string, preset: EvSpread) {
    if (!run) return;
    let next = { ...allocations, [entryId]: emptyEvSpread() };
    for (const [stat] of statEntries) {
      const value = legalEvValue(next, entryId, stat, preset[stat], { pokemon: run.definition.training_rules.per_pokemon_max, stat: run.definition.training_rules.per_stat_max });
      next = { ...next, [entryId]: { ...next[entryId], [stat]: value } };
    }
    allocations = next;
    trainingNotice = evSpreadTotal(next[entryId]) === evSpreadTotal(preset) ? 'Legal preset applied.' : 'Preset was reduced to this Pokémon’s legal limit.';
  }
  function stageResult(stageId: string) { return [...(run?.stage_results || [])].reverse().find((item) => item.stage_id === stageId); }
  function historyOutcomeLabel(outcome: ChallengeRunView['run']['draft_history'][number]['outcome']) {
    if (outcome === 'picked') return 'Pick locked';
    if (outcome === 'type_rerolled') return 'Type rerolled';
    if (outcome === 'generation_rerolled') return 'Generation rerolled';
    return 'Pokémon rerolled';
  }
  async function copyScaffold() { if (!view?.team_export_scaffold) return; copied = await copyText(view.team_export_scaffold); }
  function requestRestoreScaffold() {
    if (!view?.team_export_scaffold) return;
    openConfirmation({
      action: 'restore',
      title: 'Restore recommended setup?',
      detail: 'This replaces the current editor text with the saved roster, recommended EVs, legal abilities, required items, and starter moves.',
      confirmLabel: 'Restore setup',
      icon: 'ph-magic-wand'
    });
  }

  async function openConfirmation(next: Confirmation) {
    confirmation = next;
    await tick();
    confirmationButton?.focus();
  }

  function closeConfirmation() {
    confirmation = null;
  }

  async function acceptConfirmation() {
    const action = confirmation?.action;
    closeConfirmation();
    if (!run || !action) return;
    if (action === 'finalize') {
      await mutate('/team', { team_text: teamText, expected_revision: run.revision }, 'team');
    } else if (action === 'cancel') {
      await mutate('/cancel', { expected_revision: run.revision }, 'cancel');
    } else if (action === 'reset-all') {
      allocations = Object.fromEntries(run.picks.map((pick) => [pick.candidate.entry_id, emptyEvSpread()]));
      trainingNotice = 'All EV allocations reset.';
    } else if (action === 'restore' && view?.team_export_scaffold) {
      teamText = view.team_export_scaffold;
    }
  }

  function primaryLabel(current: ChallengeRunView['run']) {
    if (current.active_match_id) return current.battle_experience === 'quick-sim' ? 'Quick Sim in progress' : 'Resume battle';
    if (current.status === 'drafting') return current.draft_controller.kind === 'agent' ? 'Continue AI draft' : 'Continue draft';
    if (current.status === 'training') return 'Review EVs';
    if (current.status === 'team_review') return 'Complete team review';
    if (current.status === 'ready') return `Fight ${view?.current_stage?.name || 'first stage'}`;
    if (current.status === 'stage_result') return latestResult?.status === 'won' ? `Continue to ${view?.current_stage?.name}` : `Retry ${view?.current_stage?.name}`;
    if (current.status === 'completed') return 'View finale';
    if (current.status === 'cancelled') return 'Start a new Draft run';
    return 'Review run';
  }
  function primaryHref(current: ChallengeRunView['run']) {
    if (current.active_match_id) return current.battle_experience === 'quick-sim' ? '#quick-sim' : `/battle/${current.active_match_id}`;
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
    if (status === 'won') return 'The next stage is unlocked. Progression stays focused on the canonical gauntlet without a separate reward currency.';
    if (status === 'lost') return 'This was a genuine battle loss. The same stage remains available for a retry.';
    if (status === 'draw') return 'No winner was recorded. The stage remains available for a clean retry.';
    return 'This did not count as a loss. The same stage remains available after the technical issue is resolved.';
  }
</script>

{#if initialLoading}<p class="lede" role="status">Loading saved Draft state…</p>{:else if !view}<section class="panel load-error" role="alert"><h1>Draft run could not be loaded</h1><p>{error}</p>{#if technicalError && technicalError !== error}<details><summary>Technical details</summary><code>{technicalError}</code></details>{/if}<button class="button secondary" on:click={() => refresh()}>Retry</button><a class="button ghost" href="/challenges">Back to Draft</a></section>{:else if run}
<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/challenges">Draft</a><i class="ph ph-caret-right" aria-hidden="true"></i><span>{run.name}</span></nav>
<div class="page-head"><div><span class="eyebrow">{run.definition.name}</span><h1>{run.name}</h1><p>{run.definition.description}</p></div><div class="head-actions"><span class={`status-pill ${run.status}`}>{challengeStatusLabel(run.status)}</span>{#if !['completed','cancelled'].includes(run.status)}<button class="button danger compact" disabled={Boolean(loading)} on:click={requestCancelRun}>Cancel run</button>{/if}</div></div>

{#if ['drafting','training','team_review','cancelled','abandoned'].includes(run.status)}
  <section class="continue-card panel" aria-labelledby="continue-title"><div><span class="eyebrow">Continue where you left off</span><h2 id="continue-title">{primaryLabel(run)}</h2><p>Saved revision {run.revision} · updated {new Date(run.updated_at).toLocaleString()}</p></div><a class="button" href={primaryHref(run)}>{primaryLabel(run)}<i class="ph ph-arrow-right" aria-hidden="true"></i></a></section>
{:else if run.status !== 'completed' && view.current_stage}
  <section class="stage-focus panel" aria-label={`Current battle ${run.current_stage_index + 1} of ${view.stages.length}`} style={`--stage-accent:${view.current_stage.visual_accent}`}><div><span>Battle {run.current_stage_index + 1} of {view.stages.length}</span><h2>{view.current_stage.name}</h2><p>{view.current_stage.title} · {view.current_stage.specialty || 'Kanto specialist'} · Level {view.current_stage.level}</p></div><div class="auto-control"><strong>{run.active_match_id ? (run.battle_experience === 'quick-sim' ? 'Simulating real Showdown battle…' : 'Battle in progress') : run.auto_run_paused ? 'Auto-Run paused' : autoCountdown !== null ? `Next battle in ${autoCountdown}…` : primaryLabel(run)}</strong>{#if autoRunAvailable && run.auto_run_paused}<button class="button" disabled={Boolean(loading)} on:click={continueAutoRun}>{loading === 'continue-auto' ? 'Continuing…' : 'Continue Run'}</button>{:else if autoRunAvailable && (run.active_match_id || run.auto_advance_at)}<button class="button ghost compact" disabled={Boolean(loading)} on:click={pauseAutoRun}>{loading === 'pause-auto' ? 'Pausing…' : 'Pause Auto-Run'}</button>{:else}<a class="button" href={primaryHref(run)}>{primaryLabel(run)}</a>{/if}</div></section>
{/if}

{#if run.compatibility_notice}<section class="snapshot-warning panel" role="alert"><i class="ph ph-warning" aria-hidden="true"></i><div><strong>This saved run uses retired Draft Rules</strong><p>{run.compatibility_notice}</p></div></section>{/if}

{#if latestResult && (run.status === 'stage_result' || run.status === 'completed')}
  <span id="latest-result" class="result-anchor" aria-hidden="true"></span>
  <section class:success={latestResult.status === 'won'} class:technical={['failed','cancelled','interrupted'].includes(latestResult.status)} class="result-card panel"><div class="result-icon"><i class={`ph ${latestResult.status === 'won' ? 'ph-trophy' : latestResult.status === 'lost' ? 'ph-x-circle' : 'ph-warning'}`} aria-hidden="true"></i></div><div class="result-copy"><span class="eyebrow">Battle result</span><h2>{outcomeTitle(latestResult.status)} — {latestStage?.name}{latestResult.status === 'won' ? ' defeated' : ''}</h2><p>{outcomeDetail(latestResult.status)}</p>{#if view.latest_battle_summary}<div class="battle-summary"><div><strong>Your team used</strong><div>{#each view.latest_battle_summary.player_participants as species}<span><PokemonSprite {species} size="small" decorative />{species}</span>{/each}</div></div><div><strong>Defeated</strong><small>Yours</small><div>{#each view.latest_battle_summary.player_fainted as species}<span class="fainted"><PokemonSprite {species} size="small" decorative />{species}</span>{:else}<em>None</em>{/each}</div><small>{latestStage?.name}</small><div>{#each view.latest_battle_summary.opponent_fainted as species}<span class="fainted opponent"><PokemonSprite {species} size="small" decorative />{species}</span>{:else}<em>None</em>{/each}</div></div></div>{/if}{#if latestResult.status === 'won' && run.status !== 'completed' && !run.auto_run_paused && autoCountdown !== null}<p class="next-countdown" role="status"><i class="ph ph-timer" aria-hidden="true"></i>Next: {view.current_stage?.name} in {autoCountdown}…</p>{/if}</div><div class="result-actions"><a class="button secondary" href={`/replay/${latestResult.match_id}`}><i class="ph ph-play-circle" aria-hidden="true"></i>Watch replay</a>{#if run.status !== 'completed' && (!autoRunAvailable || run.auto_run_paused || latestResult.status !== 'won')}<button class="button" disabled={Boolean(loading)} on:click={run.auto_run_paused ? continueAutoRun : launch}>{latestResult.status === 'won' ? `Continue to ${view.current_stage?.name}` : `Retry ${latestStage?.name}`}</button>{/if}</div></section>
{/if}

{#if !['drafting','training','team_review'].includes(run.status)}<section id="campaign" class="campaign panel">
  <header><div><span class="eyebrow">Campaign route</span><h2>{run.status === 'completed' ? 'Kanto Gauntlet complete' : campaignBattleLabel(run.current_stage_index, view.stages.length, view.current_stage?.name || '')}</h2></div></header>
  <ol aria-label="Kanto campaign progression">{#each view.stages as stage, index}{@const result = stageResult(stage.id)}<li class:current={index === run.current_stage_index && run.status !== 'completed'} class:won={result?.status === 'won'} class:failed={result && result.status !== 'won'} style={`--stage-accent:${stage.visual_accent}`} aria-current={index === run.current_stage_index && run.status !== 'completed' ? 'step' : undefined}><TrainerPortrait trainerId={stage.trainer_asset_id} name={stage.name} accent={stage.visual_accent} compact decorative /><span class="stage-number">{result?.status === 'won' ? '✓' : index + 1}</span><div><strong>{stage.name}</strong><small>{stage.specialty || stage.title} · Lv. {stage.level}</small></div>{#if result}<a href={`/replay/${result.match_id}`} aria-label={`${stage.name} ${outcomeTitle(result.status)} replay`}>{outcomeTitle(result.status)} · {result.turns} turns</a>{:else if index > run.current_stage_index}<small class="locked">Upcoming</small>{/if}</li>{/each}</ol>
</section>{/if}

{#if run.stage_results.length}
  <section id="battle-history" class="battle-history panel" aria-labelledby="battle-history-title">
    <header><div><span class="eyebrow">Battle history</span><h2 id="battle-history-title">Every campaign attempt</h2></div><span>{run.stage_results.length} recorded {run.stage_results.length === 1 ? 'battle' : 'battles'}</span></header>
    <ol>{#each run.stage_results as result, index}<li><div><span class={`status-pill ${result.status === 'won' ? 'completed' : result.status === 'lost' ? 'failed' : result.status}`}>{outcomeTitle(result.status)}</span><strong>{view.stages[result.stage_index]?.name || result.stage_id}</strong><small>Battle {index + 1} · {result.turns} turns · {formatDuration(result.duration_seconds)}</small></div><a class="button secondary compact" href={`/replay/${result.match_id}`}>View replay</a></li>{/each}</ol>
  </section>
{/if}

{#if run.status === 'drafting' && run.current_offer}
  <section id="draft" class="draft panel" aria-labelledby="draft-title">
    {#if rollReveal}<div class={`roll-reveal ${rollReveal.mode}`} role="status" aria-live="polite"><span>{rollReveal.mode === 'both' ? 'Rolling Generation + Type' : rollReveal.mode === 'type' ? 'Generation locked · rolling Type' : 'Type locked · rolling Generation'}</span><div><strong class:rolling={rollReveal.mode !== 'type'} class:locked={rollReveal.mode === 'type'}>GEN {rollReveal.generation}</strong><i class="ph ph-plus" aria-hidden="true"></i><strong class:rolling={rollReveal.mode !== 'generation'} class:locked={rollReveal.mode === 'generation'}>{rollReveal.type}</strong></div></div>{/if}
    {#key run.current_offer.fingerprint}
    <header class="roll-result">
      <div class="roll-copy"><span class="eyebrow"><i class="ph ph-sparkle" aria-hidden="true"></i> Draft roll · Pick {run.current_offer.round} of {run.definition.draft_rules.roster_size}</span><h2 id="draft-title"><span>Generation {run.current_offer.generation}</span><i class="ph ph-x" aria-hidden="true"></i><span>{run.current_offer.type}</span></h2><p>Choose one Pokémon. Your next Generation and Type roll automatically.</p></div>
      <div class="reroll-wallet" aria-label="Draft powers remaining"><span title="Keep Generation and Type; replace only the Pokémon"><i class="ph ph-arrows-clockwise" aria-hidden="true"></i><strong>{run.rerolls_remaining}</strong><b>Pokémon</b></span><span title="Keep the Generation; replace Type and Pokémon"><i class="ph ph-palette" aria-hidden="true"></i><strong>{run.type_rerolls_remaining}</strong><b>Type</b></span><span title="Keep the Type; replace Generation and Pokémon"><i class="ph ph-clock-counter-clockwise" aria-hidden="true"></i><strong>{run.generation_rerolls_remaining}</strong><b>Gen</b></span></div>
      <div class="pick-progress" aria-label={`${run.picks.length} of ${run.definition.draft_rules.roster_size} Pokémon drafted`}>
        {#each Array(run.definition.draft_rules.roster_size) as _, index}<span class:complete={index < run.picks.length} class:current={index === run.picks.length}><i aria-hidden="true"></i><b>{index < run.picks.length ? 'Picked' : index === run.picks.length ? 'Current pick' : `Pick ${index + 1}`}</b></span>{/each}
      </div>
    </header>
    <div class="draft-workspace"><div class="draft-choice-area"><div class="draft-guidance"><span><i class="ph ph-users-three" aria-hidden="true"></i><b>{run.definition.draft_rules.roster_size - run.picks.length}</b> picks left</span><span><i class="ph ph-eye-slash" aria-hidden="true"></i>All shown cards retire after this choice</span></div>
      {#if run.current_offer.options.length < run.definition.draft_rules.choice_count}<p class="pool-note" role="status"><i class="ph ph-info" aria-hidden="true"></i>The legal pool is nearly exhausted, so this offer contains fewer cards.</p>{/if}
      <div class="offer-grid">{#each run.current_offer.options as option, index}<button style={`--reveal-index:${index}`} disabled={Boolean(loading)} aria-label={`Draft ${option.species}`} aria-keyshortcuts={index < 9 ? String(index + 1) : undefined} on:click={() => pick(option.entry_id)}><span class="shortcut" aria-hidden="true">{index + 1}</span><span class="dex">#{String(option.national_dex_number).padStart(4, '0')} · Gen {option.introduction_generation}</span><div class="offer-sprite"><PokemonSprite species={option.species} size="large" decorative /></div><h3>{option.species}</h3><p class="type-badges"><TypeBadges types={option.types} /></p><div class="card-foot">{#if option.base_stat_total}<small>BST <b>{option.base_stat_total}</b></small>{/if}<span>Choose <i class="ph ph-arrow-right" aria-hidden="true"></i></span></div>{#if loading === `pick:${option.entry_id}`}<em role="status"><i class="ph ph-spinner-gap" aria-hidden="true"></i> Locking pick…</em>{/if}</button>{/each}</div>
      <footer>{#if run.draft_controller.kind === 'human'}<div class="reroll-actions"><button class="button secondary" title="Keep Generation and Type; replace only these Pokémon" disabled={!run.rerolls_remaining || !view.can_reroll || Boolean(loading)} on:click={() => requestReroll('pokemon')}><i class="ph ph-arrows-clockwise" aria-hidden="true"></i><span><strong>{loading === 'reroll:pokemon' ? 'Rolling…' : 'Reroll Pokémon'}</strong><small>Keep Gen + Type</small></span><b>{run.rerolls_remaining}</b></button><button class="button ghost" title="Keep Generation; change Type and Pokémon" disabled={!run.type_rerolls_remaining || !view.can_reroll_type || Boolean(loading)} on:click={() => requestReroll('type')}><i class="ph ph-palette" aria-hidden="true"></i><span><strong>{loading === 'reroll:type' ? 'Rolling…' : 'Reroll Type'}</strong><small>Keep Generation</small></span><b>{run.type_rerolls_remaining}</b></button><button class="button ghost" title="Keep Type; change Generation and Pokémon" disabled={!run.generation_rerolls_remaining || !view.can_reroll_generation || Boolean(loading)} on:click={() => requestReroll('generation')}><i class="ph ph-clock-counter-clockwise" aria-hidden="true"></i><span><strong>{loading === 'reroll:generation' ? 'Rolling…' : 'Reroll Generation'}</strong><small>Keep Type</small></span><b>{run.generation_rerolls_remaining}</b></button></div>{:else if run.draft_controller.kind === 'agent'}<div class="agent-actions"><button class="button" disabled={Boolean(loading)} on:click={agentDraft}><i class="ph ph-robot" aria-hidden="true"></i>{loading === 'agent' ? 'AI is choosing…' : agentFailed ? 'Retry AI decision' : 'Ask AI to choose'}</button><button class="button secondary" disabled={Boolean(loading)} on:click={takeOverDraft}>{loading === 'takeover' ? 'Taking over…' : 'Take over manually'}</button></div>{/if}<span class:busy={Boolean(loading)} class="offer-saved" role="status"><i class={`ph ${loading ? 'ph-circle-notch' : 'ph-cloud-check'}`} aria-hidden="true"></i>{loading ? 'Saving change…' : 'All progress saved'}</span></footer>
    </div><aside class="draft-roster" aria-label="Current drafted roster"><span class="eyebrow">Your team</span><h3>{run.picks.length} / {run.definition.draft_rules.roster_size}</h3><div>{#each Array(run.definition.draft_rules.roster_size) as _, index}{#if run.picks[index]}{@const pick = run.picks[index]}<article><PokemonSprite species={pick.candidate.species} size="small" decorative /><span><strong>{pick.candidate.species}</strong><TypeBadges types={pick.candidate.types} compact /></span></article>{:else}<article class="empty"><b>{index + 1}</b><span>Open slot</span></article>{/if}{/each}</div><details><summary>How drafting works</summary><p>Every shown card leaves the run. Pokémon keeps Gen + Type; Type keeps Gen; Generation keeps Type. Each power is single-use.</p></details></aside></div>
    {#if loading === 'agent'}<p class="async-note" role="status">Waiting for one strict legal action. This offer will not reroll while the AI responds.</p>{/if}
    {/key}
  </section>
{/if}

{#if run.picks.length && run.status !== 'drafting'}
  <section class="roster panel"><header><div><span class="eyebrow">Drafted roster</span><h2>{run.picks.length} of {run.definition.draft_rules.roster_size} locked</h2></div><strong>{run.definition.draft_rules.roster_size - run.picks.length} picks remaining</strong></header><div>{#each run.picks as pick}<article><PokemonSprite species={pick.candidate.species} size="medium" decorative /><span>Round {pick.round} · {pick.selected_by === 'human' ? 'Me' : pick.selected_by === 'agent' ? 'AI' : 'Random'}</span><h3>{pick.candidate.species}</h3><p class="type-badges"><TypeBadges types={pick.candidate.types} compact /></p><small>{pick.candidate.base_stat_total ? `BST ${pick.candidate.base_stat_total}` : `Gen ${pick.candidate.introduction_generation}`}</small></article>{/each}</div></section>
{/if}

{#if run.draft_history.length}
  <details class="draft-history panel"><summary>Draft history · {run.draft_history.length} resolved {run.draft_history.length === 1 ? 'offer' : 'offers'}</summary><ol>{#each run.draft_history as item}<li><header><strong>Round {item.offer.round} · Generation {item.offer.generation} · {item.offer.type}</strong><span class={`history-outcome ${item.outcome}`}>{historyOutcomeLabel(item.outcome)}</span></header><div>{#each item.offer.options as option}<span class:selected={option.entry_id === item.selected_entry_id}><PokemonSprite species={option.species} size="small" decorative /><b>{option.species}</b>{#if option.entry_id === item.selected_entry_id}<small>selected</small>{:else}<small>consumed</small>{/if}</span>{/each}</div></li>{/each}</ol></details>
{/if}

{#if ['training','team_review'].includes(run.status)}
  <section id="training" class="training panel" aria-labelledby="training-title"><header><div><span class="eyebrow">Optional advanced setup</span><h2 id="training-title">Recommended EVs applied</h2><p>Every drafted Pokémon starts with its own legal recommended spread. Use a preset or fine-tune only if you want to.</p></div><div class="training-actions"><button class="button ghost compact" on:click={requestResetAll}>Reset all</button><div class="ev-counter"><strong>{evUsed}</strong><span>team EV total</span></div></div></header>
    <div class="ev-cards">{#each run.picks as pick}{@const spread = allocations[pick.candidate.entry_id] || emptyEvSpread()}{@const pokemonPresets = recommendedEvPresets(pick.candidate)}<article><div class="ev-identity"><PokemonSprite species={pick.candidate.species} size="medium" decorative /><div class="ev-mon"><div><strong>{pick.candidate.species}</strong><TypeBadges types={pick.candidate.types} compact /><small>{evSpreadTotal(spread)} / {run.definition.training_rules.per_pokemon_max} EV</small></div><button class="link-button" on:click={() => resetPokemon(pick.candidate.entry_id)}>Reset</button></div></div>{#if run.draft_pool.abilities_supported}<label class="ability-field"><span>Legal ability</span><select value={run.ability_selections[pick.candidate.entry_id] || ''} disabled={Boolean(loading) || pick.candidate.abilities.length <= 1} aria-label={`${pick.candidate.species} ability`} on:change={(event) => saveAbility(pick.candidate.entry_id, event.currentTarget.value)}>{#each pick.candidate.abilities as ability}<option value={ability.id}>{ability.name}{ability.hidden ? ' · Hidden' : ''}</option>{/each}</select><small>{pick.candidate.abilities.length <= 1 ? 'Only legal ability; selected automatically.' : 'Saved separately and enforced by final validation.'}</small></label>{:else}<p class="ability-unavailable"><i class="ph ph-info" aria-hidden="true"></i>Abilities do not exist in this format.</p>{/if}<div class="ev-progress" aria-label={`${evSpreadTotal(spread)} of ${run.definition.training_rules.per_pokemon_max} EV allocated`}><span style={`width:${Math.min(100, evSpreadTotal(spread) / run.definition.training_rules.per_pokemon_max * 100)}%`}></span></div><div class="preset-row" aria-label={`${pick.candidate.species} recommended EV presets`}>{#each pokemonPresets as preset}<button class:recommended={preset.recommended} on:click={() => applyPreset(pick.candidate.entry_id, preset.spread)}><span>{#if preset.recommended}<b>Recommended</b>{/if}{preset.label}</span><small>{preset.reason}</small></button>{/each}</div><div class="stat-grid">{#each statEntries as stat}<label><span>{stat[1]}{#if baseStat(pick.candidate, stat[0]) !== null}<b>{baseStat(pick.candidate, stat[0])}</b>{/if}</span><input type="number" inputmode="numeric" min="0" max={run.definition.training_rules.per_stat_max} value={spread[stat[0]]} aria-label={`${pick.candidate.species} ${stat[1]} EVs`} on:input={(event) => setEv(pick.candidate.entry_id, stat[0], Number(event.currentTarget.value))} /><button title={`Set ${stat[1]} to the largest legal value`} aria-label={`Maximize ${pick.candidate.species} ${stat[1]}`} on:click={() => setEv(pick.candidate.entry_id, stat[0], run?.definition.training_rules.per_stat_max || 252)}>Max</button></label>{/each}</div></article>{/each}</div>
    {#if trainingNotice}<p class="training-notice" role="status">{trainingNotice}</p>{/if}<footer><span>Limits apply per Pokémon: {run.definition.training_rules.per_pokemon_max} total and {run.definition.training_rules.per_stat_max} per stat. There is no shared team pool.</span><button class="button" disabled={Boolean(loading)} on:click={saveTraining}>{loading === 'training' ? 'Saving legal spreads…' : run.status === 'team_review' ? 'Save updated spreads' : 'Keep these EVs and continue'}</button></footer></section>
{/if}

{#if run.status === 'team_review'}
  <section id="team-review" class="team-review panel"><div><span class="eyebrow">Advanced team setup</span><h2>Your legal recommended sets are ready</h2><p>The editor starts with every drafted species, exact recommended EVs, selected legal abilities, required form items, and up to four practical legal moves from the pinned Showdown data. Continue immediately or customize the sets.</p><div class="team-tools"><button class="button secondary compact" on:click={copyScaffold}><i class={`ph ${copied ? 'ph-check' : 'ph-copy'}`} aria-hidden="true"></i>{copied ? 'Scaffold copied' : 'Copy scaffold'}</button><button class="button ghost compact" on:click={requestRestoreScaffold}>Restore recommended setup</button></div><div class="lock-note"><i class="ph ph-lock" aria-hidden="true"></i><span><strong>Validation locks the roster.</strong><small>Drafted species/forms, abilities, and EVs cannot change after the campaign starts.</small></span></div></div><label>Showdown team export<textarea rows="26" bind:value={teamText} placeholder="Review or customize the six recommended sets…" spellcheck="false"></textarea></label><footer><span>The pinned Showdown validator is authoritative. Exact validator output stays available under technical details if validation fails.</span><button class="button" disabled={!teamText.trim() || Boolean(loading)} on:click={requestFinalizeTeam}>{loading === 'team' ? 'Validating with Showdown…' : 'Validate and lock team'}</button></footer></section>
{/if}

{#if ['ready','stage_result'].includes(run.status) && view.current_stage}
  <section id="current-stage" class="stage panel" style={`--stage-accent:${view.current_stage.visual_accent}`}><TrainerPortrait trainerId={view.current_stage.trainer_asset_id} name={view.current_stage.name} accent={view.current_stage.visual_accent} /><div class="stage-copy"><span class="eyebrow">Battle {run.current_stage_index + 1} of {view.stages.length}</span><div class="stage-title"><h2>{view.current_stage.name}</h2>{#if view.current_stage.specialty}<span>{view.current_stage.specialty} specialist</span>{/if}</div><p>{view.current_stage.title} · {view.current_stage.theme}</p><div class="level-rule"><strong>Level {view.current_stage.level}</strong><span>Your derived match snapshot and the private opponent snapshot receive this exact same level.</span></div>{#if latestResult && latestResult.stage_id === view.current_stage.id && latestResult.status !== 'won'}<p class="retry-note">{outcomeTitle(latestResult.status)} recorded. Retrying creates a new normal match and retains the previous replay.</p>{/if}</div>{#if !run.auto_advance_at || run.auto_run_paused}<button class="button launch" disabled={Boolean(loading)} on:click={run.auto_run_paused ? continueAutoRun : launch}><i class="ph ph-sword" aria-hidden="true"></i>{loading === 'launch' || loading === 'continue-auto' ? 'Validating teams and creating match…' : run.status === 'stage_result' && latestResult?.status !== 'won' ? `Retry ${view.current_stage.name}` : run.auto_run_paused ? 'Continue Run' : `Fight ${view.current_stage.name}`}</button>{:else}<span class="stage-auto" role="status"><i class="ph ph-circle-notch" aria-hidden="true"></i>Starting automatically…</span>{/if}</section>
  {#if run.status === 'ready' && run.current_stage_index === 0}<div class="advanced-team-link"><span>Recommended EVs and legal starter sets are already applied.</span><button class="button ghost compact" disabled={Boolean(loading)} on:click={openAdvancedTeam}>Advanced team setup</button></div>{/if}
{/if}

{#if run.active_match_id}<section id="quick-sim" class="active panel"><div><span class="live-dot"></span><div><span class="eyebrow">{run.battle_experience === 'quick-sim' ? 'Quick Sim running' : 'Stage match in progress'}</span><h2>{view.current_stage?.name || 'Draft stage'}</h2><p>{run.battle_experience === 'quick-sim' ? 'The real Showdown match is resolving without presentation delays. Result and replay appear here automatically.' : 'Human pending turns and the linked Match archive are reconnect-safe in this browser session.'}</p></div></div>{#if run.battle_experience !== 'quick-sim'}<a class="button" href={`/battle/${run.active_match_id}`}>Resume battle<i class="ph ph-arrow-up-right" aria-hidden="true"></i></a>{:else}<span class="quick-sim-spinner" role="status"><i class="ph ph-circle-notch" aria-hidden="true"></i>Simulating</span>{/if}</section>{/if}

{#if run.status === 'cancelled'}<section class="ending panel"><i class="ph ph-flag" aria-hidden="true"></i><span class="eyebrow">Run ended</span><h2>Draft run cancelled</h2><p>The saved draft, results, and existing replays remain available. No active stage can advance this run.</p><div><a class="button" href="/challenges/new">Start a new Draft run</a><a class="button secondary" href="/challenges">Back to history</a></div></section>{/if}

{#if run.status === 'completed'}<section id="summary" class="complete panel"><i class="ph ph-crown" aria-hidden="true"></i><span class="eyebrow">Kanto Gauntlet complete</span><h2>Champion cleared</h2><p>{view.statistics.wins} wins · {view.statistics.total_battles} battles · {view.statistics.total_turns} turns · {formatDuration(view.statistics.duration_seconds)}</p><dl><div><dt>Draft</dt><dd>{run.picks.length} Pokémon · {run.consumed_species_ids.length} species consumed</dd></div><div><dt>Recommended EVs</dt><dd>{view.statistics.ev_used} allocated</dd></div><div><dt>Rerolls</dt><dd>{view.statistics.rerolls_used} used</dd></div><div><dt>Controllers</dt><dd>{run.draft_controller_history.length ? 'AI → Me draft' : `${run.draft_controller.kind} draft`} · {run.battle_controller.agent_type} battle</dd></div><div><dt>Estimated API cost</dt><dd>${view.statistics.estimated_cost.toFixed(4)}</dd></div><div><dt>Average decision</dt><dd>{view.statistics.average_decision_latency_ms == null ? 'Not available' : `${Math.round(view.statistics.average_decision_latency_ms)} ms`}</dd></div></dl><div class="final-roster">{#each run.picks as pick}<span>{pick.candidate.species}<small>{pick.candidate.abilities.find((ability) => ability.id === run.ability_selections[pick.candidate.entry_id])?.name || 'No ability'}</small></span>{/each}</div><div class="final-actions"><a class="button" href="/challenges/new">Start new Draft run</a><a class="button secondary" href="#battle-history">View all battles</a></div></section>{/if}

<details class="run-details panel"><summary>Saved run details</summary><dl><div><dt>Seed</dt><dd>{run.seed}</dd></div><div><dt>Definition</dt><dd>{run.definition.id} · v{run.definition.version}</dd></div><div><dt>Draft rules</dt><dd>{run.draft_rules_version}</dd></div><div><dt>Format</dt><dd>{run.definition.format} · Gen {run.draft_pool.format_generation}</dd></div><div><dt>Showdown</dt><dd>{run.draft_pool.showdown_version}</dd></div><div><dt>Pool catalog</dt><dd><code>{run.draft_pool.catalog_hash}</code></dd></div>{#if run.definition.source}<div><dt>Opponent source</dt><dd>{run.definition.source.game} · Gen {run.definition.source.generation}</dd></div><div><dt>Source variant</dt><dd>{run.definition.source.variant}</dd></div><div><dt>Compatibility</dt><dd>{run.definition.source.compatibility_note}</dd></div>{/if}</dl></details>

{#if confirmation}
  <div class="confirmation-layer">
    <button class="confirmation-backdrop" aria-label="Close confirmation" on:click={closeConfirmation}></button>
    <div class:danger={confirmation.danger} class="confirmation-card" role="alertdialog" aria-modal="true" aria-labelledby="confirmation-title" aria-describedby="confirmation-detail">
      <div class="confirmation-icon"><i class={`ph ${confirmation.icon}`} aria-hidden="true"></i></div>
      <div><span class="eyebrow">Confirm action</span><h2 id="confirmation-title">{confirmation.title}</h2><p id="confirmation-detail">{confirmation.detail}</p></div>
      <div class="confirmation-actions"><button class="button ghost" on:click={closeConfirmation}>Keep current state</button><button bind:this={confirmationButton} class:danger={confirmation.danger} class="button confirmation-primary" on:click={acceptConfirmation}>{confirmation.confirmLabel}</button></div>
    </div>
  </div>
{/if}

{#if error}<section class="error-box" role="alert"><strong>{error}</strong>{#if technicalError && technicalError !== error}<details><summary>Technical details</summary><code>{technicalError}</code></details>{/if}<button class="link-button" on:click={() => { error = ''; technicalError = ''; }}>Dismiss</button></section>{/if}
{/if}

<style>
  .advanced-team-link{display:flex;align-items:center;justify-content:flex-end;gap:.7rem;margin:-.35rem 0 .9rem;color:var(--muted);font:.6rem var(--mono)}.quick-sim-spinner,.stage-auto{display:flex;align-items:center;gap:.4rem;color:var(--accent);font:700 .68rem var(--mono)}.quick-sim-spinner i,.stage-auto i{animation:spin .8s linear infinite}@media(prefers-reduced-motion:reduce){.quick-sim-spinner i,.stage-auto i{animation:none}}
  .stage-focus{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.8rem;padding:1.1rem 1.25rem;border-color:color-mix(in srgb,var(--stage-accent) 58%,var(--border));background:linear-gradient(105deg,color-mix(in srgb,var(--stage-accent) 14%,var(--panel)),var(--panel))}.stage-focus span{color:var(--stage-accent);font:700 .62rem var(--mono);letter-spacing:.08em;text-transform:uppercase}.stage-focus h2{margin:.15rem 0;font-size:clamp(1.7rem,4vw,2.5rem)}.stage-focus p{margin:0!important}.auto-control{display:grid;justify-items:end;gap:.45rem;text-align:right}.auto-control strong{font:.7rem var(--mono)}
  .battle-summary{display:grid;grid-template-columns:1fr 1fr;gap:.65rem;margin-top:.8rem}.battle-summary>div{padding:.65rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.battle-summary>div>strong,.battle-summary>div>small{display:block;margin-bottom:.4rem}.battle-summary>div>small{margin:.45rem 0 .25rem;color:var(--muted);font:.54rem var(--mono);text-transform:uppercase}.battle-summary>div>div{display:flex;flex-wrap:wrap;gap:.35rem}.battle-summary span{display:flex;align-items:center;gap:.3rem;padding:.25rem .4rem;border-radius:.5rem;background:var(--surface);font-size:.65rem}.battle-summary span.fainted{opacity:.68;filter:grayscale(.75)}.battle-summary span.opponent{border:1px solid color-mix(in srgb,var(--danger) 30%,var(--border))}.battle-summary em{color:var(--muted);font:.6rem var(--mono)}.next-countdown{display:flex;align-items:center;gap:.35rem;margin-top:.7rem!important;color:var(--accent)!important;font-weight:750}.result-copy{min-width:0;flex:1}
  .roll-reveal{position:absolute;z-index:20;inset:0;display:grid;place-content:center;gap:.75rem;border-radius:inherit;background:color-mix(in srgb,var(--panel-strong) 94%,transparent);backdrop-filter:blur(14px);text-align:center;animation:round-transition 1.32s ease both}.roll-reveal>span{color:var(--muted);font:.58rem var(--mono);letter-spacing:.14em;text-transform:uppercase}.roll-reveal>div{display:flex;align-items:center;justify-content:center;gap:.8rem}.roll-reveal strong{min-width:150px;padding:.5rem .75rem;border:1px solid var(--border);border-radius:.7rem;background:var(--surface);font-size:clamp(1.4rem,4vw,2.8rem)}.roll-reveal strong.rolling{border-color:var(--accent);color:var(--accent);animation:value-roll .24s ease-in-out 4,settle .3s .92s ease-out both}.roll-reveal strong.locked{color:var(--muted);box-shadow:inset 0 0 0 1px var(--border)}.roll-reveal i{color:var(--accent)}@keyframes round-transition{0%{opacity:0}12%,84%{opacity:1}100%{opacity:0}}@keyframes value-roll{0%,100%{transform:translateY(0);filter:blur(0)}50%{transform:translateY(-8px);filter:blur(2px)}}@keyframes settle{from{transform:scale(1.08)}to{transform:scale(1)}}@media(max-width:600px){.stage-focus{align-items:stretch;flex-direction:column}.auto-control{justify-items:start;text-align:left}.battle-summary{grid-template-columns:1fr}.roll-reveal>div{flex-direction:column}.roll-reveal i{transform:rotate(90deg)}}@media(prefers-reduced-motion:reduce){.roll-reveal{animation:none;opacity:.96}.roll-reveal strong.rolling{animation:none}}
  .battle-history{margin-bottom:.9rem;padding:1.25rem;box-shadow:none}.battle-history header{display:flex;align-items:end;justify-content:space-between;gap:1rem}.battle-history h2{margin:.25rem 0}.battle-history header>span{color:var(--muted);font:.62rem var(--mono)}.battle-history ol{display:grid;gap:.45rem;margin:.8rem 0 0;padding:0;list-style:none}.battle-history li{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.7rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong)}.battle-history li>div{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:.2rem .55rem}.battle-history li small{grid-column:2;color:var(--muted);font:.58rem var(--mono)}
  .draft-history{margin-bottom:.9rem;padding:1rem;box-shadow:none}.draft-history>summary{font-weight:700}.draft-history ol{display:grid;gap:.6rem;margin:.9rem 0 0;padding:0;list-style:none}.draft-history li{padding:.75rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong)}.draft-history li header{display:flex;align-items:center;justify-content:space-between;gap:.6rem}.draft-history li>div{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.55rem}.draft-history li>div>span{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:0 .4rem;min-width:145px;padding:.35rem .5rem;border:1px solid var(--border);border-radius:.5rem;color:var(--muted)}.draft-history li>div>span.selected{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,transparent);color:var(--text)}.draft-history li>div small{grid-column:2;font:.52rem var(--mono)}.history-outcome{padding:.25rem .45rem;border-radius:999px;background:color-mix(in srgb,var(--warning) 10%,transparent);color:var(--warning);font:.55rem var(--mono)}.history-outcome.picked{background:color-mix(in srgb,var(--accent) 10%,transparent);color:var(--accent)}
  .breadcrumbs{display:flex;align-items:center;gap:.35rem;margin-bottom:.8rem;color:var(--muted);font:.65rem var(--mono)}.breadcrumbs a{color:var(--accent)}.page-head p,.panel p{color:var(--muted);line-height:1.5}.head-actions{display:flex;align-items:center;gap:.6rem}.button.danger{border-color:color-mix(in srgb,var(--danger) 45%,var(--border));background:transparent;color:var(--danger)}.continue-card{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.8rem;padding:1.15rem;border-color:color-mix(in srgb,var(--accent) 42%,var(--border));background:linear-gradient(110deg,color-mix(in srgb,var(--accent) 8%,var(--panel)),var(--panel))}.continue-card h2{margin:.2rem 0}.continue-card p{margin:0;font-size:.7rem}.snapshot-warning,.result-card{display:flex;align-items:center;gap:1rem;margin-bottom:.8rem;padding:1rem}.snapshot-warning>i{color:var(--warning);font-size:1.7rem}.snapshot-warning p{margin:.25rem 0}.result-card{border-color:color-mix(in srgb,var(--danger) 42%,var(--border))}.result-card.success{border-color:color-mix(in srgb,var(--accent) 48%,var(--border))}.result-card.technical{border-color:color-mix(in srgb,var(--warning) 48%,var(--border))}.result-icon{display:grid;place-items:center;width:52px;aspect-ratio:1;border-radius:50%;background:color-mix(in srgb,var(--danger) 12%,var(--surface));color:var(--danger);font-size:1.6rem}.result-card.success .result-icon{background:color-mix(in srgb,var(--accent) 12%,var(--surface));color:var(--accent)}.result-card.technical .result-icon{background:color-mix(in srgb,var(--warning) 12%,var(--surface));color:var(--warning)}.result-card>div:nth-child(2){flex:1}.result-card h2{margin:.2rem 0}.result-card p{margin:.2rem 0}.result-meta{color:var(--muted);font:.62rem var(--mono)}.result-actions{display:flex;gap:.5rem}.campaign,.draft,.roster,.training,.team-review,.stage,.active,.complete,.ending{margin-bottom:.9rem;padding:1.25rem;box-shadow:none}.campaign header,.draft header,.roster header,.training header{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem}.campaign h2,.draft h2,.roster h2,.training h2,.team-review h2,.stage h2,.active h2,.complete h2,.ending h2{margin:.25rem 0}.campaign-stats{display:flex;gap:1rem}.campaign-stats span{display:grid;color:var(--muted);font:.6rem var(--mono)}.campaign-stats strong{color:var(--text);font:700 1.1rem var(--display)}.campaign ol{display:grid;grid-template-columns:repeat(13,minmax(108px,1fr));gap:.4rem;overflow-x:auto;margin:1rem 0 0;padding:0 0 .5rem;list-style:none}.campaign li{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:.4rem;min-width:108px;padding:.58rem;border:1px solid var(--border);border-radius:.55rem}.campaign li>span{display:grid;place-items:center;width:24px;aspect-ratio:1;border-radius:50%;background:var(--surface);font:.62rem var(--mono)}.campaign li small{display:block;color:var(--muted);font:.52rem var(--mono)}.campaign li a,.campaign li .locked{grid-column:1/-1;color:var(--muted);font:.55rem var(--mono)}.campaign li.current{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 7%,var(--panel))}.campaign li.won>span{background:var(--accent);color:var(--accent-ink)}.campaign li.failed{border-color:color-mix(in srgb,var(--danger) 40%,var(--border))}.draft-guidance{display:flex;flex-wrap:wrap;gap:.45rem;margin-top:.8rem}.draft-guidance span{display:flex;align-items:center;gap:.35rem;padding:.35rem .5rem;border:1px solid var(--border);border-radius:999px;color:var(--muted);font:.6rem var(--mono)}.draft-guidance i{color:var(--accent)}.draft-guidance b{color:var(--text)}.pool-note,.async-note{display:flex;align-items:center;gap:.45rem;padding:.65rem;border-radius:.55rem;background:color-mix(in srgb,var(--warning) 8%,transparent);font-size:.72rem}.offer-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem;margin-top:1rem}.offer-grid button{position:relative;display:grid;gap:.35rem;min-height:205px;padding:1.1rem;border:1px solid var(--border);border-radius:.75rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer;transition:transform .16s ease,border-color .16s ease}.offer-grid button:hover:not(:disabled),.offer-grid button:focus-visible{transform:translateY(-3px);border-color:var(--accent)}.offer-grid button>span,.offer-grid button p{color:var(--muted);font:.65rem var(--mono)}.offer-grid h3{margin:.5rem 0 0;font-size:1.25rem}.offer-grid em{position:absolute;inset:0;display:grid;place-items:center;border-radius:inherit;background:color-mix(in srgb,var(--bg) 88%,transparent);color:var(--accent);font-style:normal}.draft footer,.training footer,.team-review footer{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-top:1rem}.agent-actions,.team-tools{display:flex;flex-wrap:wrap;gap:.5rem}.offer-saved{color:var(--muted);font:.6rem var(--mono)}.offer-saved i{color:var(--accent)}.roster>div{display:grid;grid-template-columns:repeat(6,1fr);gap:.5rem;margin-top:1rem}.roster article{position:relative;padding:.8rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong)}.roster article span,.roster article p,.roster article small{color:var(--muted);font:.6rem var(--mono)}.roster article h3{margin:.35rem 0}.training-actions{display:flex;align-items:center;gap:.8rem}.ev-counter{display:grid;text-align:right}.ev-counter strong{color:var(--accent);font-size:1.7rem}.ev-counter span{color:var(--muted);font:.62rem var(--mono)}.ev-cards{display:grid;gap:.55rem;margin-top:1rem}.ev-cards article{display:grid;gap:.65rem;padding:.8rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.ev-mon{display:flex;align-items:center;justify-content:space-between}.ev-mon>div{display:grid}.ev-mon small{color:var(--muted);font:.6rem var(--mono)}.ability-field{display:grid;gap:.25rem;padding:.6rem;border:1px solid color-mix(in srgb,var(--accent) 30%,var(--border));border-radius:.55rem;background:color-mix(in srgb,var(--accent) 5%,transparent)}.ability-field>span{font-weight:700}.ability-field select{width:100%}.ability-field small,.ability-unavailable{color:var(--muted);font:.58rem/1.4 var(--mono)}.ability-unavailable{display:flex;align-items:center;gap:.4rem;margin:0}.preset-row{display:flex;flex-wrap:wrap;gap:.35rem}.preset-row button,.stat-grid label button{min-height:30px;padding:.3rem .45rem;border:1px solid var(--border);border-radius:.45rem;background:var(--surface);color:var(--muted);font:.58rem var(--mono);cursor:pointer}.preset-row button:hover,.stat-grid label button:hover{border-color:var(--accent);color:var(--accent)}.stat-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:.4rem}.stat-grid label{display:grid;grid-template-columns:1fr auto;gap:.25rem}.stat-grid label span{grid-column:1/-1;color:var(--muted);font:.58rem var(--mono)}.stat-grid input{min-width:0;min-height:34px;padding:.35rem;text-align:center}.training-notice{padding:.55rem;border-radius:.5rem;background:color-mix(in srgb,var(--accent) 7%,transparent);font-size:.68rem}.team-review{display:grid;grid-template-columns:.8fr 1.2fr;gap:1.25rem}.team-review>label{display:grid;gap:.35rem}.team-review textarea{width:100%;font:.7rem/1.5 var(--mono)}.team-review footer{grid-column:1/-1}.team-review footer span{color:var(--muted);font-size:.68rem}.lock-note{display:flex;align-items:center;gap:.55rem;margin-top:1rem;padding:.7rem;border:1px solid var(--border);border-radius:.55rem}.lock-note i{color:var(--warning);font-size:1.2rem}.lock-note span{display:grid}.lock-note small{color:var(--muted);font:.6rem var(--mono)}.stage,.active{display:flex;align-items:center;justify-content:space-between;gap:2rem}.stage>div{max-width:700px}.level-rule{display:flex;align-items:center;gap:.8rem;margin-top:1rem;padding:.75rem;border:1px solid var(--border);border-radius:.6rem}.level-rule strong{color:var(--accent);font-size:1.2rem;white-space:nowrap}.level-rule span{color:var(--muted);font-size:.7rem}.retry-note{padding:.55rem;border-radius:.5rem;background:color-mix(in srgb,var(--warning) 8%,transparent);font-size:.68rem}.launch{min-height:54px}.active>div{display:flex;align-items:center;gap:.8rem}.live-dot{width:12px;aspect-ratio:1;border-radius:50%;background:var(--accent);box-shadow:0 0 0 6px color-mix(in srgb,var(--accent) 14%,transparent);animation:pulse 1.8s infinite}@keyframes pulse{50%{opacity:.45}}.complete,.ending{display:grid;place-items:center;padding:2.5rem;text-align:center}.complete>.ph,.ending>.ph{color:var(--accent);font-size:3rem}.complete dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;width:100%;margin:1rem 0}.complete dl div{display:grid;padding:.65rem;border:1px solid var(--border);border-radius:.55rem}.complete dt{color:var(--muted);font:.58rem var(--mono)}.complete dd{margin:.2rem 0 0;font-weight:700}.final-roster{display:flex;flex-wrap:wrap;justify-content:center;gap:.4rem}.final-roster span{display:grid;padding:.4rem .6rem;border:1px solid var(--border);border-radius:.55rem}.final-roster small{color:var(--muted);font:.55rem var(--mono)}.final-actions,.ending>div{display:flex;gap:.5rem;margin-top:1rem}.run-details{margin-bottom:1rem;padding:1rem;box-shadow:none}.run-details dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}.run-details dt{color:var(--muted);font:.58rem var(--mono)}.run-details dd{overflow-wrap:anywhere;margin:.2rem 0}.error-box{position:sticky;bottom:1rem;z-index:5;display:grid;grid-template-columns:1fr auto;gap:.5rem;margin-top:1rem;padding:.8rem;border:1px solid var(--danger);border-radius:.65rem;background:var(--panel);color:var(--danger);box-shadow:var(--shadow)}.error-box details{grid-column:1/-1;color:var(--muted)}.load-error{display:grid;justify-items:start;gap:.7rem;padding:1.5rem}@media(max-width:900px){.page-head,.campaign header,.draft header,.roster header,.training header,.stage,.active,.result-card{align-items:stretch;flex-direction:column}.campaign-stats{flex-wrap:wrap}.offer-grid{grid-template-columns:repeat(2,1fr)}.roster>div{grid-template-columns:repeat(3,1fr)}.team-review{grid-template-columns:1fr}.team-review footer{grid-column:auto}.ev-counter{text-align:left}.result-actions{align-self:stretch}.result-actions>*{flex:1}.stat-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){.continue-card,.snapshot-warning{align-items:stretch;flex-direction:column}.continue-card .button{width:100%}.head-actions{align-items:flex-start;flex-direction:column}.offer-grid,.roster>div,.complete dl,.run-details dl{grid-template-columns:1fr}.draft footer,.training footer,.team-review footer{align-items:stretch;flex-direction:column}.stat-grid{grid-template-columns:repeat(2,1fr)}.final-actions,.ending>div,.result-actions{display:grid;width:100%}.error-box{grid-template-columns:1fr}}
  .campaign ol{grid-template-columns:repeat(13,minmax(166px,1fr))}.campaign li{position:relative;grid-template-columns:64px 1fr;min-width:166px;border-color:color-mix(in srgb,var(--stage-accent) 22%,var(--border));background:linear-gradient(145deg,color-mix(in srgb,var(--stage-accent) 5%,var(--panel-strong)),var(--panel))}.campaign li .stage-number{position:absolute;top:.35rem;right:.35rem;width:21px}.campaign li.current{border-color:var(--stage-accent);background:linear-gradient(145deg,color-mix(in srgb,var(--stage-accent) 17%,var(--panel)),var(--panel))}.campaign li.won .stage-number{background:var(--stage-accent);color:#101216}.campaign li a,.campaign li .locked{grid-column:1/-1}
  .offer-grid button{grid-template-columns:1fr auto;min-height:360px;overflow:hidden;background:radial-gradient(circle at 50% 35%,color-mix(in srgb,var(--accent) 9%,transparent),transparent 40%),var(--panel-strong)}.offer-grid button::after{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;box-shadow:inset 0 1px rgba(255,255,255,.06)}.offer-grid .shortcut{position:absolute;top:.75rem;right:.75rem;display:grid;place-items:center;width:28px;aspect-ratio:1;border:1px solid var(--border);border-radius:.45rem;background:var(--surface);color:var(--text);font:700 .64rem var(--mono)}.offer-grid .dex{grid-column:1/-1}.offer-sprite{grid-column:1/-1;display:grid;place-items:center;min-height:138px}.offer-grid h3{grid-column:1/-1;margin:0;font-size:1.4rem}.offer-grid :global(.type-list){grid-column:1/-1}.offer-grid em{z-index:3;grid-template-columns:auto auto;gap:.35rem}.offer-grid em i{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
  .roster>div{grid-template-columns:repeat(6,minmax(132px,1fr))}.roster article{display:grid;justify-items:center;overflow:hidden;text-align:center;background:radial-gradient(circle at 50% 35%,color-mix(in srgb,var(--accent) 8%,transparent),transparent 42%),var(--panel-strong)}.roster article :global(.pokemon-sprite){margin:.25rem 0 .65rem}.roster article h3{margin:.15rem 0}
  .ev-cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem}.ev-cards article{padding:1rem;background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 4%,var(--panel-strong)),var(--panel-strong))}.ev-identity{display:flex;align-items:center;gap:.8rem}.ev-mon{flex:1}.ev-mon>div{gap:.32rem}.ev-progress{height:5px;overflow:hidden;border-radius:999px;background:var(--surface)}.ev-progress span{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),color-mix(in srgb,var(--accent) 55%,#58a6ff));transition:width .2s ease}.preset-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.4rem}.preset-row button{display:grid;align-content:start;gap:.22rem;min-height:72px;padding:.55rem;text-align:left}.preset-row button span{display:grid;gap:.15rem;color:var(--text);font-weight:700}.preset-row button small{line-height:1.3}.preset-row button b{width:max-content;padding:.12rem .3rem;border-radius:999px;background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent);font:.47rem var(--mono);text-transform:uppercase}.preset-row button.recommended{border-color:color-mix(in srgb,var(--accent) 58%,var(--border));background:color-mix(in srgb,var(--accent) 8%,var(--surface))}.stat-grid label{padding:.45rem;border:1px solid color-mix(in srgb,var(--border) 75%,transparent);border-radius:.5rem;background:color-mix(in srgb,var(--surface) 72%,transparent)}.stat-grid label span{display:flex;justify-content:space-between}.stat-grid label span b{color:var(--text);font-weight:700}
  .stage{position:relative;overflow:hidden;justify-content:flex-start;border-color:color-mix(in srgb,var(--stage-accent) 42%,var(--border));background:radial-gradient(circle at 10% 50%,color-mix(in srgb,var(--stage-accent) 16%,transparent),transparent 30%),linear-gradient(105deg,color-mix(in srgb,var(--stage-accent) 8%,var(--panel)),var(--panel))}.stage::after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(115deg,transparent 42%,color-mix(in srgb,var(--stage-accent) 6%,transparent))}.stage-copy{position:relative;z-index:1;flex:1}.stage-title{display:flex;align-items:center;gap:.55rem}.stage-title h2{font-size:2rem}.stage-title span{padding:.24rem .5rem;border:1px solid color-mix(in srgb,var(--stage-accent) 65%,var(--border));border-radius:999px;background:color-mix(in srgb,var(--stage-accent) 14%,transparent);color:color-mix(in srgb,var(--stage-accent) 44%,white);font:700 .55rem var(--mono);text-transform:uppercase}.stage .level-rule{border-color:color-mix(in srgb,var(--stage-accent) 30%,var(--border))}.stage .level-rule strong{color:color-mix(in srgb,var(--stage-accent) 50%,white)}.stage .launch{position:relative;z-index:1;border-color:var(--stage-accent);background:var(--stage-accent);color:#101216}
  .roll-result{align-items:center!important;padding:clamp(.9rem,2vw,1.35rem);border:1px solid color-mix(in srgb,var(--accent) 48%,var(--border));border-radius:.8rem;background:radial-gradient(circle at 20% 50%,color-mix(in srgb,var(--accent) 16%,transparent),transparent 48%),var(--panel-strong)}.roll-result h2{display:flex;align-items:center;gap:.65rem;margin:.35rem 0;font-size:clamp(1.55rem,3vw,2.45rem)}.roll-result h2 span{padding:.22rem .55rem;border-radius:.45rem;background:color-mix(in srgb,var(--accent) 13%,transparent)}.roll-result h2 i{color:var(--muted);font-size:1rem}.roll-result p{margin:0}.draft-workspace{display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:1rem;margin-top:1rem}.draft-choice-area{min-width:0}.draft-roster{position:sticky;top:1rem;align-self:start;padding:.9rem;border:1px solid var(--border);border-radius:.75rem;background:var(--panel-strong)}.draft-roster h3{margin:.2rem 0 .65rem;color:var(--accent);font-size:1.4rem}.draft-roster>div{display:grid;gap:.4rem}.draft-roster article{display:grid;grid-template-columns:42px 1fr;align-items:center;gap:.45rem;min-height:52px;padding:.35rem;border:1px solid var(--border);border-radius:.55rem;background:var(--panel)}.draft-roster article>span{display:grid;min-width:0}.draft-roster article strong{overflow:hidden;font-size:.7rem;text-overflow:ellipsis;white-space:nowrap}.draft-roster article.empty{color:var(--muted)}.draft-roster article.empty b{display:grid;place-items:center;width:34px;aspect-ratio:1;border:1px dashed var(--border);border-radius:50%;font:.6rem var(--mono)}.draft-roster article.empty span{font:.6rem var(--mono)}.draft-roster details{margin-top:.7rem;color:var(--muted);font-size:.65rem}.draft-roster details p{margin:.5rem 0 0;font-size:.65rem}
  @media(max-width:1100px){.ev-cards{grid-template-columns:1fr}.roster>div{grid-template-columns:repeat(3,1fr)}.draft-workspace{grid-template-columns:1fr}.draft-roster{position:static}.draft-roster>div{grid-template-columns:repeat(6,1fr)}.draft-roster article{grid-template-columns:1fr;justify-items:center;text-align:center}.draft-roster article>span{justify-items:center}.draft-roster article.empty b{width:28px}}
  @media(max-width:900px){.stage :global(.trainer){align-self:center}.stage .launch{width:100%}}
  .type-badges{margin:0}.offer-grid .type-badges{grid-column:1/-1}
  .stat-grid label{grid-template-columns:1fr}.stat-grid input,.stat-grid label button{width:100%}
  @media(max-width:600px){.battle-history header,.battle-history li{align-items:stretch;flex-direction:column}.battle-history li .button{width:100%}.offer-grid button{min-height:340px}.roster>div{grid-template-columns:repeat(2,1fr)}.preset-row{grid-template-columns:1fr}.stage-title{align-items:flex-start;flex-direction:column}.stage-title h2{font-size:1.65rem}.ev-identity{align-items:flex-start}.roll-result h2{align-items:flex-start;flex-direction:column}.roll-result h2 i{transform:rotate(90deg)}.draft-roster>div{grid-template-columns:repeat(3,1fr)}.draft-roster article{min-width:0}}
  @media(prefers-reduced-motion:reduce){.live-dot,.offer-grid em i{animation:none}.offer-grid button,.ev-progress span{transition:none}}
  .confirmation-layer{position:fixed;z-index:100;inset:0;display:grid;place-items:center;padding:1rem}.confirmation-backdrop{position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:0;background:color-mix(in srgb,#05070a 76%,transparent);backdrop-filter:blur(8px);cursor:default}.confirmation-card{position:relative;display:grid;grid-template-columns:auto 1fr;gap:1rem;width:min(520px,100%);padding:1.35rem;border:1px solid color-mix(in srgb,var(--accent) 45%,var(--border));border-radius:1rem;background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 7%,var(--panel-strong)),var(--panel));box-shadow:0 28px 90px rgba(0,0,0,.55);animation:confirmation-in .16s ease-out}.confirmation-card.danger{border-color:color-mix(in srgb,var(--danger) 52%,var(--border));background:linear-gradient(145deg,color-mix(in srgb,var(--danger) 7%,var(--panel-strong)),var(--panel))}.confirmation-icon{display:grid;place-items:center;width:52px;aspect-ratio:1;border-radius:.75rem;background:color-mix(in srgb,var(--accent) 13%,var(--surface));color:var(--accent);font-size:1.55rem}.confirmation-card.danger .confirmation-icon{background:color-mix(in srgb,var(--danger) 13%,var(--surface));color:var(--danger)}.confirmation-card h2{margin:.22rem 0 .35rem;font-size:1.4rem}.confirmation-card p{margin:0}.confirmation-actions{grid-column:1/-1;display:flex;justify-content:flex-end;gap:.55rem;margin-top:.25rem}.confirmation-primary.danger{border-color:var(--danger);background:var(--danger);color:white}@keyframes confirmation-in{from{opacity:0;transform:translateY(8px) scale(.98)}}@media(max-width:600px){.confirmation-card{grid-template-columns:1fr;padding:1.1rem}.confirmation-actions{display:grid}.confirmation-actions .button{width:100%}}@media(prefers-reduced-motion:reduce){.confirmation-card{animation:none}.confirmation-backdrop{backdrop-filter:none}}
  .draft{position:relative;overflow:hidden;border-color:color-mix(in srgb,var(--accent) 22%,var(--border));background:linear-gradient(160deg,color-mix(in srgb,var(--accent) 3%,var(--panel)),var(--panel) 38%)}
  .roll-result{position:relative;isolation:isolate;display:grid!important;grid-template-columns:minmax(0,1fr) auto;overflow:hidden;animation:roll-reveal .34s cubic-bezier(.2,.8,.2,1)}.roll-result::before{position:absolute;z-index:-1;top:-90px;right:16%;width:220px;aspect-ratio:1;border:1px solid color-mix(in srgb,var(--accent) 15%,transparent);border-radius:50%;box-shadow:0 0 0 34px color-mix(in srgb,var(--accent) 3%,transparent),0 0 0 72px color-mix(in srgb,var(--accent) 2%,transparent);content:"";animation:orbit-drift 8s ease-in-out infinite alternate}.roll-copy{min-width:0}.roll-copy>.eyebrow{display:flex;align-items:center;gap:.35rem}.roll-copy>.eyebrow i{animation:sparkle 2.4s ease-in-out infinite}.roll-result h2 span:first-child{animation:roll-chip .38s cubic-bezier(.2,.8,.2,1)}.roll-result h2 span:last-child{animation:roll-chip .38s .08s cubic-bezier(.2,.8,.2,1) both}
  .reroll-wallet{display:flex;align-self:start;gap:.45rem}.reroll-wallet>span{display:grid;grid-template-columns:auto auto;align-items:center;justify-content:center;gap:0 .32rem;min-width:68px;padding:.48rem .58rem;border:1px solid color-mix(in srgb,var(--accent) 18%,var(--border));border-radius:.65rem;background:color-mix(in srgb,var(--surface) 84%,transparent);box-shadow:inset 0 1px rgba(255,255,255,.05);text-align:center}.reroll-wallet i{color:var(--muted);font-size:.78rem}.reroll-wallet strong{color:var(--accent);font:800 1.3rem/1 var(--display)}.reroll-wallet b{grid-column:1/-1;margin-top:.2rem;color:var(--muted);font:.5rem var(--mono);letter-spacing:.08em;text-transform:uppercase}
  .pick-progress{grid-column:1/-1;display:grid;grid-template-columns:repeat(6,1fr);gap:.35rem;margin-top:1rem}.pick-progress span{position:relative;display:grid;gap:.25rem}.pick-progress span::after{position:absolute;z-index:-1;top:5px;right:50%;left:-50%;height:2px;background:var(--border);content:""}.pick-progress span:first-child::after{display:none}.pick-progress i{z-index:1;width:12px;aspect-ratio:1;border:2px solid var(--border);border-radius:50%;background:var(--panel-strong);transition:border-color .24s ease,background .24s ease,box-shadow .24s ease}.pick-progress b{overflow:hidden;color:var(--muted);font:.48rem var(--mono);text-overflow:ellipsis;white-space:nowrap}.pick-progress .complete::after{background:color-mix(in srgb,var(--accent) 70%,var(--border))}.pick-progress .complete i{border-color:var(--accent);background:var(--accent)}.pick-progress .current i{border-color:var(--accent);box-shadow:0 0 0 5px color-mix(in srgb,var(--accent) 13%,transparent);animation:current-pick 1.8s ease-in-out infinite}.pick-progress .current b{color:var(--text)}
  .offer-grid button{isolation:isolate;border-radius:.9rem;box-shadow:0 8px 24px transparent;animation:card-reveal .36s calc(.11s + var(--reveal-index) * .08s) cubic-bezier(.2,.8,.2,1) both;transition:transform .22s cubic-bezier(.2,.8,.2,1),border-color .22s ease,box-shadow .22s ease,background .22s ease}.offer-grid button::before{position:absolute;z-index:-1;inset:auto 12% -40% 12%;height:55%;border-radius:50%;background:color-mix(in srgb,var(--accent) 12%,transparent);filter:blur(28px);opacity:0;content:"";transition:opacity .22s ease,transform .22s ease}.offer-grid button:hover:not(:disabled),.offer-grid button:focus-visible{transform:translateY(-6px);border-color:color-mix(in srgb,var(--accent) 72%,var(--border));background:radial-gradient(circle at 50% 34%,color-mix(in srgb,var(--accent) 15%,transparent),transparent 44%),var(--panel-strong);box-shadow:0 18px 40px color-mix(in srgb,var(--accent) 10%,rgba(0,0,0,.12))}.offer-grid button:hover::before,.offer-grid button:focus-visible::before{opacity:1;transform:translateY(-12px)}.offer-sprite{transition:transform .25s cubic-bezier(.2,.8,.2,1),filter .25s ease}.offer-grid button:hover:not(:disabled) .offer-sprite,.offer-grid button:focus-visible .offer-sprite{transform:translateY(-5px) scale(1.035);filter:drop-shadow(0 14px 13px color-mix(in srgb,var(--accent) 16%,transparent))}.card-foot{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;min-height:28px;margin-top:.2rem;padding-top:.65rem;border-top:1px solid color-mix(in srgb,var(--border) 76%,transparent)}.card-foot small{color:var(--muted);font:.6rem var(--mono)}.card-foot small b{color:var(--text)}.card-foot>span{display:flex;align-items:center;gap:.28rem;color:var(--muted);font:750 .62rem var(--display);transition:color .2s ease}.card-foot i{transition:transform .2s ease}.offer-grid button:hover .card-foot>span,.offer-grid button:focus-visible .card-foot>span{color:var(--accent)}.offer-grid button:hover .card-foot i,.offer-grid button:focus-visible .card-foot i{transform:translateX(3px)}
  .reroll-actions{display:flex;flex-wrap:wrap;gap:.45rem}.reroll-actions .button{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.15rem .5rem;min-height:48px;padding:.48rem .62rem;text-align:left}.reroll-actions .button>i{grid-row:1/3;color:var(--accent);font-size:1.05rem;transition:transform .25s ease}.reroll-actions .button>span{display:grid;min-width:92px}.reroll-actions .button strong{font-size:.67rem}.reroll-actions .button small{color:var(--muted);font:.5rem var(--mono)}.reroll-actions .button>b{grid-row:1/3;display:grid;place-items:center;min-width:25px;aspect-ratio:1;border-radius:999px;background:color-mix(in srgb,var(--accent) 12%,var(--surface));color:var(--accent);font:.65rem var(--mono)}.reroll-actions .button:hover:not(:disabled)>i{transform:rotate(-18deg) scale(1.08)}.offer-saved{display:flex;align-items:center;gap:.35rem;white-space:nowrap}.offer-saved.busy i{animation:spin .8s linear infinite}.draft-roster article:not(.empty){animation:roster-lock .32s cubic-bezier(.2,.8,.2,1) both}
  @keyframes roll-reveal{from{opacity:.2;transform:translateY(-8px) scale(.995)}}@keyframes roll-chip{from{opacity:0;transform:translateY(-10px) scale(.95)}}@keyframes card-reveal{from{opacity:0;transform:translateY(15px) scale(.975)}}@keyframes current-pick{50%{box-shadow:0 0 0 8px color-mix(in srgb,var(--accent) 5%,transparent)}}@keyframes sparkle{50%{transform:rotate(12deg) scale(1.18);opacity:.65}}@keyframes orbit-drift{to{transform:translate(18px,12px) rotate(8deg)}}@keyframes roster-lock{from{opacity:0;transform:translateX(7px)}}
  @media(max-width:750px){.roll-result{grid-template-columns:1fr}.reroll-wallet{margin-top:.85rem}.draft{padding:1rem}.offer-grid{gap:.55rem}.offer-grid button{min-height:320px;padding:.9rem}.reroll-actions{display:grid;grid-template-columns:1fr 1fr}.reroll-actions .button:first-child{grid-column:1/-1}.offer-saved{align-self:center}}
  @media(max-width:600px){.reroll-wallet{width:100%}.reroll-wallet>span{flex:1}.pick-progress b{display:none}.pick-progress{margin-top:.85rem}.reroll-actions{grid-template-columns:1fr;width:100%}.reroll-actions .button,.reroll-actions .button:first-child{grid-column:auto;width:100%}.roll-result::before{right:-55px}.offer-grid button{min-height:300px}.card-foot{padding-top:.5rem}.offer-saved{justify-content:center}}
  @media(prefers-reduced-motion:reduce){.roll-result,.roll-result::before,.roll-result h2 span,.roll-copy>.eyebrow i,.pick-progress .current i,.offer-grid button,.offer-sprite,.card-foot i,.reroll-actions .button>i,.offer-saved.busy i,.draft-roster article:not(.empty){animation:none;transition:none}.offer-grid button:hover:not(:disabled),.offer-grid button:focus-visible{transform:none}.offer-grid button:hover:not(:disabled) .offer-sprite,.offer-grid button:focus-visible .offer-sprite{transform:none}}
</style>
