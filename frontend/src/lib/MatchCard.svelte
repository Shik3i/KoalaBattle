<script lang="ts">
  import type { MatchSummary } from '$lib/types';

  export let match: MatchSummary;
  export let controls = false;
  export let onAction: (action: 'pause' | 'resume' | 'cancel', match: MatchSummary) => void = () => {};
  let copied = false;

  $: players = match.config.players;
  $: title = match.config.name || `${players[0].display_name} vs ${players[1].display_name}`;
  $: statusLabel = match.status === 'waiting'
    ? players.some((player) => player.agent_type === 'manual')
      ? 'Waiting for manual response'
      : 'Waiting for provider'
    : match.status === 'running'
      ? 'Running'
      : match.status;

  async function copyOverlay() {
    await navigator.clipboard.writeText(`${location.origin}/overlay/${match.id}`);
    copied = true;
    setTimeout(() => (copied = false), 1200);
  }
</script>

<article class="match-card panel">
  <header>
    <div>
      <span class="eyebrow">{match.tournament_id ? 'Tournament match' : 'Standalone match'}</span>
      <h3>{title}</h3>
    </div>
    <span class={`status-pill ${match.status}`}>{statusLabel}</span>
  </header>
  <div class="summary">
    <span><strong>Turn {match.turns}</strong>{match.config.format}</span>
    <span><strong>{players[0].display_name}</strong>{players[0].provider || players[0].agent_type}</span>
    <span><strong>{players[1].display_name}</strong>{players[1].provider || players[1].agent_type}</span>
    <span><strong>${match.estimated_cost.toFixed(4)}</strong>estimated</span>
  </div>
  {#if match.error}<p class="failure">{match.error}</p>{/if}
  <footer>
    <a href={`/matches/${match.id}/control`}>Control</a>
    <a href={`/watch/${match.id}`}>Watch</a>
    <button on:click={copyOverlay}>{copied ? 'Copied' : 'Copy OBS URL'}</button>
    {#if match.status === 'completed'}<a href={`/replay/${match.id}`}>Replay</a>{/if}
    {#if controls && ['running', 'waiting'].includes(match.status)}
      <button on:click={() => onAction('pause', match)}>Pause</button>
    {:else if controls && match.status === 'paused'}
      <button on:click={() => onAction('resume', match)}>Resume</button>
    {/if}
    {#if controls && !['completed', 'failed', 'cancelled', 'interrupted'].includes(match.status)}
      <button class="danger" on:click={() => onAction('cancel', match)}>Cancel</button>
    {/if}
  </footer>
</article>

<style>
  .match-card{padding:1rem;box-shadow:none}.match-card header,.match-card footer{display:flex;align-items:center;justify-content:space-between;gap:.7rem}.match-card h3{margin:.25rem 0 0;font-size:1rem}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin:1rem 0;overflow:hidden;border:1px solid var(--border);border-radius:.6rem;background:var(--border)}.summary span{display:grid;padding:.7rem;background:var(--panel-strong);color:var(--muted);font:.62rem var(--mono)}.summary strong{overflow:hidden;color:var(--text);font:700 .78rem var(--display);text-overflow:ellipsis;white-space:nowrap}.match-card footer{justify-content:flex-end;flex-wrap:wrap}.match-card footer a,.match-card footer button{min-height:38px;padding:.45rem .65rem;border:1px solid var(--border);border-radius:.55rem;background:var(--panel-strong);color:var(--text);font-size:.72rem;cursor:pointer}.match-card footer a:first-child{border-color:var(--accent);color:var(--accent)}.match-card footer .danger,.failure{color:var(--danger)}.failure{font-size:.75rem}@media(max-width:680px){.summary{grid-template-columns:1fr 1fr}.match-card header{align-items:flex-start}.match-card footer{display:grid;grid-template-columns:1fr 1fr}.match-card footer>*{text-align:center}}
</style>
