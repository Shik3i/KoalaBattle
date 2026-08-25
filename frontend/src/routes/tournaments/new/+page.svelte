<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import FormatSelector from '$lib/FormatSelector.svelte';
  import { api, copyText, getFormatGroups } from '$lib/api';
  import { DEEPSEEK_V4_MODELS, deepSeekModelLabel } from '$lib/provider-models';
  import type {
    AgentType,
    FormatDescriptor,
    FormatGroup,
    ProviderKind,
    TeamSnapshot,
    TeamValidationResult,
    TournamentArchive
  } from '$lib/types';

  interface ParticipantDraft { name: string; seed: number; agentType: AgentType; provider: ProviderKind; model: string; teamSnapshotId: string }
  const providerDefaults: Partial<Record<ProviderKind, string>> = {
    openai: 'gpt-5-mini', gemini: 'gemini-2.5-flash', anthropic: 'claude-sonnet-4-5',
    deepseek: 'deepseek-v4-flash', fake: 'fake-battle-v1'
  };
  const participant = (index: number): ParticipantDraft => ({ name: `Competitor ${index}`, seed: index, agentType: 'random', provider: 'openai', model: 'gpt-5-mini', teamSnapshotId: '' });
  const steps = ['Name', 'Format', 'Match template', 'Series', 'Participants', 'Agent presets', 'Seeding', 'Concurrency', 'Safety & presentation', 'Review'];
  let step = 1;
  let name = 'KoalaBattle Championship';
  let format: 'single_elimination' | 'round_robin' = 'single_elimination';
  let bestOf = 3;
  let concurrency = 2;
  let maximumCost = '';
  let maxDrawReplays = 3;
  let manualScheduling = false;
  let randomizeSeeds = false;
  let banterEnabled = false;
  let participants = [participant(1), participant(2), participant(3), participant(4)];
  let loading = false;
  let error = '';
  let battleFormat = 'gen9randombattle';
  let descriptor: FormatDescriptor | null = null;
  let formatGroups: FormatGroup[] = [];
  let formatsLoading = true;
  let teams: TeamSnapshot[] = [];
  let teamDrafts: Record<number, string> = {};
  let teamValidation: Record<number, TeamValidationResult | null> = {};
  let importing: number | null = null;
  let promptCopied: number | null = null;
  let promptFallback: Record<number, string> = {};
  // Shared across participants: the import panels open and close together, so a long roster
  // never becomes a mix of expanded and collapsed cards.
  let teamPanelOpen = false;

  function chooseParticipantProvider(index: number, provider: ProviderKind) {
    participants[index].provider = provider;
    participants[index].model = providerDefaults[provider] || '';
  }

  $: allFormats = formatGroups.flatMap((group) => group.formats);
  $: descriptor = allFormats.find((item) => item.id === battleFormat) || descriptor;
  $: needsCustomTeam = descriptor?.custom_team_required ?? false;
  $: eligibleTeams = teams.filter((team) => team.format === battleFormat);
  // Single elimination halves the field each round; round robin plays every other participant.
  $: rounds = format === 'single_elimination'
    ? Math.max(1, Math.ceil(Math.log2(Math.max(participants.length, 2))))
    : Math.max(1, participants.length - 1);

  onMount(() => {
    const controller = new AbortController();
    void Promise.all([
      getFormatGroups(false, controller.signal),
      api<TeamSnapshot[]>('/api/teams', { signal: controller.signal })
    ]).then(([groups, teamResult]) => {
      formatGroups = groups; teams = teamResult; formatsLoading = false;
    }).catch((caught) => {
      if (!controller.signal.aborted) {
        error = caught instanceof Error ? caught.message : String(caught);
        formatsLoading = false;
      }
    });
    return () => controller.abort();
  });

  function selectBattleFormat(next: FormatDescriptor) {
    battleFormat = next.id;
    descriptor = next;
    participants = participants.map((entry) => ({
      ...entry,
      teamSnapshotId: teams.some((team) => team.id === entry.teamSnapshotId && team.format === next.id)
        ? entry.teamSnapshotId
        : ''
    }));
    // Set once, never derived: a reactive `open` would re-close the panel on every keystroke.
    teamPanelOpen = next.custom_team_required
      && !teams.some((team) => team.format === next.id);
  }

  /** The situation every tournament team is built for. */
  function promptContext() {
    return {
      opponent: 'the rest of the field',
      tournament_name: name,
      tournament_structure: format.replace('_', '-'),
      rounds,
      games_per_series: Number(bestOf),
      team_reused_across_series: true
    };
  }

  async function copyTeamPrompt(index: number) {
    error = '';
    try {
      const result = await api<{ prompt: string }>('/api/teams/prompt', {
        method: 'POST',
        body: JSON.stringify({
          format: battleFormat,
          participant: participants[index].name || `Competitor ${index + 1}`,
          context: promptContext()
        })
      });
      if (await copyText(result.prompt)) {
        promptCopied = index;
        setTimeout(() => { if (promptCopied === index) promptCopied = null; }, 2000);
      } else {
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
            name: `${participants[index].name || `Competitor ${index + 1}`} · ${descriptor?.display_name || battleFormat}`,
            format: battleFormat,
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
        participants[index].teamSnapshotId = snapshot.id;
        participants = [...participants];
        teamDrafts = { ...teamDrafts, [index]: '' };
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      importing = null;
    }
  }

  function addParticipant() { participants = [...participants, participant(participants.length + 1)]; }
  function removeParticipant(index: number) { if (participants.length > 2) participants = participants.filter((_, item) => item !== index); }
  function next() { step = Math.min(steps.length, step + 1); }
  function back() { step = Math.max(1, step - 1); }
  function setAgent(index: number, agentType: AgentType) { participants[index].agentType = agentType; participants = [...participants]; }

  async function create() {
    if (needsCustomTeam && participants.some((entry) => !eligibleTeams.some((team) => team.id === entry.teamSnapshotId))) {
      step = 6;
      error = `Give every participant a validated ${descriptor?.display_name || battleFormat} team.`;
      return;
    }
    loading = true; error = '';
    try {
      const tournament = await api<TournamentArchive>('/api/tournaments', {
        method: 'POST',
        body: JSON.stringify({
          name, format, best_of: Number(bestOf), max_concurrent_matches: Number(concurrency),
          maximum_total_cost: maximumCost === '' ? null : Number(maximumCost),
          max_draw_replays: Number(maxDrawReplays), manual_scheduling: manualScheduling,
          randomize_seeds: randomizeSeeds,
          match_template: {
            engine: 'pokemon-showdown', format: battleFormat,
            generation: descriptor?.generation ?? 9,
            fair_prompt_mode: true,
            banter_enabled: banterEnabled,
            team_policy: needsCustomTeam ? 'fixed-per-tournament' : 'showdown-random',
            presentation: { theme: 'koala-dark', layout: 'standard-landscape' }
          },
          presentation: { theme: 'koala-dark', layout: 'tournament-bracket', show_model_names: true, show_series_score: true, show_tournament_name: true },
          participants: participants.map((entry) => ({
            display_name: entry.name, seed: randomizeSeeds ? null : Number(entry.seed),
            agent: {
              agent_type: entry.agentType,
              provider: entry.agentType === 'api' ? entry.provider : null,
              model: entry.agentType === 'api' ? entry.model : null,
              team_source: needsCustomTeam ? 'preset' : 'showdown-random',
              team_snapshot_id: needsCustomTeam ? entry.teamSnapshotId : null
            }
          }))
        })
      });
      await goto(`/tournaments/${tournament.id}/control`);
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); loading = false; }
  }
</script>

<div class="page-head"><div><span class="eyebrow">Tournament setup · Step {step} of {steps.length}</span><h1>{steps[step - 1]}</h1><p class="step-summary">Configure one durable tournament draft. Every choice stays reviewable until launch.</p></div><a class="button ghost compact cancel" href="/tournaments"><i class="ph ph-x" aria-hidden="true"></i>Exit setup</a></div>
<div class="progress-rail" role="progressbar" aria-label="Tournament setup progress" aria-valuemin="1" aria-valuemax="10" aria-valuenow={step}><span style={`width:${step * 10}%`}></span></div>
<ol class="stepper" aria-label="Tournament creation progress">{#each steps as label, index}<li class:active={index + 1 === step} class:complete={index + 1 < step} aria-current={index + 1 === step ? 'step' : undefined}><span>{index + 1 < step ? '✓' : index + 1}</span><small>{label}</small></li>{/each}</ol>

<form class="wizard panel" on:submit|preventDefault={step === 10 ? create : next}>
  {#if step === 1}<section><span class="eyebrow"><i class="ph ph-identification-card" aria-hidden="true"></i> Identity</span><h2>Name the production</h2><label>Tournament name<input bind:value={name} maxlength="120" required /></label></section>
  {:else if step === 2}<section><span class="eyebrow">Competition format</span><h2>Choose progression</h2><div class="choice-grid"><button type="button" class:chosen={format === 'single_elimination'} on:click={() => (format = 'single_elimination')}><strong>Single Elimination</strong><span>Seeded bracket, deterministic byes, automatic advancement.</span></button><button type="button" class:chosen={format === 'round_robin'} on:click={() => (format = 'round_robin')}><strong>Round Robin</strong><span>Every participant meets every other participant.</span></button></div></section>
  {:else if step === 3}<section><span class="eyebrow">Match template</span><h2>Pokémon Showdown baseline</h2>
      <FormatSelector groups={formatGroups} loading={formatsLoading} value={battleFormat} on:change={(event) => selectBattleFormat(event.detail)} />
      <div class="template"><span>Engine<strong>Pokémon Showdown</strong></span><span>Teams<strong>{needsCustomTeam ? 'One fixed team per participant' : 'Showdown generates every team'}</strong></span><span>Prompt<strong>Standard Fair · v3</strong></span><span>Presentation<strong>Koala Dark</strong></span></div>
      <p class="note">{needsCustomTeam ? 'Each participant brings one validated team, used for the whole tournament. Assign them in the agent-preset step.' : 'The tournament stores a secret-free snapshot. Reusable templates can also be managed through the API.'}</p>
      <label class="check-option"><input type="checkbox" bind:checked={banterEnabled} /> <span><strong>Optional banter</strong><small>Short situational lines may address the opponent and are spoken in replays.</small></span></label>
    </section>
  {:else if step === 4}<section><span class="eyebrow">Series rules</span><h2>Best-of-N</h2><div class="choice-grid three">{#each [1,3,5] as value}<button type="button" class:chosen={bestOf === value} on:click={() => (bestOf = value)}><strong>Best of {value}</strong><span>First to {Math.floor(value / 2) + 1} wins.</span></button>{/each}</div><label>Custom odd value<input type="number" min="1" max="99" step="2" bind:value={bestOf} /></label></section>
  {:else if step === 5}<section><span class="eyebrow"><i class="ph ph-users-three" aria-hidden="true"></i> Roster</span><h2>Add participants</h2><div class="participant-list">{#each participants as entry, index}<div><span>{index + 1}</span><input bind:value={entry.name} maxlength="120" required /><button type="button" aria-label={`Remove ${entry.name}`} on:click={() => removeParticipant(index)}><i class="ph ph-trash" aria-hidden="true"></i></button></div>{/each}</div><button type="button" class="button secondary" on:click={addParticipant}><i class="ph ph-user-plus" aria-hidden="true"></i>Add participant</button></section>
  {:else if step === 6}<section><span class="eyebrow">Agent snapshots</span><h2>Choose control mode</h2><div class="agent-list">{#each participants as entry, index}<article><strong>{entry.name}</strong><label>Agent preset<select value={entry.agentType} on:change={(event) => setAgent(index, event.currentTarget.value as AgentType)}><option value="random">Random baseline</option><option value="manual">Manual Web Chat</option><option value="api">Provider API</option></select></label>{#if entry.agentType === 'api'}<label>Provider<select value={entry.provider} on:change={(event) => chooseParticipantProvider(index, event.currentTarget.value as ProviderKind)}><option value="openai">OpenAI</option><option value="gemini">Gemini</option><option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option><option value="fake">Fake (development)</option></select></label><label>Model{#if entry.provider === 'deepseek'}<select bind:value={entry.model}>{#each DEEPSEEK_V4_MODELS as model}<option value={model}>{deepSeekModelLabel(model)}</option>{/each}</select>{:else}<input bind:value={entry.model} required />{/if}</label>{/if}
      {#if needsCustomTeam}
        <label class="team-slot">Team
          <select bind:value={entry.teamSnapshotId} required>
            <option value="">Select a validated team…</option>
            {#each eligibleTeams as team}<option value={team.id}>{team.name} · {team.source}</option>{/each}
          </select>
        </label>
        <details class="team-import" bind:open={teamPanelOpen}>
          <summary>Build this team from a prompt</summary>
          <div class="team-body">
            <p class="note">The prompt names {descriptor?.display_name || battleFormat}, this tournament's structure and {rounds} round(s), and that one team must carry the whole run.</p>
            <div class="team-actions">
              <button type="button" class="button secondary compact" on:click={() => copyTeamPrompt(index)}><i class={`ph ${promptCopied === index ? 'ph-check' : 'ph-copy'}`} aria-hidden="true"></i>{promptCopied === index ? 'Prompt copied' : 'Copy team prompt'}</button>
              <button type="button" class="button secondary compact" disabled={importing === index || !(teamDrafts[index] || '').trim()} on:click={() => importTeam(index)}><i class="ph ph-shield-check" aria-hidden="true"></i>{importing === index ? 'Validating…' : 'Validate and use'}</button>
            </div>
            {#if promptFallback[index]}
              <label class="prompt-fallback">Clipboard blocked — select and copy this<textarea rows="5" readonly value={promptFallback[index]}></textarea></label>
            {/if}
            <textarea rows="5" bind:value={teamDrafts[index]} placeholder={`Paste the Showdown export for ${descriptor?.name || battleFormat} here…`}></textarea>
            {#if teamValidation[index]}
              <div class="team-result" class:valid={teamValidation[index]?.valid}><strong>{teamValidation[index]?.valid ? '✓ Legal team — selected' : 'Invalid team'}</strong>{#each teamValidation[index]?.errors || [] as item}<p>{item}</p>{/each}</div>
            {/if}
          </div>
        </details>
      {/if}</article>{/each}</div></section>
  {:else if step === 7}<section><span class="eyebrow">Seeding</span><h2>Lock the order</h2><label class="check"><input type="checkbox" bind:checked={randomizeSeeds} />Randomize once when created</label>{#if !randomizeSeeds}<div class="seed-list">{#each participants as entry}<label>{entry.name}<input type="number" min="1" bind:value={entry.seed} /></label>{/each}</div>{/if}</section>
  {:else if step === 8}<section><span class="eyebrow">Scheduling</span><h2>Concurrency</h2><label>Maximum active tournament matches<input type="number" min="1" max="64" bind:value={concurrency} /></label><label class="check"><input type="checkbox" bind:checked={manualScheduling} />Game director starts each ready series manually</label><p class="note">Tournament concurrency is always bounded by the server-wide limit.</p></section>
  {:else if step === 9}<section><span class="eyebrow">Limits and presentation</span><h2>Cost, draws, presentation</h2><div class="field-grid"><label>Tournament cost limit (USD)<input type="number" min="0" step="0.01" bind:value={maximumCost} placeholder="No limit" /></label><label>Maximum draw replays<input type="number" min="0" max="25" bind:value={maxDrawReplays} /></label></div><div class="template"><span>Theme<strong>Koala Dark</strong></span><span>Overlay<strong>Bracket + live series</strong></span><span>Model labels<strong>Visible</strong></span><span>Series score<strong>Visible</strong></span></div></section>
  {:else}<section><span class="eyebrow">Final review</span><h2>{name}</h2><div class="review"><span><strong>{format.replace('_', ' ')}</strong>format</span><span><strong>{descriptor?.name || battleFormat}</strong>battle format</span><span><strong>Best of {bestOf}</strong>series</span><span><strong>{rounds}</strong>rounds</span><span><strong>{participants.length}</strong>participants</span><span><strong>{concurrency}</strong>concurrent matches</span><span><strong>{maximumCost || 'No limit'}</strong>tournament cost limit</span><span><strong>{needsCustomTeam ? `${participants.filter((entry) => entry.teamSnapshotId).length}/${participants.length} assigned` : 'Showdown random'}</strong>teams</span></div><p class="note">Creation produces an editable draft. The bracket or round-robin schedule becomes immutable when started.</p></section>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <footer>{#if step > 1}<button type="button" class="button secondary" on:click={back}><i class="ph ph-arrow-left" aria-hidden="true"></i>Back</button>{:else}<span></span>{/if}<button class="button" disabled={loading}>{loading ? 'Creating…' : step === 10 ? 'Create draft' : 'Continue'}{#if !loading}<i class={`ph ${step === 10 ? 'ph-check' : 'ph-arrow-right'}`} aria-hidden="true"></i>{/if}</button></footer>
</form>

<style>
  .step-summary{max-width:560px;margin:.7rem 0 0;color:var(--muted);line-height:1.5}.cancel{align-self:start}.progress-rail{height:3px;margin-bottom:.8rem;overflow:hidden;border-radius:999px;background:var(--border)}.progress-rail span{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),var(--p2));transition:width .35s cubic-bezier(.2,.8,.2,1)}.wizard section{animation:wizard-enter .28s cubic-bezier(.2,.8,.2,1)}.choice-grid button,.participant-list button{transition:transform .16s ease,border-color .16s ease,background .16s ease,box-shadow .16s ease}.choice-grid button:hover,.participant-list button:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border));box-shadow:var(--shadow-sm)}@keyframes wizard-enter{from{opacity:0;transform:translateX(8px)}to{opacity:1;transform:none}}
  .stepper{display:grid;grid-template-columns:repeat(10,1fr);gap:.35rem;margin:0 0 1rem;padding:0;list-style:none}.stepper li{display:grid;gap:.25rem;color:var(--muted)}.stepper li span{display:grid;place-items:center;width:28px;aspect-ratio:1;border:1px solid var(--border);border-radius:50%;font:0.72rem var(--mono)}.stepper li small{overflow:hidden;font:0.72rem var(--mono);text-overflow:ellipsis;white-space:nowrap}.stepper li.active,.stepper li.complete{color:var(--accent)}.stepper li.complete span{background:var(--accent);color:var(--accent-ink)}.wizard{padding:clamp(1.2rem,4vw,3rem);box-shadow:none}.wizard section{display:grid;gap:1.2rem;min-height:380px;align-content:start}.wizard h2{margin:0;font-size:clamp(1.6rem,4vw,2.6rem)}.wizard>footer{display:flex;justify-content:space-between;margin-top:2rem;padding-top:1rem;border-top:1px solid var(--border)}.choice-grid{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}.choice-grid.three{grid-template-columns:repeat(3,1fr)}.choice-grid button{display:grid;gap:.5rem;min-height:130px;padding:1.2rem;border:1px solid var(--border);border-radius:.8rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer}.choice-grid button.chosen{border-color:var(--accent);box-shadow:inset 0 0 0 2px var(--accent)}.choice-grid span,.note{color:var(--muted);font-size:.76rem;line-height:1.6}.template,.review{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;overflow:hidden;border:1px solid var(--border);border-radius:.8rem;background:var(--border)}.template span,.review span{display:grid;padding:1rem;background:var(--panel-strong);color:var(--muted);font:0.72rem var(--mono)}.template strong,.review strong{color:var(--text);font:700 .86rem var(--display);text-transform:capitalize}.participant-list,.agent-list{display:grid;gap:.6rem}.participant-list>div{display:grid;grid-template-columns:32px 1fr 44px;align-items:center;gap:.5rem}.participant-list>div>span{color:var(--accent);font:0.72rem var(--mono)}.participant-list button{height:44px;border:1px solid var(--border);border-radius:.55rem;background:var(--panel-strong);color:var(--danger);cursor:pointer}.agent-list article{display:grid;grid-template-columns:1fr repeat(3,minmax(130px,1fr));align-items:end;gap:.6rem;padding:.8rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.agent-list article{min-width:0}.agent-list article:has(.team-import){grid-template-columns:1fr}.team-slot{display:grid;gap:.3rem;min-width:0}
  /* Grid on an explicit wrapper: Chrome collapses every non-summary child of <details> into one
     ::details-content box, so a grid on <details> itself never reaches them. */
  .team-import{padding:.7rem .8rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel)}.team-import summary{color:var(--accent);font-size:.75rem;font-weight:650;cursor:pointer}.team-import summary:hover{color:var(--accent-strong)}.team-body{display:grid;gap:.55rem;margin-top:.55rem;min-width:0}.team-import textarea{width:100%;min-width:0;padding:.55rem .65rem;border:1px solid var(--border);border-radius:.6rem;background:var(--bg);color:var(--text);font:.72rem/1.5 var(--mono);resize:vertical}.team-actions{display:flex;flex-wrap:wrap;gap:.5rem}.prompt-fallback{display:grid;gap:.3rem;color:var(--warning);font-size:.72rem}.team-result{padding:.5rem .65rem;border:1px solid var(--danger);border-radius:.6rem;color:var(--danger);font-size:.75rem}.team-result.valid{border-color:var(--accent);color:var(--accent)}.team-result p{margin:.25rem 0 0;line-height:1.45}
  .seed-list,.field-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:.7rem}.check{display:flex;align-items:center;gap:.6rem}.check input{width:20px;min-height:20px}@media(max-width:760px){.page-head{align-items:stretch;flex-direction:column}.stepper li small{display:none}.choice-grid,.choice-grid.three,.template,.review,.field-grid,.seed-list{grid-template-columns:1fr}.agent-list article{grid-template-columns:1fr}.wizard section{min-height:0}}
  .check-option{display:flex;align-items:flex-start;gap:.55rem}.check-option input{width:17px;min-height:17px;margin-top:.15rem;accent-color:var(--accent)}.check-option span{display:grid;gap:.2rem}.check-option small{color:var(--muted);font-size:.72rem;line-height:1.45}
</style>
