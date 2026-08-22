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
    difficultyLabel,
    DRAFT_REEL_FRAME_HEIGHT,
    draftChoiceIndexForKey,
    draftRollDuration,
    draftRollFrames,
    draftRollTransitionMode,
    emptyEvSpread,
    evSpreadTotal,
    formatDuration,
    generationRomanNumeral,
    legalEvValue,
    pokemonTypeColor,
    recommendedEvPresets,
    type DraftRollMode,
    type EvStat
  } from '$lib/challenge';
  import type { ChallengeRunView, DraftCandidate, EvolutionTrigger, EvSpread } from '$lib/types';

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
  let activeRunId: string | null = null;
  type RerollKind = 'pokemon' | 'type' | 'generation';
  type ConfirmationAction = 'finalize' | 'cancel' | 'reset-all' | 'restore' | 'delete';
  type Confirmation = {
    action: ConfirmationAction;
    title: string;
    detail: string;
    confirmLabel: string;
    icon: string;
    danger?: boolean;
  };
  let confirmation: Confirmation | null = null;
  let runMenu: HTMLDetailsElement | null = null;
  let confirmationButton: HTMLButtonElement | null = null;
  let rollReveal: {
    generation: number;
    type: string;
    mode: DraftRollMode;
    generations: number[];
    types: string[];
  } | null = null;
  let rollRevealTimer: ReturnType<typeof setTimeout> | null = null;
  let copyTimer: ReturnType<typeof setTimeout> | null = null;
  // Monotonic guards: the 1s poll must never apply an out-of-order response over
  // newer state, and the client must never re-fire one auto-advance deadline.
  let viewSequence = 0;
  let refreshing = false;
  let advancedDeadline = '';
  let dismissedRunError = '';
  /** Offer fingerprint the AI drafter was already asked about, so a failure never loops. */
  let autoDraftedOffer = '';
  /** Short "next opponent" card shown while the next stage is already starting. */
  let stageTransition: {
    name: string;
    title: string;
    specialty: string | null;
    level: number;
    playerLevel: number;
    accent: string;
    trainerId: string | null;
    index: number;
    total: number;
  } | null = null;
  let stageTransitionTimer: ReturnType<typeof setTimeout> | null = null;
  const STAGE_TRANSITION_MS = 1400;
  /** Short "X evolved into Y" reveal shown once per stage transition, before the next
   *  opponent is announced. Shown even under reduced motion — only the animation, not the
   *  card itself, is skipped then. */
  let evolutionReveal: Array<{ entryId: string; from: string; to: string }> | null = null;
  let evolutionRevealTimer: ReturnType<typeof setTimeout> | null = null;
  const EVOLUTION_REVEAL_MS = 1600;
  /** A branching species was just picked; the player chooses its future line once, here,
   *  before the pick is sent. Compact by design — this is the only draft-time interruption
   *  evolution ever causes. */
  let evolutionChoicePrompt: { entryId: string; species: string; options: EvolutionTrigger[] } | null = null;

  $: if (data.id && activeRunId !== null && data.id !== activeRunId) {
    activeRunId = data.id;
    viewSequence += 1;
    view = null; allocations = {}; teamText = ''; loading = ''; error = ''; technicalError = '';
    initializedRun = ''; scaffoldRun = ''; advancedDeadline = ''; autoDraftedOffer = '';
    agentFailed = false; initialLoading = true;
    void refresh();
  }

  $: run = view?.run;
  $: downed = new Set(run?.downed_entry_ids || []);
  /** Current (post-evolution) species/types per pick, keyed by entry id — always prefer this
   *  over `pick.candidate` once the run has left drafting; evolution never changes candidate. */
  $: currentByEntryId = new Map((view?.current_roster || []).map((item) => [item.entry_id, item]));
  // An AI draft has to actually draft. Requiring six manual "Ask AI to choose" clicks read
  // as the feature being broken; the AI now takes each offer on its own and only stops when
  // a decision fails, where Retry and Take over remain.
  $: if (
    run?.status === 'drafting'
    && run.draft_controller.kind === 'agent'
    && run.current_offer
    && !loading
    && !rollReveal
    && !agentFailed
    && autoDraftedOffer !== run.current_offer.fingerprint
  ) {
    autoDraftedOffer = run.current_offer.fingerprint;
    void agentDraft();
  }
  $: evUsed = Object.values(allocations).reduce((total, spread) => total + evSpreadTotal(spread), 0);
  $: latestResult = run?.stage_results.length ? run.stage_results[run.stage_results.length - 1] : null;
  $: latestStage = latestResult ? view?.stages[latestResult.stage_index] : null;
  $: autoRunAvailable = Boolean(run && !['human','manual'].includes(run.battle_controller.agent_type) && !['human','manual'].includes(run.opponent_controller.agent_type));
  $: if (run?.status === 'team_review' && view?.team_export_scaffold && scaffoldRun !== run.id && !teamText) {
    scaffoldRun = run.id;
    teamText = view.team_export_scaffold;
  }

  onMount(() => {
    activeRunId = data.id;
    void refresh();
    timer = setInterval(() => {
      clock = Date.now();
      const current = view?.run;
      if (current?.active_match_id || current?.status === 'preparing' || current?.auto_advance_at) void refresh(false);
      // The backend owns the deadline and launches the next stage itself. This is only a
      // fallback for a backend that was restarted mid-countdown, so it waits out a grace
      // period and fires at most once per persisted deadline.
      if (
        current?.auto_advance_at
        && !current.auto_run_paused
        && !current.active_match_id
        && advancedDeadline !== current.auto_advance_at
        && new Date(current.auto_advance_at).getTime() + 2000 <= clock
      ) {
        advancedDeadline = current.auto_advance_at;
        void requestAutoAdvance();
      }
    }, 1000);
    window.addEventListener('keydown', handleDraftShortcut);
    window.addEventListener('pointerdown', closeRunMenu);
    return () => {
      window.removeEventListener('pointerdown', closeRunMenu);
      if (timer) clearInterval(timer);
      if (rollRevealTimer) clearTimeout(rollRevealTimer);
      if (copyTimer) clearTimeout(copyTimer);
      if (stageTransitionTimer) clearTimeout(stageTransitionTimer);
      if (evolutionRevealTimer) clearTimeout(evolutionRevealTimer);
      window.removeEventListener('keydown', handleDraftShortcut);
    };
  });

  function closeRunMenu(event: Event) {
    if (runMenu?.open && !runMenu.contains(event.target as Node)) runMenu.open = false;
  }

  function handleDraftShortcut(event: KeyboardEvent) {
    if (event.key === 'Escape' && runMenu?.open) runMenu.open = false;
    if (confirmation) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeConfirmation();
      }
      return;
    }
    const target = event.target as HTMLElement | null;
    if (target?.matches('input, textarea, select, button') || target?.isContentEditable) return;
    if (event.metaKey || event.ctrlKey || event.altKey || loading || rollReveal || run?.status !== 'drafting' || run.draft_controller.kind !== 'human') return;
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

  function rarityLabel(value: DraftCandidate['draft_rarity']) {
    return value.split('-').map((part) => part[0].toUpperCase() + part.slice(1)).join(' ');
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
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const mode = draftRollTransitionMode(outcome, Boolean(firstRoll), reducedMotion);
      if (mode) {
        const generation = nextRun.current_offer!.generation;
        const type = nextRun.current_offer!.type;
        rollReveal = { generation, type, mode, ...draftRollFrames(generation, type, mode) };
        if (rollRevealTimer) clearTimeout(rollRevealTimer);
        rollRevealTimer = setTimeout(() => (rollReveal = null), draftRollDuration(mode) + 60);
      }
    }
    // The backend launches the next stage immediately, so this is the only thing that
    // announces the new opponent. It is presentation only and never gates progression.
    if (
      view
      && view.run.id === nextRun.id
      && nextRun.current_stage_index > view.run.current_stage_index
      && nextRun.status !== 'completed'
    ) {
      const stage = nextView.stages[nextRun.current_stage_index];
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const showStageCard = () => {
        if (!stage || reduced) return;
        stageTransition = {
          name: stage.name,
          title: stage.title,
          specialty: stage.specialty,
          level: stage.level,
          playerLevel: stage.player_level,
          accent: stage.visual_accent,
          trainerId: stage.trainer_asset_id,
          index: nextRun.current_stage_index,
          total: nextView.stages.length
        };
        if (stageTransitionTimer) clearTimeout(stageTransitionTimer);
        stageTransitionTimer = setTimeout(() => (stageTransition = null), STAGE_TRANSITION_MS);
      };
      // Evolution is a state transition between the same two screens; show it first, then
      // the next-opponent card, rather than layering both at once.
      if (nextRun.recent_evolutions.length) {
        evolutionReveal = nextRun.recent_evolutions.map((item) => ({
          entryId: item.entry_id,
          from: item.from_species,
          to: item.to_species
        }));
        if (evolutionRevealTimer) clearTimeout(evolutionRevealTimer);
        evolutionRevealTimer = setTimeout(() => {
          evolutionReveal = null;
          showStageCard();
        }, EVOLUTION_REVEAL_MS);
      } else {
        showStageCard();
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
    // Only follow a match that starts while this page is open. Landing on the run with a
    // match already attached must never bounce the user straight back out of the Draft map.
    if (view && nextRun.active_match_id && nextRun.active_match_id !== priorActiveMatch && nextRun.battle_experience === 'fast-watch') {
      void goto(`/battle/${nextRun.active_match_id}?speed=4`);
    }
  }

  async function refresh(showLoading = true) {
    if (showLoading && !view) initialLoading = true;
    if (loading && !showLoading) return;
    if (refreshing && !showLoading) return;
    refreshing = true;
    const sequence = ++viewSequence;
    try {
      const next = await api<ChallengeRunView>(`/api/challenges/${data.id}`);
      // A slower poll must not overwrite a newer mutation response.
      if (sequence !== viewSequence) return;
      setView(next);
      error = ''; technicalError = '';
    } catch (caught) {
      if (sequence !== viewSequence) return;
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
    } finally {
      if (sequence === viewSequence) {
        refreshing = false;
        initialLoading = false;
      }
    }
  }

  async function mutate(path: string, body: Record<string, unknown>, label: string) {
    if (!run || loading) return false;
    loading = label; error = ''; technicalError = '';
    const sequence = ++viewSequence;
    try {
      const next = await api<ChallengeRunView>(`/api/challenges/${run.id}${path}`, { method: 'POST', body: JSON.stringify(body) });
      if (sequence !== viewSequence) return false;
      setView(next);
      agentFailed = false;
      return true;
    } catch (caught) {
      if (sequence !== viewSequence) return false;
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
      if (technicalError.toLowerCase().includes('stale') || technicalError.toLowerCase().includes('not waiting')) await refresh(false);
      if (label === 'agent') agentFailed = true;
      return false;
    } finally {
      if (sequence === viewSequence) loading = '';
    }
  }

  async function requestAutoAdvance() {
    if (!run || loading || run.auto_run_paused) return;
    loading = 'auto-advance';
    const sequence = ++viewSequence;
    try {
      const result = await api<{ run: ChallengeRunView; match: { id: string } | null }>(`/api/challenges/${run.id}/auto/advance`, { method: 'POST' });
      if (sequence !== viewSequence) return;
      setView(result.run);
    } catch (caught) {
      if (sequence !== viewSequence) return;
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
    } finally { if (sequence === viewSequence) loading = ''; }
  }
  async function pauseAutoRun() { if (run) await mutate('/auto/pause', { expected_revision: run.revision }, 'pause-auto'); }
  async function continueAutoRun() {
    if (!run || loading) return;
    loading = 'continue-auto';
    const sequence = ++viewSequence;
    try {
      const result = await api<{ run: ChallengeRunView; match: { id: string } | null }>(`/api/challenges/${run.id}/auto/continue`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision }) });
      if (sequence !== viewSequence) return;
      setView(result.run);
    } catch (caught) {
      if (sequence !== viewSequence) return;
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
    } finally { if (sequence === viewSequence) loading = ''; }
  }

  async function pick(entryId: string, evolutionChoice?: string) {
    if (!run?.current_offer) return;
    if (!evolutionChoice) {
      const option = run.current_offer.options.find((item) => item.entry_id === entryId);
      if (option && option.evolves_to.length > 1) {
        evolutionChoicePrompt = { entryId, species: option.species, options: option.evolves_to };
        return;
      }
    }
    evolutionChoicePrompt = null;
    const body: Record<string, unknown> = { entry_id: entryId, offer_fingerprint: run.current_offer.fingerprint, expected_revision: run.revision };
    if (evolutionChoice) body.evolution_choice = evolutionChoice;
    await mutate('/draft/pick', body, `pick:${entryId}`);
  }
  async function requestReroll(kind: RerollKind) {
    if (!run?.current_offer) return;
    await mutate('/draft/reroll', { kind, offer_fingerprint: run.current_offer.fingerprint, expected_revision: run.revision }, `reroll:${kind}`);
  }
  async function agentDraft() {
    if (!run) return;
    const fingerprint = run.current_offer?.fingerprint || '';
    autoDraftedOffer = fingerprint;
    const ok = await mutate('/draft/agent', { expected_revision: run.revision }, 'agent');
    // A stale revision is not an AI failure — the run simply moved on between the poll and
    // the request. `mutate` has already refreshed, so let the loop ask again for this same
    // offer with the current revision instead of stranding the draft on a dead screen.
    if (!ok && technicalError.toLowerCase().includes('stale')) {
      agentFailed = false;
      if (autoDraftedOffer === fingerprint) autoDraftedOffer = '';
    }
  }
  async function takeOverDraft() { if (run && await mutate('/draft/takeover', { expected_revision: run.revision }, 'takeover')) agentFailed = false; }
  async function saveTraining() { if (run) await mutate('/training', { allocations, expected_revision: run.revision }, 'training'); }
  async function openAdvancedTeam() { if (run) await mutate('/team/advanced', { expected_revision: run.revision }, 'advanced-team'); }
  async function saveAbility(entryId: string, abilityId: string) {
    if (!run) return;
    const abilities = { ...run.ability_selections, [entryId]: abilityId };
    await mutate('/team/abilities', { abilities, expected_revision: run.revision }, `ability:${entryId}`);
  }
  async function selectMega(entryId: string, megaSpeciesId: string) {
    if (!run) return;
    await mutate('/mega-selection', {
      entry_id: entryId,
      mega_species_id: megaSpeciesId,
      expected_revision: run.revision
    }, `mega:${entryId}:${megaSpeciesId}`);
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
    const sequence = ++viewSequence;
    try {
      const result = await api<{ run: ChallengeRunView; match: { id: string } }>(`/api/challenges/${run.id}/launch`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision }) });
      if (sequence !== viewSequence) return;
      setView(result.run);
      if (run.battle_experience === 'fast-watch') await goto(`/battle/${result.match.id}?speed=4`);
      else if (run.battle_experience === 'normal' || run.battle_controller.agent_type === 'human') await goto(`/battle/${result.match.id}`);
      else if (sequence === viewSequence) loading = '';
    } catch (caught) {
      if (sequence !== viewSequence) return;
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
      if (sequence === viewSequence) loading = '';
      if (technicalError.toLowerCase().includes('stale')) await refresh(false);
    }
  }
  function requestDeleteRun() {
    if (!run) return;
    openConfirmation({
      action: 'delete',
      title: 'Delete this Draft run?',
      detail: 'The saved draft, EVs, and progress are removed permanently. Recorded stage matches and their replays are immutable and stay in Matches.',
      confirmLabel: 'Delete run',
      icon: 'ph-trash',
      danger: true
    });
  }
  async function deleteRun() {
    if (!run || loading) return;
    loading = 'delete'; error = ''; technicalError = '';
    try {
      await api<{ deleted: boolean }>(`/api/challenges/${run.id}/delete`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision }) });
      await goto('/challenges');
    } catch (caught) {
      technicalError = caught instanceof Error ? caught.message : String(caught);
      error = challengeErrorMessage(technicalError);
      loading = '';
      await refresh(false);
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
  /** Explain a dead reroll button instead of leaving the user guessing. */
  function rerollBlockedReason(
    kind: RerollKind,
    currentRun = run,
    currentView = view,
    currentLoading = loading,
    currentRollReveal = rollReveal
  ): string {
    if (!currentRun || !currentView) return '';
    if (currentLoading) return 'Another Draft change is being saved. This unlocks when it finishes.';
    if (currentRollReveal) return 'The current roll is still settling. This unlocks when the cards are ready.';
    const remaining = kind === 'pokemon' ? currentRun.rerolls_remaining
      : kind === 'type' ? currentRun.type_rerolls_remaining
      : currentRun.generation_rerolls_remaining;
    if (!remaining) return 'Already used this run.';
    const possible = kind === 'pokemon' ? currentView.can_reroll
      : kind === 'type' ? currentView.can_reroll_type
      : currentView.can_reroll_generation;
    if (!possible) {
      return kind === 'pokemon'
        ? 'The remaining pool cannot fill another offer with this Generation and Type.'
        : kind === 'type'
          ? 'No other Type in this Generation still has enough unseen Pokémon.'
          : 'No other Generation with this Type still has enough unseen Pokémon.';
    }
    return '';
  }

  function stageResult(stageId: string) { return [...(run?.stage_results || [])].reverse().find((item) => item.stage_id === stageId); }
  function historyOutcomeLabel(outcome: ChallengeRunView['run']['draft_history'][number]['outcome']) {
    if (outcome === 'picked') return 'Pick locked';
    if (outcome === 'type_rerolled') return 'Type rerolled';
    if (outcome === 'generation_rerolled') return 'Generation rerolled';
    return 'Pokémon rerolled';
  }
  async function copyScaffold() {
    if (!view?.team_export_scaffold) return;
    copied = await copyText(view.team_export_scaffold);
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => (copied = false), 2400);
  }
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
    } else if (action === 'delete') {
      await deleteRun();
    }
  }

  function primaryLabel(current: ChallengeRunView['run']) {
    if (current.active_match_id) return current.battle_experience === 'quick-sim' ? 'Quick Sim in progress' : 'Resume battle';
    if (current.status === 'drafting') return current.draft_controller.kind === 'agent' ? 'Continue AI draft' : 'Continue draft';
    if (current.status === 'training') return 'Review EVs';
    if (current.status === 'team_review') return 'Complete team review';
    if (current.status === 'mega_selection') return 'Choose a Mega Evolution';
    if (current.status === 'ready') return `Fight ${view?.current_stage?.name || 'first stage'}`;
    if (current.status === 'stage_result') return latestResult?.status === 'won' ? `Continue to ${view?.current_stage?.name}` : `Retry ${view?.current_stage?.name}`;
    if (current.status === 'completed') return 'View finale';
    if (current.status === 'cancelled') return 'Start a new Draft run';
    return 'Review run';
  }
  function primaryHref(current: ChallengeRunView['run']) {
    if (current.active_match_id) return current.battle_experience === 'quick-sim' ? '#current-stage' : `/battle/${current.active_match_id}`;
    if (current.status === 'drafting') return '#draft';
    if (current.status === 'training') return '#training';
    if (current.status === 'team_review') return '#team-review';
    if (current.status === 'mega_selection') return '#mega-selection';
    if (current.status === 'ready' || current.status === 'stage_result') return '#current-stage';
    if (current.status === 'completed') return '#summary';
    if (current.status === 'cancelled') return '/challenges/new';
    return '#campaign';
  }
  function outcomeTitle(status: ChallengeRunView['run']['stage_results'][number]['status']) {
    return status === 'won' ? 'Victory' : status === 'lost' ? 'Defeat' : status === 'draw' ? 'Draw' : status === 'failed' ? 'Technical failure' : status === 'interrupted' ? 'Battle interrupted' : 'Battle cancelled';
  }
  function outcomeDetail(status: ChallengeRunView['run']['stage_results'][number]['status']) {
    // A cleared campaign has no next stage, and the old copy still mentioned a reward
    // currency that never existed.
    if (status === 'won' && run?.status === 'completed') return 'The gauntlet is cleared. Every battle is still available as a replay below.';
    if (status === 'won') return 'The next stage starts right away.';
    if (status === 'lost') return 'This was a genuine battle loss. The same stage remains available for a retry.';
    if (status === 'draw') return 'No winner was recorded. The stage remains available for a clean retry.';
    return 'This did not count as a loss. The same stage remains available after the technical issue is resolved.';
  }
</script>

{#if initialLoading}<p class="lede" role="status">Loading saved Draft state…</p>{:else if !view}<section class="panel load-error" role="alert"><h1>Draft run could not be loaded</h1><p>{error}</p>{#if technicalError && technicalError !== error}<details><summary>Technical details</summary><code>{technicalError}</code></details>{/if}<button class="button secondary" on:click={() => refresh()}>Retry</button><a class="button ghost" href="/challenges">Back to Draft</a></section>{:else if run}
<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/challenges">Draft</a><i class="ph ph-caret-right" aria-hidden="true"></i><span>{run.name}</span></nav>
<div class="page-head"><div class="run-id"><span class="eyebrow">{run.definition.name} · v{run.definition.version}</span><h1 title={run.name}>{run.name}</h1></div><div class="head-actions"><span class={`status-pill ${run.status}`}>{challengeStatusLabel(run.status)}</span><span class="difficulty-pill" title="Raises the opponent's level above the campaign curve; your own team always follows the curve">{difficultyLabel(run.difficulty)}</span>{#if !['completed','cancelled'].includes(run.status)}<details bind:this={runMenu} class="run-menu"><summary title="Run tools"><i class="ph ph-sliders-horizontal" aria-hidden="true"></i><span>Run</span></summary><div class="run-menu-panel" role="none" on:click={() => runMenu && (runMenu.open = false)}><span class="run-menu-label">This run</span><p class="run-menu-note">{run.definition.description}</p><a class="run-menu-item" href="#run-archive"><i class="ph ph-cards-three" aria-hidden="true"></i>Battle history and saved details</a><button type="button" class="run-menu-item danger" disabled={Boolean(loading)} on:click={requestCancelRun}><i class="ph ph-x-circle" aria-hidden="true"></i>Cancel run</button><button type="button" class="run-menu-item danger" disabled={Boolean(loading)} on:click={requestDeleteRun}><i class="ph ph-trash" aria-hidden="true"></i>Delete run</button></div></details>{/if}</div></div>

{#if ['training','team_review'].includes(run.status)}
  <section class="continue-card panel" aria-labelledby="continue-title"><div><span class="eyebrow">Continue where you left off</span><h2 id="continue-title">{primaryLabel(run)}</h2></div><a class="button" href={primaryHref(run)}>{primaryLabel(run)}<i class="ph ph-arrow-right" aria-hidden="true"></i></a></section>
{:else if run.status === 'mega_selection'}
  <section id="mega-selection" class="mega-selection panel" aria-labelledby="mega-selection-title">
    <div class="mega-intro">
      <span class="eyebrow">Before the final battle</span>
      <h2 id="mega-selection-title">Choose one Mega Evolution</h2>
      <p>The chosen Pokémon receives its required Mega Stone for the finale. This choice is saved immediately and cannot be changed during battle.</p>
    </div>
    <div class="mega-options" role="group" aria-label="Available Mega Evolutions">
      {#each run.mega_options as option}
        <button
          type="button"
          disabled={Boolean(loading)}
          aria-label={`Choose ${option.mega_species} for the final battle with ${option.required_item}`}
          on:click={() => selectMega(option.entry_id, option.mega_species_id)}
        >
          <PokemonSprite species={option.mega_species} decorative size="large" />
          <span><small>{option.from_species}</small><strong>{option.mega_species}</strong><em>{option.required_item}</em></span>
          <i class={`ph ${loading === `mega:${option.entry_id}:${option.mega_species_id}` ? 'ph-circle-notch' : 'ph-arrow-right'}`} aria-hidden="true"></i>
        </button>
      {/each}
    </div>
  </section>
{:else if ['ready','battle_queued','battling','stage_result','preparing'].includes(run.status) && view.current_stage}
  <!--
    One hero owns the current opponent, the level rule and the only primary action.
    Everything else on this page is either the draft, the result, or collapsed detail.
  -->
  <section id="current-stage" class="stage-hero panel" style={`--stage-accent:${view.current_stage.visual_accent}`} aria-label={`Current battle ${run.current_stage_index + 1} of ${view.stages.length}`}>
    <TrainerPortrait trainerId={view.current_stage.trainer_asset_id} name={view.current_stage.name} accent={view.current_stage.visual_accent} />
    <div class="stage-copy">
      <span class="eyebrow">Battle {run.current_stage_index + 1} / {view.stages.length}{#if view.current_stage.specialty} · {view.current_stage.specialty} specialist{/if}</span>
      <h2>{view.current_stage.name}</h2>
      <p><b>Lv {view.current_stage.level}</b>{#if view.current_stage.opponent_level && view.current_stage.opponent_level !== view.current_stage.level} · opponent Lv {view.current_stage.opponent_level} ({difficultyLabel(run.difficulty)}){/if} · {view.current_stage.title}</p>
      {#if view.current_stage.full_heal_before === false && downed.size}<p class="gauntlet-note"><i class="ph ph-warning" aria-hidden="true"></i>Elite Four gauntlet: {downed.size} Pokémon stayed down. You go in with {run.picks.length - downed.size} of {run.picks.length}.</p>{/if}
      {#if latestResult && latestResult.stage_id === view.current_stage.id && latestResult.status !== 'won'}<p class="retry-note">{outcomeTitle(latestResult.status)} recorded. Retrying creates a new match and keeps the previous replay.</p>{/if}
    </div>
    <div class="stage-action">
      {#if run.status === 'preparing' || run.active_match_id || run.auto_run_paused}<strong role="status">{run.status === 'preparing' ? 'Preparing your team' : run.active_match_id ? (run.battle_experience === 'quick-sim' ? 'Simulating real Showdown battle…' : 'Battle in progress') : 'Auto-Run paused'}</strong>{/if}
      <div class="stage-buttons">
        {#if run.status === 'preparing'}
          <span class="stage-auto" role="status"><i class="ph ph-circle-notch" aria-hidden="true"></i>Validating your sets with Showdown…</span>
        {:else if run.active_match_id}
          {#if run.battle_experience !== 'quick-sim'}<a class="button" href={`/battle/${run.active_match_id}`}>Resume battle<i class="ph ph-arrow-up-right" aria-hidden="true"></i></a>{:else}<span class="quick-sim-spinner" role="status"><i class="ph ph-circle-notch" aria-hidden="true"></i>Resolving</span>{/if}
          {#if autoRunAvailable && !run.auto_run_paused}<button class="button secondary compact" disabled={Boolean(loading)} on:click={pauseAutoRun}>{loading === 'pause-auto' ? 'Pausing…' : 'Pause Auto-Run'}</button>{/if}
        {:else if run.auto_run_paused && autoRunAvailable}
          <button class="button" disabled={Boolean(loading)} on:click={continueAutoRun}>{loading === 'continue-auto' ? 'Continuing…' : 'Continue Run'}</button>
        {:else if run.auto_advance_at && autoRunAvailable}
          <span class="stage-auto" role="status"><i class="ph ph-circle-notch" aria-hidden="true"></i>Starting automatically…</span>
          <button class="button secondary compact" disabled={Boolean(loading)} on:click={pauseAutoRun}>{loading === 'pause-auto' ? 'Pausing…' : 'Pause Auto-Run'}</button>
        {:else}
          <button class="button launch" disabled={Boolean(loading)} on:click={launch}><i class="ph ph-sword" aria-hidden="true"></i>{loading === 'launch' ? 'Creating match…' : run.status === 'stage_result' && latestResult?.status !== 'won' ? `Retry ${view.current_stage.name}` : `Fight ${view.current_stage.name}`}</button>
        {/if}
      </div>
      {#if run.status === 'ready' && run.current_stage_index === 0}<button class="link-button" disabled={Boolean(loading)} on:click={openAdvancedTeam}>Advanced team setup</button>{/if}
    </div>
  </section>
{/if}

<!--
  The run carries its own persisted error (failed automatic team preparation, a technical
  match failure). Without this the user lands on Team review or a failed run with no reason.
-->
{#if run.error && dismissedRunError !== run.error}
  <section class="run-error panel" role="alert">
    <i class="ph ph-warning" aria-hidden="true"></i>
    <div>
      <strong>{run.status === 'team_review' ? 'Automatic team preparation could not finish' : 'This run recorded a technical problem'}</strong>
      <p>{run.error}</p>
      <small>{run.status === 'team_review' ? 'Fix the listed set details below, then validate and lock the team.' : 'The stage was not counted as a loss and can be retried.'}</small>
    </div>
    <button class="link-button" on:click={() => (dismissedRunError = run?.error || '')}>Dismiss</button>
  </section>
{/if}

{#if run.compatibility_notice}<section class="snapshot-warning panel" role="alert"><i class="ph ph-warning" aria-hidden="true"></i><div><strong>This saved run uses retired Draft Rules</strong><p>{run.compatibility_notice}</p></div></section>{/if}

<!--
  The next stage now starts within half a second, so gating this on `stage_result`
  meant the player never saw the outcome of the battle they just watched. The last
  result stays up until the next one replaces it.
-->
{#if latestResult && !['drafting','preparing','training','team_review'].includes(run.status)}
  <span id="latest-result" class="result-anchor" aria-hidden="true"></span>
  <section class:success={latestResult.status === 'won'} class:technical={['failed','cancelled','interrupted'].includes(latestResult.status)} class="result-card panel"><div class="result-icon"><i class={`ph ${latestResult.status === 'won' ? 'ph-trophy' : latestResult.status === 'lost' ? 'ph-x-circle' : 'ph-warning'}`} aria-hidden="true"></i></div><div class="result-copy"><span class="eyebrow">Battle result</span><h2>{outcomeTitle(latestResult.status)} — {latestStage?.name}{latestResult.status === 'won' ? ' defeated' : ''}</h2><p>{outcomeDetail(latestResult.status)}</p>{#if view.latest_battle_summary}<div class="battle-summary"><div><strong>Your team used</strong><div>{#each view.latest_battle_summary.player_participants as species}<span><PokemonSprite {species} size="small" decorative />{species}</span>{/each}</div></div><div><strong>Defeated</strong><small>Yours</small><div>{#each view.latest_battle_summary.player_fainted as species}<span class="fainted"><PokemonSprite {species} size="small" decorative />{species}</span>{:else}<em>None</em>{/each}</div><small>{latestStage?.name}</small><div>{#each view.latest_battle_summary.opponent_fainted as species}<span class="fainted opponent"><PokemonSprite {species} size="small" decorative />{species}</span>{:else}<em>None</em>{/each}</div></div></div>{/if}</div><div class="result-actions"><a class="button secondary" href={`/replay/${latestResult.match_id}`}><i class="ph ph-play-circle" aria-hidden="true"></i>Watch replay</a>{#if run.status !== 'completed' && (!autoRunAvailable || run.auto_run_paused || latestResult.status !== 'won')}<button class="button" disabled={Boolean(loading)} on:click={run.auto_run_paused ? continueAutoRun : launch}>{latestResult.status === 'won' ? `Continue to ${view.current_stage?.name}` : `Retry ${latestStage?.name}`}</button>{/if}</div></section>
{/if}

{#if run.status === 'completed'}<section id="summary" class="complete panel"><i class="ph ph-crown" aria-hidden="true"></i><span class="eyebrow">Kanto Gauntlet complete</span><h2>Champion cleared</h2><p>{view.statistics.wins} wins · {view.statistics.total_battles} battles · {view.statistics.total_turns} turns · {formatDuration(view.statistics.duration_seconds)}</p><dl><div><dt>Draft</dt><dd>{run.picks.length} Pokémon · {run.consumed_species_ids.length} species consumed</dd></div><div><dt>Recommended EVs</dt><dd>{view.statistics.ev_used} allocated</dd></div><div><dt>Rerolls</dt><dd>{view.statistics.rerolls_used} used</dd></div><div><dt>Controllers</dt><dd>{run.draft_controller_history.length ? 'AI → Me draft' : `${run.draft_controller.kind} draft`} · {run.battle_controller.agent_type} battle</dd></div><div><dt>Estimated API cost</dt><dd>${view.statistics.estimated_cost.toFixed(4)}</dd></div><div><dt>Average decision</dt><dd>{view.statistics.average_decision_latency_ms == null ? 'Not available' : `${Math.round(view.statistics.average_decision_latency_ms)} ms`}</dd></div></dl><div class="final-roster">{#each run.picks as pick}{@const current = currentByEntryId.get(pick.candidate.entry_id)}<span>{current?.species || pick.candidate.species}{#if current?.evolved}<i class="ph ph-sparkle evolved-mark" aria-hidden="true" title={`Evolved from ${pick.candidate.species}`}></i>{/if}<small>{pick.candidate.abilities.find((ability) => ability.id === run.ability_selections[pick.candidate.entry_id])?.name || 'No ability'}</small></span>{/each}</div><div class="final-actions"><a class="button" href="/challenges/new">Start new Draft run</a><a class="button secondary" href="#run-archive">View all battles</a></div></section>{/if}

{#if !['drafting','training','team_review'].includes(run.status)}<section id="campaign" class="campaign panel">
  <header><div><span class="eyebrow">Campaign route</span><h2>{run.status === 'completed' ? 'Kanto Gauntlet complete' : campaignBattleLabel(run.current_stage_index, view.stages.length, view.current_stage?.name || '')}</h2></div><span class="route-count">{view.statistics.stages_cleared} / {view.stages.length} cleared</span></header>
  <ol class="route-rail" aria-label="Kanto campaign progression">{#each view.stages as stage, index}{@const result = stageResult(stage.id)}<li class:current={index === run.current_stage_index && run.status !== 'completed'} class:won={result?.status === 'won'} class:failed={result && result.status !== 'won'} style={`--stage-accent:${stage.visual_accent}`} title={`${stage.name} · ${stage.specialty || stage.title} · Lv. ${stage.level}`} aria-current={index === run.current_stage_index && run.status !== 'completed' ? 'step' : undefined}><b>{result?.status === 'won' ? '✓' : index + 1}</b><span>{stage.name}</span></li>{/each}</ol>
</section>{/if}


{#if run.stage_results.length}
  <details id="run-archive" class="battle-history panel">
    <summary class="disclosure-summary"><span><i class="ph ph-clock-counter-clockwise" aria-hidden="true"></i><b>Battle history</b><small>{run.stage_results.length} recorded {run.stage_results.length === 1 ? 'battle' : 'battles'}</small></span><i class="ph ph-caret-down disclosure-caret" aria-hidden="true"></i></summary>
    <ol>{#each run.stage_results as result, index}<li><div><span class={`status-pill ${result.status === 'won' ? 'completed' : result.status === 'lost' ? 'failed' : result.status}`}>{outcomeTitle(result.status)}</span><strong>{view.stages[result.stage_index]?.name || result.stage_id}</strong><small>Battle {index + 1} · {result.turns} turns · {formatDuration(result.duration_seconds)}</small></div><a class="button secondary compact" href={`/replay/${result.match_id}`}>View replay</a></li>{/each}</ol>
  </details>
{/if}

{#if run.status === 'drafting' && run.current_offer}
  <section id="draft" class="draft panel" aria-labelledby="draft-title">
    {#key run.current_offer.fingerprint}
    <header class="roll-result">
      <h2 id="draft-title" class="draft-reels"><span class="visually-hidden" aria-live="polite">Generation {generationRomanNumeral(run.current_offer.generation)}, {run.current_offer.type} type</span><span aria-hidden="true" class:spinning={rollReveal?.mode === 'both' || rollReveal?.mode === 'generation'} class:locked={rollReveal?.mode === 'type' || rollReveal?.mode === 'pokemon'} class="draft-reel generation-reel"><small>GEN</small><span class="reel-window" aria-hidden="true"><span class="reel-track" style={`--reel-offset:${-((rollReveal?.generations.length || 1) - 1) * DRAFT_REEL_FRAME_HEIGHT}px`}>{#each rollReveal?.generations || [run.current_offer.generation] as generation}<b>{generationRomanNumeral(generation)}</b>{/each}</span></span></span><b class="reel-separator" aria-hidden="true">·</b><span aria-hidden="true" class:spinning={rollReveal?.mode === 'both' || rollReveal?.mode === 'type'} class:locked={rollReveal?.mode === 'generation' || rollReveal?.mode === 'pokemon'} class="draft-reel type-reel"><span class="reel-window" aria-hidden="true"><span class="reel-track" style={`--reel-offset:${-((rollReveal?.types.length || 1) - 1) * DRAFT_REEL_FRAME_HEIGHT}px`}>{#each rollReveal?.types || [run.current_offer.type] as type}<b style={`--type-color:${pokemonTypeColor(type)}`}>{type}</b>{/each}</span></span></span></h2>
    </header>
    <div class="draft-workspace"><div class="draft-choice-area">
      {#if run.current_offer.options.length < run.definition.draft_rules.choice_count}<p class="pool-note" role="status"><i class="ph ph-info" aria-hidden="true"></i>The legal pool is nearly exhausted, so this offer contains fewer cards.</p>{/if}
      <p class="rarity-note"><i class="ph ph-sparkle" aria-hidden="true"></i>Higher-rated Pokémon appear less often. Points use the strongest reachable non-Mega evolution.</p>
      <div class:pending-reveal={Boolean(rollReveal)} class="offer-grid">{#each run.current_offer.options as option, index}<button data-rarity={option.draft_rarity} title={`Draft Rarity · Smogon Draft Points: ${option.draft_points}. Higher-rated Pokémon appear less often.`} style={`--reveal-index:${index}`} disabled={Boolean(loading) || Boolean(rollReveal)} aria-label={`Draft ${option.species}, ${rarityLabel(option.draft_rarity)}, ${option.draft_points} Smogon Draft Points`} aria-keyshortcuts={index < 9 ? String(index + 1) : undefined} on:click={() => pick(option.entry_id)}><span class="shortcut" aria-hidden="true">{index + 1}</span><span class="dex">#{String(option.national_dex_number).padStart(4, '0')} · Gen {option.introduction_generation}</span><span class="rarity-badge">{rarityLabel(option.draft_rarity)} · {option.draft_points} pts</span><div class="offer-sprite"><PokemonSprite species={option.species} size="large" decorative /></div><h3>{option.species}</h3><p class="type-badges"><TypeBadges types={option.types} /></p><div class="card-foot">{#if option.base_stat_total}<small>BST <b>{option.base_stat_total}</b></small>{/if}<span>Choose <i class="ph ph-arrow-right" aria-hidden="true"></i></span></div>{#if loading === `pick:${option.entry_id}`}<em role="status"><i class="ph ph-spinner-gap" aria-hidden="true"></i> Locking pick…</em>{/if}</button>{/each}</div>
      <footer>
        {#if run.draft_controller.kind === 'human'}
          {@const pokemonReason = rerollBlockedReason('pokemon', run, view, loading, rollReveal)}
          {@const typeReason = rerollBlockedReason('type', run, view, loading, rollReveal)}
          {@const generationReason = rerollBlockedReason('generation', run, view, loading, rollReveal)}
          <div class="reroll-actions">
            <span class="reroll-control" class:unavailable={Boolean(pokemonReason)} data-tooltip={pokemonReason || undefined} title={pokemonReason || 'Keep Generation and Type; replace only these Pokémon'}>
              <button class="button secondary" title={pokemonReason || 'Keep Generation and Type; replace only these Pokémon'} aria-disabled={Boolean(pokemonReason)} aria-describedby={pokemonReason ? 'reroll-pokemon-reason' : undefined} on:click={() => { if (!pokemonReason) void requestReroll('pokemon'); }}><i class="ph ph-arrows-clockwise" aria-hidden="true"></i><span><strong>{loading === 'reroll:pokemon' ? 'Rolling…' : 'Reroll Pokémon'}</strong><small>Keep Gen + Type</small></span><b>{run.rerolls_remaining}</b></button>
              {#if pokemonReason}<span id="reroll-pokemon-reason" class="visually-hidden">{pokemonReason}</span>{/if}
            </span>
            <span class="reroll-control" class:unavailable={Boolean(typeReason)} data-tooltip={typeReason || undefined} title={typeReason || 'Keep Generation; change Type and Pokémon'}>
              <button class="button ghost" title={typeReason || 'Keep Generation; change Type and Pokémon'} aria-disabled={Boolean(typeReason)} aria-describedby={typeReason ? 'reroll-type-reason' : undefined} on:click={() => { if (!typeReason) void requestReroll('type'); }}><i class="ph ph-palette" aria-hidden="true"></i><span><strong>{loading === 'reroll:type' ? 'Rolling…' : 'Reroll Type'}</strong><small>Keep Generation</small></span><b>{run.type_rerolls_remaining}</b></button>
              {#if typeReason}<span id="reroll-type-reason" class="visually-hidden">{typeReason}</span>{/if}
            </span>
            <span class="reroll-control" class:unavailable={Boolean(generationReason)} data-tooltip={generationReason || undefined} title={generationReason || 'Keep Type; change Generation and Pokémon'}>
              <button class="button ghost" title={generationReason || 'Keep Type; change Generation and Pokémon'} aria-disabled={Boolean(generationReason)} aria-describedby={generationReason ? 'reroll-generation-reason' : undefined} on:click={() => { if (!generationReason) void requestReroll('generation'); }}><i class="ph ph-clock-counter-clockwise" aria-hidden="true"></i><span><strong>{loading === 'reroll:generation' ? 'Rolling…' : 'Reroll Generation'}</strong><small>Keep Type</small></span><b>{run.generation_rerolls_remaining}</b></button>
              {#if generationReason}<span id="reroll-generation-reason" class="visually-hidden">{generationReason}</span>{/if}
            </span>
          </div>
          {@const blocked = (['pokemon','type','generation'] as RerollKind[]).map((kind) => [kind, rerollBlockedReason(kind, run, view, loading, rollReveal)] as const).filter(([, reason]) => reason)}
          {#if blocked.length}<ul class="reroll-blocked" role="status">{#each blocked as [kind, reason]}<li><b>{kind === 'pokemon' ? 'Pokémon' : kind === 'type' ? 'Type' : 'Generation'} reroll</b>{reason}</li>{/each}</ul>{/if}
        {:else if run.draft_controller.kind === 'agent'}
          <div class="agent-actions">{#if agentFailed}<button class="button" disabled={Boolean(loading) || Boolean(rollReveal)} on:click={agentDraft}><i class="ph ph-robot" aria-hidden="true"></i>{loading === 'agent' ? 'AI is choosing…' : 'Retry AI decision'}</button>{:else}<span class="agent-busy" role="status"><i class="ph ph-robot" aria-hidden="true"></i>{loading === 'agent' ? 'AI is choosing…' : 'AI is drafting…'}</span>{/if}<button class="button secondary" disabled={Boolean(loading) || Boolean(rollReveal)} on:click={takeOverDraft}>{loading === 'takeover' ? 'Taking over…' : 'Take over manually'}</button></div>
        {/if}
        <span class:busy={Boolean(loading)} class="offer-saved" role="status"><i class={`ph ${loading ? 'ph-circle-notch' : 'ph-cloud-check'}`} aria-hidden="true"></i>{loading ? 'Saving change…' : 'All progress saved'}</span>
      </footer>
    </div><aside class="draft-roster" aria-label="Current drafted roster"><span class="eyebrow">Your team</span><h3>{run.picks.length} / {run.definition.draft_rules.roster_size}</h3><div>{#each Array(run.definition.draft_rules.roster_size) as _, index}{#if run.picks[index]}{@const pick = run.picks[index]}<article><PokemonSprite species={pick.candidate.species} size="small" decorative /><span><strong>{pick.candidate.species}</strong><TypeBadges types={pick.candidate.types} compact /></span></article>{:else}<article class="empty"><b>{index + 1}</b><span>Open slot</span></article>{/if}{/each}</div><details class="opponent-preview"><summary class="disclosure-summary"><span><i class="ph ph-path" aria-hidden="true"></i><b>Who you will fight</b><small>{view.stages.length} stages</small></span><i class="ph ph-caret-down disclosure-caret" aria-hidden="true"></i></summary><ol class="campaign-preview">{#each view.stages as stage (stage.id)}<li style={`--stage-accent:${stage.visual_accent}`}><b>{stage.name}</b><span>{stage.specialty || stage.title}</span><i>Lv {stage.level}</i></li>{/each}</ol><p>Draft coverage for these types. Every shown card leaves the run: Pokémon keeps Gen + Type, Type keeps Gen, Generation keeps Type, and each power is single-use.</p></details></aside></div>
    {#if loading === 'agent'}<p class="async-note" role="status">Waiting for one strict legal action. This offer will not reroll while the AI responds.</p>{/if}
    {/key}
  </section>
{/if}

{#if run.picks.length && run.status !== 'drafting'}
  <!-- The locked roster is reference, not a dashboard: one slim sprite strip. -->
  <section class="roster-strip" aria-label="Drafted roster">{#each run.picks as pick}{@const out = downed.has(pick.candidate.entry_id)}{@const current = currentByEntryId.get(pick.candidate.entry_id)}{@const species = current?.species || pick.candidate.species}<span class:downed={out} title={out ? `${species} is out for the rest of this gauntlet` : `${species} · ${(current?.types || pick.candidate.types).join('/')}${current?.evolved ? ` · evolved from ${pick.candidate.species}` : ''}`}><PokemonSprite {species} size="small" decorative /><b>{species}</b>{#if current?.evolved}<i class="ph ph-sparkle evolved-mark" aria-hidden="true"></i>{/if}{#if out}<i class="ph ph-x" aria-hidden="true"></i>{/if}</span>{/each}</section>
{/if}

{#if run.draft_history.length}
  <details class="draft-history panel"><summary class="disclosure-summary"><span><i class="ph ph-cards" aria-hidden="true"></i><b>Draft history</b><small>{run.draft_history.length} resolved {run.draft_history.length === 1 ? 'offer' : 'offers'}</small></span><i class="ph ph-caret-down disclosure-caret" aria-hidden="true"></i></summary><ol>{#each run.draft_history as item}<li><header><strong>Round {item.offer.round} · Generation {item.offer.generation} · {item.offer.type}</strong><span class={`history-outcome ${item.outcome}`}>{historyOutcomeLabel(item.outcome)}</span></header><div>{#each item.offer.options as option}<span class:selected={option.entry_id === item.selected_entry_id}><PokemonSprite species={option.species} size="small" decorative /><b>{option.species}</b>{#if option.entry_id === item.selected_entry_id}<small>selected</small>{:else}<small>consumed</small>{/if}</span>{/each}</div></li>{/each}</ol></details>
{/if}

{#if ['training','team_review'].includes(run.status)}
  <section id="training" class="training panel" aria-labelledby="training-title"><header><div><span class="eyebrow">Optional advanced setup</span><h2 id="training-title">Recommended EVs applied</h2><p>Every drafted Pokémon starts with its own legal recommended spread. Use a preset or fine-tune only if you want to.</p></div><div class="training-actions"><button class="button ghost compact" on:click={requestResetAll}>Reset all</button><div class="ev-counter"><strong>{evUsed}</strong><span>team EV total</span></div></div></header>
    <div class="ev-cards">{#each run.picks as pick}{@const spread = allocations[pick.candidate.entry_id] || emptyEvSpread()}{@const pokemonPresets = recommendedEvPresets(pick.candidate)}<article><div class="ev-identity"><PokemonSprite species={pick.candidate.species} size="medium" decorative /><div class="ev-mon"><div><strong>{pick.candidate.species}</strong><TypeBadges types={pick.candidate.types} compact /><small>{evSpreadTotal(spread)} / {run.definition.training_rules.per_pokemon_max} EV</small></div><button class="link-button" on:click={() => resetPokemon(pick.candidate.entry_id)}>Reset</button></div></div>{#if run.draft_pool.abilities_supported}<label class="ability-field"><span>Legal ability</span><select value={run.ability_selections[pick.candidate.entry_id] || ''} disabled={Boolean(loading) || pick.candidate.abilities.length <= 1} aria-label={`${pick.candidate.species} ability`} on:change={(event) => saveAbility(pick.candidate.entry_id, event.currentTarget.value)}>{#each pick.candidate.abilities as ability}<option value={ability.id}>{ability.name}{ability.hidden ? ' · Hidden' : ''}</option>{/each}</select><small>{pick.candidate.abilities.length <= 1 ? 'Only legal ability; selected automatically.' : 'Saved separately and enforced by final validation.'}</small></label>{:else}<p class="ability-unavailable"><i class="ph ph-info" aria-hidden="true"></i>Abilities do not exist in this format.</p>{/if}<div class="ev-progress" aria-label={`${evSpreadTotal(spread)} of ${run.definition.training_rules.per_pokemon_max} EV allocated`}><span style={`width:${Math.min(100, evSpreadTotal(spread) / run.definition.training_rules.per_pokemon_max * 100)}%`}></span></div><div class="preset-row" aria-label={`${pick.candidate.species} recommended EV presets`}>{#each pokemonPresets as preset}<button class:recommended={preset.recommended} on:click={() => applyPreset(pick.candidate.entry_id, preset.spread)}><span>{#if preset.recommended}<b>Recommended</b>{/if}{preset.label}</span><small>{preset.reason}</small></button>{/each}</div><div class="stat-grid">{#each statEntries as stat}<label><span>{stat[1]}{#if baseStat(pick.candidate, stat[0]) !== null}<b>{baseStat(pick.candidate, stat[0])}</b>{/if}</span><input type="number" inputmode="numeric" min="0" max={run.definition.training_rules.per_stat_max} value={spread[stat[0]]} aria-label={`${pick.candidate.species} ${stat[1]} EVs`} on:input={(event) => setEv(pick.candidate.entry_id, stat[0], Number(event.currentTarget.value))} /><button title={`Set ${stat[1]} to the largest legal value`} aria-label={`Maximize ${pick.candidate.species} ${stat[1]}`} on:click={() => setEv(pick.candidate.entry_id, stat[0], run?.definition.training_rules.per_stat_max || 252)}>Max</button></label>{/each}</div></article>{/each}</div>
    {#if trainingNotice}<p class="training-notice" role="status">{trainingNotice}</p>{/if}<footer><span>Limits apply per Pokémon: {run.definition.training_rules.per_pokemon_max} total and {run.definition.training_rules.per_stat_max} per stat. There is no shared team pool.</span><button class="button" disabled={Boolean(loading)} on:click={saveTraining}>{loading === 'training' ? 'Saving legal spreads…' : run.status === 'team_review' ? 'Save updated spreads' : 'Keep these EVs and continue'}</button></footer></section>
{/if}

{#if run.status === 'team_review'}
  <section id="team-review" class="team-review panel"><div><span class="eyebrow">Advanced team setup</span><h2>Your legal recommended sets are ready</h2><p>The editor starts with every drafted species, exact recommended EVs, selected legal abilities, required form items, and up to four practical legal moves from the pinned Showdown data. Continue immediately or customize the sets.</p><div class="team-tools"><button class="button secondary compact" on:click={copyScaffold}><i class={`ph ${copied ? 'ph-check' : 'ph-copy'}`} aria-hidden="true"></i>{copied ? 'Scaffold copied' : 'Copy scaffold'}</button><button class="button ghost compact" on:click={requestRestoreScaffold}>Restore recommended setup</button></div><div class="lock-note"><i class="ph ph-lock" aria-hidden="true"></i><span><strong>Validation locks the roster.</strong><small>Drafted species/forms, abilities, and EVs cannot change after the campaign starts.</small></span></div></div><label>Showdown team export<textarea rows="26" bind:value={teamText} placeholder="Review or customize the six recommended sets…" spellcheck="false"></textarea></label><footer><span>The pinned Showdown validator is authoritative. Exact validator output stays available under technical details if validation fails.</span><button class="button" disabled={!teamText.trim() || Boolean(loading)} on:click={requestFinalizeTeam}>{loading === 'team' ? 'Validating with Showdown…' : 'Validate and lock team'}</button></footer></section>
{/if}


{#if run.status === 'failed'}<section class="ending panel"><i class="ph ph-warning" aria-hidden="true"></i><span class="eyebrow">Run interrupted</span><h2>Draft run failed</h2><p>A technical problem stopped this run. The draft, results, and replays are saved. Retrying the current stage creates a new match and keeps every earlier replay.</p><div>{#if view.current_stage}<button class="button" disabled={Boolean(loading)} on:click={launch}>{loading === 'launch' ? 'Creating match…' : `Retry ${view.current_stage.name}`}</button>{/if}<a class="button secondary" href="/challenges">Back to history</a></div></section>{/if}

{#if ['cancelled','abandoned'].includes(run.status)}<section class="ending panel"><i class="ph ph-flag" aria-hidden="true"></i><span class="eyebrow">Run ended</span><h2>{run.status === 'abandoned' ? 'Draft run retired' : 'Draft run cancelled'}</h2><p>The saved draft, results, and existing replays remain available. No active stage can advance this run.</p><div><a class="button" href="/challenges/new">Start a new Draft run</a><a class="button secondary" href="/challenges">Back to history</a><button class="button ghost" disabled={Boolean(loading)} on:click={requestDeleteRun}>Delete run</button></div></section>{/if}


<details class="run-details panel"><summary class="disclosure-summary"><span><i class="ph ph-database" aria-hidden="true"></i><b>Saved run details</b><small>Seed, rules and Showdown snapshot</small></span><i class="ph ph-caret-down disclosure-caret" aria-hidden="true"></i></summary><dl><div><dt>Seed</dt><dd>{run.seed}</dd></div><div><dt>Definition</dt><dd>{run.definition.id} · v{run.definition.version}</dd></div><div><dt>Draft rules</dt><dd>{run.draft_rules_version}</dd></div><div><dt>Format</dt><dd>{run.definition.format} · Gen {run.draft_pool.format_generation}</dd></div><div><dt>Showdown</dt><dd>{run.draft_pool.showdown_version}</dd></div><div><dt>Pool catalog</dt><dd><code>{run.draft_pool.catalog_hash}</code></dd></div>{#if run.definition.source}<div><dt>Opponent source</dt><dd>{run.definition.source.game} · Gen {run.definition.source.generation}</dd></div><div><dt>Source variant</dt><dd>{run.definition.source.variant}</dd></div><div><dt>Compatibility</dt><dd>{run.definition.source.compatibility_note}</dd></div>{/if}</dl></details>

<!--
  One evolution moment per stage transition, shown before the next-opponent card. Reduced
  motion keeps the card but drops the glow/scale animation — this is a real state change,
  not decoration, so it stays visible either way.
-->
{#if evolutionReveal}
  <div class="evolution-reveal" role="status" aria-live="polite">
    {#each evolutionReveal as item (item.entryId)}
      <div class="evolution-card">
        <span class="evolution-glow" aria-hidden="true"></span>
        <PokemonSprite species={item.to} size="large" decorative />
        <p><b>{item.from}</b> evolved into <b>{item.to}</b>!</p>
      </div>
    {/each}
  </div>
{/if}

<!--
  The next stage is already starting server-side; this only announces who it is against.
  Short, self-dismissing, and skipped entirely under prefers-reduced-motion.
-->
{#if stageTransition}
  <div class="stage-transition" role="status" aria-live="polite" style={`--stage-accent:${stageTransition.accent}`}>
    <div class="stage-transition-card">
      <TrainerPortrait trainerId={stageTransition.trainerId} name={stageTransition.name} accent={stageTransition.accent} decorative />
      <div>
        <span>Battle {stageTransition.index + 1} / {stageTransition.total}</span>
        <strong>{stageTransition.name}</strong>
        <em>{stageTransition.specialty ? `${stageTransition.specialty} specialist · ` : ''}Lv {stageTransition.level}{#if stageTransition.playerLevel && stageTransition.playerLevel !== stageTransition.level} · you Lv {stageTransition.playerLevel}{/if}</em>
      </div>
    </div>
  </div>
{/if}

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

{#if evolutionChoicePrompt}
  {@const prompt = evolutionChoicePrompt}
  <div class="confirmation-layer">
    <button class="confirmation-backdrop" aria-label="Cancel this pick" on:click={() => (evolutionChoicePrompt = null)}></button>
    <div class="confirmation-card evolution-choice-card" role="alertdialog" aria-modal="true" aria-labelledby="evolution-choice-title">
      <div><span class="eyebrow">One-time choice</span><h2 id="evolution-choice-title">{prompt.species} evolves more than one way</h2><p>Pick its future line now — this applies for the rest of the run and never interrupts Auto-Run again.</p></div>
      <div class="evolution-choice-options">
        {#each prompt.options as option (option.id)}
          <button type="button" class="evolution-choice-option" disabled={Boolean(loading)} on:click={() => pick(prompt.entryId, option.id)}>
            <PokemonSprite species={option.name} size="medium" decorative />
            <span>{option.name}</span>
          </button>
        {/each}
      </div>
      <div class="confirmation-actions"><button class="button ghost" on:click={() => (evolutionChoicePrompt = null)}>Cancel</button></div>
    </div>
  </div>
{/if}

{#if error}<section class="error-box" role="alert"><strong>{error}</strong>{#if technicalError && technicalError !== error}<details><summary>Technical details</summary><code>{technicalError}</code></details>{/if}<button class="link-button" on:click={() => { error = ''; technicalError = ''; }}>Dismiss</button></section>{/if}
{/if}

<style>.battle-summary{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-top:.6rem}.battle-summary>div{padding:.5rem .55rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.battle-summary>div>strong,.battle-summary>div>small{display:block;margin-bottom:.4rem}.battle-summary>div>small{margin:.45rem 0 .25rem;color:var(--muted);font:.54rem var(--mono);text-transform:uppercase}.battle-summary>div>div{display:flex;flex-wrap:wrap;gap:.35rem}.battle-summary span{display:flex;align-items:center;gap:.28rem;padding:.18rem .38rem;border-radius:.45rem;background:var(--surface);font-size:.62rem}.battle-summary span.fainted{opacity:.68;filter:grayscale(.75)}.battle-summary span.opponent{border:1px solid color-mix(in srgb,var(--danger) 30%,var(--border))}.battle-summary em{color:var(--muted);font:.6rem var(--mono)}.result-copy{min-width:0;flex:1}.battle-history{margin-bottom:.9rem;padding:1.25rem;box-shadow:none}.battle-history>summary{display:flex;align-items:center;gap:.5rem;font:700 .85rem var(--display);cursor:pointer}.battle-history ol{display:grid;gap:.45rem;margin:.8rem 0 0;padding:0;list-style:none}.battle-history li{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.7rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong)}.battle-history li>div{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:.2rem .55rem}.battle-history li small{grid-column:2;color:var(--muted);font:.58rem var(--mono)}.draft-history{margin-bottom:.9rem;padding:1rem;box-shadow:none}.draft-history>summary{font-weight:700}.draft-history ol{display:grid;gap:.6rem;margin:.9rem 0 0;padding:0;list-style:none}.draft-history li{padding:.75rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong)}.draft-history li header{display:flex;align-items:center;justify-content:space-between;gap:.6rem}.draft-history li>div{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.55rem}.draft-history li>div>span{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:0 .4rem;min-width:145px;padding:.35rem .5rem;border:1px solid var(--border);border-radius:.5rem;color:var(--muted)}.draft-history li>div>span.selected{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,transparent);color:var(--text)}.draft-history li>div small{grid-column:2;font:.52rem var(--mono)}.history-outcome{padding:.25rem .45rem;border-radius:999px;background:color-mix(in srgb,var(--warning) 10%,transparent);color:var(--warning);font:.55rem var(--mono)}.history-outcome.picked{background:color-mix(in srgb,var(--accent) 10%,transparent);color:var(--accent)}.breadcrumbs{display:flex;align-items:center;gap:.35rem;margin-bottom:.8rem;color:var(--muted);font:.65rem var(--mono)}.breadcrumbs a{color:var(--accent)}.page-head p,.panel p{color:var(--muted);line-height:1.5}.head-actions{display:flex;align-items:center;gap:.6rem}.button.danger{border-color:color-mix(in srgb,var(--danger) 45%,var(--border));background:transparent;color:var(--danger)}.continue-card{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.8rem;padding:1.15rem;border-color:color-mix(in srgb,var(--accent) 42%,var(--border));background:linear-gradient(110deg,color-mix(in srgb,var(--accent) 8%,var(--panel)),var(--panel))}.continue-card h2{margin:.2rem 0}.snapshot-warning,.result-card{display:flex;align-items:flex-start;gap:.9rem;margin-bottom:.7rem;padding:.9rem 1rem}.snapshot-warning>i{color:var(--warning);font-size:1.7rem}.snapshot-warning p{margin:.25rem 0}.result-card{border-color:color-mix(in srgb,var(--danger) 42%,var(--border))}.result-card.success{border-color:color-mix(in srgb,var(--accent) 48%,var(--border))}.result-card.technical{border-color:color-mix(in srgb,var(--warning) 48%,var(--border))}.result-icon{display:grid;place-items:center;width:52px;aspect-ratio:1;border-radius:50%;background:color-mix(in srgb,var(--danger) 12%,var(--surface));color:var(--danger);font-size:1.6rem}.result-card.success .result-icon{background:color-mix(in srgb,var(--accent) 12%,var(--surface));color:var(--accent)}.result-card.technical .result-icon{background:color-mix(in srgb,var(--warning) 12%,var(--surface));color:var(--warning)}.result-card>div:nth-child(2){flex:1}.result-card h2{margin:.2rem 0}.result-card p{margin:.2rem 0}.result-meta{color:var(--muted);font:.62rem var(--mono)}.result-actions{display:flex;flex-shrink:0;flex-direction:column;gap:.45rem}.campaign,.draft,.roster,.training,.team-review,.stage,.active,.complete,.ending{margin-bottom:.9rem;padding:1.25rem;box-shadow:none}.campaign header,.draft header,.training header{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem}.campaign h2,.draft h2,.training h2,.team-review h2,.complete h2,.ending h2{margin:.25rem 0}.campaign-stats{display:flex;gap:1rem}.campaign ol{display:grid;grid-template-columns:repeat(13,minmax(108px,1fr));gap:.4rem;overflow-x:auto;margin:1rem 0 0;padding:0 0 .5rem;list-style:none}.campaign li{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:.4rem;min-width:108px;padding:.58rem;border:1px solid var(--border);border-radius:.55rem}.campaign li>span{display:grid;place-items:center;width:24px;aspect-ratio:1;border-radius:50%;background:var(--surface);font:.62rem var(--mono)}.campaign li.current{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 7%,var(--panel))}.campaign li.won>span{background:var(--accent);color:var(--accent-ink)}.campaign li.failed{border-color:color-mix(in srgb,var(--danger) 40%,var(--border))}.pool-note,.async-note{display:flex;align-items:center;gap:.45rem;padding:.65rem;border-radius:.55rem;background:color-mix(in srgb,var(--warning) 8%,transparent);font-size:.72rem}.offer-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem;margin-top:1rem}.offer-grid button{position:relative;display:grid;gap:.35rem;min-height:205px;padding:1.1rem;border:1px solid var(--border);border-radius:.75rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer;transition:transform .16s ease,border-color .16s ease}.offer-grid button:hover:not(:disabled),.offer-grid button:focus-visible{transform:translateY(-3px);border-color:var(--accent)}.offer-grid button>span,.offer-grid button p{color:var(--muted);font:.65rem var(--mono)}.offer-grid h3{margin:.5rem 0 0;font-size:1.25rem}.offer-grid em{position:absolute;inset:0;display:grid;place-items:center;border-radius:inherit;background:color-mix(in srgb,var(--bg) 88%,transparent);color:var(--accent);font-style:normal}.draft footer,.training footer,.team-review footer{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-top:1rem}.agent-actions,.team-tools{display:flex;flex-wrap:wrap;gap:.5rem}.offer-saved{color:var(--muted);font:.6rem var(--mono)}.offer-saved i{color:var(--accent)}.training-actions{display:flex;align-items:center;gap:.8rem}.ev-counter{display:grid;text-align:right}.ev-counter strong{color:var(--accent);font-size:1.7rem}.ev-counter span{color:var(--muted);font:.62rem var(--mono)}.ev-cards{display:grid;gap:.55rem;margin-top:1rem}.ev-cards article{display:grid;gap:.65rem;padding:.8rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.ev-mon{display:flex;align-items:center;justify-content:space-between}.ev-mon>div{display:grid}.ev-mon small{color:var(--muted);font:.6rem var(--mono)}.ability-field{display:grid;gap:.25rem;padding:.6rem;border:1px solid color-mix(in srgb,var(--accent) 30%,var(--border));border-radius:.55rem;background:color-mix(in srgb,var(--accent) 5%,transparent)}.ability-field>span{font-weight:700}.ability-field select{width:100%}.ability-field small,.ability-unavailable{color:var(--muted);font:.58rem/1.4 var(--mono)}.ability-unavailable{display:flex;align-items:center;gap:.4rem;margin:0}.preset-row{display:flex;flex-wrap:wrap;gap:.35rem}.preset-row button,.stat-grid label button{min-height:30px;padding:.3rem .45rem;border:1px solid var(--border);border-radius:.45rem;background:var(--surface);color:var(--muted);font:.58rem var(--mono);cursor:pointer}.preset-row button:hover,.stat-grid label button:hover{border-color:var(--accent);color:var(--accent)}.stat-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:.4rem}.stat-grid label{display:grid;grid-template-columns:1fr auto;gap:.25rem}.stat-grid label span{grid-column:1/-1;color:var(--muted);font:.58rem var(--mono)}.stat-grid input{min-width:0;min-height:34px;padding:.35rem;text-align:center}.training-notice{padding:.55rem;border-radius:.5rem;background:color-mix(in srgb,var(--accent) 7%,transparent);font-size:.68rem}.team-review{display:grid;grid-template-columns:.8fr 1.2fr;gap:1.25rem}.team-review>label{display:grid;gap:.35rem}.team-review textarea{width:100%;font:.7rem/1.5 var(--mono)}.team-review footer{grid-column:1/-1}.team-review footer span{color:var(--muted);font-size:.68rem}.lock-note{display:flex;align-items:center;gap:.55rem;margin-top:1rem;padding:.7rem;border:1px solid var(--border);border-radius:.55rem}.lock-note i{color:var(--warning);font-size:1.2rem}.lock-note span{display:grid}.lock-note small{color:var(--muted);font:.6rem var(--mono)}.stage,.active{display:flex;align-items:center;justify-content:space-between;gap:2rem}.level-rule{display:flex;align-items:center;gap:.8rem;margin-top:1rem;padding:.75rem;border:1px solid var(--border);border-radius:.6rem}.retry-note{padding:.55rem;border-radius:.5rem;background:color-mix(in srgb,var(--warning) 8%,transparent);font-size:.68rem}.launch{min-height:54px}.live-dot{width:12px;aspect-ratio:1;border-radius:50%;background:var(--accent);box-shadow:0 0 0 6px color-mix(in srgb,var(--accent) 14%,transparent);animation:pulse 1.8s infinite}@keyframes pulse{50%{opacity:.45}}.complete,.ending{display:grid;place-items:center;padding:2.5rem;text-align:center}.complete>.ph,.ending>.ph{color:var(--accent);font-size:3rem}.complete dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;width:100%;margin:1rem 0}.complete dl div{display:grid;padding:.65rem;border:1px solid var(--border);border-radius:.55rem}.complete dt{color:var(--muted);font:.58rem var(--mono)}.complete dd{margin:.2rem 0 0;font-weight:700}.final-roster{display:flex;flex-wrap:wrap;justify-content:center;gap:.4rem}.final-roster span{display:grid;padding:.4rem .6rem;border:1px solid var(--border);border-radius:.55rem}.final-roster small{color:var(--muted);font:.55rem var(--mono)}.final-actions,.ending>div{display:flex;gap:.5rem;margin-top:1rem}.run-details{margin-bottom:1rem;padding:1rem;box-shadow:none}.run-details dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}.run-details dt{color:var(--muted);font:.58rem var(--mono)}.run-details dd{overflow-wrap:anywhere;margin:.2rem 0}.error-box{position:sticky;bottom:1rem;z-index:5;display:grid;grid-template-columns:1fr auto;gap:.5rem;margin-top:1rem;padding:.8rem;border:1px solid var(--danger);border-radius:.65rem;background:var(--panel);color:var(--danger);box-shadow:var(--shadow)}.error-box details{grid-column:1/-1;color:var(--muted)}.load-error{display:grid;justify-items:start;gap:.7rem;padding:1.5rem}@media(max-width:900px){.page-head,.campaign header,.draft header,.training header,.stage,.active,.result-card{align-items:stretch;flex-direction:column}.campaign-stats{flex-wrap:wrap}.offer-grid{grid-template-columns:repeat(2,1fr)}.team-review{grid-template-columns:1fr}.team-review footer{grid-column:auto}.ev-counter{text-align:left}.result-actions{align-self:stretch}.result-actions>*{flex:1}.stat-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){.continue-card,.snapshot-warning{align-items:stretch;flex-direction:column}.continue-card .button{width:100%}.head-actions{align-items:flex-start;flex-direction:column}.offer-grid,.complete dl,.run-details dl{grid-template-columns:1fr}.draft footer,.training footer,.team-review footer{align-items:stretch;flex-direction:column}.stat-grid{grid-template-columns:repeat(2,1fr)}.final-actions,.ending>div,.result-actions{display:grid;width:100%}.error-box{grid-template-columns:1fr}}.offer-grid button{grid-template-columns:1fr auto;min-height:360px;overflow:hidden;background:radial-gradient(circle at 50% 35%,color-mix(in srgb,var(--accent) 9%,transparent),transparent 40%),var(--panel-strong)}.offer-grid button::after{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;box-shadow:inset 0 1px rgba(255,255,255,.06)}.offer-grid .shortcut{position:absolute;top:.75rem;right:.75rem;display:grid;place-items:center;width:28px;aspect-ratio:1;border:1px solid var(--border);border-radius:.45rem;background:var(--surface);color:var(--text);font:700 .64rem var(--mono)}.offer-grid .dex{grid-column:1/-1}.offer-sprite{grid-column:1/-1;display:grid;place-items:center;min-height:138px}.offer-grid h3{grid-column:1/-1;margin:0;font-size:1.4rem}.offer-grid :global(.type-list){grid-column:1/-1}.offer-grid em{z-index:3;grid-template-columns:auto auto;gap:.35rem}.offer-grid em i{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.ev-cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem}.ev-cards article{padding:1rem;background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 4%,var(--panel-strong)),var(--panel-strong))}.ev-identity{display:flex;align-items:center;gap:.8rem}.ev-mon{flex:1}.ev-mon>div{gap:.32rem}.ev-progress{height:5px;overflow:hidden;border-radius:999px;background:var(--surface)}.ev-progress span{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),color-mix(in srgb,var(--accent) 55%,#58a6ff));transition:width .2s ease}.preset-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.4rem}.preset-row button{display:grid;align-content:start;gap:.22rem;min-height:72px;padding:.55rem;text-align:left}.preset-row button span{display:grid;gap:.15rem;color:var(--text);font-weight:700}.preset-row button small{line-height:1.3}.preset-row button b{width:max-content;padding:.12rem .3rem;border-radius:999px;background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent);font:.47rem var(--mono);text-transform:uppercase}.preset-row button.recommended{border-color:color-mix(in srgb,var(--accent) 58%,var(--border));background:color-mix(in srgb,var(--accent) 8%,var(--surface))}.stat-grid label{padding:.45rem;border:1px solid color-mix(in srgb,var(--border) 75%,transparent);border-radius:.5rem;background:color-mix(in srgb,var(--surface) 72%,transparent)}.stat-grid label span{display:flex;justify-content:space-between}.stat-grid label span b{color:var(--text);font-weight:700}.roll-result{align-items:center!important;padding:.7rem clamp(.9rem,2vw,1.35rem);border:1px solid color-mix(in srgb,var(--accent) 48%,var(--border));border-radius:.8rem;background:radial-gradient(circle at 20% 50%,color-mix(in srgb,var(--accent) 16%,transparent),transparent 48%),var(--panel-strong)}.roll-result h2{display:flex;align-items:center;gap:.65rem;margin:.35rem 0;font-size:clamp(1.55rem,3vw,2.45rem)}.roll-result h2 span{padding:.22rem .55rem;border-radius:.45rem;background:color-mix(in srgb,var(--accent) 13%,transparent)}.draft-workspace{display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:1rem;margin-top:1rem}.draft-choice-area{min-width:0}.draft-roster{position:sticky;top:1rem;align-self:start;padding:.9rem;border:1px solid var(--border);border-radius:.75rem;background:var(--panel-strong)}.draft-roster h3{margin:.2rem 0 .65rem;color:var(--accent);font-size:1.4rem}.draft-roster>div{display:grid;gap:.4rem}.draft-roster article{display:grid;grid-template-columns:42px 1fr;align-items:center;gap:.45rem;min-height:52px;padding:.35rem;border:1px solid var(--border);border-radius:.55rem;background:var(--panel)}.draft-roster article>span{display:grid;min-width:0}.draft-roster article strong{overflow:hidden;font-size:.7rem;text-overflow:ellipsis;white-space:nowrap}.draft-roster article.empty{color:var(--muted)}.draft-roster article.empty b{display:grid;place-items:center;width:34px;aspect-ratio:1;border:1px dashed var(--border);border-radius:50%;font:.6rem var(--mono)}.draft-roster article.empty span{font:.6rem var(--mono)}.draft-roster details{margin-top:.7rem;color:var(--muted);font-size:.65rem}.draft-roster details p{margin:.5rem 0 0;font-size:.65rem}
  @media(max-width:1100px){.ev-cards{grid-template-columns:1fr}.draft-workspace{grid-template-columns:1fr}.draft-roster{position:static}.draft-roster>div{grid-template-columns:repeat(6,1fr)}.draft-roster article{grid-template-columns:1fr;justify-items:center;text-align:center}.draft-roster article>span{justify-items:center}.draft-roster article.empty b{width:28px}}
  @media(max-width:900px){.stage-hero :global(.trainer){align-self:center}.stage-hero .launch{width:100%}}.type-badges{margin:0}.offer-grid .type-badges{grid-column:1/-1}.stat-grid label{grid-template-columns:1fr}.stat-grid input,.stat-grid label button{width:100%}
  @media(max-width:600px){.battle-history li{align-items:stretch;flex-direction:column}.battle-history li .button{width:100%}.offer-grid button{min-height:340px}.preset-row{grid-template-columns:1fr}.stage-title{align-items:flex-start;flex-direction:column}.ev-identity{align-items:flex-start}.roll-result h2{align-items:flex-start;flex-direction:column}.draft-roster>div{grid-template-columns:repeat(3,1fr)}.draft-roster article{min-width:0}}
  @media(prefers-reduced-motion:reduce){.live-dot,.offer-grid em i{animation:none}.offer-grid button,.ev-progress span{transition:none}}.confirmation-layer{position:fixed;z-index:100;inset:0;display:grid;place-items:center;padding:1rem}.confirmation-backdrop{position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:0;background:color-mix(in srgb,#05070a 76%,transparent);backdrop-filter:blur(8px);cursor:default}.confirmation-card{position:relative;display:grid;grid-template-columns:auto 1fr;gap:1rem;width:min(520px,100%);padding:1.35rem;border:1px solid color-mix(in srgb,var(--accent) 45%,var(--border));border-radius:1rem;background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 7%,var(--panel-strong)),var(--panel));box-shadow:0 28px 90px rgba(0,0,0,.55);animation:confirmation-in .16s ease-out}.confirmation-card.danger{border-color:color-mix(in srgb,var(--danger) 52%,var(--border));background:linear-gradient(145deg,color-mix(in srgb,var(--danger) 7%,var(--panel-strong)),var(--panel))}.confirmation-icon{display:grid;place-items:center;width:52px;aspect-ratio:1;border-radius:.75rem;background:color-mix(in srgb,var(--accent) 13%,var(--surface));color:var(--accent);font-size:1.55rem}.confirmation-card.danger .confirmation-icon{background:color-mix(in srgb,var(--danger) 13%,var(--surface));color:var(--danger)}.confirmation-card h2{margin:.22rem 0 .35rem;font-size:1.4rem}.confirmation-card p{margin:0}.confirmation-actions{grid-column:1/-1;display:flex;justify-content:flex-end;gap:.55rem;margin-top:.25rem}.confirmation-primary.danger{border-color:var(--danger);background:var(--danger);color:white}@keyframes confirmation-in{from{opacity:0;transform:translateY(8px) scale(.98)}}@media(max-width:600px){.confirmation-card{grid-template-columns:1fr;padding:1.1rem}.confirmation-actions{display:grid}.confirmation-actions .button{width:100%}}@media(prefers-reduced-motion:reduce){.confirmation-card{animation:none}.confirmation-backdrop{backdrop-filter:none}}.draft{position:relative;overflow:hidden;border-color:color-mix(in srgb,var(--accent) 22%,var(--border));background:linear-gradient(160deg,color-mix(in srgb,var(--accent) 3%,var(--panel)),var(--panel) 38%)}.roll-result{position:relative;isolation:isolate;display:grid!important;grid-template-columns:minmax(0,1fr) auto;overflow:hidden;animation:roll-reveal .34s cubic-bezier(.2,.8,.2,1)}.roll-result::before{position:absolute;z-index:-1;top:-90px;right:16%;width:220px;aspect-ratio:1;border:1px solid color-mix(in srgb,var(--accent) 15%,transparent);border-radius:50%;box-shadow:0 0 0 34px color-mix(in srgb,var(--accent) 3%,transparent),0 0 0 72px color-mix(in srgb,var(--accent) 2%,transparent);content:"";animation:orbit-drift 8s ease-in-out infinite alternate}.roll-result h2 span:first-child{animation:roll-chip .38s cubic-bezier(.2,.8,.2,1)}.roll-result h2 span:last-child{animation:roll-chip .38s .08s cubic-bezier(.2,.8,.2,1) both}.draft-reels{display:flex!important;align-items:center;justify-content:center;gap:.55rem;width:100%;margin:0}.roll-result .draft-reel{display:flex;align-items:center;gap:.42rem;height:44px;padding:0 .62rem;border:1px solid color-mix(in srgb,var(--accent) 42%,var(--border));border-radius:.55rem;background:color-mix(in srgb,var(--surface) 92%,transparent);animation:none}.draft-reel small{color:var(--muted);font:.58rem var(--mono);letter-spacing:.1em}.reel-window{display:block;overflow:hidden;height:42px;padding:0!important;background:none!important;animation:none!important}.reel-track{display:flex!important;flex-direction:column;padding:0!important;background:none!important;animation:none!important;will-change:transform}.reel-track b{display:flex;align-items:center;gap:.38rem;height:42px;min-width:34px;color:var(--text);font:800 1.1rem/42px var(--display);letter-spacing:.04em;text-transform:uppercase;white-space:nowrap}.type-reel .reel-track b{min-width:112px}.type-reel .reel-track b::before{width:.76rem;aspect-ratio:1;border:1px solid color-mix(in srgb,var(--type-color) 74%,white);background:var(--type-color);box-shadow:0 0 7px color-mix(in srgb,var(--type-color) 42%,transparent);clip-path:polygon(25% 7%,75% 7%,100% 50%,75% 93%,25% 93%,0 50%);content:""}.draft-reel.spinning{border-color:var(--accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 8%,transparent)}.draft-reel.locked{border-style:dashed;opacity:.72}.offer-grid.pending-reveal button{visibility:hidden;opacity:0;animation:none}@keyframes slot-reel{0%{transform:translateY(0);filter:blur(0)}12%{filter:blur(2.2px)}62%{filter:blur(1.6px)}88%{transform:translateY(calc(var(--reel-offset) - 7px));filter:blur(0)}100%{transform:translateY(var(--reel-offset));filter:blur(0)}}.offer-grid button{isolation:isolate;border-radius:.9rem;box-shadow:0 8px 24px transparent;animation:card-reveal .36s calc(.11s + var(--reveal-index) * .08s) cubic-bezier(.2,.8,.2,1) both;transition:transform .22s cubic-bezier(.2,.8,.2,1),border-color .22s ease,box-shadow .22s ease,background .22s ease}.offer-grid button::before{position:absolute;z-index:-1;inset:auto 12% -40% 12%;height:55%;border-radius:50%;background:color-mix(in srgb,var(--accent) 12%,transparent);filter:blur(28px);opacity:0;content:"";transition:opacity .22s ease,transform .22s ease}.offer-grid button:hover:not(:disabled),.offer-grid button:focus-visible{transform:translateY(-6px);border-color:color-mix(in srgb,var(--accent) 72%,var(--border));background:radial-gradient(circle at 50% 34%,color-mix(in srgb,var(--accent) 15%,transparent),transparent 44%),var(--panel-strong);box-shadow:0 18px 40px color-mix(in srgb,var(--accent) 10%,rgba(0,0,0,.12))}.offer-grid button:hover::before,.offer-grid button:focus-visible::before{opacity:1;transform:translateY(-12px)}.offer-sprite{transition:transform .25s cubic-bezier(.2,.8,.2,1),filter .25s ease}.offer-grid button:hover:not(:disabled) .offer-sprite,.offer-grid button:focus-visible .offer-sprite{transform:translateY(-5px) scale(1.035);filter:drop-shadow(0 14px 13px color-mix(in srgb,var(--accent) 16%,transparent))}.card-foot{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;min-height:28px;margin-top:.2rem;padding-top:.65rem;border-top:1px solid color-mix(in srgb,var(--border) 76%,transparent)}.card-foot small{color:var(--muted);font:.6rem var(--mono)}.card-foot small b{color:var(--text)}.card-foot>span{display:flex;align-items:center;gap:.28rem;color:var(--muted);font:750 .62rem var(--display);transition:color .2s ease}.card-foot i{transition:transform .2s ease}.offer-grid button:hover .card-foot>span,.offer-grid button:focus-visible .card-foot>span{color:var(--accent)}.offer-grid button:hover .card-foot i,.offer-grid button:focus-visible .card-foot i{transform:translateX(3px)}.reroll-actions{display:flex;flex-wrap:wrap;gap:.45rem}.reroll-actions .button{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.15rem .5rem;min-height:48px;padding:.48rem .62rem;text-align:left}.reroll-actions .button>i{grid-row:1/3;color:var(--accent);font-size:1.05rem;transition:transform .25s ease}.reroll-actions .button>span{display:grid;min-width:92px}.reroll-actions .button strong{font-size:.67rem}.reroll-actions .button small{color:var(--muted);font:.5rem var(--mono)}.reroll-actions .button>b{grid-row:1/3;display:grid;place-items:center;width:25px;height:25px;border-radius:999px;background:color-mix(in srgb,var(--accent) 12%,var(--surface));color:var(--accent);font:.65rem var(--mono)}.reroll-actions .button:hover:not(:disabled)>i{transform:rotate(-18deg) scale(1.08)}.offer-saved{display:flex;align-items:center;gap:.35rem;white-space:nowrap}.offer-saved.busy i{animation:spin .8s linear infinite}.draft-roster article:not(.empty){animation:roster-lock .32s cubic-bezier(.2,.8,.2,1) both}
  @keyframes roll-reveal{from{opacity:.2;transform:translateY(-8px) scale(.995)}}@keyframes roll-chip{from{opacity:0;transform:translateY(-10px) scale(.95)}}@keyframes card-reveal{from{opacity:0;transform:translateY(15px) scale(.975)}}@keyframes current-pick{50%{box-shadow:0 0 0 8px color-mix(in srgb,var(--accent) 5%,transparent)}}@keyframes sparkle{50%{transform:rotate(12deg) scale(1.18);opacity:.65}}@keyframes orbit-drift{to{transform:translate(18px,12px) rotate(8deg)}}@keyframes roster-lock{from{opacity:0;transform:translateX(7px)}}
  @media(max-width:750px){.roll-result{grid-template-columns:1fr}.draft{padding:1rem}.offer-grid{gap:.55rem}.offer-grid button{min-height:320px;padding:.9rem}.reroll-actions{display:grid;grid-template-columns:1fr 1fr}.reroll-actions .button:first-child{grid-column:1/-1}.offer-saved{align-self:center}}
  @media(max-width:600px){.reroll-actions{grid-template-columns:1fr;width:100%}.reroll-actions .button,.reroll-actions .button:first-child{grid-column:auto;width:100%}.roll-result::before{right:-55px}.offer-grid button{min-height:300px}.card-foot{padding-top:.5rem}.offer-saved{justify-content:center}.draft-reels{align-items:center!important;flex-direction:row!important;gap:.35rem}.roll-result .draft-reel{padding:0 .48rem}.type-reel .reel-track b{min-width:96px}}
  @media(prefers-reduced-motion:reduce){.roll-result,.roll-result::before,.roll-result h2 span,.offer-grid button,.offer-sprite,.card-foot i,.reroll-actions .button>i,.offer-saved.busy i,.draft-roster article:not(.empty),.roll-result h2 .draft-reel.spinning .reel-track,.roll-result h2 .draft-reel.spinning.generation-reel,.roll-result h2 .draft-reel.spinning.type-reel,.roll-result h2 .draft-reel.spinning{animation:none!important;transition:none!important}.offer-grid button:hover:not(:disabled),.offer-grid button:focus-visible{transform:none}.offer-grid button:hover:not(:disabled) .offer-sprite,.offer-grid button:focus-visible .offer-sprite{transform:none}}/* ── Compact game screen ────────────────────────────────────────────────── */
  .page-head{position:relative;z-index:90;display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.35rem}.run-id{min-width:0}.run-id h1{margin:.1rem 0 0;overflow:hidden;font-size:clamp(1.05rem,1.8vw,1.45rem);text-overflow:ellipsis;white-space:nowrap}.head-actions{display:flex;flex-shrink:0;align-items:center;gap:.45rem}.difficulty-pill{padding:.24rem .55rem;border:1px solid color-mix(in srgb,var(--accent) 40%,var(--border));border-radius:999px;color:var(--accent);font:700 .6rem var(--mono);letter-spacing:.05em;text-transform:uppercase;white-space:nowrap}.run-menu{position:relative;z-index:50}.run-menu>summary{display:flex;min-height:44px;align-items:center;gap:.35rem;padding:.3rem .65rem;border:1px solid var(--border);border-radius:999px;background:var(--panel);color:var(--muted);font:650 .72rem var(--display);cursor:pointer;list-style:none}.run-menu>summary::-webkit-details-marker{display:none}.run-menu[open]>summary,.run-menu>summary:hover{border-color:color-mix(in srgb,var(--accent) 45%,var(--border));color:var(--text)}.run-menu-panel{position:absolute;z-index:60;top:calc(100% + .4rem);right:0;display:grid;gap:.18rem;width:min(21rem,80vw);padding:.5rem;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--panel);box-shadow:var(--shadow)}.run-menu-label{margin:.25rem .35rem 0;color:var(--accent);font:700 .58rem var(--mono);letter-spacing:.13em;text-transform:uppercase}.run-menu-note{margin:0 .35rem .3rem!important;font-size:.68rem;line-height:1.45}.run-menu-item{display:flex;min-height:44px;align-items:center;gap:.5rem;width:100%;padding:.45rem .55rem;border:0;border-radius:.5rem;background:transparent;color:var(--text);font:600 .8rem var(--display);text-align:left;cursor:pointer}.run-menu-item:hover{background:var(--surface)}.run-menu-item.danger{color:var(--danger)}.stage-hero{display:flex;align-items:center;gap:1.1rem;margin-bottom:.7rem;padding:1rem 1.2rem;border-color:color-mix(in srgb,var(--stage-accent) 55%,var(--border));background:linear-gradient(105deg,color-mix(in srgb,var(--stage-accent) 16%,var(--panel)),var(--panel))}.stage-copy{min-width:0;flex:1}.stage-copy .eyebrow{color:var(--stage-accent)}.stage-copy h2{margin:.1rem 0;font-size:clamp(1.5rem,3.4vw,2.1rem);line-height:1.05}.stage-copy p{margin:.15rem 0 0!important;font-size:.76rem}.stage-copy p b{color:var(--text)}.retry-note{color:var(--danger)!important}.stage-action{display:grid;flex-shrink:0;justify-items:end;gap:.4rem;text-align:right}.stage-action>strong{font:700 .68rem var(--mono)}.stage-buttons{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:.45rem}.stage-action .link-button{font-size:.66rem}.campaign{margin-bottom:.7rem;padding:.85rem 1.1rem;box-shadow:none}.campaign header{display:flex;align-items:center;justify-content:space-between;gap:1rem}.campaign h2{margin:.1rem 0;font-size:.98rem}.route-count{color:var(--muted);font:.62rem var(--mono)}.route-rail{display:flex;flex-wrap:wrap;gap:.3rem;margin:.6rem 0 0;padding:0;list-style:none}.route-rail li{display:flex;align-items:center;gap:.32rem;padding:.24rem .5rem;border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--muted);font:650 .64rem var(--display)}.route-rail li b{display:grid;place-items:center;width:15px;aspect-ratio:1;border-radius:50%;background:var(--surface);color:var(--muted);font:800 .55rem var(--mono);box-shadow:inset 0 0 0 1px var(--border)}.route-rail li.won{border-color:color-mix(in srgb,var(--accent) 45%,var(--border));color:var(--text)}.route-rail li.won b{background:var(--accent);color:var(--bg);box-shadow:none}.route-rail li.failed b{background:var(--danger);color:#fff;box-shadow:none}.route-rail li.current{border-color:var(--stage-accent);background:color-mix(in srgb,var(--stage-accent) 20%,var(--panel));color:var(--text)}.route-rail li.current b{background:var(--stage-accent);color:#0b100c;box-shadow:none}.route-rail li:not(.current):not(.won):not(.failed) span{display:none}.roster-strip{display:flex;flex-wrap:wrap;gap:.35rem;margin-bottom:.7rem}.roster-strip span{display:flex;align-items:center;gap:.35rem;padding:.22rem .5rem .22rem .25rem;border:1px solid var(--border);border-radius:999px;background:var(--panel);color:var(--muted);font:650 .66rem var(--display)}.evolved-mark{color:var(--accent);font-size:.8em}.final-roster .evolved-mark{margin-left:.2rem}/* ── Slot reels ─────────────────────────────────────────────────────────── */
  .reel-separator{align-self:center;color:var(--muted);font:800 1.1rem var(--display)}.reel-window{-webkit-mask-image:linear-gradient(to bottom,transparent,#000 26%,#000 74%,transparent);mask-image:linear-gradient(to bottom,transparent,#000 26%,#000 74%,transparent)}/* The base .reel-track/.draft-reel rules use !important,so the spin has to as well. */
  .roll-result .draft-reel.spinning .reel-track{animation:slot-reel 620ms cubic-bezier(.16,.62,0,1) both!important}.roll-result .type-reel.spinning .reel-track{animation-duration:620ms!important;animation-delay:70ms!important}.roll-result .generation-reel.spinning .reel-track{animation-duration:480ms!important;animation-delay:0ms!important}.roll-result h2 .draft-reel.spinning{animation:reel-lock 620ms ease-out both!important}.roll-result h2 .generation-reel.spinning{animation-duration:480ms!important;animation-delay:0ms!important}.roll-result h2 .type-reel.spinning{animation-delay:70ms!important}
  @keyframes reel-lock{0%,74%{border-color:var(--accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 8%,transparent)}88%{border-color:color-mix(in srgb,var(--accent) 90%,white);box-shadow:0 0 22px 2px color-mix(in srgb,var(--accent) 55%,transparent),0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent);transform:scale(1.06)}100%{border-color:var(--accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 10%,transparent);transform:scale(1)}}.reroll-control{position:relative;display:block;min-width:0}.reroll-control .button{width:100%;height:100%}.reroll-control.unavailable{border-radius:.7rem;cursor:help}.reroll-control[data-tooltip]::after{position:absolute;z-index:120;right:0;bottom:calc(100% + .55rem);width:max-content;max-width:min(320px,80vw);padding:.55rem .65rem;border:1px solid color-mix(in srgb,var(--accent) 38%,var(--border));border-radius:.55rem;background:var(--panel-strong);box-shadow:var(--shadow-sm);color:var(--text);font:600 .68rem/1.4 var(--display);text-align:left;white-space:normal;content:attr(data-tooltip);opacity:0;pointer-events:none;transform:translateY(4px);transition:opacity .14s ease,transform .14s ease}.reroll-control[data-tooltip]:hover::after,.reroll-control[data-tooltip]:focus-visible::after,.reroll-control[data-tooltip]:focus-within::after{opacity:1;transform:none}.reroll-control:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.reroll-blocked{display:grid;gap:.2rem;margin:.5rem 0 0;padding:0;list-style:none}.reroll-blocked li{display:flex;flex-wrap:wrap;gap:.35rem;color:var(--muted);font-size:.66rem}.reroll-blocked b{color:var(--text)}.agent-busy{display:flex;align-items:center;gap:.4rem;color:var(--accent);font:700 .74rem var(--display)}.agent-busy i{animation:agent-pulse 1.6s ease-in-out infinite}
  @keyframes agent-pulse{50%{opacity:.45}}
  @media(prefers-reduced-motion:reduce){.agent-busy i{animation:none}}.visually-hidden{position:absolute;overflow:hidden;clip-path:inset(50%);width:1px;height:1px;white-space:nowrap}/* A blind draft is a lottery. Showing the campaign makes coverage a real decision. */
  .campaign-preview{display:grid;gap:.15rem;margin:.5rem 0 .6rem;padding:0;list-style:none}.campaign-preview li{display:grid;grid-template-columns:auto 1fr auto;align-items:baseline;gap:.4rem;padding:.16rem .4rem;border-left:3px solid var(--stage-accent);border-radius:.3rem;background:var(--surface)}.campaign-preview b{color:var(--text);font:700 .66rem var(--display)}.campaign-preview span{overflow:hidden;color:var(--stage-accent);font:650 .58rem var(--mono);text-overflow:ellipsis;text-transform:uppercase;white-space:nowrap}.campaign-preview i{color:var(--muted);font:600 .56rem var(--mono);font-style:normal}.run-error{display:flex;align-items:flex-start;gap:.75rem;margin-bottom:.7rem;padding:.8rem 1rem;border-color:color-mix(in srgb,var(--danger) 45%,var(--border));background:color-mix(in srgb,var(--danger) 7%,var(--panel))}.run-error>i{color:var(--danger);font-size:1.15rem}.run-error>div{min-width:0;flex:1}.run-error strong{display:block;font-size:.88rem}.run-error p{margin:.2rem 0!important;overflow-wrap:anywhere;font-size:.72rem}.run-error small{color:var(--muted);font:.64rem var(--mono)}

  /* Narrow viewports: stack the hero, keep one full-width primary action. */
  @media(max-width:720px){.page-head{align-items:flex-start;flex-direction:column;gap:.5rem}.head-actions{flex-direction:row;flex-wrap:wrap;align-items:center;width:100%}.stage-hero{align-items:flex-start;flex-direction:column;text-align:left}.stage-hero :global(.trainer){width:96px;max-height:96px;align-self:flex-start}.stage-action{justify-items:stretch;width:100%;text-align:left}.stage-buttons{justify-content:flex-start}.stage-buttons .button{flex:1}.result-actions{flex-direction:row;flex-wrap:wrap}.battle-summary{grid-template-columns:1fr}}
  .breadcrumbs a{display:inline-flex;min-height:44px;align-items:center}
  .draft-roster details>summary,.run-details>summary,.draft-history>summary,.battle-history>summary{display:flex;min-height:44px;align-items:center;cursor:pointer;list-style:none}
  .draft-roster details>summary::-webkit-details-marker,.run-details>summary::-webkit-details-marker,.draft-history>summary::-webkit-details-marker,.battle-history>summary::-webkit-details-marker{display:none}
  .disclosure-summary{justify-content:space-between;gap:.65rem}
  .disclosure-summary>span{display:flex;align-items:center;gap:.45rem;min-width:0}
  .disclosure-summary>span>i{color:var(--accent);font-size:1rem}
  .disclosure-summary small{overflow:hidden;color:var(--muted);font:.58rem var(--mono);text-overflow:ellipsis;white-space:nowrap}
  .disclosure-caret{flex:0 0 auto;color:var(--muted);transition:transform .16s ease}
  details[open]>.disclosure-summary .disclosure-caret{transform:rotate(180deg)}
  .offer-grid button{min-height:clamp(270px,38vh,340px)}
  .reroll-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));width:100%}
  .reroll-actions .button{border-color:var(--border);background:var(--surface);color:var(--text)}
  @media(max-width:750px){.reroll-actions{grid-template-columns:1fr 1fr}.reroll-actions .reroll-control:first-child{grid-column:1/-1}}
  @media(max-width:600px){.offer-grid{display:flex;overflow-x:auto;overscroll-behavior-inline:contain;padding-bottom:.4rem;scroll-snap-type:x mandatory;scrollbar-width:thin}.offer-grid button{flex:0 0 auto;width:min(82vw,300px);min-width:min(82vw,300px);min-height:300px;scroll-snap-align:start}.reroll-actions{grid-template-columns:1fr}.reroll-actions .reroll-control:first-child{grid-column:auto}.reroll-control[data-tooltip]::after{right:auto;left:0}.disclosure-summary small{white-space:normal}}
  @media(prefers-reduced-motion:reduce){.disclosure-caret{transition:none}}

  /* ── Stage transition & evolution reveal ─────────────────────────────── */
  .stage-transition,.evolution-reveal{position:fixed;z-index:80;inset:0;display:grid;place-items:center;pointer-events:none;padding:1rem}
  .stage-transition-card{display:flex;align-items:center;gap:.9rem;padding:.85rem 1.3rem .85rem .85rem;border:1px solid color-mix(in srgb,var(--stage-accent) 55%,var(--border));border-radius:var(--radius-lg);background:color-mix(in srgb,var(--panel) 94%,var(--stage-accent) 6%);box-shadow:var(--shadow);animation:transition-pop .38s cubic-bezier(.2,.8,.2,1) both}
  .stage-transition-card div{display:grid;gap:.1rem}
  .stage-transition-card span{color:var(--stage-accent);font:700 .62rem var(--mono);letter-spacing:.08em;text-transform:uppercase}
  .stage-transition-card strong{font-size:1.15rem;letter-spacing:-.01em}
  .stage-transition-card em{color:var(--muted);font-size:.76rem;font-style:normal}
  .evolution-card{position:relative;isolation:isolate;display:grid;justify-items:center;gap:.35rem;padding:1.3rem 1.6rem;border:1px solid color-mix(in srgb,var(--accent) 55%,var(--border));border-radius:var(--radius-lg);background:color-mix(in srgb,var(--panel) 92%,var(--accent) 8%);box-shadow:var(--shadow);text-align:center;animation:transition-pop .42s cubic-bezier(.2,.8,.2,1) both}
  .evolution-card p{margin:.2rem 0 0;font-size:.92rem}
  .evolution-card b{color:var(--accent)}
  .evolution-glow{position:absolute;z-index:-1;inset:-20%;border-radius:50%;background:radial-gradient(circle,color-mix(in srgb,var(--accent) 30%,transparent),transparent 70%);animation:evolution-pulse 1.6s ease-in-out infinite}
  @keyframes transition-pop{from{opacity:0;transform:translateY(8px) scale(.96)}to{opacity:1;transform:none}}
  @keyframes evolution-pulse{0%,100%{opacity:.55;transform:scale(.9)}50%{opacity:1;transform:scale(1.08)}}
  @media(prefers-reduced-motion:reduce){.stage-transition-card,.evolution-card{animation:none}.evolution-glow{animation:none;opacity:.7}}
  .evolution-choice-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.6rem;margin:1rem 0}
  .evolution-choice-option{display:grid;justify-items:center;gap:.4rem;min-height:110px;padding:.75rem .5rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong);color:var(--text);cursor:pointer;transition:border-color .16s ease,transform .16s ease}
  .evolution-choice-option:hover:not(:disabled){border-color:var(--accent);transform:translateY(-2px)}
  .evolution-choice-option span{font-weight:700;font-size:.78rem}
  .rarity-note{display:flex;align-items:center;gap:.4rem;margin:.55rem 0;color:var(--muted);font-size:.67rem}
  .rarity-note i{color:var(--accent)}
  .rarity-badge{justify-self:start;padding:.22rem .45rem;border:1px solid var(--rarity-border,var(--border));border-radius:999px;background:color-mix(in srgb,var(--rarity-accent,var(--accent)) 9%,var(--surface));color:var(--rarity-accent,var(--text));font:750 .58rem var(--mono);letter-spacing:.03em;text-transform:uppercase}
  .offer-grid button[data-rarity="common"]{--rarity-border:#7f9189;--rarity-accent:#b7c4be}
  .offer-grid button[data-rarity="uncommon"]{--rarity-border:#4f9d69;--rarity-accent:#75d394}
  .offer-grid button[data-rarity="rare"]{--rarity-border:#4f86ca;--rarity-accent:#78b4ff}
  .offer-grid button[data-rarity="super-rare"]{--rarity-border:#9a68cf;--rarity-accent:#c69aff}
  .offer-grid button[data-rarity="ultra-rare"]{--rarity-border:#d39b39;--rarity-accent:#ffd06d;box-shadow:inset 0 0 0 1px color-mix(in srgb,#ffd06d 10%,transparent)}
  .offer-grid button[data-rarity]{border-color:color-mix(in srgb,var(--rarity-border) 68%,var(--border))}
  .mega-selection{display:grid;grid-template-columns:minmax(15rem,.72fr) minmax(18rem,1.28fr);gap:1.2rem;margin-bottom:.7rem;padding:1.1rem;border-color:color-mix(in srgb,#b987ff 45%,var(--border));background:linear-gradient(120deg,color-mix(in srgb,#7c48bd 11%,var(--panel)),var(--panel))}
  .mega-intro h2{margin:.15rem 0;font-size:clamp(1.35rem,3vw,2rem)}
  .mega-intro p{margin:.35rem 0 0!important;color:var(--muted);font-size:.76rem;line-height:1.55}
  .mega-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.55rem}
  .mega-options button{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.55rem;min-height:96px;padding:.6rem;border:1px solid var(--border);border-radius:.8rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer;transition:border-color .16s ease,transform .16s ease}
  .mega-options button:hover:not(:disabled),.mega-options button:focus-visible{border-color:#b987ff;transform:translateY(-2px)}
  .mega-options button:disabled{cursor:wait;opacity:.66}
  .mega-options button>span{display:grid;gap:.1rem;min-width:0}.mega-options small,.mega-options em{overflow:hidden;color:var(--muted);font:.58rem var(--mono);font-style:normal;text-overflow:ellipsis;white-space:nowrap}.mega-options strong{font-size:.78rem}.mega-options i{color:#b987ff}
  .mega-options .ph-circle-notch{animation:spin .8s linear infinite}
  .reroll-control.unavailable .button{opacity:.5;cursor:help}
  .reroll-control.unavailable .button:hover{filter:none;transform:none;box-shadow:none}
  .reroll-control.unavailable .button::before{display:none}
  @media(max-width:720px){.mega-selection{grid-template-columns:1fr}.mega-options{grid-template-columns:1fr}}
  @media(prefers-reduced-motion:reduce){.mega-options button{transition:none}.mega-options button:hover:not(:disabled),.mega-options button:focus-visible{transform:none}.mega-options .ph-circle-notch{animation:none}}
</style>
