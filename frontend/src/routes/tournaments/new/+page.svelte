<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import type { AgentType, TournamentArchive } from '$lib/types';

  interface ParticipantDraft { name: string; seed: number; agentType: AgentType; provider: string; model: string }
  const participant = (index: number): ParticipantDraft => ({ name: `Competitor ${index}`, seed: index, agentType: 'random', provider: 'openai', model: 'gpt-5-mini' });
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
  let participants = [participant(1), participant(2), participant(3), participant(4)];
  let loading = false;
  let error = '';

  function addParticipant() { participants = [...participants, participant(participants.length + 1)]; }
  function removeParticipant(index: number) { if (participants.length > 2) participants = participants.filter((_, item) => item !== index); }
  function next() { step = Math.min(10, step + 1); }
  function back() { step = Math.max(1, step - 1); }
  function setAgent(index: number, agentType: AgentType) { participants[index].agentType = agentType; participants = [...participants]; }

  async function create() {
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
            engine: 'pokemon-showdown', format: 'gen9randombattle', generation: 9,
            fair_prompt_mode: true,
            presentation: { theme: 'koala-dark', layout: 'standard-landscape' }
          },
          presentation: { theme: 'koala-dark', layout: 'tournament-bracket', show_model_names: true, show_series_score: true, show_tournament_name: true },
          participants: participants.map((entry) => ({
            display_name: entry.name, seed: randomizeSeeds ? null : Number(entry.seed),
            agent: {
              agent_type: entry.agentType,
              provider: entry.agentType === 'api' ? entry.provider : null,
              model: entry.agentType === 'api' ? entry.model : null
            }
          }))
        })
      });
      await goto(`/tournaments/${tournament.id}/control`);
    } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); loading = false; }
  }
</script>

<div class="page-head"><div><span class="eyebrow">Tournament wizard · Step {step} of 10</span><h1>{steps[step - 1]}</h1></div><a class="button secondary" href="/tournaments">Cancel</a></div>
<ol class="stepper" aria-label="Tournament creation progress">{#each steps as label, index}<li class:active={index + 1 === step} class:complete={index + 1 < step}><span>{index + 1}</span><small>{label}</small></li>{/each}</ol>

<form class="wizard panel" on:submit|preventDefault={step === 10 ? create : next}>
  {#if step === 1}<section><span class="eyebrow">Identity</span><h2>Name the production</h2><label>Tournament name<input bind:value={name} maxlength="120" required /></label></section>
  {:else if step === 2}<section><span class="eyebrow">Competition format</span><h2>Choose progression</h2><div class="choice-grid"><button type="button" class:chosen={format === 'single_elimination'} on:click={() => (format = 'single_elimination')}><strong>Single Elimination</strong><span>Seeded bracket, deterministic byes, automatic advancement.</span></button><button type="button" class:chosen={format === 'round_robin'} on:click={() => (format = 'round_robin')}><strong>Round Robin</strong><span>Every participant meets every other participant.</span></button></div></section>
  {:else if step === 3}<section><span class="eyebrow">Match template</span><h2>Pokémon Showdown baseline</h2><div class="template"><span>Engine<strong>Pokémon Showdown</strong></span><span>Format<strong>Gen 9 Random Battle</strong></span><span>Prompt<strong>Standard Fair · v3</strong></span><span>Presentation<strong>Koala Dark</strong></span></div><p class="note">The tournament stores a secret-free snapshot. Reusable templates can also be managed through the API.</p></section>
  {:else if step === 4}<section><span class="eyebrow">Series rules</span><h2>Best-of-N</h2><div class="choice-grid three">{#each [1,3,5] as value}<button type="button" class:chosen={bestOf === value} on:click={() => (bestOf = value)}><strong>Best of {value}</strong><span>First to {Math.floor(value / 2) + 1} wins.</span></button>{/each}</div><label>Custom odd value<input type="number" min="1" max="99" step="2" bind:value={bestOf} /></label></section>
  {:else if step === 5}<section><span class="eyebrow">Roster</span><h2>Add participants</h2><div class="participant-list">{#each participants as entry, index}<div><span>{index + 1}</span><input bind:value={entry.name} maxlength="120" required /><button type="button" aria-label={`Remove ${entry.name}`} on:click={() => removeParticipant(index)}>×</button></div>{/each}</div><button type="button" class="button secondary" on:click={addParticipant}>Add participant</button></section>
  {:else if step === 6}<section><span class="eyebrow">Agent snapshots</span><h2>Choose control mode</h2><div class="agent-list">{#each participants as entry, index}<article><strong>{entry.name}</strong><label>Agent preset<select value={entry.agentType} on:change={(event) => setAgent(index, event.currentTarget.value as AgentType)}><option value="random">Random baseline</option><option value="manual">Manual Web Chat</option><option value="api">Provider API</option></select></label>{#if entry.agentType === 'api'}<label>Provider<select bind:value={entry.provider}><option value="openai">OpenAI</option><option value="gemini">Gemini</option><option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option><option value="fake">Fake (development)</option></select></label><label>Model<input bind:value={entry.model} required /></label>{/if}</article>{/each}</div></section>
  {:else if step === 7}<section><span class="eyebrow">Seeding</span><h2>Lock the order</h2><label class="check"><input type="checkbox" bind:checked={randomizeSeeds} />Randomize once when created</label>{#if !randomizeSeeds}<div class="seed-list">{#each participants as entry}<label>{entry.name}<input type="number" min="1" bind:value={entry.seed} /></label>{/each}</div>{/if}</section>
  {:else if step === 8}<section><span class="eyebrow">Scheduling</span><h2>Concurrency</h2><label>Maximum active tournament matches<input type="number" min="1" max="64" bind:value={concurrency} /></label><label class="check"><input type="checkbox" bind:checked={manualScheduling} />Game director starts each ready series manually</label><p class="note">Tournament concurrency is always bounded by the server-wide limit.</p></section>
  {:else if step === 9}<section><span class="eyebrow">Safety envelope</span><h2>Cost, draws, presentation</h2><div class="field-grid"><label>Tournament cost limit (USD)<input type="number" min="0" step="0.01" bind:value={maximumCost} placeholder="No limit" /></label><label>Maximum draw replays<input type="number" min="0" max="25" bind:value={maxDrawReplays} /></label></div><div class="template"><span>Theme<strong>Koala Dark</strong></span><span>Overlay<strong>Bracket + live series</strong></span><span>Model labels<strong>Visible</strong></span><span>Series score<strong>Visible</strong></span></div></section>
  {:else}<section><span class="eyebrow">Final review</span><h2>{name}</h2><div class="review"><span><strong>{format.replace('_', ' ')}</strong>format</span><span><strong>Best of {bestOf}</strong>series</span><span><strong>{participants.length}</strong>participants</span><span><strong>{concurrency}</strong>concurrent matches</span><span><strong>{maximumCost || 'No limit'}</strong>tournament cost limit</span><span><strong>{participants.filter((entry) => entry.agentType === 'manual').length}</strong>manual participants</span></div><p class="note">Creation produces an editable draft. The bracket or round-robin schedule becomes immutable when started.</p></section>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <footer>{#if step > 1}<button type="button" class="button secondary" on:click={back}>← Back</button>{:else}<span></span>{/if}<button class="button" disabled={loading}>{loading ? 'Creating…' : step === 10 ? 'Create draft →' : 'Continue →'}</button></footer>
</form>

<style>
  .stepper{display:grid;grid-template-columns:repeat(10,1fr);gap:.35rem;margin:0 0 1rem;padding:0;list-style:none}.stepper li{display:grid;gap:.25rem;color:var(--muted)}.stepper li span{display:grid;place-items:center;width:28px;aspect-ratio:1;border:1px solid var(--border);border-radius:50%;font:.65rem var(--mono)}.stepper li small{overflow:hidden;font:.55rem var(--mono);text-overflow:ellipsis;white-space:nowrap}.stepper li.active,.stepper li.complete{color:var(--accent)}.stepper li.complete span{background:var(--accent);color:var(--accent-ink)}.wizard{padding:clamp(1.2rem,4vw,3rem);box-shadow:none}.wizard section{display:grid;gap:1.2rem;min-height:380px;align-content:start}.wizard h2{margin:0;font-size:clamp(1.6rem,4vw,2.6rem)}.wizard>footer{display:flex;justify-content:space-between;margin-top:2rem;padding-top:1rem;border-top:1px solid var(--border)}.choice-grid{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}.choice-grid.three{grid-template-columns:repeat(3,1fr)}.choice-grid button{display:grid;gap:.5rem;min-height:130px;padding:1.2rem;border:1px solid var(--border);border-radius:.8rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer}.choice-grid button.chosen{border-color:var(--accent);box-shadow:inset 0 0 0 2px var(--accent)}.choice-grid span,.note{color:var(--muted);font-size:.76rem;line-height:1.6}.template,.review{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;overflow:hidden;border:1px solid var(--border);border-radius:.8rem;background:var(--border)}.template span,.review span{display:grid;padding:1rem;background:var(--panel-strong);color:var(--muted);font:.62rem var(--mono)}.template strong,.review strong{color:var(--text);font:700 .86rem var(--display);text-transform:capitalize}.participant-list,.agent-list{display:grid;gap:.6rem}.participant-list>div{display:grid;grid-template-columns:32px 1fr 44px;align-items:center;gap:.5rem}.participant-list>div>span{color:var(--accent);font:.7rem var(--mono)}.participant-list button{height:44px;border:1px solid var(--border);border-radius:.55rem;background:var(--panel-strong);color:var(--danger);cursor:pointer}.agent-list article{display:grid;grid-template-columns:1fr repeat(3,minmax(130px,1fr));align-items:end;gap:.6rem;padding:.8rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.seed-list,.field-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:.7rem}.check{display:flex;align-items:center;gap:.6rem}.check input{width:20px;min-height:20px}@media(max-width:760px){.page-head{align-items:stretch;flex-direction:column}.stepper li small{display:none}.choice-grid,.choice-grid.three,.template,.review,.field-grid,.seed-list{grid-template-columns:1fr}.agent-list article{grid-template-columns:1fr}.wizard section{min-height:0}}
</style>
