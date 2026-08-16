<script lang="ts">
  import { onMount } from 'svelte';
  import MatchCard from '$lib/MatchCard.svelte';
  import { api } from '$lib/api';
  import type { MatchSummary } from '$lib/types';
  let matches: MatchSummary[] = [];
  let loading = true;
  let error = '';
  let search = '';
  let status = '';
  async function load() {
    loading = true;
    const query = new URLSearchParams({ limit: '100' });
    if (search.trim()) query.set('search', search.trim());
    if (status) query.set('status', status);
    try { matches = await api<MatchSummary[]>(`/api/matches?${query}`); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
    finally { loading = false; }
  }
  onMount(load);
</script>
<div class="page-head"><div><span class="eyebrow">Persistent archive</span><h1>Matches</h1></div><div class="actions"><a class="button secondary" href="/admin"><i class="ph ph-squares-four" aria-hidden="true"></i>Director</a><a class="button" href="/new"><i class="ph ph-plus" aria-hidden="true"></i>New battle</a></div></div>
<section class="filters panel"><label>Search<input bind:value={search} on:change={load} placeholder="ID, name, participant, model" /></label><label>Status<select bind:value={status} on:change={load}><option value="">All</option><option value="queued">Queued</option><option value="running">Running</option><option value="waiting">Waiting</option><option value="paused">Paused</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="interrupted">Interrupted</option></select></label><button class="button secondary" on:click={load}><i class="ph ph-funnel" aria-hidden="true"></i>Filter</button></section>
{#if loading}<p class="lede">Loading archive…</p>{:else if error}<p class="error">{error}</p>{:else if !matches.length}<section class="empty panel"><h2>No matching matches</h2><p>Create a battle or change the archive filter.</p><a class="button" href="/new">Create battle</a></section>{:else}<div class="match-list">{#each matches as match}<MatchCard {match} />{/each}</div>{/if}
<style>.filters{display:grid;grid-template-columns:2fr 1fr auto;align-items:end;gap:.7rem;padding:1rem;box-shadow:none}.match-list{display:grid;gap:.7rem;margin-top:1rem}.empty{margin-top:1rem;padding:4rem;text-align:center}.empty p{color:var(--muted)}@media(max-width:620px){.page-head{align-items:stretch;flex-direction:column}.filters{grid-template-columns:1fr}}</style>
