<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { challengeErrorMessage, STANDARD_CHALLENGE_SETTINGS } from '$lib/challenge';
  import { deepSeekModelLabel, knownProviderModels } from '$lib/provider-models';
  import type { AgentType, ChallengeDefinitionSummary, ChallengeRunView, ProviderKind, ProviderStatus } from '$lib/types';

  let providers: ProviderStatus[] = [];
  let definitions: ChallengeDefinitionSummary[] = [];
  let setupLoading = true;
  let setupError = '';
  let loading = false;
  let error = '';
  let name = 'Kanto Draft Gauntlet';
  let nameEdited = false;
  let definitionId = 'kanto-gym-gauntlet';
  let seed = Math.floor(Date.now() / 1000);
  let choiceCount = STANDARD_CHALLENGE_SETTINGS.choiceCount;
  let draftPoolMode: 'all-forms' | 'base-forms-only' = STANDARD_CHALLENGE_SETTINGS.draftPoolMode;
  let opponentTeamMode: 'original' | 'filled' = STANDARD_CHALLENGE_SETTINGS.opponentTeamMode;
  let battleType: 'tactical-auto' | 'human' | 'api' = STANDARD_CHALLENGE_SETTINGS.battleType;
  let battleExperience: 'quick-sim' | 'fast-watch' | 'normal' = STANDARD_CHALLENGE_SETTINGS.battleExperience;
  type Difficulty = 'normal' | 'hard' | 'expert' | 'nightmare';
  // Difficulty only ever raises the opponent above the campaign's own level curve; the
  // player always follows that curve, so their own levelling and evolution are never undone.
  const DIFFICULTIES: Array<{ id: Difficulty; label: string; detail: string; icon: string }> = [
    { id: 'normal', label: 'Normal', detail: 'Campaign levels', icon: 'ph-shield-check' },
    { id: 'hard', label: 'Hard', detail: 'Opponent +5 levels', icon: 'ph-barbell' },
    { id: 'expert', label: 'Expert', detail: 'Opponent +10 levels', icon: 'ph-scales' },
    { id: 'nightmare', label: 'Nightmare', detail: 'Opponent +15 levels', icon: 'ph-flame' }
  ];
  let difficulty: Difficulty = STANDARD_CHALLENGE_SETTINGS.difficulty;
  let battleProvider: ProviderKind = 'fake';
  let battleModel = 'fake-battle-v1';

  $: readyProviders = providers.filter((item) => item.configured);
  // A human battler has to answer every turn, so there is nothing to fast-forward.
  // Keep the choice honest instead of shipping a Quick Sim that opens a control page.
  $: playerIsInteractive = battleType === 'human';
  $: if (playerIsInteractive && battleExperience !== 'normal') battleExperience = 'normal';
  $: needsAi = battleType === 'api';
  $: aiReady = !needsAi || readyProviders.length > 0;
  $: valid = Boolean(name.trim()) && Number.isSafeInteger(Number(seed)) && choiceCount >= 2 && choiceCount <= 8 && aiReady;
  $: selectedDefinition = definitions.find((item) => item.id === definitionId) || null;

  function selectDefinition(id: string) {
    definitionId = id;
    if (!nameEdited) {
      const definition = definitions.find((item) => item.id === id);
      if (definition) name = definition.name;
    }
  }

  onMount(() => { void loadSetup(); });

  async function loadSetup() {
    setupLoading = true;
    try {
      const [result, availableDefinitions] = await Promise.all([
        api<{ providers: ProviderStatus[] }>('/api/providers'),
        api<ChallengeDefinitionSummary[]>('/api/challenges/definitions')
      ]);
      providers = result.providers;
      definitions = availableDefinitions;
      const requestedDefinition = new URLSearchParams(window.location.search).get('definition');
      if (requestedDefinition && definitions.some((item) => item.id === requestedDefinition)) {
        selectDefinition(requestedDefinition);
      }
      const preferred = providers.find((item) => item.configured && !['fake', 'openai-compatible'].includes(item.id))
        || providers.find((item) => item.configured && item.id === 'fake')
        || providers.find((item) => item.configured);
      if (preferred) {
        battleProvider = preferred.id; battleModel = preferred.default_model;
      }
      setupError = '';
    } catch (caught) {
      setupError = caught instanceof Error ? caught.message : String(caught);
    } finally { setupLoading = false; }
  }

  function configuration(provider: ProviderKind) {
    const status = providers.find((item) => item.id === provider);
    return { timeout_seconds: 300, max_retries: 1, fallback: 'random', temperature: null, max_output_tokens: 2048, reasoning_effort: null, base_url: provider === 'openai-compatible' ? (status?.default_base_url || 'http://host.docker.internal:1234/v1') : null, maximum_cost: null, fake_scenario: 'valid' };
  }
  function controller(agentType: AgentType, provider: ProviderKind, model: string) {
    return { agent_type: agentType, provider: agentType === 'api' ? provider : null, model: agentType === 'api' ? model.trim() : null, configuration: configuration(provider) };
  }
  function chooseProvider(target: 'battle', provider: ProviderKind) {
    const model = providers.find((item) => item.id === provider)?.default_model || '';
    if (target === 'battle') { battleProvider = provider; battleModel = model; }
  }
  function modelsFor(provider: ProviderKind) { return knownProviderModels(provider, providers); }

  async function create() {
    if (!valid || loading) return;
    loading = true; error = '';
    try {
      const view = await api<ChallengeRunView>('/api/challenges', { method: 'POST', body: JSON.stringify({
        name: name.trim(), definition_id: definitionId, seed: Number(seed),
        draft_controller: { kind: 'human', provider: null, model: null, configuration: configuration('fake') },
        battle_controller: controller(battleType, battleProvider, battleModel),
        opponent_controller: controller('tactical-auto', 'fake', ''),
        battle_experience: battleExperience,
        difficulty,
        opponent_team_mode: opponentTeamMode,
        draft_rules: { roster_size: 6, rerolls: 3, type_rerolls: 1, generation_rerolls: 1, choice_count: Number(choiceCount), species_clause: true, draft_pool_mode: draftPoolMode }
      }) });
      if (view.run.current_offer) sessionStorage.setItem(`draft-first-roll:${view.run.id}`, view.run.current_offer.fingerprint);
      await goto(`/challenges/${view.run.id}`);
    } catch (caught) {
      error = challengeErrorMessage(caught instanceof Error ? caught.message : String(caught));
      loading = false;
    }
  }
</script>

<div class="page-head"><div><span class="eyebrow">Draft</span><h1>{selectedDefinition?.name || 'Choose a campaign'}</h1><p>{selectedDefinition?.description || 'Draft six Pokémon, prepare them, then face real story teams from across the Pokémon regions.'}</p></div><a class="button ghost compact" href="/challenges">Draft history</a></div>

  <form class="launch-card panel" on:submit|preventDefault={create}>
  <header><div class="region-mark"><i class="ph ph-map-trifold" aria-hidden="true"></i></div><div><span class="eyebrow">Campaign</span><h2>{selectedDefinition?.region || 'Loading campaigns…'}</h2><p>{selectedDefinition?.stage_count_label || 'Regional Gym, Trial, Elite Four and Champion stages'}</p></div><span class="selected">{selectedDefinition?.campaign_kind === 'multi-generation' ? 'Gen I–IX' : selectedDefinition?.generation ? `Gen ${selectedDefinition.generation}` : 'Available'}</span></header>
  <div class="quick-choices">
    <fieldset class="campaign-picker"><legend>Campaign route</legend><div class="campaign-options">{#each definitions as definition}<button type="button" class:chosen={definitionId === definition.id} aria-pressed={definitionId === definition.id} on:click={() => selectDefinition(definition.id)}><span><strong>{definition.name}</strong><small>{definition.campaign_kind === 'multi-generation' ? 'One draft · every region' : `Gen ${definition.generation} · ${definition.stage_count} stages`}</small></span><i class={`ph ${definition.campaign_kind === 'multi-generation' ? 'ph-arrows-clockwise' : 'ph-map-pin'}`} aria-hidden="true"></i></button>{/each}</div><p class="difficulty-note">Regional routes use their authentic leader, Elite Four and Champion order. All Generations keeps one drafted roster while progressing through every available regional campaign.</p></fieldset>
    <fieldset><legend>Who plays the battles?</legend><div class="segmented three"><button type="button" class:chosen={battleType === 'tactical-auto'} aria-pressed={battleType === 'tactical-auto'} on:click={() => (battleType = 'tactical-auto')}><i class="ph ph-lightning" aria-hidden="true"></i><span><strong>Fast Auto</strong><small>Local · tactical · free</small></span></button><button type="button" class:chosen={battleType === 'human'} aria-pressed={battleType === 'human'} on:click={() => (battleType = 'human')}><i class="ph ph-game-controller" aria-hidden="true"></i><span><strong>Me</strong><small>Interactive</small></span></button><button type="button" class:chosen={battleType === 'api'} aria-pressed={battleType === 'api'} on:click={() => (battleType = 'api')}><i class="ph ph-brain" aria-hidden="true"></i><span><strong>LLM</strong><small>Uses a provider</small></span></button></div></fieldset>
    <fieldset class="difficulty"><legend>Difficulty</legend><div class="segmented four">{#each DIFFICULTIES as option}<button type="button" class:chosen={difficulty === option.id} aria-pressed={difficulty === option.id} on:click={() => (difficulty = option.id)}><i class={`ph ${option.icon}`} aria-hidden="true"></i><span><strong>{option.label}</strong><small>{option.detail}</small></span></button>{/each}</div><p class="difficulty-note">Opponent species and sets are identical on every difficulty. Harder modes only raise the opponent's level above the campaign curve; your own team always follows that curve.</p></fieldset>
    <fieldset class="experience"><legend>Battle experience</legend><div class="segmented three"><button type="button" class:chosen={battleExperience === 'quick-sim'} aria-pressed={battleExperience === 'quick-sim'} disabled={playerIsInteractive} on:click={() => (battleExperience = 'quick-sim')}><i class="ph ph-fast-forward" aria-hidden="true"></i><span><strong>Quick Sim</strong><small>Result + replay</small></span></button><button type="button" class:chosen={battleExperience === 'fast-watch'} aria-pressed={battleExperience === 'fast-watch'} disabled={playerIsInteractive} on:click={() => (battleExperience = 'fast-watch')}><i class="ph ph-monitor-play" aria-hidden="true"></i><span><strong>Fast Watch</strong><small>Watch at speed</small></span></button><button type="button" class:chosen={battleExperience === 'normal'} aria-pressed={battleExperience === 'normal'} on:click={() => (battleExperience = 'normal')}><i class="ph ph-play" aria-hidden="true"></i><span><strong>Normal</strong><small>Full pacing</small></span></button></div>{#if playerIsInteractive}<p class="difficulty-note" role="status">You are playing every turn yourself, so each stage opens its control page at normal pacing.</p>{/if}</fieldset>
    <fieldset><legend>Draft pool</legend><div class="segmented two"><button type="button" class:chosen={draftPoolMode === 'base-forms-only'} aria-pressed={draftPoolMode === 'base-forms-only'} on:click={() => (draftPoolMode = 'base-forms-only')}><i class="ph ph-plant" aria-hidden="true"></i><span><strong>Base forms only</strong><small>First forms evolve during the run; single-stage Pokémon remain eligible</small></span></button><button type="button" class:chosen={draftPoolMode === 'all-forms'} aria-pressed={draftPoolMode === 'all-forms'} on:click={() => (draftPoolMode = 'all-forms')}><i class="ph ph-sparkle" aria-hidden="true"></i><span><strong>All forms</strong><small>Developed forms can appear, with lower odds</small></span></button></div></fieldset>
    <fieldset><legend>Opponent teams</legend><div class="segmented two"><button type="button" class:chosen={opponentTeamMode === 'original'} aria-pressed={opponentTeamMode === 'original'} on:click={() => (opponentTeamMode = 'original')}><i class="ph ph-game-controller" aria-hidden="true"></i><span><strong>Original teams</strong><small>Authentic story rosters and legal modern moves</small></span></button><button type="button" class:chosen={opponentTeamMode === 'filled'} aria-pressed={opponentTeamMode === 'filled'} on:click={() => (opponentTeamMode = 'filled')}><i class="ph ph-users-three" aria-hidden="true"></i><span><strong>Filled teams</strong><small>Six themed competitive Pokémon for every trainer</small></span></button></div></fieldset>
  </div>
  {#if needsAi}<section class="ai-strip" class:blocked={!aiReady} aria-live="polite"><i class={`ph ${aiReady ? 'ph-check-circle' : 'ph-warning'}`} aria-hidden="true"></i><span>{#if setupLoading}<strong>Checking AI providers…</strong>{:else if aiReady}<strong>AI ready</strong><small>{readyProviders[0].label}{readyProviders.length > 1 ? ` and ${readyProviders.length - 1} more configured` : ''}</small>{:else}<strong>No AI provider configured</strong><small><a href="/settings">Add a provider in Settings</a> or choose Me.</small>{/if}</span></section>{/if}
  <details class="advanced"><summary><i class="ph ph-sliders-horizontal" aria-hidden="true"></i>Advanced settings</summary><div class="advanced-grid"><label>Draft name<input bind:value={name} on:input={() => (nameEdited = true)} maxlength="120" required /></label><label>Draft seed<input type="number" bind:value={seed} required /></label><label>Cards per roll<input type="number" min="2" max="8" bind:value={choiceCount} /></label><div class="fixed-opponent"><span>Opponent controller</span><strong><i class="ph ph-lightning" aria-hidden="true"></i> Fast Auto</strong><small>Always local, tactical and switch-capable.</small></div></div>
    {#if battleType === 'api'}<div class="provider-row"><strong>Battle AI</strong><label>Provider<select value={battleProvider} on:change={(event) => chooseProvider('battle', event.currentTarget.value as ProviderKind)}>{#each readyProviders as item}<option value={item.id}>{item.label}</option>{/each}</select></label><label>Model{#if modelsFor(battleProvider).length}<select bind:value={battleModel}>{#each modelsFor(battleProvider) as model}<option value={model}>{battleProvider === 'deepseek' ? deepSeekModelLabel(model) : model}</option>{/each}</select>{:else}<input bind:value={battleModel} />{/if}</label></div>{/if}
    <p>Every run includes one Pokémon, one Type, and one Generation power. Recommended legal EVs and abilities are applied automatically after the sixth pick.</p></details>
  {#if needsAi && setupError}<p class="error" role="alert">AI status unavailable: {setupError} <button type="button" class="link-button" on:click={loadSetup}>Retry</button></p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <button class="start" disabled={!valid || loading}><span>{loading ? 'Creating saved run…' : needsAi && setupLoading ? 'Checking AI providers…' : 'Start drafting'}</span><i class="ph ph-arrow-right" aria-hidden="true"></i></button>
  <p class="save-note"><i class="ph ph-cloud-check" aria-hidden="true"></i>Every roll and pick is saved automatically.</p>
</form>

<style>
  .page-head p{max-width:52ch}.launch-card{max-width:900px;margin:0 auto;padding:clamp(1rem,3vw,1.8rem);box-shadow:none}.launch-card>header{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:1rem;padding:1rem;border:1px solid color-mix(in srgb,var(--accent) 48%,var(--border));border-radius:.8rem;background:linear-gradient(120deg,color-mix(in srgb,var(--accent) 12%,var(--panel-strong)),var(--panel-strong))}.region-mark{display:grid;place-items:center;width:58px;aspect-ratio:1;border-radius:.7rem;background:var(--accent);color:var(--accent-ink);font-size:1.7rem}.launch-card h2{margin:.15rem 0;font-size:1.65rem}.launch-card p{margin:.2rem 0;color:var(--muted);font-size:.72rem;line-height:1.5}.selected{padding:.3rem .55rem;border-radius:999px;background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent);font:.58rem var(--mono);text-transform:uppercase}.quick-choices{display:grid;grid-template-columns:1fr;gap:.8rem;margin-top:1rem}.quick-choices fieldset{margin:0;padding:.8rem;border:1px solid var(--border);border-radius:.75rem}.quick-choices legend{padding:0 .35rem;font-weight:800}.campaign-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.45rem}.campaign-options button{display:flex;align-items:center;justify-content:space-between;gap:.55rem;min-height:68px;padding:.7rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer}.campaign-options button:hover{border-color:color-mix(in srgb,var(--accent) 55%,var(--border))}.campaign-options button.chosen{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,var(--panel-strong));box-shadow:inset 0 0 0 1px var(--accent)}.campaign-options span{display:grid;gap:.15rem}.campaign-options small{color:var(--muted);font-size:.6rem;line-height:1.3}.campaign-options i{color:var(--accent);font-size:1.1rem}.segmented{display:grid;grid-template-columns:1fr 1fr;gap:.45rem}.segmented.two{grid-template-columns:repeat(2,1fr)}.segmented.three{grid-template-columns:repeat(3,1fr)}.segmented.four{grid-template-columns:repeat(4,1fr)}.difficulty-note{margin:.55rem 0 0;color:var(--muted);font-size:.68rem;line-height:1.45}.segmented button{display:flex;align-items:center;gap:.6rem;min-height:76px;padding:.7rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer}.segmented button:hover{border-color:color-mix(in srgb,var(--accent) 55%,var(--border))}.segmented button:disabled{opacity:.42;cursor:not-allowed}.segmented button.chosen{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,var(--panel-strong));box-shadow:inset 0 0 0 1px var(--accent)}.segmented i{color:var(--accent);font-size:1.35rem}.segmented span{display:grid}.segmented small{color:var(--muted);font-size:.62rem;line-height:1.35}.ai-strip{display:flex;align-items:center;gap:.6rem;margin-top:.8rem;padding:.65rem .8rem;border:1px solid color-mix(in srgb,var(--accent) 40%,var(--border));border-radius:.6rem;background:color-mix(in srgb,var(--accent) 6%,transparent)}.ai-strip.blocked{border-color:color-mix(in srgb,var(--warning) 55%,var(--border))}.ai-strip i{color:var(--accent);font-size:1.2rem}.ai-strip.blocked i{color:var(--warning)}.ai-strip span{display:grid}.ai-strip small{color:var(--muted)}.ai-strip a{color:var(--accent)}.advanced{margin-top:.8rem;padding:.8rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.advanced summary{display:flex;align-items:center;gap:.45rem;font-weight:750;cursor:pointer}.advanced-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:.55rem;margin-top:.8rem}.provider-row{display:grid;grid-template-columns:120px 1fr 1fr;align-items:end;gap:.55rem;margin-top:.7rem;padding-top:.7rem;border-top:1px solid var(--border)}.provider-row>strong{align-self:center}.start{display:flex;align-items:center;justify-content:space-between;width:100%;min-height:64px;margin-top:1rem;padding:0 1.2rem;border:0;border-radius:.75rem;background:linear-gradient(100deg,var(--accent),color-mix(in srgb,var(--accent) 65%,#58a6ff));color:var(--accent-ink);font:800 1.1rem var(--display);cursor:pointer;box-shadow:0 10px 30px color-mix(in srgb,var(--accent) 22%,transparent);transition:transform .16s ease,filter .16s ease}.start:hover:not(:disabled){transform:translateY(-2px);filter:brightness(1.06)}.start:disabled{cursor:not-allowed;filter:saturate(.2);opacity:.55}.save-note{display:flex;align-items:center;justify-content:center;gap:.35rem!important;margin:.65rem 0 0!important;font:.6rem var(--mono)!important}.save-note i{color:var(--accent)}.error{margin-top:.8rem!important;color:var(--danger)!important}
  .fixed-opponent{display:grid;align-content:center;gap:.2rem;color:var(--muted);font-size:.72rem}.fixed-opponent strong{color:var(--text)}.fixed-opponent strong i{color:var(--accent)}.fixed-opponent small{font-size:.62rem;line-height:1.35}
  @media(max-width:850px){.advanced-grid{grid-template-columns:repeat(2,1fr)}.provider-row{grid-template-columns:1fr 1fr}.provider-row>strong{grid-column:1/-1}}
  @media(max-width:850px){.campaign-options{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:650px){.quick-choices,.advanced-grid,.campaign-options{grid-template-columns:1fr}.segmented.two,.segmented.three,.segmented.four{grid-template-columns:1fr}.launch-card>header{grid-template-columns:auto 1fr}.selected{grid-column:1/-1;justify-self:start}.provider-row{grid-template-columns:1fr}.provider-row>strong{grid-column:auto}}
  @media(max-width:400px){.segmented{grid-template-columns:1fr}}
  @media(prefers-reduced-motion:reduce){.start{transition:none}}
</style>
