<script lang="ts">
  import { onMount } from 'svelte';
  import MatchCard from '$lib/MatchCard.svelte';
  import { api, wsBase } from '$lib/api';
  import type { AdminOverview, MatchSummary, ProviderStatus, TournamentSummary } from '$lib/types';

  let overview: AdminOverview | null = null;
  let matches: MatchSummary[] = [];
  let tournaments: TournamentSummary[] = [];
  let providers: ProviderStatus[] = [];
  let search = '';
  let status = '';
  let error = '';
  let socket: WebSocket | null = null;
  let refreshTimer: ReturnType<typeof setTimeout> | null = null;

  $: active = matches.filter((match) => ['starting', 'running', 'waiting', 'paused'].includes(match.status));
  $: queued = matches.filter((match) => match.status === 'queued');
  $: recent = matches.filter((match) => !['starting', 'running', 'waiting', 'paused', 'queued'].includes(match.status)).slice(0, 8);

  onMount(() => {
    void load();
    socket = new WebSocket(`${wsBase()}/api/admin/stream`);
    socket.onmessage = () => scheduleRefresh();
    socket.onerror = () => (error = 'Director live updates disconnected; manual refresh remains available.');
    return () => { socket?.close(); if (refreshTimer) clearTimeout(refreshTimer); };
  });

  function scheduleRefresh() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(() => { refreshTimer = null; void load(); }, 180);
  }

  async function load() {
    error = '';
    try {
      const query = new URLSearchParams({ limit: '100' });
      if (search.trim()) query.set('search', search.trim());
      if (status) query.set('status', status);
      [overview, matches, tournaments, providers] = await Promise.all([
        api<AdminOverview>('/api/admin/overview'),
        api<MatchSummary[]>(`/api/matches?${query}`),
        api<TournamentSummary[]>('/api/tournaments?limit=50'),
        api<{ providers: ProviderStatus[] }>('/api/providers').then((result) => result.providers)
      ]);
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }

  async function action(kind: 'pause' | 'resume' | 'cancel', match: MatchSummary) {
    if (kind === 'cancel' && !confirm(`Cancel ${match.config.name || match.id}? Recorded events remain available.`)) return;
    try { await api(`/api/matches/${match.id}/${kind}`, { method: 'POST' }); await load(); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
</script>

<div class="page-head director-head">
  <div><span class="eyebrow">Game director</span><h1>Control center</h1></div>
  <div class="head-actions"><a class="button secondary" href="/admin/prompts">Prompt playground</a><a class="button secondary" href="/tournaments/new">New tournament</a><a class="button" href="/new">New match</a></div>
</div>

{#if overview}
  <section class="system-strip" aria-label="System overview">
    <article><strong>{overview.active_matches}</strong><span>Active matches</span></article>
    <article><strong>{overview.queued_matches}</strong><span>Queued / {overview.concurrency_limit} slots</span></article>
    <article><strong>{overview.active_tournaments}</strong><span>Active tournaments</span></article>
    <article class:bad={overview.showdown.status !== 'healthy'}><strong>{overview.showdown.status}</strong><span>Showdown</span></article>
    <article><strong>{overview.backend.version}</strong><span>Backend</span></article>
  </section>
{/if}

<section class="filters panel">
  <label>Search<input bind:value={search} on:change={load} placeholder="Match ID, name, participant, model" /></label>
  <label>Status<select bind:value={status} on:change={load}><option value="">All statuses</option><option value="running">Running</option><option value="waiting">Waiting</option><option value="paused">Paused</option><option value="queued">Queued</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="interrupted">Interrupted</option></select></label>
  <button class="button secondary" on:click={load}>Refresh</button>
</section>
{#if error}<p class="error" role="alert">{error}</p>{/if}

<div class="director-grid">
  <div class="director-main">
    <section class="director-section"><header><div><span class="eyebrow">Live operations</span><h2>Active matches</h2></div><span>{active.length}</span></header>{#if active.length}<div class="card-stack">{#each active as match}<MatchCard {match} controls onAction={action} />{/each}</div>{:else}<p class="empty">No active matches.</p>{/if}</section>
    <section class="director-section"><header><div><span class="eyebrow">Scheduler</span><h2>Queued matches</h2></div><span>{queued.length}</span></header>{#if queued.length}<div class="card-stack">{#each queued as match}<MatchCard {match} controls onAction={action} />{/each}</div>{:else}<p class="empty">Queue is clear.</p>{/if}</section>
    <section class="director-section"><header><div><span class="eyebrow">History</span><h2>Recent matches</h2></div><a href="/matches">Full archive →</a></header><div class="card-stack">{#each recent as match}<MatchCard {match} />{/each}</div></section>
  </div>
  <aside>
    <section class="panel side-panel"><header><span class="eyebrow">Tournaments</span><a href="/tournaments">All →</a></header>{#if tournaments.length}{#each tournaments.slice(0, 8) as tournament}<a class="tournament-row" href={`/tournaments/${tournament.id}/control`}><span><strong>{tournament.name}</strong><small>{tournament.participant_count} participants · {tournament.format.replace('_', ' ')}</small></span><span class={`status-pill ${tournament.status}`}>{tournament.status}</span></a>{/each}{:else}<p class="empty">No tournaments.</p>{/if}</section>
    <section class="panel side-panel"><span class="eyebrow">Provider status</span><div class="provider-list">{#each providers as provider}<span><i class:ready={provider.configured}></i><strong>{provider.id}</strong><small>{provider.configured ? 'configured' : 'not configured'}</small></span>{/each}</div></section>
    <section class="panel side-panel warning"><span class="eyebrow">Exposure boundary</span><p>Admin and control routes are intended for a protected local network. Spectator and OBS routes are read-only.</p></section>
  </aside>
</div>

<style>
  .director-head{align-items:center}.head-actions{display:flex;gap:.6rem}.system-strip{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;margin-bottom:1rem;overflow:hidden;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--border)}.system-strip article{display:grid;padding:1rem;background:var(--panel)}.system-strip strong{font-size:1.45rem;text-transform:capitalize}.system-strip span{color:var(--muted);font:.62rem var(--mono)}.system-strip .bad strong{color:var(--danger)}.filters{display:grid;grid-template-columns:2fr 1fr auto;align-items:end;gap:.7rem;padding:1rem;box-shadow:none}.director-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(270px,.8fr);gap:1rem;margin-top:1rem}.director-main,.card-stack,aside{display:grid;align-content:start;gap:1rem}.director-section{padding-block:1rem}.director-section>header,.side-panel>header{display:flex;align-items:end;justify-content:space-between;margin-bottom:.8rem}.director-section h2{margin:.25rem 0}.director-section>header>span{color:var(--muted);font:1rem var(--mono)}.director-section>header>a,.side-panel header a{color:var(--accent);font-size:.72rem}.side-panel{padding:1rem;box-shadow:none}.tournament-row{display:flex;align-items:center;justify-content:space-between;gap:.5rem;padding:.8rem 0;border-bottom:1px solid var(--border)}.tournament-row>span:first-child{display:grid}.tournament-row small{color:var(--muted);font:.6rem var(--mono);text-transform:capitalize}.provider-list{display:grid;margin-top:.8rem}.provider-list>span{display:grid;grid-template-columns:10px 1fr auto;align-items:center;gap:.5rem;padding:.55rem 0;border-bottom:1px solid var(--border)}.provider-list i{width:7px;aspect-ratio:1;border-radius:50%;background:var(--muted)}.provider-list i.ready{background:var(--accent)}.provider-list small{color:var(--muted);font:.58rem var(--mono)}.warning p,.empty{color:var(--muted);font-size:.78rem;line-height:1.6}@media(max-width:900px){.system-strip{grid-template-columns:repeat(3,1fr)}.director-grid{grid-template-columns:1fr}}@media(max-width:600px){.director-head{align-items:stretch;flex-direction:column}.head-actions{display:grid;grid-template-columns:1fr 1fr}.system-strip{grid-template-columns:1fr 1fr}.filters{grid-template-columns:1fr}.filters button{width:100%}}
</style>
