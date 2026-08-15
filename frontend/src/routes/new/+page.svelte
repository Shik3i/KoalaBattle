<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { AgentType, MatchArchive, ProviderKind, ProviderStatus } from '$lib/types';

  interface PlayerDraft {
    name: string; agentType: AgentType; provider: ProviderKind; model: string; baseUrl: string;
    timeout: number; retries: number; fallback: 'random' | 'manual' | 'forfeit';
    temperature: string; maxTokens: number; reasoning: '' | 'low' | 'medium' | 'high' | 'max';
    maximumCost: string; fakeScenario: string;
  }
  const providerLabels: Record<ProviderKind, string> = {
    openai: 'OpenAI', gemini: 'Google Gemini', anthropic: 'Anthropic', deepseek: 'DeepSeek',
    'openai-compatible': 'OpenAI-compatible', fake: 'Fake provider (test)'
  };
  const defaultModels: Record<ProviderKind, string> = {
    openai: 'gpt-5-mini', gemini: 'gemini-2.5-flash', anthropic: 'claude-sonnet-4-5',
    deepseek: 'deepseek-chat', 'openai-compatible': 'local-model', fake: 'fake-battle-v1'
  };
  const draft = (name: string): PlayerDraft => ({
    name, agentType: 'random', provider: 'openai', model: defaultModels.openai, baseUrl: '',
    timeout: 45, retries: 1, fallback: 'random', temperature: '', maxTokens: 256,
    reasoning: '', maximumCost: '', fakeScenario: 'valid'
  });

  let players = [draft('Player One'), draft('Player Two')];
  let matchName = '';
  let providers: ProviderStatus[] = [];
  let seed = ''; let maximumTotalCost = ''; let maximumTurns = '';
  let preset: 'economy' | 'balanced' | 'power' = 'balanced';
  let loading = false; let error = ''; let discovering: number | null = null;
  let discoveredModels: Record<number, string[]> = {};

  onMount(() => void loadProviders());
  async function loadProviders() {
    try { providers = (await api<{ providers: ProviderStatus[] }>('/api/providers')).providers; }
    catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
  }
  function selectProvider(index: number, value: ProviderKind) {
    players[index].provider = value; players[index].model = defaultModels[value]; players = [...players];
  }
  function applyPreset(value: typeof preset) {
    preset = value;
    const values = value === 'economy' ? { timeout: 25, retries: 0, maxTokens: 128 }
      : value === 'power' ? { timeout: 90, retries: 2, maxTokens: 512 }
      : { timeout: 45, retries: 1, maxTokens: 256 };
    players = players.map((player) => ({ ...player, ...values }));
  }
  async function discover(index: number) {
    discovering = index; error = '';
    try {
      const player = players[index];
      const result = await api<{ models: Array<{ id: string }> }>('/api/providers/models', {
        method: 'POST', body: JSON.stringify({ provider: player.provider, base_url: player.baseUrl || null })
      });
      discoveredModels = { ...discoveredModels, [index]: result.models.map((item) => item.id) };
      if (result.models.length && !result.models.some((item) => item.id === player.model)) {
        player.model = result.models[0].id; players = [...players];
      }
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
    finally { discovering = null; }
  }
  function playerPayload(player: PlayerDraft) {
    return {
      display_name: player.name, agent_type: player.agentType,
      provider: player.agentType === 'api' ? player.provider : null,
      model: player.agentType === 'api' ? player.model : null,
      configuration: {
        timeout_seconds: player.timeout, max_retries: player.retries, fallback: player.fallback,
        temperature: player.temperature === '' ? null : Number(player.temperature),
        max_output_tokens: player.maxTokens, reasoning_effort: player.reasoning || null,
        base_url: player.provider === 'openai-compatible' ? player.baseUrl : null,
        maximum_cost: player.maximumCost === '' ? null : Number(player.maximumCost),
        fake_scenario: player.fakeScenario
      }
    };
  }
  async function createBattle() {
    loading = true; error = '';
    try {
      const match = await api<MatchArchive>('/api/matches', {
        method: 'POST',
        body: JSON.stringify({
          name: matchName || null,
          player1: playerPayload(players[0]), player2: playerPayload(players[1]),
          random_seed: seed ? Number(seed) : null, fair_prompt_mode: true,
          limits: {
            maximum_total_cost: maximumTotalCost ? Number(maximumTotalCost) : null,
            maximum_turns: maximumTurns ? Number(maximumTurns) : null
          }
        })
      });
      await goto(`/battle/${match.id}`);
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); loading = false; }
  }
</script>

<div class="page-head">
  <div><span class="eyebrow">New production</span><h1>Stage a battle</h1></div>
  <span class="status-pill">Standard information · Gen 9 Random Battle</span>
</div>
<form class="builder" on:submit|preventDefault={createBattle}>
  <section class="panel match-name"><label>Optional match name<input bind:value={matchName} maxlength="120" placeholder="Benchmark Run 14" /></label><span>Stable URLs continue to use the match UUID.</span></section>
  <div class="preset-bar panel">
    <div><span class="eyebrow">Run preset</span><strong>{preset}</strong></div>
    <div class="segmented">
      <button type="button" class:active={preset === 'economy'} on:click={() => applyPreset('economy')}>Economy</button>
      <button type="button" class:active={preset === 'balanced'} on:click={() => applyPreset('balanced')}>Balanced</button>
      <button type="button" class:active={preset === 'power'} on:click={() => applyPreset('power')}>Power</button>
    </div>
  </div>
  <div class="players">
    {#each players as player, index}
      <section class:second={index === 1} class="player panel">
        <header><span class="player-number">P{index + 1}</span><h2>{index ? 'Player two' : 'Player one'}</h2></header>
        <label>Display name<input bind:value={player.name} required maxlength="80" /></label>
        <label>Control mode
          <select bind:value={player.agentType}><option value="random">Random agent</option><option value="manual">Manual Web Chat</option><option value="api">Provider API · full auto</option></select>
        </label>
        {#if player.agentType === 'manual'}
          <div class="mode-note"><strong>Manual Web Chat</strong><span>Each turn pauses. Copy the prompt to any chat, then paste its JSON response.</span></div>
        {:else if player.agentType === 'random'}
          <div class="mode-note"><strong>Local random</strong><span>No provider, credentials, or network request.</span></div>
        {:else}
          <div class="provider-grid">
            <label>Provider<select value={player.provider} on:change={(event) => selectProvider(index, event.currentTarget.value as ProviderKind)}>
              {#each providers as status}<option value={status.id}>{providerLabels[status.id]}{status.configured ? '' : ' · not configured'}</option>{/each}
            </select></label>
            <label>Model ID<input bind:value={player.model} required list={`models-${index}`} /></label>
            <datalist id={`models-${index}`}>{#each discoveredModels[index] || [] as model}<option value={model}></option>{/each}</datalist>
            {#if player.provider === 'openai-compatible'}<label class="wide">Base URL<input type="url" bind:value={player.baseUrl} required placeholder="http://localhost:11434/v1" /></label>{/if}
            <button type="button" class="discover" on:click={() => discover(index)} disabled={discovering === index}>{discovering === index ? 'Discovering…' : 'Discover models'}</button>
          </div>
          <details>
            <summary>Advanced run controls</summary>
            <div class="advanced">
              <label>Timeout (seconds)<input type="number" min="1" max="600" bind:value={player.timeout} /></label>
              <label>Retries<input type="number" min="0" max="5" bind:value={player.retries} /></label>
              <label>Fallback<select bind:value={player.fallback}><option value="random">Random</option><option value="manual">Manual Web Chat</option><option value="forfeit">Forfeit</option></select></label>
              <label>Temperature<input type="number" min="0" max="2" step="0.1" bind:value={player.temperature} placeholder="Provider default" /></label>
              <label>Max output tokens<input type="number" min="32" max="8192" bind:value={player.maxTokens} /></label>
              <label>Reasoning effort<select bind:value={player.reasoning}><option value="">Provider default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="max">Max</option></select></label>
              <label>Player cost limit (USD)<input type="number" min="0" step="0.01" bind:value={player.maximumCost} placeholder="No limit" /></label>
              {#if player.provider === 'fake'}<label>Failure scenario<select bind:value={player.fakeScenario}><option value="valid">Valid</option><option value="malformed_then_valid">Malformed then valid</option><option value="invalid_then_valid">Illegal then valid</option><option value="rate_limit_then_valid">Rate limit then valid</option><option value="provider_error">Provider error</option><option value="timeout">Timeout</option></select></label>{/if}
            </div>
          </details>
        {/if}
      </section>
    {/each}
  </div>
  <section class="limits panel">
    <div><span class="eyebrow">Safety envelope</span><h2>Match limits</h2><p>Unknown model pricing remains unavailable; it is never guessed.</p></div>
    <label>Optional deterministic seed<input type="number" bind:value={seed} placeholder="Unseeded" /></label>
    <label>Total cost limit (USD)<input type="number" min="0" step="0.01" bind:value={maximumTotalCost} placeholder="No limit" /></label>
    <label>Maximum turns<input type="number" min="1" bind:value={maximumTurns} placeholder="No limit" /></label>
  </section>
  <div class="launch">{#if error}<span class="error" role="alert">{error}</span>{/if}<button class="button" disabled={loading}>{loading ? 'Starting…' : 'Start battle →'}</button></div>
</form>

<style>
  .builder{display:grid;gap:1rem}.match-name{display:grid;grid-template-columns:1fr auto;align-items:end;gap:1rem;padding:1rem 1.2rem;box-shadow:none}.match-name span{color:var(--muted);font:.65rem var(--mono)}.preset-bar{display:flex;justify-content:space-between;align-items:center;padding:1rem 1.2rem;box-shadow:none}.preset-bar strong{display:block;margin-top:.2rem;text-transform:capitalize}.segmented{display:flex;padding:.2rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.segmented button{min-height:36px;padding:.4rem .8rem;border:0;border-radius:.5rem;background:transparent;color:var(--muted);cursor:pointer}.segmented button.active{background:var(--surface);color:var(--text)}.players{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.player{padding:clamp(1.2rem,3vw,2rem);background:linear-gradient(145deg,color-mix(in srgb,var(--p1) 7%,var(--panel)),var(--panel) 45%)}.player.second{background:linear-gradient(215deg,color-mix(in srgb,var(--p2) 7%,var(--panel)),var(--panel) 45%)}.player header{display:flex;align-items:baseline;gap:.8rem}.player h2{font-size:1.6rem}.player-number{color:var(--accent);font:.72rem var(--mono)}.player label+label{margin-top:.85rem}.mode-note{display:grid;gap:.3rem;margin-top:1rem;padding:1rem;border:1px solid var(--border);border-radius:.75rem;background:var(--panel-strong)}.mode-note span,.limits p{color:var(--muted);font-size:.78rem;line-height:1.5}.provider-grid{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-top:1rem}.provider-grid label+label{margin-top:0}.provider-grid .wide{grid-column:1/-1}.discover{grid-column:1/-1;min-height:40px;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong);color:var(--text);cursor:pointer}details{margin-top:1rem;border-top:1px solid var(--border);padding-top:1rem}summary{color:var(--muted);font-size:.78rem;cursor:pointer}.advanced{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-top:1rem}.advanced label+label{margin-top:0}.limits{display:grid;grid-template-columns:1.6fr repeat(3,1fr);align-items:end;gap:1rem;padding:1.2rem;box-shadow:none}.limits h2{margin:.3rem 0}.limits p{margin:.2rem 0}.launch{display:flex;justify-content:flex-end;align-items:center;gap:1rem}.launch .error{margin-right:auto}@media(max-width:880px){.players{grid-template-columns:1fr}.limits{grid-template-columns:1fr 1fr}.limits>div{grid-column:1/-1}}@media(max-width:560px){.page-head,.preset-bar{align-items:flex-start;flex-direction:column}.match-name{grid-template-columns:1fr}.segmented{width:100%}.segmented button{flex:1}.provider-grid,.advanced,.limits{grid-template-columns:1fr}.limits>div{grid-column:auto}.launch{align-items:stretch;flex-direction:column}.launch .button{width:100%}}
</style>
