<script lang="ts">
  import { onMount } from 'svelte';
  import { api, getMatch } from '$lib/api';
  import type { ContextMetrics, MatchArchive, MatchSummary } from '$lib/types';

  let matches: MatchSummary[] = [];
  let archive: MatchArchive | null = null;
  let matchId = '';
  let decisionId = '';
  let promptProfile: 'standard-competitive' | 'benchmark-fair' = 'benchmark-fair';
  let contextProfile: 'pokemon-standard' | 'pokemon-compact' = 'pokemon-standard';
  let result: { available: boolean; detail?: string; prompt?: string; snapshot?: Record<string, unknown>; metrics?: ContextMetrics } | null = null;
  let busy = false;
  let error = '';

  onMount(() => {
    const controller = new AbortController();
    void api<MatchSummary[]>('/api/matches?limit=100', { signal: controller.signal }).then((value) => (matches = value)).catch((caught) => {
      if (!controller.signal.aborted) error = caught instanceof Error ? caught.message : String(caught);
    });
    return () => controller.abort();
  });

  async function chooseMatch() {
    archive = null; decisionId = ''; result = null; error = '';
    if (!matchId) return;
    try { archive = await getMatch(matchId); }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }

  async function render() {
    if (!matchId || !decisionId || busy) return;
    busy = true; error = ''; result = null;
    try {
      result = await api('/api/admin/prompts/render', {
        method: 'POST',
        body: JSON.stringify({ match_id: matchId, decision_id: Number(decisionId), prompt_profile: promptProfile, context_profile: contextProfile })
      });
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><span class="eyebrow">Local admin tool</span><h1>Prompt playground</h1><p>Re-render a persisted authoritative context under another versioned prompt or context profile. No provider call.</p></div><a class="button secondary" href="/admin">Control center →</a></div>

<section class="panel controls">
  <label>Historical match<select bind:value={matchId} on:change={chooseMatch}><option value="">Select a match…</option>{#each matches as match}<option value={match.id}>{match.config.name || match.id} · {match.status}</option>{/each}</select></label>
  <label>Decision<select bind:value={decisionId} disabled={!archive}><option value="">Select a decision…</option>{#each archive?.decisions || [] as record}<option value={record.id}>Turn {record.decision.turn} · {record.decision.side.toUpperCase()} · {record.decision.action}</option>{/each}</select></label>
  <label>Prompt profile<select bind:value={promptProfile}><option value="benchmark-fair">Benchmark Fair</option><option value="standard-competitive">Standard Competitive</option></select></label>
  <label>Context profile<select bind:value={contextProfile}><option value="pokemon-standard">Standard</option><option value="pokemon-compact">Compact</option></select></label>
  <button class="button" disabled={busy || !decisionId} on:click={render}>{busy ? 'Rendering…' : 'Render prompt'}</button>
</section>

{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if result}
  {#if !result.available}<div class="panel unavailable">{result.detail || 'Context snapshot unavailable for this historical decision.'}</div>
  {:else}<section class="output"><div class="metrics"><span><strong>{result.metrics?.rendered_characters}</strong> characters</span><span><strong>≈ {result.metrics?.estimated_tokens}</strong> tokens</span><span><strong>{result.metrics?.history_event_count}</strong> history events</span></div><label>Rendered prompt<textarea readonly value={result.prompt || ''}></textarea></label><details class="panel"><summary>Normalized context snapshot</summary><pre>{JSON.stringify(result.snapshot, null, 2)}</pre></details></section>{/if}
{/if}

<style>
  .page-head{display:flex;align-items:end;justify-content:space-between;gap:2rem}.page-head h1{margin:.3rem 0;font-size:clamp(2rem,6vw,4rem)}.page-head p{max-width:700px;color:var(--muted)}.controls{display:grid;grid-template-columns:1.4fr 1.2fr 1fr 1fr auto;align-items:end;gap:.75rem;margin-top:2rem;padding:1rem;box-shadow:none}.output{display:grid;gap:1rem;margin-top:1rem}.metrics{display:flex;gap:1rem;flex-wrap:wrap}.metrics span{display:grid;padding:.7rem 1rem;border:1px solid var(--border);border-radius:.7rem;color:var(--muted);font:.65rem var(--mono)}.metrics strong{color:var(--text);font-size:1rem}.output textarea{min-height:580px;font:400 .7rem/1.55 var(--mono)}.output details,.unavailable{padding:1rem;box-shadow:none}.output pre{max-height:500px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font:400 .68rem/1.5 var(--mono)}@media(max-width:1000px){.controls{grid-template-columns:1fr 1fr}.controls button{grid-column:1/-1}}@media(max-width:600px){.page-head{align-items:start;flex-direction:column}.controls{grid-template-columns:1fr}.controls button{grid-column:auto}}
</style>
