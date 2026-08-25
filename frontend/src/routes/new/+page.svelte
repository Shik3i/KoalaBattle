<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import FormatSelector from '$lib/FormatSelector.svelte';
  import {
    CUSTOM_ENDPOINT_PRESET_ID,
    LOCAL_ENDPOINT_PRESETS,
    localEndpointPreset
  } from '$lib/local-endpoints';
  import { api, copyText, getFormatGroups } from '$lib/api';
  import { hydrateStoredProviderSettings } from '$lib/provider-settings';
  import { deepSeekModelLabel, knownProviderModels } from '$lib/provider-models';
  import type {
    AgentType,
    FormatDescriptor,
    FormatGroup,
    MatchArchive,
    ProviderKind,
    ProviderStatus,
    TeamSnapshot,
    TeamValidationResult
  } from '$lib/types';

  interface PlayerDraft {
    name: string; agentType: AgentType; provider: ProviderKind; model: string; baseUrl: string;
    endpointPreset: string;
    timeout: number; retries: number; fallback: 'random' | 'manual' | 'forfeit';
    temperature: string; maxTokens: number; reasoning: '' | 'low' | 'medium' | 'high' | 'max';
    maximumCost: string; fakeScenario: string; teamSnapshotId: string;
  }
  const providerLabels: Record<ProviderKind, string> = {
    openai: 'OpenAI', gemini: 'Google Gemini', anthropic: 'Anthropic', deepseek: 'DeepSeek',
    'openai-compatible': 'OpenAI-compatible', fake: 'Deterministic Fake (testing)'
  };
  const defaultModels: Record<ProviderKind, string> = {
    openai: 'gpt-5-mini', gemini: 'gemini-2.5-flash', anthropic: 'claude-sonnet-4-5',
    deepseek: 'deepseek-v4-flash', 'openai-compatible': 'local-model', fake: 'fake-battle-v1'
  };
  const draft = (name: string): PlayerDraft => ({
    name, agentType: 'random', provider: 'openai', model: defaultModels.openai, baseUrl: '',
    endpointPreset: CUSTOM_ENDPOINT_PRESET_ID,
    timeout: 300, retries: 1, fallback: 'random', temperature: '', maxTokens: 256,
    reasoning: '', maximumCost: '', fakeScenario: 'valid', teamSnapshotId: ''
  });

  /**
   * Agent resource profiles. These are LLM cost/latency settings only — they never touch
   * Pokemon stats, battle mechanics or Showdown legality.
   */
  const RESOURCE_PROFILES = {
    economy: { label: 'Economy', hint: 'Five-minute timeout, one retry, 128 output tokens', timeout: 300, retries: 1, maxTokens: 128 },
    balanced: { label: 'Balanced', hint: 'Five-minute timeout, one retry, 256 output tokens', timeout: 300, retries: 1, maxTokens: 256 },
    power: { label: 'Power', hint: 'Five-minute timeout, one retry, 512 output tokens', timeout: 300, retries: 1, maxTokens: 512 }
  } as const;
  type ResourceProfile = keyof typeof RESOURCE_PROFILES;

  let players = [draft('Player One'), draft('Player Two')];
  let matchName = '';
  let providers: ProviderStatus[] = [];
  let teams: TeamSnapshot[] = [];
  let formatGroups: FormatGroup[] = [];
  let formatsLoading = true;
  let format = 'gen9randombattle';
  let descriptor: FormatDescriptor | null = null;
  let seed = ''; let maximumTotalCost = ''; let maximumTurns = '200';
  let banterEnabled = false;
  let resourceProfile: ResourceProfile = 'balanced';
  let loading = false; let error = ''; let discovering: number | null = null;
  let discoveredModels: Record<number, string[]> = {};
  // Inline team import, so a custom-team match never has to leave this page.
  let teamDrafts: Record<number, string> = {};
  let teamValidation: Record<number, TeamValidationResult | null> = {};
  let importing: number | null = null;
  let promptCopied: number | null = null;
  let promptFallback: Record<number, string> = {};
  let teamPanelOpen = false;

  function selectableModels(index: number): string[] {
    return [...new Set([
      ...knownProviderModels(players[index].provider, providers),
      ...(discoveredModels[index] || [])
    ])];
  }

  $: allFormats = formatGroups.flatMap((group) => group.formats);
  $: descriptor = allFormats.find((item) => item.id === format) || descriptor;
  $: needsCustomTeam = descriptor?.custom_team_required ?? false;
  $: usesApi = players.some((player) => player.agentType === 'api');
  $: eligibleTeams = teams.filter((team) => team.format === format);

  onMount(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        await hydrateStoredProviderSettings();
        const [providerResult, teamResult, groups] = await Promise.all([
          api<{ providers: ProviderStatus[] }>('/api/providers', { signal: controller.signal }),
          api<TeamSnapshot[]>('/api/teams', { signal: controller.signal }),
          getFormatGroups(false, controller.signal)
        ]);
        providers = providerResult.providers; teams = teamResult; formatGroups = groups;
        const configured = providers.filter((provider) => provider.configured && provider.id !== 'fake');
        if (configured.length) {
          players = players.map((player) => {
            const current = providers.find((provider) => provider.id === player.provider);
            if (current?.configured) return player;
            const next = configured[0];
            return { ...player, provider: next.id, model: next.default_model, baseUrl: next.default_base_url || '' };
          });
        }
        formatsLoading = false;
      } catch (caught) {
        if (!controller.signal.aborted) {
          error = caught instanceof Error ? caught.message : String(caught);
          formatsLoading = false;
        }
      }
    })();
    return () => controller.abort();
  });

  function selectFormat(next: FormatDescriptor) {
    format = next.id;
    descriptor = next;
    // Team snapshots are format-specific; clear any that no longer apply.
    players = players.map((player) => ({
      ...player,
      teamSnapshotId: teams.some((team) => team.id === player.teamSnapshotId && team.format === next.id)
        ? player.teamSnapshotId
        : ''
    }));
    // Offer the import panel when this format has nothing to select yet. Set once here rather
    // than derived, so later state changes cannot slam an open panel shut.
    teamPanelOpen = next.custom_team_required
      && !teams.some((team) => team.format === next.id);
  }
  async function copyTeamPrompt(index: number) {
    error = '';
    try {
      const result = await api<{ prompt: string }>('/api/teams/prompt', {
        method: 'POST',
        body: JSON.stringify({
          format,
          participant: players[index].name || `Player ${index + 1}`,
          context: {
            opponent: players[1 - index].name || `Player ${2 - index}`,
            maximum_turns: Number(maximumTurns) || null
          }
        })
      });
      if (await copyText(result.prompt)) {
        promptCopied = index;
        setTimeout(() => { if (promptCopied === index) promptCopied = null; }, 2000);
      } else {
        // Clipboard refused: show the prompt so it can still be copied by hand.
        promptFallback = { ...promptFallback, [index]: result.prompt };
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }
  async function importTeam(index: number) {
    const text = (teamDrafts[index] || '').trim();
    if (!text) return;
    importing = index; error = ''; teamValidation = { ...teamValidation, [index]: null };
    try {
      const result = await api<{ validation: TeamValidationResult; snapshot: TeamSnapshot | null }>(
        '/api/teams/validate',
        {
          method: 'POST',
          body: JSON.stringify({
            name: `${players[index].name || `Player ${index + 1}`} · ${descriptor?.name || format}`,
            format,
            team_text: text,
            source: 'imported',
            save: true
          })
        }
      );
      teamValidation = { ...teamValidation, [index]: result.validation };
      if (result.snapshot) {
        const snapshot = result.snapshot;
        teams = [snapshot, ...teams.filter((item) => item.id !== snapshot.id)];
        players[index].teamSnapshotId = snapshot.id;
        players = [...players];
        teamDrafts = { ...teamDrafts, [index]: '' };
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      importing = null;
    }
  }
  function selectProvider(index: number, value: ProviderKind) {
    players[index].provider = value;
    const status = providers.find((provider) => provider.id === value);
    players[index].model = status?.default_model || defaultModels[value];
    players[index].endpointPreset = CUSTOM_ENDPOINT_PRESET_ID;
    players[index].baseUrl = status?.default_base_url || '';
    if (value === 'openai-compatible' && !players[index].baseUrl) applyEndpointPreset(index, 'lm-studio-gemma-4', false);
    players = [...players];
  }
  function selectAgentType(index: number, value: AgentType) {
    players[index].agentType = value;
    if (value === 'api') {
      const current = providers.find((provider) => provider.id === players[index].provider);
      const fallback = providers.find((provider) => provider.configured && provider.id !== 'fake')
        || providers.find((provider) => provider.configured);
      if (!current?.configured && fallback) selectProvider(index, fallback.id);
    }
    players = [...players];
  }
  function applyResourceProfile(value: ResourceProfile) {
    resourceProfile = value;
    const { timeout, retries, maxTokens } = RESOURCE_PROFILES[value];
    players = players.map((player) => ({ ...player, timeout, retries, maxTokens }));
  }
  function applyEndpointPreset(index: number, presetId: string, rerender = true) {
    players[index].endpointPreset = presetId;
    const preset = localEndpointPreset(presetId);
    if (preset) {
      players[index].provider = 'openai-compatible';
      players[index].baseUrl = preset.baseUrl;
      players[index].model = preset.model;
      players[index].timeout = preset.timeoutSeconds;
      players[index].retries = preset.maxRetries;
    }
    if (rerender) players = [...players];
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
      },
      team_source: needsCustomTeam ? 'preset' : 'showdown-random',
      team_snapshot_id: needsCustomTeam ? player.teamSnapshotId : null
    };
  }
  async function createBattle() {
    if (loading) return;
    if (needsCustomTeam && players.some((player) => !eligibleTeams.some((team) => team.id === player.teamSnapshotId))) {
      // Covers both "nothing chosen" and a snapshot that has since been deleted or belongs to
      // another format; the server would otherwise reject the create with a bare 422.
      error = `Select one validated ${descriptor?.name || format} team for each player.`; return;
    }
    loading = true; error = '';
    try {
      const match = await api<MatchArchive>('/api/matches', {
        method: 'POST',
        body: JSON.stringify({
          name: matchName || null,
          format,
          player1: playerPayload(players[0]), player2: playerPayload(players[1]),
          random_seed: seed ? Number(seed) : null, fair_prompt_mode: true,
          prompt_profile: 'benchmark-fair', context_profile: 'pokemon-standard',
          memory_policy: 'strategy-note',
          banter_enabled: banterEnabled,
          team_policy: needsCustomTeam ? 'fixed' : 'showdown-random',
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
  <div>
    <span class="eyebrow">New match</span>
    <h1>Create match</h1>
    <p>A Random Battle needs nothing but two agents. Everything else is optional.</p>
  </div>
</div>

<form class="builder" on:submit|preventDefault={createBattle}>
  <div class="row players">
    {#each players as player, index}
      <section class:second={index === 1} class="card player">
        <header>
          <span class="slot">Player {index + 1}</span>
          <input class="name" bind:value={player.name} required maxlength="80" aria-label={`Player ${index + 1} display name`} />
        </header>
        <label>Agent
          <select value={player.agentType} on:change={(event) => selectAgentType(index, event.currentTarget.value as AgentType)}>
            <option value="random">Random agent · free local baseline</option>
            <option value="manual">Manual Web Chat · copy and paste</option>
            <option value="api">Provider API · full auto</option>
          </select>
        </label>
        {#if player.agentType === 'api'}
          <label>Provider
            <select value={player.provider} on:change={(event) => selectProvider(index, event.currentTarget.value as ProviderKind)}>
              <optgroup label="Configured providers">{#each providers.filter((status) => status.id !== 'fake' && status.configured) as status}<option value={status.id}>{status.label || providerLabels[status.id]} · ready</option>{/each}{#if !providers.some((status) => status.id !== 'fake' && status.configured)}<option disabled>Open Settings to configure a provider</option>{/if}</optgroup>
              {#if providers.some((status) => status.id === 'fake')}<optgroup label="Development / Testing">{#each providers.filter((status) => status.id === 'fake') as status}<option value={status.id} disabled={!status.configured}>{providerLabels[status.id]}{status.configured ? ' · enabled' : ' · disabled'}</option>{/each}</optgroup>{/if}
            </select>
          </label>
          {#if player.provider === 'openai-compatible'}
            <label>Local endpoint preset
              <select
                value={player.endpointPreset}
                aria-label={`Player ${index + 1} local endpoint preset`}
                on:change={(event) => applyEndpointPreset(index, event.currentTarget.value)}
              >
                <option value={CUSTOM_ENDPOINT_PRESET_ID}>Custom endpoint</option>
                {#each LOCAL_ENDPOINT_PRESETS as preset}
                  <option value={preset.id}>{preset.label}</option>
                {/each}
              </select>
            </label>
            {#if localEndpointPreset(player.endpointPreset)}
              <small class="field-hint endpoint-hint">{localEndpointPreset(player.endpointPreset)?.hint}</small>
            {/if}
          {/if}
          <label>Model
            {#if selectableModels(index).length}
              <select bind:value={player.model} required>{#each selectableModels(index) as model}<option value={model}>{player.provider === 'deepseek' ? deepSeekModelLabel(model) : model}</option>{/each}</select>
            {:else}
              <input bind:value={player.model} required list={`models-${index}`} />
            {/if}
          </label>
          {#if !selectableModels(index).length}<datalist id={`models-${index}`}>{#each discoveredModels[index] || [] as model}<option value={model}></option>{/each}</datalist>{/if}
          {#if player.provider === 'openai-compatible'}<label>Base URL<input type="url" bind:value={player.baseUrl} required placeholder="http://host.docker.internal:1234/v1" /></label>{/if}
          <button type="button" class="link-button" on:click={() => discover(index)} disabled={discovering === index}>{discovering === index ? 'Discovering…' : 'Discover models'}</button>
        {:else}
          <p class="mode-note">
            {player.agentType === 'manual'
              ? 'Each turn pauses. Copy the prompt into any web chat, then paste the JSON response.'
              : 'Plays legal random actions locally. No provider, credentials or network request.'}
          </p>
        {/if}
        {#if needsCustomTeam}
          <label>Team
            <select bind:value={player.teamSnapshotId} required>
              <option value="">Select a validated team…</option>
              {#each eligibleTeams as team}<option value={team.id}>{team.name} · {team.source}</option>{/each}
            </select>
            <small class="field-hint">{eligibleTeams.length ? `${eligibleTeams.length} validated ${descriptor?.name} team(s)` : 'No validated team for this format yet — paste one below.'}</small>
          </label>
          <!-- One shared open state, so both player columns expand and collapse together and
               the two cards never drift out of alignment. -->
          <details class="team-import" bind:open={teamPanelOpen}>
            <summary>Paste a Showdown export instead</summary>
            <div class="team-body">
              <p class="team-steps">Copy the prompt into any web chat, then paste the team it returns.</p>
              <div class="team-actions">
                <button type="button" class="button secondary compact" on:click={() => copyTeamPrompt(index)}>
                  <i class={`ph ${promptCopied === index ? 'ph-check' : 'ph-copy'}`} aria-hidden="true"></i>
                  {promptCopied === index ? 'Prompt copied' : 'Copy team prompt'}
                </button>
                <button
                  type="button"
                  class="button secondary compact"
                  disabled={importing === index || !(teamDrafts[index] || '').trim()}
                  on:click={() => importTeam(index)}
                >
                  <i class="ph ph-shield-check" aria-hidden="true"></i>
                  {importing === index ? 'Validating…' : 'Validate and use'}
                </button>
              </div>
              {#if promptFallback[index]}
                <label class="prompt-fallback">Clipboard blocked — select and copy this
                  <textarea rows="5" readonly value={promptFallback[index]}></textarea>
                </label>
              {/if}
              <textarea
                rows="6"
                bind:value={teamDrafts[index]}
                placeholder={`Paste the Showdown export for ${descriptor?.name || format} here…`}
              ></textarea>
              {#if teamValidation[index]}
                <div class="team-result" class:valid={teamValidation[index]?.valid}>
                  <strong>{teamValidation[index]?.valid ? `✓ Legal ${descriptor?.name || format} team — selected` : 'Invalid team'}</strong>
                  {#each teamValidation[index]?.errors || [] as item}<p>{item}</p>{/each}
                </div>
              {/if}
              <small class="field-hint">Validated against {descriptor?.name || format} by the local Showdown validator and saved as an immutable snapshot.</small>
            </div>
          </details>
        {/if}
      </section>
    {/each}
  </div>

  <div class="row settings">
    <section class="card">
      <h2>Battle</h2>
      <FormatSelector
        groups={formatGroups}
        loading={formatsLoading}
        value={format}
        on:change={(event) => selectFormat(event.detail)}
      />
      <p class="field-hint format-note">
        {#if descriptor}
          {descriptor.name} ·
          {descriptor.custom_team_required ? 'both players bring a validated team' : 'Showdown generates both teams'}
          {#if needsCustomTeam}<a href="/teams"> · open Team Lab →</a>{/if}
        {:else}
          Formats come from the pinned local Pokémon Showdown build.
        {/if}
      </p>
      <label>Match name <span class="optional">Optional</span>
        <input bind:value={matchName} maxlength="120" placeholder="Benchmark Run 14" />
      </label>
      <label class="check-option">
        <input type="checkbox" bind:checked={banterEnabled} />
        <span><strong>Optional banter</strong><small>Short, situational opponent lines are included in the JSON and spoken aloud.</small></span>
      </label>
    </section>

    <section class="card">
      <h2>Limits</h2>
      <div class="pair">
        <label>Maximum turns<input type="number" min="1" max="10000" bind:value={maximumTurns} /></label>
        <label>Total cost limit (USD)<input type="number" min="0" step="0.01" bind:value={maximumTotalCost} placeholder="No limit" /></label>
      </div>
      <small class="field-hint">Safety default is 200 turns. Model pricing is never guessed; unknown pricing stays unavailable.</small>
    </section>
  </div>

  <details class="card advanced-card">
    <summary>Advanced AI settings</summary>
    <div class="advanced-body">
      <section class="resource-profile">
        <div>
          <h3>Agent resource profile</h3>
          <p class="field-hint">
            Controls AI model cost and latency settings: request timeout, retry count and output-token
            ceiling. It does not affect Pokémon, teams or battle rules.
          </p>
        </div>
        <div class="segmented" role="group" aria-label="Agent resource profile">
          {#each Object.entries(RESOURCE_PROFILES) as [key, profile]}
            <button
              type="button"
              class:active={resourceProfile === key}
              title={profile.hint}
              on:click={() => applyResourceProfile(key as ResourceProfile)}
            >{profile.label}</button>
          {/each}
        </div>
        <p class="field-hint profile-hint">{RESOURCE_PROFILES[resourceProfile].hint}</p>
        {#if !usesApi}<p class="field-hint">Applies to Provider API agents only.</p>{/if}
      </section>

      {#each players as player, index}
        <section class="advanced-player">
          <h3>{player.name || `Player ${index + 1}`}</h3>
          <div class="advanced-grid">
            <label>Timeout (seconds)<input type="number" min="1" max="600" bind:value={player.timeout} /></label>
            <label>Retries<input type="number" min="0" max="5" bind:value={player.retries} /></label>
            <label>Max output tokens<input type="number" min="32" max="8192" bind:value={player.maxTokens} /></label>
            <label>Fallback<select bind:value={player.fallback}><option value="random">Random</option><option value="manual">Manual Web Chat</option><option value="forfeit">Forfeit</option></select></label>
            <label>Temperature<input type="number" min="0" max="2" step="0.1" bind:value={player.temperature} placeholder="Provider default" /></label>
            <label>Reasoning effort<select bind:value={player.reasoning}><option value="">Provider default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="max">Max</option></select></label>
            <label>Player cost limit (USD)<input type="number" min="0" step="0.01" bind:value={player.maximumCost} placeholder="No limit" /></label>
            {#if player.provider === 'fake' && player.agentType === 'api'}<label>Failure scenario<select bind:value={player.fakeScenario}><option value="valid">Valid</option><option value="malformed_then_valid">Malformed then valid</option><option value="invalid_then_valid">Illegal then valid</option><option value="rate_limit_then_valid">Rate limit then valid</option><option value="provider_error">Provider error</option><option value="timeout">Timeout</option></select></label>{/if}
          </div>
        </section>
      {/each}

      <section class="advanced-player">
        <h3>Random agent seed</h3>
        <label>Seed<input type="number" bind:value={seed} placeholder="Unseeded" /></label>
        <!-- This only reaches RandomAgent (see service.py). Calling it a
             "deterministic seed" under a "Reproducibility" heading promised a
             repeatable battle, which Showdown's own RNG makes impossible from here. -->
        <small>
          Makes <strong>Random</strong> agents choose the same actions again. Other agent types
          ignore it. Showdown rolls damage, criticals, accuracy and speed ties itself and does not
          accept a seed over the battle protocol, so a battle is never repeated move for move.
        </small>
      </section>
    </div>
  </details>

  <div class="launch">
    {#if error}<span class="error" role="alert">{error}</span>{/if}
    <button class:loading class="button" disabled={loading}>{loading ? 'Starting…' : 'Start battle'}</button>
  </div>
</form>

<style>
  .builder{display:grid;gap:1rem;width:min(var(--content),100%);margin-inline:auto}
  /* min-width:0 lets both columns actually share the row: without it a grid item refuses to
     shrink below its content and the wider side pushes the other one out of alignment. */
  .row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;align-items:start}
  .card{display:grid;align-content:start;gap:.85rem;min-width:0;padding:1.25rem 1.35rem;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--panel)}
  .card h2{margin:0;font-size:var(--step-1);letter-spacing:-.01em}
  .card h3{margin:0 0 .2rem;font-size:.88rem}
  .player{position:relative;overflow:hidden}
  .player::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--p1)}
  .player.second::before{background:var(--p2)}
  .player header{display:grid;gap:.3rem}
  .slot{color:var(--muted);font:600 .6rem var(--mono);letter-spacing:.12em;text-transform:uppercase}
  .name{min-height:40px;padding:.4rem .6rem;border-color:transparent;background:transparent;font-size:var(--step-1);font-weight:750;letter-spacing:-.02em}
  .name:hover{border-color:var(--border)}
  .mode-note{margin:0;color:var(--muted);font-size:.78rem;line-height:1.5}
  .endpoint-hint{margin:-.45rem 0 -.15rem;color:var(--accent)}
  /* The grid lives on an explicit wrapper: Chrome puts every non-summary child of <details>
     into one ::details-content box, so a grid on <details> itself never reaches them. */
  .team-import{padding:.7rem .8rem;border:1px solid var(--border);border-radius:var(--radius);background:var(--panel-strong)}
  .team-import summary{color:var(--accent);font-size:.75rem;font-weight:650;cursor:pointer}
  .team-import summary:hover{color:var(--accent-strong)}
  .team-body{display:grid;gap:.55rem;margin-top:.55rem;min-width:0}
  .team-import textarea{width:100%;min-width:0;padding:.55rem .65rem;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);font:.72rem/1.5 var(--mono);resize:vertical}
  .team-actions{display:flex;flex-wrap:wrap;gap:.5rem}
  .team-steps{margin:0;color:var(--muted);font-size:.75rem;line-height:1.5}
  .prompt-fallback{display:grid;gap:.3rem;color:var(--warning);font-size:.72rem}
  .team-result{padding:.5rem .65rem;border:1px solid var(--danger);border-radius:var(--radius);color:var(--danger);font-size:.75rem}
  .team-result.valid{border-color:var(--accent);color:var(--accent)}
  .team-result p{margin:.25rem 0 0;line-height:1.45}
  .link-button{justify-self:start;padding:.2rem 0;border:0;background:none;color:var(--accent);font-size:.75rem;font-weight:650;cursor:pointer}
  .link-button:disabled{color:var(--muted);cursor:default}
  .optional{margin-left:.35rem;padding:.05rem .35rem;border-radius:999px;background:var(--surface);color:var(--muted);font-size:.62rem;font-weight:600}
  label:has(.optional){grid-template-columns:auto auto 1fr}
  label:has(.optional) input{grid-column:1/-1}
  .check-option{display:flex;align-items:flex-start;gap:.55rem;grid-template-columns:none}
  .check-option input{width:17px;min-height:17px;margin-top:.1rem;accent-color:var(--accent)}
  .check-option span{display:grid;gap:.2rem}
  .check-option small{color:var(--muted);font-size:.72rem;line-height:1.45}
  .advanced-card summary::marker{color:var(--accent)}
  .format-note{margin:-.35rem 0 0}
  .format-note a{color:var(--accent);font-weight:650}
  .pair{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
  .advanced-card{padding:0}
  .advanced-card summary{padding:1rem 1.35rem;color:var(--muted);font-size:.82rem;font-weight:650;cursor:pointer}
  .advanced-card[open] summary{border-bottom:1px solid var(--border)}
  .advanced-body{display:grid;gap:1.25rem;padding:1.25rem 1.35rem}
  .resource-profile{display:grid;gap:.7rem;max-width:var(--reading)}
  .segmented{display:flex;padding:.2rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}
  .segmented button{flex:1;min-height:36px;padding:.4rem .8rem;border:0;border-radius:.5rem;background:transparent;color:var(--muted);font-weight:650;cursor:pointer}
  .segmented button.active{background:var(--surface);color:var(--text)}
  .profile-hint{color:var(--accent)}
  .advanced-player{display:grid;gap:.7rem;padding-top:1rem;border-top:1px solid var(--border)}
  .advanced-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem}
  .launch{display:flex;justify-content:flex-end;align-items:center;gap:1rem;margin-top:.5rem}
  .launch .error{margin-right:auto}
  .launch .button{min-width:190px}
  @media(max-width:880px){
    .row{grid-template-columns:1fr}
    .advanced-grid{grid-template-columns:1fr 1fr}
  }
  @media(max-width:560px){
    .pair,.advanced-grid{grid-template-columns:1fr}
    .segmented{flex-direction:column}
    .launch{align-items:stretch;flex-direction:column-reverse}
    .launch .button{width:100%}
  }
</style>
