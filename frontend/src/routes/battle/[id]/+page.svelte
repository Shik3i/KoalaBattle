<script lang="ts">
  import { onMount } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import { api, getMatch, wsBase } from '$lib/api';
  import { loadRendererConfig, saveRendererConfig } from '$lib/presentation/config';
  import { PresentationTimeline } from '$lib/presentation/timeline';
  import { defaultRendererConfig, type AgentPresentationStatus, type RendererConfig, type RendererLayout, type RendererTheme, type TimelineSnapshot } from '$lib/presentation/types';
  import type { AgentLifecycleState, AgentRequest, BattleEvent, MatchArchive, Side } from '$lib/types';

  export let data: { id: string };
  let match: MatchArchive | null = null;
  let pending: Partial<Record<Side, AgentRequest>> = {};
  let responses: Partial<Record<Side, string>> = {};
  let validation: Partial<Record<Side, string>> = {};
  let submitting: Partial<Record<Side, boolean>> = {};
  let copied: Side | null = null;
  let copyTimer: ReturnType<typeof setTimeout> | null = null;
  let error = ''; let socket: WebSocket | null = null;
  let timeline: PresentationTimeline | null = null; let snapshot: TimelineSnapshot | null = null;
  let config: RendererConfig = defaultRendererConfig();
  let lifecycle: Partial<Record<Side, AgentLifecycleState>> = { p1: 'idle', p2: 'idle' };

  $: agentStatus = Object.fromEntries(Object.entries(lifecycle).map(([side, state]) => [
    side, state === 'waiting' || state === 'thinking' || state === 'retrying' ? 'thinking'
      : state === 'decided' ? 'decided' : state === 'executing' ? 'executing'
      : state === 'finished' ? 'finished' : state === 'error' ? 'error' : 'idle'
  ])) as Partial<Record<Side, AgentPresentationStatus>>;

  interface StreamMessage {
    kind: string; match?: MatchArchive; event?: BattleEvent; request?: AgentRequest;
    decision?: MatchArchive['decisions'][number]; request_id?: string; error?: string;
  }
  onMount(() => {
    config = loadRendererConfig(); void connect();
    return () => { socket?.close(); timeline?.destroy(); if (copyTimer) clearTimeout(copyTimer); };
  });
  async function connect() {
    try {
      initialize(await getMatch(data.id));
      const result = await api<{ requests: AgentRequest[] }>(`/api/matches/${data.id}/pending`);
      result.requests.forEach(setPending);
      socket = new WebSocket(`${wsBase()}/api/matches/${data.id}/stream`);
      socket.onmessage = ({ data: raw }) => handleMessage(JSON.parse(raw) as StreamMessage);
      socket.onerror = () => (error = 'Realtime connection failed.');
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  function initialize(archive: MatchArchive) {
    match = archive; timeline?.destroy();
    timeline = new PresentationTimeline(archive, archive.events, undefined, true);
    timeline.subscribe((value) => (snapshot = value));
    timeline.setPreset(config.preset); timeline.setSpeed(config.playbackSpeed);
    timeline.seek(archive.events.length); timeline.play();
  }
  function setPending(request: AgentRequest) {
    pending = { ...pending, [request.side]: request };
    lifecycle = { ...lifecycle, [request.side]: 'waiting' };
    responses = { ...responses, [request.side]: JSON.stringify({ action: request.legal_actions[0]?.id || 'move:1', commentary: 'Short public explanation.' }, null, 2) };
    validation = { ...validation, [request.side]: '' };
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
      match.decisions = [...match.decisions, message.decision];
      lifecycle = { ...lifecycle, [message.decision.decision.side]: 'decided' };
    }
    if (message.kind === 'agent_waiting' && message.request) {
      setPending(message.request); if (match) match.status = 'waiting';
    }
    if (message.kind === 'manual_response_accepted' && message.request_id) {
      const side = (Object.keys(pending) as Side[]).find((item) => pending[item]?.request_id === message.request_id);
      if (side) {
        lifecycle = { ...lifecycle, [side]: 'executing' };
        pending = { ...pending }; delete pending[side];
      }
      if (match && Object.keys(pending).length === 0) match.status = 'running';
    }
    if (message.kind === 'match_completed') {
      if (match) match.status = 'completed'; lifecycle = { p1: 'finished', p2: 'finished' }; void refreshMetadata();
    }
    if (message.kind === 'match_cancelled') { if (match) match.status = 'cancelled'; }
    if (message.kind === 'match_paused') { if (match) match.status = 'paused'; }
    if (message.kind === 'match_resumed') { if (match) match.status = Object.keys(pending).length ? 'waiting' : 'running'; }
    if (message.kind === 'match_failed') { if (match) match.status = 'failed'; error = message.error || 'Battle failed.'; }
  }
  async function refreshMetadata() {
    const archive = await getMatch(data.id);
    if (match) match = { ...archive, events: match.events };
  }
  function updateConfig(patch: Partial<RendererConfig>) {
    config = { ...config, ...patch }; saveRendererConfig(config);
    if (patch.playbackSpeed !== undefined) timeline?.setSpeed(config.playbackSpeed);
    if (patch.preset !== undefined) timeline?.setPreset(config.preset);
  }
  async function copyPrompt(side: Side) {
    const request = pending[side]; if (!request) return;
    await navigator.clipboard.writeText(request.prompt); copied = side;
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => (copied = null), 1200);
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
</script>

<div class="live-head">
  <div><span class="eyebrow">Production control · {data.id}</span><h1>{match ? (match.config.name || `${match.config.players[0].display_name} vs ${match.config.players[1].display_name}`) : 'Loading battle…'}</h1></div>
  <div class="live-tools">
    <label>Layout<select value={config.layout} on:change={(event) => updateConfig({ layout: event.currentTarget.value as RendererLayout })}><option value="standard-landscape">Landscape</option><option value="standard-vertical">Vertical</option><option value="overlay-landscape">Overlay</option></select></label>
    <label>Theme<select value={config.theme} on:change={(event) => updateConfig({ theme: event.currentTarget.value as RendererTheme })}><option value="koala-dark">Koala Dark</option><option value="koala-light">Koala Light</option></select></label>
    {#if match}<span class={`status-pill ${match.status}`}>{match.status}</span>{/if}
  </div>
</div>
<BattleRenderer presentation={snapshot?.state || null} {config} {agentStatus} />

{#if match}
  <section class="agent-strip panel">
    {#each match.config.players as player}
      <article><span class="side">{player.side}</span><div><strong>{player.display_name}</strong><small>{player.provider || player.agent_type}{player.model ? ` · ${player.model}` : ''}</small></div><span class={`lifecycle ${lifecycle[player.side] || 'idle'}`}>{lifecycle[player.side] || 'idle'}</span></article>
    {/each}
  </section>
{/if}

{#if Object.keys(pending).length}
  <section class="manual-stack">
    {#each Object.entries(pending) as [sideValue, request]}
      {@const side = sideValue as Side}
      {#if request}
        <article class="manual panel">
          <header><div><span class="eyebrow">{side} · Turn {request.turn} · Prompt {request.prompt_profile_id} {request.prompt_profile_version}</span><h2>{side.toUpperCase()} manual workspace</h2></div><button class="button secondary" on:click={() => copyPrompt(side)}>{copied === side ? 'Copied' : 'Copy prompt'}</button></header>
          <p class="instruction">Paste the prompt into any web chat. Ask it to return one JSON object using an exact legal action ID. Markdown fences are accepted.</p>
          <div class="prompt-meta"><span>Context {request.context?.context_profile_id || 'historical'} {request.context?.context_profile_version || ''}</span><span>{request.context_metrics?.rendered_characters ?? request.prompt.length} chars</span><span>≈ {request.context_metrics?.estimated_tokens ?? Math.ceil(request.prompt.length / 4)} tokens</span><span>Memory {request.memory_policy}{request.context?.strategy_memory ? ' · populated' : ' · empty'}</span></div>
          <div class="manual-grid"><label>Generated prompt<textarea readonly value={request.prompt}></textarea></label><label>LLM response<textarea value={responses[side] || ''} on:input={(event) => (responses = { ...responses, [side]: event.currentTarget.value })} spellcheck="false"></textarea></label></div>
          <footer><span class:valid={validation[side]?.startsWith('Valid')} class:error-text={validation[side] && !validation[side]?.startsWith('Valid')}>{validation[side] || `${request.legal_actions.length} legal actions`}</span><div><button class="button secondary" disabled={submitting[side]} on:click={() => validate(side)}>Validate</button><button class="button" disabled={submitting[side]} on:click={() => submit(side)}>{submitting[side] ? 'Submitting…' : 'Submit decision →'}</button></div></footer>
        </article>
      {/if}
    {/each}
  </section>
{/if}
{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if match}
  {#if match.config.players.some((player) => player.team_export)}
    <section class="team-inspector panel"><div><span class="eyebrow">Private control data</span><h2>Fixed team snapshots</h2><p>Available only in the local control archive; spectator and OBS payloads exclude these exports.</p></div>{#each match.config.players as player}{#if player.team_export}<details><summary>{player.side.toUpperCase()} · {player.display_name}</summary><textarea readonly value={player.team_export}></textarea></details>{/if}{/each}</section>
  {/if}
  <section class="audit-head"><div><span class="eyebrow">Audit trail</span><h2>Decisions and events</h2></div><div class="audit-stats"><span><strong>{snapshot?.eventCount || match.events.length}</strong> events</span><span><strong>{match.decisions.length}</strong> decisions</span><span><strong>{match.turns}</strong> turns</span></div><div class="audit-actions"><a class="button secondary" href={`/watch/${match.id}`}>Spectator</a><a class="button secondary" href={`/overlay/${match.id}?layout=overlay-landscape&theme=${config.theme}`}>OBS overlay</a><a class="button secondary" href={`/replay/${match.id}`}>Replay</a>{#if ['running','waiting'].includes(match.status)}<button class="button secondary" on:click={() => lifecycleAction('pause')}>Pause</button>{:else if match.status === 'paused'}<button class="button secondary" on:click={() => lifecycleAction('resume')}>Resume</button>{/if}{#if !['completed','failed','cancelled','interrupted'].includes(match.status)}<button class="button danger" on:click={cancel}>Cancel</button>{/if}</div></section>
  <div class="decision-list">
    {#each [...match.decisions].reverse() as record}
      <details class="decision panel">
        <summary><span>Turn {record.decision.turn} · {record.decision.side.toUpperCase()}</span><strong>{record.decision.action}</strong><span>{record.decision.provider || 'local'}{record.decision.model ? ` / ${record.decision.model}` : ''}</span><span>{record.decision.latency_ms ?? '—'} ms</span></summary>
        <div class="decision-grid">
          <div><span class="eyebrow">Commentary</span><p>{record.decision.commentary || 'No public commentary.'}</p></div>
          <div><span class="eyebrow">Usage and cost</span><p>{record.decision.usage?.total_tokens ?? '—'} tokens · {record.decision.estimated_cost?.available ? `${record.decision.estimated_cost.amount} ${record.decision.estimated_cost.currency}` : 'cost unavailable'}</p></div>
          <div><span class="eyebrow">Validation</span><p>{record.decision.validation_attempts || 1} attempt(s){record.decision.fallback ? ` · ${record.decision.fallback.policy} fallback` : ''}</p></div>
          <section class="inspector">
            <span class="eyebrow">Decision inspector</span>
            {#if contextChanges(record).length}<div class="context-diff">{#each contextChanges(record) as change}<span>{change}</span>{/each}</div>{/if}
            <details><summary>Game State</summary>{#if record.request?.state}<pre>{JSON.stringify(record.request.state, null, 2)}</pre>{:else}<p>Game state unavailable for this historical decision.</p>{/if}</details>
            <details><summary>Player Knowledge</summary>{#if record.request?.knowledge}<pre>{JSON.stringify(record.request.knowledge, null, 2)}</pre>{:else}<p>Player knowledge unavailable for this historical decision.</p>{/if}</details>
            <details><summary>Agent Context</summary>{#if record.request?.context}<pre>{JSON.stringify(record.request.context, null, 2)}</pre>{:else}<p>Context snapshot unavailable for this historical decision.</p>{/if}</details>
            <details><summary>Rendered Prompt</summary>{#if record.generated_prompt}<pre>{record.generated_prompt}</pre>{:else}<p>Rendered prompt unavailable.</p>{/if}</details>
            <details><summary>Raw Response</summary>{#if record.raw_response}<pre>{record.raw_response}</pre>{:else}<p>Raw provider response unavailable.</p>{/if}</details>
            <details><summary>Parsed Decision</summary>{#if record.parsed_response}<pre>{JSON.stringify(record.parsed_response, null, 2)}</pre>{:else}<p>Parsed decision unavailable.</p>{/if}</details>
            <details><summary>Validation</summary><pre>{JSON.stringify({ attempts: record.decision.validation_attempts, errors: record.decision.validation_errors, retry_attempts: record.decision.retry_attempts, fallback: record.decision.fallback, error_category: record.decision.error_category }, null, 2)}</pre></details>
          </section>
        </div>
      </details>
    {/each}
  </div>
{/if}

<style>
  .live-head{display:flex;justify-content:space-between;align-items:end;gap:1rem;margin-bottom:1.5rem}.live-head h1{margin:.3rem 0 0;font-size:clamp(1.7rem,4vw,3rem)}.live-tools{display:flex;align-items:end;gap:.6rem}.live-tools label{min-width:120px}.live-tools select{min-height:38px;padding:.45rem}.agent-strip{display:grid;grid-template-columns:1fr 1fr;margin-top:1rem;overflow:hidden;box-shadow:none}.agent-strip article{display:flex;align-items:center;gap:.8rem;padding:.85rem 1rem}.agent-strip article+article{border-left:1px solid var(--border)}.agent-strip .side{color:var(--accent);font:.7rem var(--mono);text-transform:uppercase}.agent-strip div{display:grid;flex:1}.agent-strip small{color:var(--muted);font:.66rem var(--mono)}.lifecycle{padding:.25rem .45rem;border-radius:999px;background:var(--surface);color:var(--muted);font:.62rem var(--mono);text-transform:uppercase}.lifecycle.thinking,.lifecycle.waiting,.lifecycle.retrying{color:var(--warning)}.lifecycle.decided,.lifecycle.finished{color:var(--accent)}.lifecycle.error{color:var(--danger)}.manual-stack{display:grid;gap:1rem;margin-top:1rem}.manual{padding:1.4rem;box-shadow:none}.manual header,.manual footer{display:flex;justify-content:space-between;align-items:center;gap:1rem}.manual h2{margin:.3rem 0}.instruction{color:var(--muted);font-size:.82rem}.prompt-meta{display:flex;gap:.45rem;flex-wrap:wrap}.prompt-meta span,.context-diff span{padding:.28rem .45rem;border:1px solid var(--border);border-radius:999px;color:var(--muted);font:.62rem var(--mono)}.manual-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}.manual textarea{height:250px;resize:vertical;font:400 .72rem/1.55 var(--mono)}.manual footer>span{color:var(--muted);font:.72rem var(--mono)}.manual footer>span.valid{color:var(--accent)}.manual footer>span.error-text{color:var(--danger)}.manual footer div{display:flex;gap:.5rem}.team-inspector{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-top:2rem;padding:1rem;box-shadow:none}.team-inspector h2{margin:.3rem 0}.team-inspector p{color:var(--muted);font-size:.76rem}.team-inspector details{margin:0;padding:0}.team-inspector textarea{width:100%;min-height:220px;margin-top:.7rem;font:400 .65rem/1.5 var(--mono)}.audit-head{display:flex;align-items:center;justify-content:space-between;gap:2rem;margin-top:3rem;padding-top:2rem;border-top:1px solid var(--border)}.audit-head h2{margin:.4rem 0}.audit-stats,.audit-actions{display:flex;gap:1rem}.audit-stats span{display:grid;color:var(--muted);font:.7rem var(--mono)}.audit-stats strong{color:var(--text);font:700 1.5rem var(--display)}.button.danger{border-color:color-mix(in srgb,var(--danger) 45%,var(--border));background:transparent;color:var(--danger)}.decision-list{display:grid;gap:.6rem;margin-top:1rem}.decision{box-shadow:none}.decision>summary{display:grid;grid-template-columns:1fr 1fr 1.4fr auto;gap:1rem;align-items:center;padding:1rem;cursor:pointer}.decision>summary span{color:var(--muted);font:.7rem var(--mono)}.decision-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;padding:0 1rem 1rem;border-top:1px solid var(--border)}.decision-grid>div{padding-top:1rem}.decision-grid p{font-size:.8rem}.inspector{grid-column:1/-1;display:grid;gap:.55rem;padding-top:1rem}.inspector details{margin:0;padding:.7rem;border:1px solid var(--border);border-radius:.65rem}.inspector details summary{color:var(--text)}.inspector pre{max-height:360px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font:400 .68rem/1.5 var(--mono)}.context-diff{display:flex;flex-wrap:wrap;gap:.4rem}.context-diff span{color:var(--accent)}@media(max-width:850px){.live-head{align-items:start;flex-direction:column}.live-tools{width:100%;flex-wrap:wrap}.live-tools label{flex:1}.manual-grid{grid-template-columns:1fr}.team-inspector{grid-template-columns:1fr}.audit-head{align-items:stretch;flex-direction:column}.decision>summary{grid-template-columns:1fr 1fr}.decision-grid{grid-template-columns:1fr}}@media(max-width:560px){.live-tools label{min-width:100%}.agent-strip{grid-template-columns:1fr}.agent-strip article+article{border-left:0;border-top:1px solid var(--border)}.manual header,.manual footer{align-items:stretch;flex-direction:column}.manual footer div{display:grid;grid-template-columns:1fr 1fr}.audit-stats{justify-content:space-between}.audit-actions{display:grid}.decision>summary{grid-template-columns:1fr}}
</style>
