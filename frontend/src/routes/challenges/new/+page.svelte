<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { deepSeekModelLabel, knownProviderModels } from '$lib/provider-models';
  import { challengeErrorMessage } from '$lib/challenge';
  import type { AgentType, ChallengeRunView, PricingStatus, ProviderKind, ProviderStatus } from '$lib/types';

  const steps = ['Campaign', 'Draft rules', 'Controllers', 'Training', 'Review & start'];
  let step = 0;
  let furthest = 0;
  let pricing: PricingStatus | null = null;
  let providers: ProviderStatus[] = [];
  let setupLoading = true;
  let setupError = '';
  let name = 'Kanto Draft Gauntlet';
  let seed = Math.floor(Date.now() / 1000);
  let draftKind: 'human' | 'agent' | 'random' = 'human';
  let draftProvider: ProviderKind = 'fake';
  let draftModel = 'fake-battle-v1';
  let battleType: AgentType = 'human';
  let battleProvider: ProviderKind = 'fake';
  let battleModel = 'fake-battle-v1';
  let opponentType: AgentType = 'random';
  let opponentProvider: ProviderKind = 'fake';
  let opponentModel = 'fake-battle-v1';
  let credits = 68;
  let rerolls = 2;
  let evBudget = 1200;
  let loading = false;
  let error = '';

  $: readyProviders = providers.filter((item) => item.configured);
  $: draftProviderReady = draftKind !== 'agent' || readyProviders.some((item) => item.id === draftProvider);
  $: battleProviderReady = battleType !== 'api' || readyProviders.some((item) => item.id === battleProvider);
  $: opponentProviderReady = opponentType !== 'api' || readyProviders.some((item) => item.id === opponentProvider);
  $: currentValid = validStep(step);

  onMount(() => { void loadSetup(); });

  async function loadSetup() {
    setupLoading = true;
    try {
      const [priceStatus, providerResult] = await Promise.all([
        api<PricingStatus>('/api/challenge-prices/status'),
        api<{ providers: ProviderStatus[] }>('/api/providers')
      ]);
      pricing = priceStatus;
      providers = providerResult.providers;
      const preferred = providers.find((item) => item.configured && item.id !== 'fake') || providers.find((item) => item.configured);
      if (preferred) {
        draftProvider = preferred.id; draftModel = preferred.default_model;
        battleProvider = preferred.id; battleModel = preferred.default_model;
        opponentProvider = preferred.id; opponentModel = preferred.default_model;
      }
      setupError = '';
    } catch (caught) {
      setupError = caught instanceof Error ? caught.message : String(caught);
    } finally {
      setupLoading = false;
    }
  }

  function configuration(provider: ProviderKind) {
    const status = providers.find((item) => item.id === provider);
    return { timeout_seconds: 300, max_retries: 1, fallback: 'random', temperature: null, max_output_tokens: 2048, reasoning_effort: null, base_url: provider === 'openai-compatible' ? (status?.default_base_url || 'http://host.docker.internal:1234/v1') : null, maximum_cost: null, fake_scenario: 'valid' };
  }

  function battleController(agentType: AgentType, provider: ProviderKind, model: string) {
    return { agent_type: agentType, provider: agentType === 'api' ? provider : null, model: agentType === 'api' ? model : null, configuration: configuration(provider) };
  }

  function validStep(index: number): boolean {
    if (index === 0) return Boolean(name.trim()) && Number.isSafeInteger(Number(seed));
    if (index === 1) return credits >= 1 && credits <= 500 && rerolls >= 0 && rerolls <= 20;
    if (index === 2) return draftProviderReady && battleProviderReady && opponentProviderReady && (draftKind !== 'agent' || Boolean(draftModel.trim())) && (battleType !== 'api' || Boolean(battleModel.trim())) && (opponentType !== 'api' || Boolean(opponentModel.trim()));
    if (index === 3) return evBudget >= 0 && evBudget <= 3060;
    return Boolean(pricing?.ready) && validStep(0) && validStep(1) && validStep(2) && validStep(3);
  }

  function next() {
    if (!currentValid) { error = 'Complete the highlighted settings before continuing.'; return; }
    error = '';
    step = Math.min(steps.length - 1, step + 1);
    furthest = Math.max(furthest, step);
  }

  function chooseProvider(target: 'draft' | 'battle' | 'opponent', value: ProviderKind) {
    const status = providers.find((item) => item.id === value);
    if (target === 'draft') { draftProvider = value; draftModel = status?.default_model || ''; }
    if (target === 'battle') { battleProvider = value; battleModel = status?.default_model || ''; }
    if (target === 'opponent') { opponentProvider = value; opponentModel = status?.default_model || ''; }
  }

  function modelsFor(provider: ProviderKind): string[] {
    return knownProviderModels(provider, providers);
  }

  function controllerLabel(type: AgentType) {
    if (type === 'human') return 'Me · Human Player';
    if (type === 'manual') return 'Manual Web Chat';
    if (type === 'random') return 'Deterministic Random';
    return 'AI Agent';
  }

  async function create() {
    if (!validStep(4) || !pricing) return;
    loading = true; error = '';
    try {
      const view = await api<ChallengeRunView>('/api/challenges', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(), definition_id: 'kanto-gym-gauntlet', seed: Number(seed), expected_catalog_hash: pricing.catalog_hash,
          draft_controller: { kind: draftKind, provider: draftKind === 'agent' ? draftProvider : null, model: draftKind === 'agent' ? draftModel.trim() : null, configuration: configuration(draftProvider) },
          battle_controller: battleController(battleType, battleProvider, battleModel.trim()),
          opponent_controller: battleController(opponentType, opponentProvider, opponentModel.trim()),
          draft_rules: { roster_size: 6, starting_credits: Number(credits), rerolls: Number(rerolls), choice_count: 3, species_clause: true },
          training_rules: { global_ev_budget: Number(evBudget), per_pokemon_max: 510, per_stat_max: 252 }
        })
      });
      await goto(`/challenges/${view.run.id}`);
    } catch (caught) {
      error = challengeErrorMessage(caught instanceof Error ? caught.message : String(caught));
      loading = false;
    }
  }
</script>

<div class="page-head"><div><span class="eyebrow">Guided setup</span><h1>New Kanto Gym Gauntlet</h1><p>Strong defaults are already selected. Drafting and battling are separate choices.</p></div><a class="button ghost compact" href="/challenges"><i class="ph ph-x" aria-hidden="true"></i>Exit setup</a></div>

{#if setupLoading}
  <section class="panel blocked" role="status"><span class="spinner"></span><div><h2>Checking pricing and AI providers…</h2><p>This does not create or modify a run.</p></div></section>
{:else if setupError}
  <section class="panel blocked" role="alert"><div><h2>Setup could not be loaded</h2><p>{setupError}</p></div><button class="button secondary" on:click={loadSetup}>Retry</button></section>
{:else if pricing && !pricing.ready}
  <section class="panel blocked"><i class="ph ph-database" aria-hidden="true"></i><div><span class="eyebrow">Setup required</span><h2>Draft pricing is not ready</h2><p>A Challenge cannot be created until a local Draft Board copy has been imported and verified. Existing Battles and Tournaments are unaffected.</p>{#each pricing.errors as item}<small>{item}</small>{/each}</div><a class="button" href="/challenges#pricing-setup">Open exact setup steps</a></section>
{:else}
  <nav class="stepper" aria-label="Challenge setup progress">
    {#each steps as item, index}<button type="button" class:active={step === index} class:done={index < step} disabled={index > furthest} aria-current={step === index ? 'step' : undefined} on:click={() => (step = index)}><span>{index < step ? '✓' : index + 1}</span>{item}</button>{/each}
  </nav>

  <form class="wizard panel" on:submit|preventDefault={create}>
    {#if step === 0}
      <section aria-labelledby="campaign-step"><span class="eyebrow">Step 1 of 5</span><h2 id="campaign-step">Choose the campaign</h2><p>The first pack is a thirteen-stage Kanto route. Every run stores its exact rules and content version.</p><article class="campaign-card"><div class="campaign-mark"><i class="ph ph-map-trifold" aria-hidden="true"></i></div><div><strong>Kanto Gym Gauntlet</strong><span>Brock → eight Gyms → Elite Four → Blue</span><small>Exact Pokémon Red/Blue species, order, source levels, and moves · equal modern battle levels</small></div><span class="selected">Selected</span></article><div class="field-grid"><label>Challenge name<input bind:value={name} maxlength="120" required aria-describedby="name-help" /><small id="name-help">Shown in Challenge history and stage match titles.</small></label><label>Draft seed<input type="number" bind:value={seed} required aria-describedby="seed-help" /><small id="seed-help">The same seed, catalog, version, and rules reproduce draft offers.</small></label></div></section>
    {:else if step === 1}
      <section aria-labelledby="draft-step"><span class="eyebrow">Step 2 of 5</span><h2 id="draft-step">Set the draft economy</h2><p>Imported Pokémon prices stay exact. Every offered choice is checked against the credits needed to finish all six picks.</p><div class="rule-grid"><label><span>Draft Credits <button class="help" type="button" title="The point cost imported for each Pokémon. Prices are never inferred from competitive tiers." aria-label="About Draft Credits">?</button></span><input type="number" min="1" max="500" bind:value={credits} /><small>Default 68 · spent only on Pokémon.</small></label><label><span>Rerolls <button class="help" type="button" title="Discard the current Generation + Type offer and deterministically generate another." aria-label="About rerolls">?</button></span><input type="number" min="0" max="20" bind:value={rerolls} /><small>Default 2 · each use is confirmed.</small></label><div><span>Roster size</span><strong>6 Pokémon</strong><small>Species Clause uses National Pokédex identity.</small></div><div><span>Choices per offer</span><strong>Up to 3</strong><small>A smaller safe offer appears only if the pool is exhausted.</small></div></div></section>
    {:else if step === 2}
      <section aria-labelledby="controller-step"><span class="eyebrow">Step 3 of 5</span><h2 id="controller-step">Choose who drafts and who battles</h2><p>These three roles are independent. “Me” drafting does not force “Me” to play the battles.</p><div class="role-stack"><fieldset><legend>Drafted by</legend><p>Chooses the six-Pokémon roster.</p><div class="choice-grid">{#each [['human','Me','Choose every offer myself.'],['agent','AI Agent','One strict legal draft action at a time.'],['random','Random','Instant deterministic choices; no provider.']] as option}<button type="button" class:chosen={draftKind === option[0]} aria-pressed={draftKind === option[0]} on:click={() => (draftKind = option[0] as typeof draftKind)}><i class={`ph ${option[0] === 'human' ? 'ph-user' : option[0] === 'agent' ? 'ph-robot' : 'ph-dice-five'}`} aria-hidden="true"></i><strong>{option[1]}</strong><span>{option[2]}</span></button>{/each}</div>{#if draftKind === 'agent'}<div class="provider"><label>Provider<select value={draftProvider} on:change={(event) => chooseProvider('draft', event.currentTarget.value as ProviderKind)}>{#each readyProviders as item}<option value={item.id}>{item.label}{item.id === 'fake' ? ' · testing' : ''}</option>{/each}</select></label><label>Model{#if modelsFor(draftProvider).length}<select bind:value={draftModel}>{#each modelsFor(draftProvider) as model}<option value={model}>{draftProvider === 'deepseek' ? deepSeekModelLabel(model) : model}</option>{/each}</select>{:else}<input bind:value={draftModel} required />{/if}</label></div>{#if !draftProviderReady}<p class="inline-error">No ready provider is selected. <a href="/settings">Configure one in Settings.</a></p>{/if}{/if}</fieldset><fieldset><legend>Battled by</legend><p>Controls your team during every stage.</p><div class="choice-grid four">{#each [['human','Me','Move and switch buttons.'],['api','AI Agent','KoalaBattle provider agent.'],['manual','Manual Chat','Copy prompt, paste JSON.'],['random','Random','Legal random actions.']] as option}<button type="button" class:chosen={battleType === option[0]} aria-pressed={battleType === option[0]} on:click={() => (battleType = option[0] as AgentType)}><strong>{option[1]}</strong><span>{option[2]}</span></button>{/each}</div>{#if battleType === 'api'}<div class="provider"><label>Provider<select value={battleProvider} on:change={(event) => chooseProvider('battle', event.currentTarget.value as ProviderKind)}>{#each readyProviders as item}<option value={item.id}>{item.label}{item.id === 'fake' ? ' · testing' : ''}</option>{/each}</select></label><label>Model{#if modelsFor(battleProvider).length}<select bind:value={battleModel}>{#each modelsFor(battleProvider) as model}<option value={model}>{battleProvider === 'deepseek' ? deepSeekModelLabel(model) : model}</option>{/each}</select>{:else}<input bind:value={battleModel} required />{/if}</label></div>{#if !battleProviderReady}<p class="inline-error">Configure an AI provider in <a href="/settings">Settings</a>, or choose Me/Manual/Random.</p>{/if}{/if}</fieldset><fieldset><legend>Opponents controlled by</legend><p>One controller is reused across all stages; authored teams remain private.</p><div class="choice-grid">{#each [['random','Random baseline','Fast, free, deterministic.'],['api','AI Agent','Use a configured provider.']] as option}<button type="button" class:chosen={opponentType === option[0]} aria-pressed={opponentType === option[0]} on:click={() => (opponentType = option[0] as AgentType)}><strong>{option[1]}</strong><span>{option[2]}</span></button>{/each}</div>{#if opponentType === 'api'}<div class="provider"><label>Provider<select value={opponentProvider} on:change={(event) => chooseProvider('opponent', event.currentTarget.value as ProviderKind)}>{#each readyProviders as item}<option value={item.id}>{item.label}{item.id === 'fake' ? ' · testing' : ''}</option>{/each}</select></label><label>Model{#if modelsFor(opponentProvider).length}<select bind:value={opponentModel}>{#each modelsFor(opponentProvider) as model}<option value={model}>{opponentProvider === 'deepseek' ? deepSeekModelLabel(model) : model}</option>{/each}</select>{:else}<input bind:value={opponentModel} required />{/if}</label></div>{#if !opponentProviderReady}<p class="inline-error">No ready provider is selected. <a href="/settings">Configure one in Settings.</a></p>{/if}{/if}</fieldset></div></section>
    {:else if step === 3}
      <section aria-labelledby="training-step"><span class="eyebrow">Step 4 of 5</span><h2 id="training-step">Set the Training Budget</h2><p>EVs are separate from Draft Credits. After drafting, distribute this shared budget across the six Pokémon.</p><div class="training-choice"><label>Global EV budget<input type="number" min="0" max="3060" bind:value={evBudget} /><small>Default 1200 · up to 510 per Pokémon and 252 per stat.</small></label><div><i class="ph ph-scales" aria-hidden="true"></i><span><strong>Fair level normalization</strong><small>Your finalized team and every opponent use the same exact level for each stage. Later stages become harder through teams and strategy, not hidden level advantages.</small></span></div></div><details><summary>What happens after the draft?</summary><p>Training Camp provides numeric EV controls, legal presets, resets, and a live used/remaining counter. You then complete items, abilities, natures, and moves before the pinned Showdown validator locks the team.</p></details></section>
    {:else}
      <section aria-labelledby="review-step"><span class="eyebrow">Step 5 of 5</span><h2 id="review-step">Review the run</h2><p>Nothing has been created yet. These settings become the durable run snapshot when you start.</p><div class="review-grid"><article><span>Campaign</span><strong>Kanto Gym Gauntlet</strong><small>13 stages · Lv. 50–100 · {pricing?.board_name}</small></article><article><span>Source fidelity</span><strong>Pokémon Red and Blue</strong><small>Exact recorded rosters and moves · Blue variant for a Bulbasaur player</small></article><article><span>Draft</span><strong>6 Pokémon · {credits} credits</strong><small>{rerolls} rerolls · up to 3 choices · seed {seed}</small></article><article><span>Controllers</span><strong>{draftKind === 'human' ? 'Me' : draftKind === 'agent' ? 'AI Agent' : 'Random'} drafts → {controllerLabel(battleType)} battles</strong><small>{controllerLabel(opponentType)} controls opponents</small></article><article><span>Training</span><strong>{evBudget} shared EVs</strong><small>510 per Pokémon · 252 per stat</small></article><article><span>Battle rules</span><strong>Canonical NatDex Draft singles</strong><small>Equal stage levels · source-incompatible clauses disabled · special gimmick actions disabled</small></article><article><span>Pricing snapshot</span><strong>{pricing?.context}</strong><small>Catalog {pricing?.catalog_hash?.slice(0, 12)} · {pricing?.source_verified ? 'source verified' : 'verification warning'}</small></article></div><div class="ready-note"><i class="ph ph-shield-check" aria-hidden="true"></i><p><strong>Safe to resume.</strong> Refreshes and restarts retain the exact current offer, pricing snapshot, rules, and campaign version.</p></div></section>
    {/if}

    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <footer class="wizard-actions"><button type="button" class="button secondary" disabled={step === 0 || loading} on:click={() => { error = ''; step -= 1; }}>Back</button><span>Step {step + 1} of {steps.length}</span>{#if step < steps.length - 1}<button type="button" class="button" disabled={!currentValid} on:click={next}>Continue<i class="ph ph-arrow-right" aria-hidden="true"></i></button>{:else}<button class="button" disabled={loading || !currentValid}>{loading ? 'Creating durable run…' : 'Create and begin draft'}<i class="ph ph-arrow-right" aria-hidden="true"></i></button>{/if}</footer>
  </form>
{/if}

<style>
  .page-head p,.wizard p,.blocked p{color:var(--muted);font-size:.78rem;line-height:1.55}.stepper{display:grid;grid-template-columns:repeat(5,1fr);gap:.4rem;margin-bottom:.8rem}.stepper button{display:flex;align-items:center;gap:.45rem;min-height:44px;padding:.55rem;border:1px solid var(--border);border-radius:.6rem;background:var(--panel);color:var(--muted);font-size:.7rem;text-align:left}.stepper button span{display:grid;place-items:center;width:22px;aspect-ratio:1;border-radius:50%;background:var(--surface);font:.62rem var(--mono)}.stepper button.active{border-color:var(--accent);color:var(--text)}.stepper button.active span,.stepper button.done span{background:var(--accent);color:var(--accent-ink)}.wizard{padding:1.4rem;box-shadow:none}.wizard>section{display:grid;gap:1rem;min-height:420px;align-content:start}.wizard h2,.blocked h2{margin:.2rem 0;font-size:1.55rem}.campaign-card{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:1rem;padding:1rem;border:1px solid var(--accent);border-radius:.75rem;background:color-mix(in srgb,var(--accent) 6%,var(--panel-strong))}.campaign-mark{display:grid;place-items:center;width:52px;aspect-ratio:1;border-radius:.65rem;background:var(--accent);color:var(--accent-ink);font-size:1.5rem}.campaign-card>div:nth-child(2){display:grid;gap:.2rem}.campaign-card strong{font-size:1.05rem}.campaign-card span,.campaign-card small{color:var(--muted)}.campaign-card .selected{padding:.3rem .5rem;border-radius:999px;background:var(--accent);color:var(--accent-ink);font:.58rem var(--mono);text-transform:uppercase}.field-grid,.provider{display:grid;grid-template-columns:repeat(2,1fr);gap:.7rem}.field-grid label,.provider label,.rule-grid label,.training-choice label{display:grid;gap:.35rem}.field-grid small,.rule-grid small,.training-choice small{color:var(--muted);font:.62rem/1.4 var(--mono)}.rule-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:.7rem}.rule-grid>label,.rule-grid>div{display:grid;gap:.35rem;padding:1rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.rule-grid>div span,.rule-grid label>span{font-size:.76rem}.rule-grid>div strong{font-size:1.2rem}.help{display:inline-grid;place-items:center;width:1.15rem;aspect-ratio:1;padding:0;border:1px solid var(--border);border-radius:50%;background:transparent;color:var(--muted);font:.62rem var(--mono);cursor:help}.role-stack{display:grid;gap:.8rem}.role-stack fieldset{display:grid;gap:.7rem;margin:0;padding:1rem;border:1px solid var(--border);border-radius:.75rem}.role-stack legend{padding:0 .35rem;font-weight:800}.role-stack fieldset>p{margin:0}.choice-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}.choice-grid.four{grid-template-columns:repeat(4,1fr)}.choice-grid button{display:grid;align-content:start;gap:.3rem;min-height:96px;padding:.75rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer}.choice-grid button.chosen{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent);background:color-mix(in srgb,var(--accent) 6%,var(--panel-strong))}.choice-grid i{color:var(--accent);font-size:1.15rem}.choice-grid span{color:var(--muted);font-size:.64rem;line-height:1.35}.provider{padding-top:.2rem}.inline-error{margin:0;color:var(--danger)!important}.inline-error a{color:inherit;text-decoration:underline}.training-choice{display:grid;grid-template-columns:.7fr 1.3fr;gap:.8rem}.training-choice>label,.training-choice>div{padding:1rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.training-choice>div{display:flex;align-items:center;gap:.8rem}.training-choice i{color:var(--accent);font-size:1.7rem}.training-choice span{display:grid;gap:.2rem}.review-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:.6rem}.review-grid article{display:grid;gap:.25rem;padding:.85rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.review-grid article>span{color:var(--muted);font:.58rem var(--mono);text-transform:uppercase}.review-grid small{color:var(--muted);font:.62rem/1.4 var(--mono)}.ready-note{display:flex;align-items:center;gap:.7rem;padding:.8rem;border-radius:.65rem;background:color-mix(in srgb,var(--accent) 8%,transparent)}.ready-note i{color:var(--accent);font-size:1.5rem}.ready-note p{margin:0}.wizard-actions{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:1rem;margin-top:1.2rem;padding-top:1rem;border-top:1px solid var(--border)}.wizard-actions>span{color:var(--muted);font:.62rem var(--mono)}.wizard-actions .button:last-child{justify-self:end}.blocked{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:1.5rem}.blocked>i{color:var(--warning);font-size:2rem}.blocked>div{flex:1}.blocked small{display:block;color:var(--warning);font:.62rem var(--mono)}.spinner{width:1.5rem;aspect-ratio:1;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:850px){.page-head{align-items:stretch;flex-direction:column}.stepper{grid-template-columns:repeat(5,auto);overflow-x:auto}.stepper button{min-width:115px}.choice-grid.four{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.field-grid,.rule-grid,.choice-grid,.choice-grid.four,.provider,.training-choice,.review-grid{grid-template-columns:1fr}.campaign-card{grid-template-columns:auto 1fr}.campaign-card .selected{grid-column:1/-1;justify-self:start}.wizard{padding:1rem}.wizard-actions{grid-template-columns:1fr 1fr}.wizard-actions>span{display:none}.blocked{align-items:stretch;flex-direction:column}}
</style>
