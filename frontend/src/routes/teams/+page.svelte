<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { formatLabel } from '$lib/format-label';
  import { hydrateStoredProviderSettings } from '$lib/provider-settings';
  import { deepSeekModelLabel, knownProviderModels } from '$lib/provider-models';
  import type { ProviderKind, ProviderStatus, TeamBuildAudit, TeamSnapshot, TeamValidationResult } from '$lib/types';

  let teams: TeamSnapshot[] = [];
  let providers: ProviderStatus[] = [];
  let name = 'My Gen 9 OU Team';
  let teamText = '';
  let validation: TeamValidationResult | null = null;
  let buildAudit: TeamBuildAudit | null = null;
  let provider: ProviderKind = 'fake';
  let model = 'fake-battle-v1';
  let busy = false;
  let error = '';

  function chooseProvider(value: ProviderKind) {
    provider = value;
    model = providers.find((item) => item.id === value)?.default_model || '';
  }

  onMount(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        await hydrateStoredProviderSettings();
        const [stored, status] = await Promise.all([
          api<TeamSnapshot[]>('/api/teams', { signal: controller.signal }),
          api<{ providers: ProviderStatus[] }>('/api/providers', { signal: controller.signal })
        ]);
        teams = stored; providers = status.providers;
        const configured = providers.find((item) => item.configured);
        if (configured) { provider = configured.id; model = configured.default_model; }
      } catch (caught) {
        if (!controller.signal.aborted) error = caught instanceof Error ? caught.message : String(caught);
      }
    })();
    return () => controller.abort();
  });

  async function validateAndSave() {
    if (busy) return;
    busy = true; error = ''; validation = null;
    try {
      const result = await api<{ validation: TeamValidationResult; snapshot: TeamSnapshot | null }>('/api/teams/validate', {
        method: 'POST', body: JSON.stringify({ name, format: 'gen9ou', team_text: teamText, source: 'imported', save: true })
      });
      validation = result.validation;
      if (result.snapshot) teams = [result.snapshot, ...teams.filter((item) => item.id !== result.snapshot?.id)];
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
    finally { busy = false; }
  }

  async function generate() {
    if (busy) return;
    busy = true; error = ''; buildAudit = null;
    try {
      const result = await api<{ audit: TeamBuildAudit; snapshot: TeamSnapshot | null }>('/api/teams/build', {
        method: 'POST', body: JSON.stringify({ name, participant: name, format: 'gen9ou', provider, model, max_repair_attempts: 2 })
      });
      buildAudit = result.audit;
      if (result.snapshot) {
        teams = [result.snapshot, ...teams.filter((item) => item.id !== result.snapshot?.id)];
        teamText = result.snapshot.normalized_export;
      }
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
    finally { busy = false; }
  }

  async function copy(team: TeamSnapshot) {
    await navigator.clipboard.writeText(team.normalized_export);
  }
</script>

<div class="page-head"><div><span class="eyebrow">Private local team library</span><h1>Gen 9 OU teams</h1><p>Every imported or generated team is parsed, normalized and legality-checked by the pinned Pokémon Showdown runtime.</p></div><a class="button secondary" href="/new"><i class="ph ph-sword" aria-hidden="true"></i>Use in battle</a></div>

{#if error}<p class="error" role="alert">{error}</p>{/if}

<section class="team-workspace">
  <article class="panel editor">
    <span class="eyebrow">Import and validate</span>
    <label>Snapshot name<input bind:value={name} maxlength="120" /></label>
    <label>Pokémon Showdown export<textarea bind:value={teamText} maxlength="50000" spellcheck="false" placeholder="Great Tusk @ Leftovers&#10;Ability: Protosynthesis&#10;..."></textarea></label>
    <button class="button" disabled={busy || !teamText.trim()} on:click={validateAndSave}><i class="ph ph-shield-check" aria-hidden="true"></i>{busy ? 'Working…' : 'Validate and save immutable snapshot'}</button>
    {#if validation}
      <div class:valid={validation.valid} class="result"><strong>{validation.valid ? '✓ Legal Gen 9 OU team' : 'Invalid team'}</strong>{#each validation.errors as item}<p>{item}</p>{/each}</div>
    {/if}
  </article>

  <article class="panel builder">
    <span class="eyebrow">AI team builder</span><h2>Generate, validate, repair</h2>
    <p>No provider is called until this button is selected. Fake is deterministic and costs nothing.</p>
  <label>Provider<select value={provider} on:change={(event) => chooseProvider(event.currentTarget.value as ProviderKind)}>{#each providers.filter((item) => item.configured) as item}<option value={item.id}>{item.label || item.id} · ready</option>{/each}{#if !providers.some((item) => item.configured)}<option disabled>No configured provider — use Settings</option>{/if}</select></label>
    <label>Model{#if knownProviderModels(provider, providers).length}<select bind:value={model}>{#each knownProviderModels(provider, providers) as item}<option value={item}>{provider === 'deepseek' ? deepSeekModelLabel(item) : item}</option>{/each}</select>{:else}<input bind:value={model} maxlength="200" />{/if}</label>
    <button class="button secondary" disabled={busy || !model.trim()} on:click={generate}><i class="ph ph-sparkle" aria-hidden="true"></i>{busy ? 'Working…' : 'Generate team explicitly'}</button>
    {#if buildAudit}<div class:valid={buildAudit.success} class="result"><strong>{buildAudit.success ? '✓ Generated team is legal' : 'Generation failed'}</strong><p>{buildAudit.repair_attempts} repair attempt(s) · {buildAudit.latency_ms} ms</p>{#each buildAudit.validation_errors.flat() as item}<p>{item}</p>{/each}</div>{/if}
  </article>
</section>

<section class="library"><div class="section-head"><div><span class="eyebrow">Immutable snapshots</span><h2>Saved teams</h2></div><span>{teams.length} local</span></div>
  {#if teams.length === 0}<div class="empty panel">No validated custom teams yet.</div>{/if}
  <div class="cards">{#each teams as team}<details class="panel team"><summary><div><strong>{team.name}</strong><small>{team.source} · {formatLabel(team.format)} · {new Date(team.created_at).toLocaleString()}</small></div><span>✓ Legal</span></summary><div class="team-body"><p class="team-body-label">Normalized Showdown export{#if team.generation_audit} · AI-generated{/if}</p><textarea readonly aria-label={`${team.name} normalized Showdown export`} value={team.normalized_export}></textarea><button class="button secondary" on:click={() => copy(team)}><i class="ph ph-copy" aria-hidden="true"></i>Copy Showdown team</button></div></details>{/each}</div>
</section>

<style>
  .page-head,.section-head{display:flex;justify-content:space-between;align-items:end;gap:2rem}.page-head h1{margin:.3rem 0}.page-head p,.builder p{color:var(--muted);max-width:680px}.team-workspace{display:grid;grid-template-columns:1.4fr .8fr;gap:1rem;margin-top:2rem}.editor,.builder{padding:1.3rem;display:grid;gap:1rem;align-content:start}.editor textarea{min-height:390px;font:400 .72rem/1.5 var(--mono)}.builder h2{margin:.2rem 0}.result{padding:.8rem;border:1px solid var(--danger);border-radius:10px;color:var(--danger)}.result.valid{border-color:var(--accent);color:var(--accent)}.result p{margin:.35rem 0;font:0.72rem var(--mono)}.library{margin-top:3rem}.cards{display:grid;gap:.7rem;margin-top:1rem}.team{box-shadow:none}.team summary{display:flex;justify-content:space-between;align-items:center;padding:1rem;cursor:pointer}.team summary div{display:grid}.team small{color:var(--muted);font:0.72rem var(--mono)}.team summary>span{color:var(--accent);font:0.72rem var(--mono)}.team-body{padding:0 1rem 1rem;border-top:1px solid var(--border)}.team-body textarea{width:100%;min-height:300px;font:400 0.72rem/1.5 var(--mono)}.team-body-label{margin:.8rem 0 .5rem;color:var(--muted);font:0.72rem var(--mono);letter-spacing:.06em;text-transform:uppercase}.empty{padding:2rem;color:var(--muted)}@media(max-width:850px){.page-head{align-items:start;flex-direction:column}.team-workspace{grid-template-columns:1fr}}
</style>
