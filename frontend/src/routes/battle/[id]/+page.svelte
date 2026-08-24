<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import { api, broadcastRendererConfig, copyText as copyToClipboard, getMatch, getPresentationMatch, rematch, resumeMatch, wsUrl } from '$lib/api';
  import { loadRendererConfig, saveRendererConfig } from '$lib/presentation/config';
  import { PresentationTimeline } from '$lib/presentation/timeline';
  import { connectLiveSocket } from '$lib/presentation/live-socket';
  import { defaultRendererConfig, HUD_SCALE_RANGE, type CommentaryMode, type EffectQuality, type MoveEffectSkin, type PlaybackSpeed, type RendererConfig, type RendererLayout, type RendererTheme, type TimelineSnapshot } from '$lib/presentation/types';
  import type { AgentLifecycleState, AgentRequest, BattleAction, BattleEvent, ChallengeRunView, MatchArchive, Side } from '$lib/types';
  import { actionIndexForKey, actionPreview, isForcedSwitch, shortcutFor } from '$lib/manual-action';
  import { campaignOpponentHeading, challengeErrorMessage } from '$lib/challenge';

  export let data: { id: string };
  let match: MatchArchive | null = null;
  let pending: Partial<Record<Side, AgentRequest>> = {};
  let responses: Partial<Record<Side, string>> = {};
  let validation: Partial<Record<Side, string>> = {};
  let submitting: Partial<Record<Side, boolean>> = {};
  let accepted: Partial<Record<Side, string>> = {};
  let copied: string | null = null;
  let copyTimer: ReturnType<typeof setTimeout> | null = null;
  let configBroadcastTimer: ReturnType<typeof setTimeout> | null = null;
  let draftReturnTimer: ReturnType<typeof setTimeout> | null = null;
  let liveRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  let connectionGeneration = 0;
  let refreshSequence = 0;
  let configSyncError = '';
  let error = ''; let stopSocket: (() => void) | null = null;
  let timeline: PresentationTimeline | null = null; let snapshot: TimelineSnapshot | null = null;
  let config: RendererConfig = defaultRendererConfig();
  let lifecycle: Partial<Record<Side, AgentLifecycleState>> = { p1: 'idle', p2: 'idle' };
  let activeTab: Side | null = null;
  let toolMenu: HTMLDetailsElement | null = null;
  let auditOpen = false;
  let auditLoaded = false;
  let auditLoading = false;

  function closeToolMenu(event: Event) {
    if (!toolMenu?.open) return;
    if (event instanceof KeyboardEvent) {
      if (event.key === 'Escape') toolMenu.open = false;
      return;
    }
    if (!toolMenu.contains(event.target as Node)) toolMenu.open = false;
  }

  $: campaign = match?.config.campaign || null;
  $: battleHeading = campaign
    ? campaignOpponentHeading(campaign)
    : match
      ? (match.config.name || `${match.config.players[0].display_name} vs ${match.config.players[1].display_name}`)
      : 'Loading battle…';
  $: pendingSides = (Object.keys(pending) as Side[]).filter((side) => pending[side]);
  $: humanSides = (['p1', 'p2'] as Side[]).filter((side) => isHuman(side));
  // The player who can actually act is preselected, so nobody has to hunt for the right tab.
  $: activeTab = activeTab && pendingSides.includes(activeTab) ? activeTab : pendingSides[0] || null;
  $: battleViewUrl = typeof location === 'undefined' ? '' : `${location.origin}/watch/${data.id}`;
  // Carry the tuned settings into the OBS source, so the capture matches the preview instead
  // of falling back to whatever defaults that browser happens to hold.
  $: obsUrl = typeof location === 'undefined' ? '' : `${location.origin}/overlay/${data.id}?${overlayQuery(config)}`;

  function overlayQuery(current: RendererConfig) {
    return new URLSearchParams({
      layout: 'overlay-landscape',
      theme: current.theme,
      near: current.nearSide,
      effects: current.effects,
      moveEffects: current.moveEffectSkin,
      commentary: current.commentaryMode,
      hudScale: String(current.hudScale),
      roster: current.showTeamRoster ? '1' : '0',
      log: current.showBattleLog ? '1' : '0',
      damageNumbers: current.showDamageNumbers ? '1' : '0',
      reducedMotion: current.reducedMotion ? '1' : '0'
    }).toString();
  }

  function playerFor(side: Side) {
    return match?.config.players.find((player) => player.side === side);
  }
  function agentLabel(side: Side) {
    const player = playerFor(side);
    if (!player) return side.toUpperCase();
    return player.display_name;
  }
  function agentKind(side: Side) {
    const player = playerFor(side);
    if (!player) return '';
    if (player.agent_type === 'human') return 'Human Player';
    if (player.agent_type === 'manual') return 'Manual Web Chat';
    if (player.agent_type === 'random') return 'Random agent';
    if (player.agent_type === 'tactical-auto') return 'Fast Auto · local tactical AI';
    return [player.provider, player.model].filter(Boolean).join(' · ');
  }
  function isHuman(side: Side) {
    return playerFor(side)?.agent_type === 'human';
  }
  function tabState(side: Side) {
    if (submitting[side]) return 'Submitting…';
    if (pending[side]) return 'Waiting for response';
    if (lifecycle[side] === 'executing' || lifecycle[side] === 'decided') return 'Submitted';
    return 'Waiting for opponent';
  }

  interface StreamMessage {
    kind: string; match?: MatchArchive; event?: BattleEvent; request?: AgentRequest;
    decision?: MatchArchive['decisions'][number]; request_id?: string; error?: string;
  }
  let activeMatchId: string | null = null;
  $: if (data.id && activeMatchId !== null && data.id !== activeMatchId) {
    activeMatchId = data.id;
    stopSocket?.();
    timeline?.destroy();
    connectionGeneration += 1;
    refreshSequence += 1;
    if (liveRefreshTimer) clearTimeout(liveRefreshTimer);
    match = null;
    pending = {}; responses = {}; validation = {}; submitting = {}; accepted = {};
    lifecycle = { p1: 'idle', p2: 'idle' };
    auditOpen = false;
    auditLoaded = false;
    auditLoading = false;
    error = '';
    void connect();
  }

  onMount(() => {
    config = loadRendererConfig();
    const requestedSpeed = new URLSearchParams(window.location.search).get('speed');
    if (requestedSpeed === '4') config = { ...config, playbackSpeed: 4 };
    activeMatchId = data.id;
    window.addEventListener('keydown', handleManualShortcut);
    window.addEventListener('keydown', closeToolMenu);
    window.addEventListener('pointerdown', closeToolMenu);
    void connect();
    return () => {
      window.removeEventListener('keydown', handleManualShortcut);
      window.removeEventListener('keydown', closeToolMenu);
      window.removeEventListener('pointerdown', closeToolMenu);
      stopSocket?.(); timeline?.destroy();
      if (copyTimer) clearTimeout(copyTimer);
      if (configBroadcastTimer) clearTimeout(configBroadcastTimer);
      if (draftReturnTimer) clearTimeout(draftReturnTimer);
      if (liveRefreshTimer) clearTimeout(liveRefreshTimer);
      connectionGeneration += 1;
      refreshSequence += 1;
    };
  });
  async function connect() {
    const matchId = data.id;
    const generation = ++connectionGeneration;
    // The socket's onConnected also fires on the very first open, right after the explicit
    // fetch above already ran — without this guard every page load fetched the full archive
    // twice. A genuine reconnect (this flag already flipped) still refreshes to catch up on
    // anything missed while disconnected.
    let firstConnection = true;
    try {
      await refreshLiveState(matchId, generation);
      if (generation !== connectionGeneration || matchId !== data.id) return;
      stopSocket = connectLiveSocket({
        url: wsUrl(`/api/matches/${matchId}/stream`),
        onMessage: (raw) => {
          if (generation === connectionGeneration && matchId === data.id) {
            handleMessage(JSON.parse(raw) as StreamMessage);
          }
        },
        onConnected: () => {
          if (firstConnection) {
            firstConnection = false;
            return;
          }
          return refreshLiveState(matchId, generation);
        },
        onStatus: (status) => {
          if (generation === connectionGeneration && matchId === data.id) {
            error = status === 'connected' ? '' : 'Live control reconnecting…';
          }
        }
      });
    } catch (caught) {
      if (generation === connectionGeneration && matchId === data.id) {
        error = caught instanceof Error ? caught.message : String(caught);
      }
    }
  }
  async function refreshLiveState(matchId = data.id, generation = connectionGeneration) {
    const sequence = ++refreshSequence;
    const [archive, result] = await Promise.all([
      getPresentationMatch(matchId),
      api<{ requests: AgentRequest[] }>(`/api/matches/${matchId}/pending`)
    ]);
    if (generation !== connectionGeneration || sequence !== refreshSequence || matchId !== data.id) return;
    if (!match || archive.events.length > (snapshot?.eventCount || 0)) initialize(archive);
    else match = { ...match, ...archive, events: match.events };
    const liveSides = new Set(result.requests.map((request) => request.side));
    pending = Object.fromEntries(Object.entries(pending).filter(([side]) => liveSides.has(side as Side)));
    result.requests.forEach(setPending);
  }
  function initialize(archive: MatchArchive) {
    match = archive; timeline?.destroy();
    timeline = new PresentationTimeline(archive, archive.events, undefined, true);
    timeline.subscribe((value) => (snapshot = value));
    timeline.setPreset(config.preset); timeline.setSpeed(config.playbackSpeed);
    timeline.seek(archive.events.length); timeline.play();
  }
  function setPending(request: AgentRequest) {
    const sameRequest = pending[request.side]?.request_id === request.request_id;
    pending = { ...pending, [request.side]: request };
    lifecycle = { ...lifecycle, [request.side]: 'waiting' };
    if (!sameRequest) {
      responses = { ...responses, [request.side]: '' };
      validation = { ...validation, [request.side]: '' };
      accepted = { ...accepted, [request.side]: '' };
    }
  }
  function handleMessage(message: StreamMessage) {
    if (message.kind === 'snapshot' && message.match) {
      if (!match || message.match.events.length > (snapshot?.eventCount || 0)) initialize({ ...message.match, decisions: match?.decisions || message.match.decisions });
      else if (match) match = { ...match, status: message.match.status };
    }
    if (message.kind === 'battle_event' && message.event && match) {
      if (!match.events.some((item) => item.sequence === message.event?.sequence)) match.events = [...match.events, message.event];
      match.turns = Math.max(match.turns, message.event.turn); timeline?.append(message.event);
      if (message.event.event_type === 'agent_state') {
        const side = message.event.payload.side as Side; const state = message.event.payload.state as AgentLifecycleState;
        lifecycle = { ...lifecycle, [side]: state };
      }
    }
    if (message.kind === 'agent_submitted' && message.decision && match) {
      if (!match.decisions.some((item) => item.id === message.decision?.id)) {
        match.decisions = [...match.decisions, message.decision];
      }
      lifecycle = { ...lifecycle, [message.decision.decision.side]: 'decided' };
    }
    if (message.kind === 'agent_waiting' && message.request) {
      setPending(message.request); if (match) match.status = 'waiting';
    }
    if (message.kind === 'manual_response_accepted' && message.request_id) {
      const side = (Object.keys(pending) as Side[]).find((item) => pending[item]?.request_id === message.request_id);
      if (side) {
        lifecycle = { ...lifecycle, [side]: 'executing' };
        accepted = { ...accepted, [side]: 'Action accepted · waiting for the opponent' };
        pending = { ...pending }; delete pending[side];
      }
      if (match && Object.keys(pending).length === 0) match.status = 'running';
    }
    if (message.kind === 'match_completed') {
      if (match) match.status = 'completed'; lifecycle = { p1: 'finished', p2: 'finished' }; void finishMatch();
    }
    if (message.kind === 'match_cancelled') { if (match) match.status = 'cancelled'; }
    if (message.kind === 'match_paused') { if (match) match.status = 'paused'; }
    if (message.kind === 'match_resumed') { if (match) match.status = Object.keys(pending).length ? 'waiting' : 'running'; }
    if (message.kind === 'match_failed') { if (match) match.status = 'failed'; error = message.error || 'Battle failed.'; }
    // The server sends this when its outgoing queue overflowed and had to drop this
    // subscriber's backlog — the stream is now discontinuous. Refetch a fresh snapshot
    // instead of trying to reason about events with a gap in their sequence.
    if (message.kind === 'resync_required') void refreshLiveState();
  }
  async function refreshMetadata(matchId = data.id, generation = connectionGeneration) {
    const archive = await getPresentationMatch(matchId);
    if (generation !== connectionGeneration || matchId !== data.id || !match || archive.id !== match.id) return;
    const knownSequences = new Set(match.events.map((event) => event.sequence));
    for (const event of archive.events) {
      if (!knownSequences.has(event.sequence)) timeline?.append(event);
    }
    match = {
      ...archive,
      events: [...archive.events],
      decisions: archive.decisions.length >= match.decisions.length ? archive.decisions : match.decisions
    };
  }
  async function loadAuditArchive() {
    if (!auditOpen || auditLoaded || auditLoading || !match) return;
    auditLoading = true;
    try {
      const archive = await getMatch(data.id);
      if (archive.id !== match.id) return;
      match = { ...match, config: archive.config, decisions: archive.decisions };
      auditLoaded = true;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      auditLoading = false;
    }
  }
  async function finishMatch() {
    const matchId = data.id;
    const generation = connectionGeneration;
    await refreshMetadata(matchId, generation);
    if (generation !== connectionGeneration || matchId !== data.id) return;
    if (!match?.challenge_run_id) return;
    const fastDraftWatch = new URLSearchParams(window.location.search).get('speed') === '4';
    const challengeRunId = match.challenge_run_id;
    const waitForPresentation = async () => {
      if (snapshot && snapshot.index >= snapshot.eventCount && snapshot.state.finished && !snapshot.playing) {
        if (fastDraftWatch && match?.winner === 'p1') {
          try {
            const result = await api<{ run: ChallengeRunView; match: MatchArchive | null }>(`/api/challenges/${challengeRunId}/auto/advance`, { method: 'POST' });
            if (result.match) {
              await goto(`/battle/${result.match.id}?speed=4`);
              return;
            }
          } catch {
            // The Challenge page exposes the saved result and a retry/continue action.
          }
        }
        await goto(`/challenges/${challengeRunId}#latest-result`);
        return;
      }
      draftReturnTimer = setTimeout(() => void waitForPresentation(), 100);
    };
    void waitForPresentation();
  }
  function updateConfig(patch: Partial<RendererConfig>) {
    config = { ...config, ...patch }; saveRendererConfig(config);
    if (patch.playbackSpeed !== undefined) timeline?.setSpeed(config.playbackSpeed);
    if (patch.preset !== undefined) timeline?.setPreset(config.preset);
    // The local preview updates instantly; already-open OBS sources and battle-view tabs only
    // hear about it over the match's live socket, so push it there too (debounced, since a
    // dragged slider fires this on every pixel of movement).
    if (configBroadcastTimer) clearTimeout(configBroadcastTimer);
    configSyncError = '';
    configBroadcastTimer = setTimeout(() => {
      configBroadcastTimer = null;
      void broadcastRendererConfig(data.id, config).catch((caught) => {
        configSyncError = caught instanceof Error ? caught.message : String(caught);
      });
    }, 200);
  }
  async function copyText(key: string, value: string) {
    if (!await copyToClipboard(value)) {
      error = 'Clipboard access was blocked. Select and copy the value manually.';
      return;
    }
    copied = key;
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => (copied = null), 1400);
  }
  async function validate(side: Side) {
    const request = pending[side]; if (!request) return;
    validation = { ...validation, [side]: 'Checking…' };
    try {
      await api(`/api/decisions/${request.request_id}/validate`, { method: 'POST', body: JSON.stringify({ raw_response: responses[side] }) });
      validation = { ...validation, [side]: 'Valid response · ready to submit' };
    } catch (caught) { validation = { ...validation, [side]: caught instanceof Error ? caught.message : String(caught) }; }
  }
  async function submit(side: Side) {
    const request = pending[side]; if (!request || submitting[side]) return; error = '';
    submitting = { ...submitting, [side]: true };
    try {
      await api(`/api/decisions/${request.request_id}`, { method: 'POST', body: JSON.stringify({ raw_response: responses[side] }) });
    } catch (caught) { validation = { ...validation, [side]: caught instanceof Error ? caught.message : String(caught) }; }
    finally { submitting = { ...submitting, [side]: false }; }
  }
  async function chooseAction(side: Side, action: BattleAction) {
    const request = pending[side]; if (!request) return;
    validation = { ...validation, [side]: `Selected ${action.name} · submitting…` };
    submitting = { ...submitting, [side]: true };
    try {
      await api(`/api/human-decisions/${request.request_id}`, {
        method: 'POST', body: JSON.stringify({ action: action.id })
      });
      lifecycle = { ...lifecycle, [side]: 'executing' };
      accepted = { ...accepted, [side]: `${action.name} accepted · waiting for the opponent` };
      validation = { ...validation, [side]: '' };
      pending = { ...pending }; delete pending[side];
      if (match && Object.keys(pending).length === 0) match.status = 'running';
      if (liveRefreshTimer) clearTimeout(liveRefreshTimer);
      liveRefreshTimer = setTimeout(() => {
        liveRefreshTimer = null;
        void refreshLiveState().catch(() => undefined);
      }, 500);
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : String(caught);
      validation = { ...validation, [side]: challengeErrorMessage(detail) };
      if (detail.toLowerCase().includes('not pending')) void refreshLiveState();
    } finally {
      submitting = { ...submitting, [side]: false };
    }
  }
  function handleManualShortcut(event: KeyboardEvent) {
    const target = event.target as HTMLElement | null;
    if (target?.matches('input, textarea, select, [contenteditable="true"]')) return;
    if (!activeTab || event.metaKey || event.ctrlKey || event.altKey) return;
    const index = actionIndexForKey(event.key);
    const request = activeTab ? pending[activeTab] : null;
    if (index == null || !isHuman(activeTab) || !request?.legal_actions[index] || submitting[activeTab]) return;
    event.preventDefault();
    void chooseAction(activeTab, request.legal_actions[index]);
  }
  function actionSummary(action: BattleAction) {
    if (action.type === 'switch') {
      return `${action.species || action.name}${action.hp_fraction != null ? ` · ${Math.round(action.hp_fraction * 100)}%` : ''}`;
    }
    return [
      action.move_type,
      action.category,
      action.power ? `${action.power} BP` : null,
      action.accuracy != null ? `${Math.round(Number(action.accuracy) <= 1 ? Number(action.accuracy) * 100 : Number(action.accuracy))}%` : null,
      action.current_pp != null && action.max_pp != null ? `${action.current_pp}/${action.max_pp} PP` : null,
      action.priority ? `priority ${action.priority > 0 ? '+' : ''}${action.priority}` : null
    ].filter(Boolean).join(' · ');
  }
  function insertAction(side: Side, action: BattleAction) {
    responses = {
      ...responses,
      [side]: JSON.stringify({ action: action.id, commentary: '', strategy_memory: null }, null, 2)
    };
  }
  function ownsEvent(event: BattleEvent, side: Side, field: 'side' | 'actor' | 'target') {
    const value = event.payload[field];
    return typeof value === 'string' && value.startsWith(`${side}a:`);
  }
  function interviewFor(side: Side) {
    const archive = match;
    const decisions = archive?.decisions.filter((record) => record.decision.side === side) || [];
    const events = archive?.events || [];
    const opponent = side === 'p1' ? 'p2' : 'p1';
    const moves = decisions.map((record) => record.decision.action).filter(Boolean);
    const damageDealt = events.filter(
      (event) => event.event_type === 'damage' && ownsEvent(event, opponent, 'target')
    ).length;
    const knockouts = events.filter(
      (event) => event.event_type === 'pokemon_fainted' && ownsEvent(event, opponent, 'target')
    ).length;
    const ownKnockouts = events.filter(
      (event) => event.event_type === 'pokemon_fainted' && ownsEvent(event, side, 'target')
    ).length;
    const switches = events.filter(
      (event) => event.event_type === 'pokemon_switched' && ownsEvent(event, side, 'actor')
    ).length;
    const criticals = events.filter(
      (event) => event.event_type === 'critical_hit' && ownsEvent(event, side, 'actor')
    ).length;
    const outcome = archive?.winner === side
      ? 'I won the match.'
      : archive?.winner
        ? 'I lost the match.'
        : 'The match ended without a winner.';
    const lastMove = moves[moves.length - 1] || 'the final action';
    return {
      outcome,
      good: damageDealt || knockouts || criticals
        ? `${outcome} The plan created ${damageDealt} visible damage beat${damageDealt === 1 ? '' : 's'}${knockouts ? ` and ${knockouts} knockout${knockouts === 1 ? '' : 's'}` : ''}. ${criticals ? 'The critical hit was a real momentum swing.' : 'The pressure sequence was the clearest success.'}`
        : `${outcome} I kept the decision path consistent, but the archive shows no decisive damage swing to celebrate.`,
      bad: ownKnockouts || switches > 2
        ? `${ownKnockouts ? `${ownKnockouts} of my Pokémon went down` : 'The match forced several switches'}; that cost tempo and made the plan reactive.`
        : 'I avoided a major collapse, but I still left room to make the mid-game plan more decisive.',
      change: moves.length
        ? `I would revisit ${lastMove} first and change the setup around it before the next match.`
        : 'I would make the opening plan more explicit before the next match.',
      detail: `${decisions.length} decisions · ${switches} switches · ${moves.slice(0, 3).join(' · ') || 'no recorded move names'}`
    };
  }
  function previousDecision(record: MatchArchive['decisions'][number]) {
    return match?.decisions.filter((item) => item.decision.side === record.decision.side && item.decision.turn < record.decision.turn)
      .sort((a, b) => b.decision.turn - a.decision.turn)[0];
  }
  function contextChanges(record: MatchArchive['decisions'][number]): string[] {
    const current = record.request?.context; const previous = previousDecision(record)?.request?.context;
    if (!current || !previous) return [];
    const changes: string[] = [];
    if (current.turn !== previous.turn) changes.push(`Turn ${previous.turn} → ${current.turn}`);
    const nowActive = current.knowledge.own_side.active; const beforeActive = previous.knowledge.own_side.active;
    if (nowActive?.hp_fraction !== beforeActive?.hp_fraction) changes.push(`Own active HP ${beforeActive?.hp_fraction ?? '—'} → ${nowActive?.hp_fraction ?? '—'}`);
    const nowKnown = current.knowledge.known_opponent.flatMap((item) => item.revealed_moves.map((move) => move.name));
    const beforeKnown = new Set(previous.knowledge.known_opponent.flatMap((item) => item.revealed_moves.map((move) => move.name)));
    const revealed = nowKnown.filter((move) => !beforeKnown.has(move));
    if (revealed.length) changes.push(`New opponent move: ${revealed.join(', ')}`);
    if (current.strategy_memory !== previous.strategy_memory) changes.push('Strategy memory changed');
    return changes;
  }
  async function cancel() {
    if (!confirm('Cancel this match? The recorded events remain replayable.')) return;
    try { await api(`/api/matches/${data.id}/cancel`, { method: 'POST' }); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  async function lifecycleAction(action: 'pause' | 'resume') {
    try { await api(`/api/matches/${data.id}/${action}`, { method: 'POST' }); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  let rematching = false;
  async function handleRematch() {
    error = '';
    rematching = true;
    try {
      const created = await rematch(data.id);
      await goto(`/battle/${created.id}`);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      rematching = false;
    }
  }

  let resuming = false;
  async function handleResume() {
    error = '';
    resuming = true;
    try {
      const updated = await resumeMatch(data.id);
      match = updated;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      resuming = false;
    }
  }
</script>

<section class="preview">
  <BattleRenderer presentation={snapshot?.state || null} {config} campaign={match?.config.campaign || null} />
</section>

<!--
  Identity row sits below the renderer/team bar now: the battle owns the top of the
  screen, and the run's progress reads as a caption under it instead of pushing the
  arena down. Battle-view, OBS and presentation controls stay one click away in the
  tools menu.
-->
<div class="live-head">
  <div class="head-id">
    <span class="eyebrow">{campaign ? `${campaign.definition_name} · Battle ${campaign.stage_index + 1}/${campaign.stage_count}` : 'Match control'} · {data.id.slice(0, 8)}</span>
    <h1 title={battleHeading}>{battleHeading}</h1>
  </div>
  <div class="battle-context">
    {#if campaign}<span class="campaign-rail" aria-label={`Battle ${campaign.stage_index + 1} of ${campaign.stage_count}`} style={`--stage-accent:${campaign.visual_accent}`}>{#each Array(campaign.stage_count) as _, index}<i class:done={index < campaign.stage_index} class:current={index === campaign.stage_index}></i>{/each}</span>
    <span class="campaign-levels" title="Your level vs the stage level">Lv {campaign.player_level}{#if campaign.player_level !== campaign.opponent_level} vs {campaign.opponent_level}{/if}</span>{/if}
    {#if match}{#if match.challenge_run_id}<a class="button secondary compact" href={`/challenges/${match.challenge_run_id}`}><i class="ph ph-map-trifold" aria-hidden="true"></i>Draft map</a>{/if}<span class={`status-pill ${match.status}`}>{match.status}</span>{/if}
    <details bind:this={toolMenu} class="tool-menu">
      <summary title="Battle view, OBS and streaming tools"><i class="ph ph-sliders-horizontal" aria-hidden="true"></i><span>Tools</span></summary>
      <!-- Activating an item closes the menu; leaving it open hides the battle. -->
      <div class="tool-menu-panel" on:click={() => toolMenu && (toolMenu.open = false)} role="none">
        <span class="tool-menu-label">Battle view</span>
        <a class="tool-menu-item" href={`/watch/${data.id}`} target="_blank" rel="noopener"><i class="ph ph-monitor-play" aria-hidden="true"></i>Open battle view</a>
        <button type="button" class="tool-menu-item" on:click={() => copyText('watch', battleViewUrl)}><i class="ph ph-copy" aria-hidden="true"></i>{copied === 'watch' ? 'Copied' : 'Copy battle view URL'}</button>
        <span class="tool-menu-label">Streaming / advanced</span>
        <button type="button" class="tool-menu-item" on:click={() => copyText('obs', obsUrl)}><i class="ph ph-broadcast" aria-hidden="true"></i>{copied === 'obs' ? 'Copied' : 'Copy OBS URL'}</button>
        <a class="tool-menu-item" href={obsUrl} target="_blank" rel="noopener"><i class="ph ph-arrow-square-out" aria-hidden="true"></i>Open OBS overlay</a>
        <p class="tool-menu-note">The battle view is a clean full-screen battle with no controls. Both links carry the presentation settings below.</p>
      </div>
    </details>
  </div>
</div>

{#if match && humanSides.length && !pendingSides.some((side) => isHuman(side)) && !['completed','failed','cancelled','interrupted'].includes(match.status)}
  <section class="human-wait panel" role="status">
    <span class="wait-pulse"></span>
    <div><span class="eyebrow">Human Player</span><h2>{humanSides.map((side) => accepted[side] || `${agentLabel(side)} is waiting for the next legal turn`).join(' · ')}</h2><p>The battle state is live. Move and switch controls appear automatically when your next decision is legal.</p></div>
    {#if match.challenge_run_id}<a class="button secondary compact" href={`/challenges/${match.challenge_run_id}`}>Draft overview</a>{/if}
  </section>
{/if}

{#if pendingSides.length}
  <section class="workspace">
    <!-- Agent identity is the primary heading; P1/P2 is secondary metadata. -->
    <div class="agent-tabs" role="tablist" aria-label="Players waiting for an action">
      {#each (['p1', 'p2'] as Side[]).filter((side) => playerFor(side)) as side}
        <button
          role="tab"
          type="button"
          data-side={side}
          class:active={activeTab === side}
          class:actionable={Boolean(pending[side])}
          aria-selected={activeTab === side}
          disabled={!pending[side]}
          on:click={() => (activeTab = side)}
        >
          <b>{agentLabel(side)}</b>
          <span>{side.toUpperCase()} · {agentKind(side)}</span>
          <em data-state={pending[side] ? 'waiting' : 'idle'}>{tabState(side)}</em>
        </button>
      {/each}
    </div>

    {#each pendingSides.filter((side) => side === activeTab) as side (side)}
      {@const request = pending[side]}
      {#if request}
        <article class="manual panel" data-side={side}>
          <header>
            <div>
              <h2>{agentLabel(side)}</h2>
              <p>Player {side === 'p1' ? '1' : '2'} · Turn {request.turn} · {agentKind(side)}</p>
            </div>
            {#if !isHuman(side)}<button class="button" on:click={() => copyText(`prompt-${side}`, request.prompt)}>
              <i class="ph ph-copy" aria-hidden="true"></i>{copied === `prompt-${side}` ? 'Copied' : 'Copy prompt'}
            </button>{/if}
          </header>

          <div class="manual-grid">
            {#if isHuman(side)}
              <section class="action-picker" aria-label="Choose a legal battle action">
                <div class="column-head">
                  <h3>{isForcedSwitch(request) ? 'Choose a replacement' : 'Choose your action'}</h3>
                  <span class="meta">{isForcedSwitch(request) ? 'Forced switch · only legal replacements are shown' : 'Click or press 1–9 · submits immediately'}</span>
                </div>
                {#if isForcedSwitch(request)}<p class="forced-note" role="status"><i class="ph ph-warning" aria-hidden="true"></i>Your active Pokémon cannot continue. Select one of the legal, non-fainted replacements below.</p>{/if}
                <div class="action-grid">
                  {#each request.legal_actions as action, index (action.id)}
                    {@const preview = actionPreview(action)}
                    <button type="button" class="action-choice" disabled={Boolean(submitting[side])} aria-keyshortcuts={shortcutFor(index) || undefined} on:click={() => chooseAction(side, action)}>
                      {#if shortcutFor(index)}<kbd>{shortcutFor(index)}</kbd>{/if}
                      <span class="action-kind">{action.type === 'move' ? 'MOVE' : 'SWITCH'}</span>
                      <strong>{action.name}</strong>
                      <small>{actionSummary(action)}</small>
                      <span class="action-preview"><b>{preview.impact}</b><em>{preview.tempo}</em></span>
                    </button>
                  {/each}
                </div>
              </section>
            {/if}
            {#if !isHuman(side)}<section class="column">
              <div class="column-head">
                <h3>Prompt</h3>
                <span class="meta">{request.context_metrics?.rendered_characters ?? request.prompt.length} chars · ≈{request.context_metrics?.estimated_tokens ?? Math.ceil(request.prompt.length / 4)} tokens</span>
              </div>
              <textarea readonly value={request.prompt} aria-label="Generated prompt"></textarea>
            </section>
            <section class="column">
              <div class="column-head">
                <h3>Response</h3>
                <span class="meta">Paste the JSON object the chat returns</span>
              </div>
              <textarea
                value={responses[side] || ''}
                placeholder={'{\n  "action": "move:1",\n  "commentary": "…"\n}'}
                on:input={(event) => (responses = { ...responses, [side]: event.currentTarget.value })}
                spellcheck="false"
                aria-label="LLM response"
              ></textarea>
              <footer>
                <span class:valid={validation[side]?.startsWith('Valid')} class:error-text={validation[side] && !validation[side]?.startsWith('Valid')}>
                  {validation[side] || `${request.legal_actions.length} legal actions`}
                </span>
                <div>
                  <button class="button secondary" disabled={submitting[side]} on:click={() => validate(side)}>Validate</button>
                  <button class:loading={submitting[side]} class="button" disabled={submitting[side]} on:click={() => submit(side)}>{submitting[side] ? 'Submitting…' : 'Submit'}</button>
                </div>
              </footer>
            </section>{/if}
          </div>

          {#if !isHuman(side)}<details class="legal-actions">
            <summary>Legal actions ({request.legal_actions.length}) · click to prefill a response</summary>
            <ul>
              {#each request.legal_actions as action}
                <li>
                  <button type="button" on:click={() => insertAction(side, action)}>
                    <code>{action.id}</code>
                    <b>{action.name}</b>
                    <span>{actionSummary(action)}</span>
                  </button>
                </li>
              {/each}
            </ul>
          </details>{/if}
        </article>
      {/if}
    {/each}
  </section>
{/if}
{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if match}
  <div class="battle-drawers">
    {#if match.status === 'completed'}
      <details class="battle-drawer interview panel">
        <summary><span class="drawer-icon"><i class="ph ph-microphone-stage" aria-hidden="true"></i></span><span class="drawer-label"><b>Post-match interview</b><small>Replay-based reflections from both players</small></span><i class="ph ph-caret-down drawer-caret" aria-hidden="true"></i></summary>
        <div class="drawer-body interview-body">
          <div class="interview-grid">
            {#each (['p1', 'p2'] as Side[]) as side (side)}
              {@const interview = interviewFor(side)}
              <article class="interview-card" data-side={side}>
                <header><h3>{agentLabel(side)}</h3><span>{interview.detail}</span></header>
                <div><b>What worked?</b><p>{interview.good}</p></div>
                <div><b>What was weak?</b><p>{interview.bad}</p></div>
                <div><b>What would you change?</b><p>{interview.change}</p></div>
              </article>
            {/each}
          </div>
        </div>
      </details>
    {/if}
    {#if match.config.players.some((player) => player.team_export)}
      <details class="battle-drawer team-drawer panel">
        <summary><span class="drawer-icon"><i class="ph ph-lock-key" aria-hidden="true"></i></span><span class="drawer-label"><b>Fixed team snapshots</b><small>Private control data</small></span><i class="ph ph-caret-down drawer-caret" aria-hidden="true"></i></summary>
        <div class="drawer-body team-inspector"><p>Available only in the local control archive; spectator and OBS payloads exclude these exports.</p>{#each match.config.players as player}{#if player.team_export}<details><summary>{player.side.toUpperCase()} · {player.display_name}</summary><textarea readonly value={player.team_export}></textarea></details>{/if}{/each}</div>
      </details>
    {/if}
    <details bind:open={auditOpen} on:toggle={loadAuditArchive} class="battle-drawer audit-drawer panel">
      <summary><span class="drawer-icon"><i class="ph ph-list-magnifying-glass" aria-hidden="true"></i></span><span class="drawer-label"><b>Decisions and events</b><small>{snapshot?.eventCount || match.events.length} events · {match.decisions.length} decisions · {match.turns} turns</small></span><i class="ph ph-caret-down drawer-caret" aria-hidden="true"></i></summary>
      {#if auditOpen}
        <div class="drawer-body audit-body">
          {#if auditLoading}<p class="audit-empty" role="status"><i class="ph ph-circle-notch" aria-hidden="true"></i>Loading private decision details…</p>{/if}
          <div class="audit-toolbar"><div class="audit-stats"><span><strong>{snapshot?.eventCount || match.events.length}</strong> events</span><span><strong>{match.decisions.length}</strong> decisions</span><span><strong>{match.turns}</strong> turns</span></div><div class="audit-actions"><a class="button secondary" href={`/replay/${match.id}`}>Replay</a>{#if ['running','waiting'].includes(match.status)}<button class="button secondary" on:click={() => lifecycleAction('pause')}>Pause</button>{:else if match.status === 'paused'}<button class="button secondary" on:click={() => lifecycleAction('resume')}>Resume</button>{/if}{#if ['failed','cancelled','interrupted'].includes(match.status)}<button class="button" disabled={resuming || rematching} on:click={handleResume}>{resuming ? 'Continuing…' : 'Continue'}</button><button class="button secondary" disabled={resuming || rematching} on:click={handleRematch}>{rematching ? 'Rematching…' : 'Rematch'}</button>{/if}{#if !['completed','failed','cancelled','interrupted'].includes(match.status)}<button class="button danger" on:click={cancel}>Cancel</button>{/if}</div></div>
          <div class="decision-list">
    {#each [...match.decisions].reverse() as record}
      <details class="decision panel">
        <summary><span>Turn {record.decision.turn} · {record.decision.side.toUpperCase()}</span><strong>{record.decision.action}</strong><span>{record.decision.provider || 'local'}{record.decision.model ? ` / ${record.decision.model}` : ''}</span><span>{record.decision.latency_ms ?? '—'} ms</span></summary>
        <div class="decision-grid">
          <div><span class="eyebrow">Commentary</span><p>{record.decision.commentary || 'No public commentary.'}</p></div>
          <div><span class="eyebrow">Usage and cost</span><p>{record.decision.usage?.total_tokens ?? '—'} tokens · {record.decision.estimated_cost?.available ? `${record.decision.estimated_cost.amount} ${record.decision.estimated_cost.currency}` : 'cost unavailable'}</p></div>
          <div><span class="eyebrow">Validation</span><p>{record.decision.validation_attempts || 1} attempt(s){record.decision.fallback ? ` · ${record.decision.fallback.policy} fallback` : ''}</p></div>
          <section class="inspector">
            <span class="eyebrow">Prompt inspector</span>
            <p class="inspector-note">The rendered prompt is a view of the structured context below, not the context itself.</p>
            {#if contextChanges(record).length}<div class="context-diff">{#each contextChanges(record) as change}<span>{change}</span>{/each}</div>{/if}
            <details><summary>Structured agent context</summary>{#if record.request?.context}<pre>{JSON.stringify(record.request.context, null, 2)}</pre>{:else}<p>Context snapshot unavailable for this historical decision.</p>{/if}</details>
            <details><summary>Rendered prompt</summary>{#if record.generated_prompt}<pre>{record.generated_prompt}</pre>{:else}<p>Rendered prompt unavailable.</p>{/if}</details>
            {#if record.request?.system_prompt}<details><summary>System message</summary><pre>{record.request.system_prompt}</pre></details>{/if}
            {#if record.request?.user_prompt}<details><summary>User message</summary><pre>{record.request.user_prompt}</pre></details>{/if}
            <details><summary>Player knowledge</summary>{#if record.request?.knowledge}<pre>{JSON.stringify(record.request.knowledge, null, 2)}</pre>{:else}<p>Player knowledge unavailable for this historical decision.</p>{/if}</details>
            <details><summary>Raw provider response</summary>{#if record.raw_response}<pre>{record.raw_response}</pre>{:else}<p>Raw provider response unavailable.</p>{/if}</details>
            <details><summary>Parsed decision</summary>{#if record.parsed_response}<pre>{JSON.stringify(record.parsed_response, null, 2)}</pre>{:else}<p>Parsed decision unavailable.</p>{/if}</details>
            <details><summary>Game state</summary>{#if record.request?.state}<pre>{JSON.stringify(record.request.state, null, 2)}</pre>{:else}<p>Game state unavailable for this historical decision.</p>{/if}</details>
            <details><summary>Validation</summary><pre>{JSON.stringify({ attempts: record.decision.validation_attempts, errors: record.decision.validation_errors, retry_attempts: record.decision.retry_attempts, fallback: record.decision.fallback, error_category: record.decision.error_category }, null, 2)}</pre></details>
          </section>
        </div>
      </details>
    {:else}
      <p class="audit-empty" role="status"><i class="ph ph-hourglass-simple" aria-hidden="true"></i>No decisions have been recorded yet. Events and decisions appear here as the battle advances.</p>
    {/each}
          </div>
        </div>
      {/if}
    </details>
  </div>
{/if}

<!-- Every control here edits the renderer above as you touch it, and the same settings
     drive the battle-view tab and the OBS source, so what you tune is what gets captured.
     Collapsed by default and pushed to the very bottom of the page, below everything else,
     so the battle - not the mixing desk - owns the screen. -->
<details class="preview-settings">
<summary><i class="ph ph-faders" aria-hidden="true"></i>Presentation settings</summary>
<div class="preview-tools">
  <div class="tool-group">
    <span class="tool-label">Frame</span>
    <label>Layout<select value={config.layout} on:change={(event) => updateConfig({ layout: event.currentTarget.value as RendererLayout })}><option value="standard-landscape">Landscape</option><option value="standard-vertical">Vertical</option><option value="overlay-landscape">Overlay</option></select></label>
    <label>Theme<select value={config.theme} on:change={(event) => updateConfig({ theme: event.currentTarget.value as RendererTheme })}><option value="pokemon-route">Pokémon Route</option><option value="pokemon-stadium">Pokémon Stadium</option><option value="koala-dark">Koala Dark</option><option value="koala-light">Koala Light</option></select></label>
    <label>Your side<select value={config.nearSide} on:change={(event) => updateConfig({ nearSide: event.currentTarget.value as Side })}><option value="p1">P1 in front</option><option value="p2">P2 in front</option></select></label>
  </div>

  <div class="tool-group">
    <span class="tool-label">Readability</span>
    <label class="range">HUD size <b>{Math.round(config.hudScale * 100)}%</b>
      <input
        type="range"
        min={HUD_SCALE_RANGE.min}
        max={HUD_SCALE_RANGE.max}
        step={HUD_SCALE_RANGE.step}
        value={config.hudScale}
        on:input={(event) => updateConfig({ hudScale: Number(event.currentTarget.value) })}
      />
    </label>
    <label class="check"><input type="checkbox" checked={config.showTeamRoster} on:change={(event) => updateConfig({ showTeamRoster: event.currentTarget.checked })} />Team roster</label>
    <label class="check"><input type="checkbox" checked={config.showTurn} on:change={(event) => updateConfig({ showTurn: event.currentTarget.checked })} />Turn counter</label>
    <label class="check"><input type="checkbox" checked={config.showBattleLog} on:change={(event) => updateConfig({ showBattleLog: event.currentTarget.checked })} />Battle feed</label>
    <label class="check"><input type="checkbox" checked={config.showAgentState} on:change={(event) => updateConfig({ showAgentState: event.currentTarget.checked })} />Agent state</label>
    <label class="check"><input type="checkbox" checked={config.showDamageNumbers} on:change={(event) => updateConfig({ showDamageNumbers: event.currentTarget.checked })} />Damage numbers</label>
  </div>

  <div class="tool-group">
    <span class="tool-label">Motion</span>
    <label>Watch speed<select value={String(config.playbackSpeed)} on:change={(event) => updateConfig({ playbackSpeed: event.currentTarget.value === 'instant' ? 'instant' : Number(event.currentTarget.value) as PlaybackSpeed })}><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="instant">Max</option></select></label>
    <label>Effects<select value={config.effects} on:change={(event) => updateConfig({ effects: event.currentTarget.value as EffectQuality })}><option value="off">Off</option><option value="low">Low</option><option value="standard">Standard</option><option value="high">High</option></select></label>
    <label>Move style<select value={config.moveEffectSkin} on:change={(event) => updateConfig({ moveEffectSkin: event.currentTarget.value as MoveEffectSkin })}><option value="broadcast">Broadcast</option><option value="retro">Retro</option><option value="procedural">Procedural</option></select></label>
    <label>Commentary<select value={config.commentaryMode} on:change={(event) => updateConfig({ commentaryMode: event.currentTarget.value as CommentaryMode })}><option value="latest">Latest only</option><option value="last-3">Last three</option><option value="full">Full detail</option><option value="hidden">Hidden</option></select></label>
    <label class="check"><input type="checkbox" checked={config.animatedSprites} on:change={(event) => updateConfig({ animatedSprites: event.currentTarget.checked })} />Animated sprites</label>
    <label class="check"><input type="checkbox" checked={config.reducedMotion} on:change={(event) => updateConfig({ reducedMotion: event.currentTarget.checked })} />Reduced motion</label>
    <label class="check"><input type="checkbox" checked={config.transparentBackground} on:change={(event) => updateConfig({ transparentBackground: event.currentTarget.checked })} />Transparent (OBS)</label>
  </div>

  <div class="tool-foot">
    <button type="button" class="link-button" on:click={() => updateConfig(defaultRendererConfig())}>Reset to defaults</button>
    <span class:sync-error={configSyncError} class="preview-note" role={configSyncError ? 'alert' : undefined}>{configSyncError || 'Live preview. The battle-view tab and the OBS source use these same settings.'}</span>
  </div>
</div>
</details>

<style>
  /* One compact identity row. Everything technical lives in the tools menu. */
  .live-head{position:relative;z-index:40;display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-top:.55rem;margin-bottom:.55rem}
  .head-id{min-width:0}
  .live-head .eyebrow{font-size:.58rem}
  .live-head h1{margin:.1rem 0 0;overflow:hidden;font-size:clamp(1.05rem,1.7vw,1.4rem);text-overflow:ellipsis;white-space:nowrap}
  .battle-context{display:flex;flex-wrap:wrap;flex-shrink:1;align-items:center;justify-content:flex-end;gap:.4rem .5rem;min-width:0}
  .campaign-rail{display:flex;gap:3px}
  .campaign-rail i{width:14px;height:5px;border-radius:999px;background:var(--border)}
  .campaign-rail i.done{background:color-mix(in srgb,var(--accent) 70%,var(--border))}
  .campaign-rail i.current{width:22px;background:var(--stage-accent)}
  .campaign-levels{color:var(--muted);font:650 .66rem var(--mono);white-space:nowrap}
  .tool-menu{position:relative}
  .tool-menu>summary{display:flex;min-height:44px;align-items:center;gap:.4rem;padding:.34rem .7rem;border:1px solid var(--border);border-radius:999px;background:var(--panel);color:var(--muted);font:650 .74rem var(--display);cursor:pointer;list-style:none}
  .tool-menu>summary::-webkit-details-marker{display:none}
  .tool-menu>summary:hover,.tool-menu[open]>summary{border-color:color-mix(in srgb,var(--accent) 45%,var(--border));color:var(--text)}
  .tool-menu-panel{position:absolute;z-index:30;top:calc(100% + .4rem);right:0;display:grid;gap:.18rem;width:min(19rem,80vw);padding:.5rem;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--panel);box-shadow:var(--shadow)}
  .tool-menu-label{margin:.3rem .35rem .1rem;color:var(--accent);font:700 .58rem var(--mono);letter-spacing:.13em;text-transform:uppercase}
  .tool-menu-item{display:flex;min-height:44px;align-items:center;gap:.5rem;width:100%;padding:.45rem .55rem;border:0;border-radius:.5rem;background:transparent;color:var(--text);font:600 .8rem var(--display);text-align:left;cursor:pointer}
  .tool-menu-item:hover{background:var(--surface)}
  .tool-menu-note{margin:.35rem .35rem 0;color:var(--muted);font-size:.68rem;line-height:1.45}
  .preview-settings{margin-top:.7rem;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--panel)}
  .preview-settings>summary{display:flex;min-height:44px;align-items:center;gap:.45rem;padding:.6rem .9rem;color:var(--muted);font:650 .78rem var(--display);cursor:pointer}
  .preview-settings[open]>summary{color:var(--text)}
  .human-wait{display:flex;align-items:center;gap:1rem;margin:1rem 0;padding:1rem;border-color:color-mix(in srgb,var(--accent) 42%,var(--border));box-shadow:none}
  .human-wait>div{flex:1}.human-wait h2{margin:.2rem 0;font-size:1rem}.human-wait p{margin:.2rem 0;color:var(--muted);font-size:.72rem}
  .wait-pulse{width:12px;aspect-ratio:1;border-radius:50%;background:var(--accent);box-shadow:0 0 0 6px color-mix(in srgb,var(--accent) 14%,transparent);animation:wait-pulse 1.6s ease-in-out infinite}@keyframes wait-pulse{50%{opacity:.4}}
  .preview{margin-top:0}
  .preview-tools{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;padding:0 1.1rem 1rem;border-top:1px solid var(--border);padding-top:1rem}
  .tool-group{display:grid;align-content:start;gap:.5rem;min-width:0}
  .tool-label{color:var(--accent);font:700 .62rem var(--mono);letter-spacing:.14em;text-transform:uppercase}
  .preview-tools label{min-width:0}
  .preview-tools select{min-height:44px;padding:.4rem}
  .preview-tools .check{display:flex;min-height:44px;align-items:center;gap:.55rem;font-size:.8rem}
  .preview-tools .check input{width:18px;min-height:18px;margin:0}
  .range{display:grid;gap:.3rem;font-size:.8rem}
  .range b{color:var(--accent);font:700 .78rem var(--mono)}
  .range input{width:100%;accent-color:var(--accent)}
  .tool-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.6rem;grid-column:1/-1;padding-top:.7rem;border-top:1px solid var(--border)}
  .preview-note{color:var(--muted);font-size:.72rem}
  .preview-note.sync-error{color:var(--danger)}

  /* ── Manual workspace ───────────────────────────────────────────────────── */
  .workspace{display:grid;gap:.75rem;margin-top:1.5rem}
  .agent-tabs{display:grid;grid-template-columns:1fr 1fr;gap:.6rem}
  .agent-tabs button{display:grid;gap:.15rem;padding:.7rem .9rem;border:1px solid var(--border);border-left:4px solid var(--side-color);border-radius:.75rem;background:var(--panel);color:var(--text);text-align:left;cursor:pointer;transition:border-color .16s ease,background .16s ease,transform .16s ease}
  .agent-tabs button[data-side='p1']{--side-color:var(--p1)}
  .agent-tabs button[data-side='p2']{--side-color:var(--p2)}
  .agent-tabs button:disabled{opacity:.55;cursor:default}
  /* The selected tab is unmistakable; an actionable tab that is not selected still nags. */
  .agent-tabs button.active{border-color:var(--side-color);border-left-width:6px;background:color-mix(in srgb,var(--side-color) 10%,var(--panel));box-shadow:0 0 0 2px color-mix(in srgb,var(--side-color) 28%,transparent)}
  .agent-tabs button.actionable:not(.active){border-color:color-mix(in srgb,var(--accent) 40%,var(--border))}
  .agent-tabs button.actionable:not(.active) em{animation:tab-nudge 2.4s ease-in-out infinite}
  @keyframes tab-nudge{50%{opacity:.55}}
  .agent-tabs b{font-size:1.05rem;font-weight:800;letter-spacing:-.02em}
  .agent-tabs span{color:var(--muted);font:.66rem var(--mono);text-transform:uppercase}
  .agent-tabs em{justify-self:start;margin-top:.2rem;padding:.15rem .45rem;border-radius:999px;background:var(--surface);color:var(--muted);font:600 .62rem var(--display);font-style:normal}
  .agent-tabs em[data-state='waiting']{background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent)}

  .manual{padding:1.25rem;box-shadow:none;border-left:4px solid var(--side-color)}
  .manual[data-side='p1']{--side-color:var(--p1)}
  .manual[data-side='p2']{--side-color:var(--p2)}
  .manual header{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;margin-bottom:1rem}
  .manual h2{margin:0;font-size:1.5rem;font-weight:800;letter-spacing:-.03em;text-transform:uppercase}
  .manual header p{margin:.15rem 0 0;color:var(--muted);font:.72rem var(--mono);text-transform:uppercase}
  /* Constrained readable columns: prompt and response never stretch to an ultra-wide monitor. */
  .manual-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;max-width:1180px}
  .action-picker{grid-column:1/-1;display:grid;gap:.6rem;padding:.9rem;border:1px solid color-mix(in srgb,var(--accent) 38%,var(--border));border-radius:.75rem;background:color-mix(in srgb,var(--accent) 5%,var(--panel))}
  .forced-note{display:flex;align-items:center;gap:.45rem;margin:0;padding:.6rem;border:1px solid color-mix(in srgb,var(--warning) 40%,var(--border));border-radius:.55rem;background:color-mix(in srgb,var(--warning) 7%,transparent);color:var(--warning);font-size:.7rem}
  .action-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:.55rem}
  .action-choice{position:relative;display:grid;gap:.14rem;min-height:112px;padding:.7rem 2.2rem .7rem .75rem;border:1px solid var(--border);border-left:3px solid var(--side-color);border-radius:.6rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer;transition:border-color .16s ease,transform .16s ease,background .16s ease}
  .action-choice:hover:not(:disabled){border-color:var(--side-color);background:color-mix(in srgb,var(--side-color) 12%,var(--panel-strong));transform:translateY(-1px)}
  .action-choice:disabled{cursor:wait;opacity:.55}
  .action-kind{color:var(--side-color);font:800 .58rem var(--mono);letter-spacing:.12em}
  .action-choice strong{font-size:.92rem}
  .action-choice small{overflow:hidden;color:var(--muted);font:.62rem var(--mono);text-overflow:ellipsis;white-space:nowrap}
  .action-choice kbd{position:absolute;top:.55rem;right:.55rem;display:grid;place-items:center;width:1.35rem;aspect-ratio:1;border:1px solid color-mix(in srgb,var(--side-color) 45%,var(--border));border-radius:.35rem;background:var(--surface);color:var(--side-color);font:800 .65rem var(--mono);box-shadow:0 2px 0 rgba(0,0,0,.35)}
  .action-preview{display:grid;gap:.08rem;margin-top:.25rem;padding-top:.35rem;border-top:1px solid var(--border)}
  .action-preview b{color:var(--text);font:700 .68rem var(--display)}
  .action-preview em{color:var(--muted);font:500 .6rem var(--mono);font-style:normal}
  .column{display:grid;gap:.4rem;min-width:0}
  .column-head{display:flex;align-items:baseline;justify-content:space-between;gap:.6rem}
  .column-head h3{margin:0;font-size:.85rem}
  .meta{color:var(--muted);font:.64rem var(--mono)}
  .manual textarea{height:300px;resize:vertical;font:400 .74rem/1.6 var(--mono)}
  .column footer{display:flex;align-items:center;justify-content:space-between;gap:.75rem;margin-top:.2rem}
  .column footer>span{color:var(--muted);font-size:.72rem}
  .column footer>span.valid{color:var(--accent)}
  .column footer>span.error-text{color:var(--danger)}
  .column footer div{display:flex;gap:.5rem}
  .legal-actions{margin-top:1rem;border-top:1px solid var(--border);padding-top:.8rem}
  .legal-actions summary{color:var(--muted);font-size:.78rem;cursor:pointer}
  .legal-actions ul{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.4rem;margin:.8rem 0 0;padding:0;list-style:none}
  .legal-actions button{display:grid;grid-template-columns:auto 1fr;gap:.1rem .5rem;width:100%;padding:.45rem .6rem;border:1px solid var(--border);border-radius:.55rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer}
  .legal-actions button:hover{border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}
  .legal-actions code{grid-row:1/3;align-self:center;color:var(--accent);font:.66rem var(--mono)}
  .legal-actions b{font-size:.8rem}
  .legal-actions button span{color:var(--muted);font:.62rem var(--mono)}

  .battle-drawers{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:.6rem;margin-top:1rem}
  .battle-drawer{min-width:0;box-shadow:none}
  .battle-drawer[open]{grid-column:1/-1}
  .battle-drawer>summary{display:grid;grid-template-columns:40px minmax(0,1fr) auto;align-items:center;gap:.7rem;min-height:58px;padding:.55rem .75rem;cursor:pointer;list-style:none}
  .battle-drawer>summary::-webkit-details-marker{display:none}
  .drawer-icon{display:grid;place-items:center;width:40px;aspect-ratio:1;border-radius:.65rem;background:color-mix(in srgb,var(--accent) 10%,var(--surface));color:var(--accent);font-size:1.05rem}
  .drawer-label{display:grid;gap:.1rem;min-width:0}
  .drawer-label b{font-size:.82rem}
  .drawer-label small{overflow:hidden;color:var(--muted);font:.6rem var(--mono);text-overflow:ellipsis;white-space:nowrap}
  .drawer-caret{color:var(--muted);transition:transform .16s ease}
  .battle-drawer[open]>summary .drawer-caret{transform:rotate(180deg)}
  .drawer-body{padding:1rem;border-top:1px solid var(--border)}
  .interview-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.85rem}
  .interview-card{display:grid;gap:.75rem;padding:1rem;border:1px solid var(--border);border-top:3px solid var(--side-color);border-radius:.75rem;background:var(--panel-strong)}
  .interview-card[data-side='p1']{--side-color:var(--p1)}
  .interview-card[data-side='p2']{--side-color:var(--p2)}
  .interview-card header{display:grid;gap:.16rem}
  .interview-card h3{margin:0;font-size:1.05rem}
  .interview-card header span{color:var(--muted);font:.62rem var(--mono)}
  .interview-card>div{display:grid;gap:.15rem}
  .interview-card b{color:var(--side-color);font:.64rem var(--mono);letter-spacing:.1em;text-transform:uppercase}
  .interview-card p{margin:0;color:var(--text);font-size:.78rem;line-height:1.48}

  .team-inspector{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;box-shadow:none}
  .team-inspector p{margin:0;color:var(--muted);font-size:.76rem}
  .team-inspector details{margin:0;padding:0}.team-inspector details>summary{display:flex;min-height:44px;align-items:center;cursor:pointer}
  .team-inspector textarea{width:100%;min-height:220px;margin-top:.7rem;font:400 .65rem/1.5 var(--mono)}
  .audit-toolbar{display:flex;align-items:center;justify-content:space-between;gap:2rem}
  .audit-stats,.audit-actions{display:flex;gap:1rem}
  .audit-stats span{display:grid;color:var(--muted);font:.7rem var(--mono)}
  .audit-stats strong{color:var(--text);font:700 1.4rem var(--display)}
  .button.danger{border-color:color-mix(in srgb,var(--danger) 45%,var(--border));background:transparent;color:var(--danger)}
  .decision-list{display:grid;gap:.6rem;margin-top:1rem}
  .audit-empty{display:flex;align-items:center;gap:.55rem;margin:0;padding:1rem;border:1px dashed var(--border);border-radius:.65rem;color:var(--muted);font-size:.74rem}
  .audit-empty i{color:var(--accent);font-size:1.1rem}
  .decision{box-shadow:none}
  .decision>summary{display:grid;grid-template-columns:1fr 1fr 1.4fr auto;gap:1rem;align-items:center;padding:1rem;cursor:pointer}
  .decision>summary span{color:var(--muted);font:.7rem var(--mono)}
  .decision-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;padding:0 1rem 1rem;border-top:1px solid var(--border)}
  .decision-grid>div{padding-top:1rem}
  .decision-grid p{font-size:.8rem}
  .inspector{grid-column:1/-1;display:grid;gap:.55rem;padding-top:1rem}
  .inspector-note{margin:0;color:var(--muted);font-size:.74rem}
  .inspector details{margin:0;padding:.7rem;border:1px solid var(--border);border-radius:.65rem}
  .inspector details summary{display:flex;min-height:44px;align-items:center;color:var(--text)}
  .inspector pre{max-height:360px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font:400 .68rem/1.5 var(--mono)}
  .context-diff{display:flex;flex-wrap:wrap;gap:.4rem}
  .context-diff span{padding:.28rem .45rem;border:1px solid var(--border);border-radius:999px;color:var(--accent);font:.62rem var(--mono)}

  @media(max-width:980px){
    .live-head{align-items:flex-start;flex-direction:column;gap:.5rem}
    .manual-grid{grid-template-columns:1fr}
    .interview-grid{grid-template-columns:1fr}
    .team-inspector{grid-template-columns:1fr}
    .audit-toolbar{align-items:stretch;flex-direction:column}
    .decision>summary{grid-template-columns:1fr 1fr}
    .decision-grid{grid-template-columns:1fr}
  }
  @media(max-width:620px){
    .live-head{align-items:flex-start;flex-direction:column}
    .agent-tabs{grid-template-columns:1fr}
    .preview-tools{flex-wrap:wrap}
    .preview-note{width:100%;margin-left:0}
    .manual header{align-items:stretch;flex-direction:column}
    .battle-drawers{grid-template-columns:1fr}
    .column footer{align-items:stretch;flex-direction:column}
    .column footer div{display:grid;grid-template-columns:1fr 1fr}
    .audit-stats{justify-content:space-between}
    .audit-actions{display:grid}
    .human-wait{align-items:stretch;flex-direction:column}
    .decision>summary{grid-template-columns:1fr}
  }
  .battle-context .button.compact,.tool-foot .link-button{min-height:44px}
  @media(prefers-reduced-motion:reduce){.wait-pulse,.agent-tabs button.actionable:not(.active) em{animation:none}.drawer-caret{transition:none}}
</style>
