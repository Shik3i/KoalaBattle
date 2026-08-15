<script lang="ts">
  import { onMount } from 'svelte';
  import { api, wsBase } from '$lib/api';
  import type { TournamentArchive } from '$lib/types';
  export let data: { id: string };
  let tournament: TournamentArchive | null = null;
  let error = '';
  let socket: WebSocket | null = null;
  $: participants = new Map((tournament?.participants || []).map((item) => [item.id, item]));
  $: live = tournament?.series.filter((series) => ['running', 'queued'].includes(series.status)).slice(0, 3) || [];
  $: recent = [...(tournament?.series || [])].reverse().find((series) => series.status === 'completed');
  onMount(() => { void connect(); return () => socket?.close(); });
  async function connect() {
    try {
      tournament = await api<TournamentArchive>(`/api/tournaments/${data.id}/presentation`);
      socket = new WebSocket(`${wsBase()}/api/tournaments/${data.id}/stream`);
      socket.onmessage = ({ data: raw }) => {
        const message = JSON.parse(raw) as { kind: string; tournament?: TournamentArchive };
        if (message.tournament) tournament = message.tournament;
      };
      socket.onerror = () => (error = 'Reconnecting…');
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  const name = (id: string | null) => id ? participants.get(id)?.display_name || 'TBD' : 'TBD';
</script>

<svelte:head><title>{tournament?.name || 'Tournament'} · KoalaBattle OBS</title></svelte:head>
{#if tournament}
  <div class="tournament-overlay">
    <header><div class="brand"><span>KB</span><div><small>KOALABATTLE TOURNAMENT</small><h1>{tournament.name}</h1></div></div><div class="stage"><small>{tournament.format.replace('_', ' ')}</small><strong>ROUND {tournament.current_round || 1}</strong></div><span class={`status ${tournament.status}`}>{tournament.status}</span></header>
    <div class="overlay-content">
      <section class="bracket"><div class="section-label">Bracket / schedule</div>{#each tournament.series.slice(-8) as series}<article class:live={['running','queued'].includes(series.status)} class:complete={series.status === 'completed'}><div><span>{name(series.participant_a_id)}</span><strong>{series.wins_a}</strong></div><div><span>{name(series.participant_b_id)}</span><strong>{series.wins_b}</strong></div><footer>R{series.round_number} · BO{series.best_of} · {series.status}</footer></article>{/each}</section>
      <section class="live-board"><div class="section-label">Live series</div>{#if live.length}{#each live as series}<article><small>ROUND {series.round_number}</small><h2>{name(series.participant_a_id)} <i>vs</i> {name(series.participant_b_id)}</h2><div><strong>{series.wins_a}</strong><span>BEST OF {series.best_of}</span><strong>{series.wins_b}</strong></div></article>{/each}{:else}<article class="waiting"><small>NEXT UPDATE</small><h2>{tournament.status === 'completed' ? 'Tournament complete' : 'Waiting for the next series'}</h2></article>{/if}{#if recent}<aside><span>Latest result</span><strong>{name(recent.winner_participant_id)} wins series {recent.wins_a}–{recent.wins_b}</strong></aside>{/if}</section>
    </div>
    <footer><span>{tournament.participants.length} PARTICIPANTS</span><span>{tournament.statistics.matches_played} MATCHES PLAYED</span><span>{tournament.statistics.series_played} SERIES COMPLETE</span><span>KOALABATTLE 0.4</span></footer>
  </div>
{/if}
{#if error}<div class="connection">{error}</div>{/if}

<style>
  :global(body){background:transparent}.tournament-overlay{--accent:#7ee09a;display:grid;grid-template-rows:auto 1fr auto;width:100vw;height:100vh;padding:clamp(18px,2.4vw,42px);overflow:hidden;background:radial-gradient(circle at 10% 0,rgba(126,224,154,.13),transparent 34%),linear-gradient(145deg,#07100a,#0d1710 55%,#080d09);color:#f1f7f3;font-family:var(--display)}header{display:flex;align-items:center;justify-content:space-between;padding-bottom:clamp(14px,2vw,28px);border-bottom:1px solid rgba(255,255,255,.15)}.brand{display:flex;align-items:center;gap:1rem}.brand>span{display:grid;place-items:center;width:48px;aspect-ratio:1;border-radius:12px;background:var(--accent);color:#082010;font:800 .8rem var(--mono)}small,.section-label,footer,.status{font-family:var(--mono);letter-spacing:.12em;text-transform:uppercase}.brand small,.stage small,.section-label{color:#829088;font-size:clamp(.48rem,.65vw,.68rem)}h1{margin:.2rem 0 0;font-size:clamp(1.4rem,2.4vw,2.8rem)}.stage{display:grid;text-align:center}.stage strong{font-size:clamp(1rem,1.7vw,1.8rem)}.status{padding:.45rem .7rem;border:1px solid currentColor;border-radius:999px;color:var(--accent);font-size:.62rem}.status.failed,.status.cancelled{color:#ff8b87}.overlay-content{display:grid;grid-template-columns:1.4fr 1fr;gap:clamp(18px,2vw,34px);min-height:0;padding:clamp(18px,2vw,34px) 0}.bracket{display:grid;grid-template-columns:repeat(4,1fr);align-content:center;gap:.65rem}.section-label{grid-column:1/-1;margin-bottom:.3rem}.bracket article{overflow:hidden;border:1px solid rgba(255,255,255,.14);border-radius:10px;background:rgba(255,255,255,.035)}.bracket article.live{border-color:var(--accent);box-shadow:0 0 28px rgba(126,224,154,.1)}.bracket article.complete{opacity:.72}.bracket article>div{display:flex;justify-content:space-between;gap:.5rem;padding:.55rem .7rem;border-bottom:1px solid rgba(255,255,255,.1);font-size:clamp(.56rem,.8vw,.8rem)}.bracket article footer{width:100%;margin:0;padding:.35rem .7rem;color:#829088;font-size:.42rem}.live-board{display:grid;align-content:center;gap:.7rem}.live-board article{padding:clamp(14px,1.5vw,24px);border:1px solid rgba(255,255,255,.14);border-radius:14px;background:rgba(255,255,255,.045)}.live-board article small{color:var(--accent);font-size:.55rem}.live-board h2{margin:.5rem 0;font-size:clamp(.9rem,1.4vw,1.5rem)}.live-board h2 i{color:#829088;font-weight:400}.live-board article>div{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;text-align:center}.live-board article>div strong{font-size:clamp(1.8rem,4vw,4rem)}.live-board article>div span{color:#829088;font:.55rem var(--mono)}.live-board aside{display:grid;padding:1rem;border-left:3px solid var(--accent);background:rgba(126,224,154,.06)}.live-board aside span{color:#829088;font:.55rem var(--mono);text-transform:uppercase}.tournament-overlay>footer{display:flex;justify-content:space-between;width:100%;margin:0;padding-top:1rem;border-top:1px solid rgba(255,255,255,.15);color:#829088;font-size:clamp(.42rem,.55vw,.58rem)}.connection{position:fixed;right:1rem;bottom:1rem;padding:.5rem .7rem;border-radius:999px;background:#151b16;color:#ffd26a;font:.6rem var(--mono)}@media(max-aspect-ratio:3/4){.overlay-content{grid-template-columns:1fr;grid-template-rows:1.1fr .9fr}.bracket{grid-template-columns:repeat(2,1fr)}header{align-items:flex-start}.stage{display:none}.tournament-overlay{padding:24px}.live-board{grid-template-columns:1fr 1fr}.live-board .section-label,.live-board aside{grid-column:1/-1}}
</style>
