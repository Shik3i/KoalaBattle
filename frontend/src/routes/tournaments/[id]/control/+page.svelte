<script lang="ts">
  import { onMount } from 'svelte';
  import MatchCard from '$lib/MatchCard.svelte';
  import { api, wsUrl } from '$lib/api';
  import { connectLiveSocket } from '$lib/presentation/live-socket';
  import type { MatchSummary, TournamentArchive, TournamentParticipant } from '$lib/types';

  export let data: { id: string };
  let tournament: TournamentArchive | null = null;
  let matches: MatchSummary[] = [];
  let error = '';
  let copied = false;
  let stopSocket: (() => void) | null = null;

  $: participantMap = new Map((tournament?.participants || []).map((participant) => [participant.id, participant]));
  $: rounds = tournament ? [...new Set(tournament.series.map((series) => series.round_number))] : [];

  onMount(() => {
    void load();
    stopSocket = connectLiveSocket({
      url: wsUrl(`/api/tournaments/${data.id}/stream`),
      onConnected: load,
      onStatus: (status) => (error = status === 'connected' ? '' : 'Tournament live updates reconnecting…'),
      onMessage: (raw) => {
        const message = JSON.parse(raw) as { kind: string; tournament?: TournamentArchive };
        if (message.kind === 'tournament_snapshot' && message.tournament) { tournament = message.tournament; void loadMatches(); }
      }
    });
    return () => stopSocket?.();
  });

  async function load() {
    try { tournament = await api<TournamentArchive>(`/api/tournaments/${data.id}`); await loadMatches(); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  async function loadMatches() { matches = await api<MatchSummary[]>(`/api/matches?tournament_id=${data.id}&limit=250`).catch(() => matches); }
  function participant(id: string | null): TournamentParticipant | null { return id ? participantMap.get(id) || null : null; }
  async function tournamentAction(action: 'start' | 'pause' | 'resume' | 'cancel') {
    if (action === 'cancel' && !confirm('Cancel this tournament and all queued/active matches?')) return;
    try { await api(`/api/tournaments/${data.id}/${action}`, { method: 'POST' }); await load(); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  async function matchAction(action: 'pause' | 'resume' | 'cancel', match: MatchSummary) {
    if (action === 'cancel' && !confirm(`Cancel ${match.config.name || match.id}?`)) return;
    try { await api(`/api/matches/${match.id}/${action}`, { method: 'POST' }); await loadMatches(); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  async function startSeries(seriesId: string) {
    try { await api(`/api/tournament-series/${seriesId}/start`, { method: 'POST' }); await load(); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  async function copyOverlay() { await navigator.clipboard.writeText(`${location.origin}/overlay/tournament/${data.id}`); copied = true; setTimeout(() => (copied = false), 1200); }
</script>

<div class="page-head tournament-head">
  <div><span class="eyebrow">Tournament director</span><h1>{tournament?.name || 'Loading tournament…'}</h1></div>
  {#if tournament}<div class="head-actions"><span class={`status-pill ${tournament.status}`}>{tournament.status}</span><a class="button secondary" href={`/overlay/tournament/${tournament.id}`}>OBS preview</a><button class="button secondary" on:click={copyOverlay}>{copied ? 'Copied' : 'Copy OBS URL'}</button>{#if ['draft','ready'].includes(tournament.status)}<button class="button" on:click={() => tournamentAction('start')}>Start</button>{:else if tournament.status === 'running'}<button class="button secondary" on:click={() => tournamentAction('pause')}>Pause scheduling</button>{:else if tournament.status === 'paused'}<button class="button" on:click={() => tournamentAction('resume')}>Resume scheduling</button>{/if}{#if !['completed','cancelled','failed'].includes(tournament.status)}<button class="button danger" on:click={() => tournamentAction('cancel')}>Cancel</button>{/if}</div>{/if}
</div>
{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if tournament}
  <section class="stats-strip">
    <span><strong>{tournament.participants.length}</strong>participants</span><span><strong>BO{tournament.best_of}</strong>series</span><span><strong>{tournament.max_concurrent_matches}</strong>concurrent</span><span><strong>{tournament.statistics.matches_played}</strong>matches played</span><span><strong>${tournament.statistics.estimated_cost.toFixed(4)}</strong>estimated cost</span><span><strong>{tournament.statistics.average_decision_latency_ms?.toFixed(0) || '—'} ms</strong>avg decision</span>
  </section>

  {#if tournament.format === 'single_elimination'}
    <section class="section-head"><div><span class="eyebrow">Persistent bracket</span><h2>Single Elimination</h2></div><span>Round {tournament.current_round}</span></section>
    <div class="bracket">
      {#each rounds as round}
        <section><header>Round {round}</header>{#each tournament.series.filter((series) => series.round_number === round) as series}<article class:complete={series.status === 'completed'}><div><span>#{participant(series.participant_a_id)?.seed || '—'}</span><strong>{participant(series.participant_a_id)?.display_name || 'TBD'}</strong><b>{series.wins_a}</b></div><div><span>#{participant(series.participant_b_id)?.seed || '—'}</span><strong>{participant(series.participant_b_id)?.display_name || 'TBD'}</strong><b>{series.wins_b}</b></div><footer><small>{series.status} · {series.draws} draws</small>{#if tournament.manual_scheduling && series.status === 'ready'}<button on:click={() => startSeries(series.id)}>Start series</button>{/if}</footer></article>{/each}</section>
      {/each}
    </div>
  {:else}
    <section class="section-head"><div><span class="eyebrow">Live standings</span><h2>Round Robin</h2></div><span>Round {tournament.current_round}</span></section>
    <div class="standings panel"><header><span>Seed / participant</span><span>Played</span><span>W</span><span>L</span><span>D</span><span>Points</span></header>{#each tournament.standings as standing}<div><strong>#{standing.seed} · {standing.display_name}</strong><span>{standing.played}</span><span>{standing.wins}</span><span>{standing.losses}</span><span>{standing.draws}</span><b>{standing.points}</b></div>{/each}</div>
    {#if tournament.manual_scheduling}<div class="manual-series">{#each tournament.series.filter((series) => series.status === 'ready') as series}<button class="button secondary" on:click={() => startSeries(series.id)}>Start {participant(series.participant_a_id)?.display_name} vs {participant(series.participant_b_id)?.display_name}</button>{/each}</div>{/if}
  {/if}

  <section class="section-head"><div><span class="eyebrow">Match operations</span><h2>Active and queued</h2></div><span>{matches.filter((match) => !['completed','failed','cancelled','interrupted'].includes(match.status)).length}</span></section>
  <div class="match-grid">{#each matches.filter((match) => !['completed','failed','cancelled','interrupted'].includes(match.status)) as match}<MatchCard {match} controls onAction={matchAction} />{/each}</div>
  <section class="section-head"><div><span class="eyebrow">Tournament history</span><h2>Completed matches</h2></div><span>{matches.filter((match) => ['completed','failed','cancelled','interrupted'].includes(match.status)).length}</span></section>
  <div class="match-grid">{#each matches.filter((match) => ['completed','failed','cancelled','interrupted'].includes(match.status)) as match}<MatchCard {match} />{/each}</div>
{/if}

<style>
  .tournament-head{align-items:center}.head-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:.5rem}.button.danger{border-color:var(--danger);background:transparent;color:var(--danger)}.stats-strip{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;overflow:hidden;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--border)}.stats-strip span{display:grid;padding:1rem;background:var(--panel);color:var(--muted);font:0.72rem var(--mono)}.stats-strip strong{color:var(--text);font:700 1.05rem var(--display)}.section-head{display:flex;align-items:end;justify-content:space-between;margin:3rem 0 1rem}.section-head h2{margin:.25rem 0}.section-head>span{color:var(--muted);font:.75rem var(--mono)}.bracket{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(250px,1fr);align-items:center;gap:1rem;overflow-x:auto;padding-bottom:1rem}.bracket>section{display:grid;align-content:center;gap:.7rem}.bracket>section>header{color:var(--muted);font:0.72rem var(--mono);text-transform:uppercase}.bracket article{overflow:hidden;border:1px solid var(--border);border-radius:.7rem;background:var(--panel)}.bracket article.complete{border-color:color-mix(in srgb,var(--accent) 35%,var(--border))}.bracket article>div{display:grid;grid-template-columns:25px 1fr auto;gap:.5rem;padding:.65rem .8rem;border-bottom:1px solid var(--border)}.bracket article>div span,.bracket footer small{color:var(--muted);font:0.72rem var(--mono)}.bracket footer{display:flex;align-items:center;justify-content:space-between;padding:.45rem .8rem}.bracket footer button{border:0;background:transparent;color:var(--accent);font-size:0.72rem;cursor:pointer}.standings{overflow:hidden;box-shadow:none}.standings header,.standings>div{display:grid;grid-template-columns:2fr repeat(5,1fr);gap:.5rem;padding:.75rem 1rem;border-bottom:1px solid var(--border)}.standings header{color:var(--muted);font:0.72rem var(--mono)}.standings>div span,.standings>div b{text-align:center}.standings>div b{color:var(--accent)}.manual-series,.match-grid{display:grid;gap:.7rem}.manual-series{grid-template-columns:repeat(2,1fr);margin-top:1rem}.match-grid:empty:after{content:'No matches in this section.';color:var(--muted);font-size:.8rem}@media(max-width:900px){.tournament-head{align-items:stretch;flex-direction:column}.head-actions{justify-content:flex-start}.stats-strip{grid-template-columns:repeat(3,1fr)}}@media(max-width:620px){.stats-strip{grid-template-columns:1fr 1fr}.head-actions{display:grid;grid-template-columns:1fr 1fr}.head-actions .status-pill{grid-column:1/-1}.standings{overflow-x:auto}.standings header,.standings>div{min-width:620px}.manual-series{grid-template-columns:1fr}}
</style>
