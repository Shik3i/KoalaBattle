<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { TournamentSummary } from '$lib/types';
  let tournaments: TournamentSummary[] = [];
  let loading = true;
  let error = '';
  onMount(async () => {
    try { tournaments = await api<TournamentSummary[]>('/api/tournaments'); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
    finally { loading = false; }
  });
</script>

<div class="page-head"><div><span class="eyebrow">Competition operations</span><h1>Tournaments</h1></div><a class="button" href="/tournaments/new"><i class="ph ph-plus" aria-hidden="true"></i>Create tournament</a></div>
{#if loading}<p class="lede">Loading tournaments…</p>{:else if error}<p class="error">{error}</p>{:else if !tournaments.length}<section class="empty panel"><h2>No tournaments yet</h2><p>Create a free Random, Fake, Manual, or hybrid tournament.</p><a class="button" href="/tournaments/new">Create first tournament</a></section>{:else}
  <div class="tournament-list">
    {#each tournaments as tournament}
      <a class="panel" href={`/tournaments/${tournament.id}/control`}>
        <div><span class="eyebrow">{tournament.format.replace('_', ' ')}</span><h2>{tournament.name}</h2></div>
        <div class="progress"><strong>{tournament.completed_series}/{tournament.series_count}</strong><span>series complete</span></div>
        <div class="progress"><strong>{tournament.participant_count}</strong><span>participants</span></div>
        <span class={`status-pill ${tournament.status}`}>{tournament.status}</span><i class="ph ph-caret-right row-arrow" aria-hidden="true"></i>
      </a>
    {/each}
  </div>
{/if}

<style>
  .tournament-list>a{transition:transform .2s cubic-bezier(.2,.8,.2,1),border-color .2s ease,box-shadow .2s ease}.tournament-list>a:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 35%,var(--border));box-shadow:var(--shadow-sm)}.row-arrow{color:var(--muted);transition:transform .2s ease}.tournament-list>a:hover .row-arrow{color:var(--accent);transform:translateX(3px)}
  .tournament-list{display:grid;gap:.7rem}.tournament-list>a{display:grid;grid-template-columns:1fr auto auto auto;align-items:center;gap:2rem;padding:1.2rem 1.4rem;box-shadow:none}.tournament-list h2{margin:.25rem 0 0}.progress{display:grid;text-align:right}.progress strong{font-size:1.1rem}.progress span{color:var(--muted);font:0.72rem var(--mono)}.empty{padding:4rem;text-align:center}.empty p{color:var(--muted)}@media(max-width:760px){.page-head{align-items:stretch;flex-direction:column}.tournament-list>a{grid-template-columns:1fr 1fr;gap:1rem}.tournament-list>a>div:first-child{grid-column:1/-1}.progress{text-align:left}}
  @media(min-width:761px){.tournament-list>a{grid-template-columns:1fr auto auto auto auto}}@media(max-width:760px){.row-arrow{display:none}}
</style>
