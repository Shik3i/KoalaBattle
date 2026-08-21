<script lang="ts">
  import { onMount } from 'svelte';
  import { api, copyText } from '$lib/api';
  import { challengeStatusLabel } from '$lib/challenge';
  import type { ChallengeRunSummary, PricingStatus } from '$lib/types';

  const setupCommands = `.venv/bin/python scripts/setup_draft_prices.py import ./my-board.xlsx \\
  --board-name "My SV NatDex copy" \\
  --sheet Pokedex \\
  --price-column "SV NatDex"
.venv/bin/python scripts/setup_draft_prices.py verify
.venv/bin/python scripts/setup_draft_prices.py status`;

  let runs: ChallengeRunSummary[] = [];
  let pricing: PricingStatus | null = null;
  let historyLoading = true;
  let pricingLoading = true;
  let historyError = '';
  let pricingError = '';
  let copied = false;

  onMount(() => {
    void loadHistory();
    void loadPricing();
  });

  async function loadHistory() {
    historyLoading = true;
    try {
      runs = await api<ChallengeRunSummary[]>('/api/challenges');
      historyError = '';
    } catch (caught) {
      historyError = caught instanceof Error ? caught.message : String(caught);
    } finally {
      historyLoading = false;
    }
  }

  async function loadPricing() {
    pricingLoading = true;
    try {
      pricing = await api<PricingStatus>('/api/challenge-prices/status');
      pricingError = '';
    } catch (caught) {
      pricingError = caught instanceof Error ? caught.message : String(caught);
    } finally {
      pricingLoading = false;
    }
  }

  async function copySetup() {
    copied = await copyText(setupCommands);
  }

  function currentProgress(run: ChallengeRunSummary) {
    if (run.status === 'completed') return 'Champion cleared';
    if (run.status === 'cancelled') return 'Run ended';
    if (run.status === 'drafting') return 'Continue the draft';
    if (run.status === 'training' || run.status === 'team_review') return 'Finish the roster';
    return `Stage ${Math.min(run.current_stage_index + 1, run.stage_count)} of ${run.stage_count}`;
  }
</script>

<div class="page-head challenge-head">
  <div>
    <span class="eyebrow">Draft · train · battle · progress</span>
    <h1>Challenges</h1>
    <p>Build one roster with Draft Credits, train it with a separate EV budget, then clear a recorded campaign at fair, equal stage levels.</p>
  </div>
  {#if pricing?.ready}
    <a class="button" href="/challenges/new"><i class="ph ph-plus" aria-hidden="true"></i>New Challenge</a>
  {:else}
    <a class="button secondary" href="#pricing-setup"><i class="ph ph-database" aria-hidden="true"></i>Configure pricing</a>
  {/if}
</div>

<section class="mode-intro panel" aria-labelledby="challenge-intro-title">
  <div class="intro-copy">
    <span class="eyebrow">Kanto Gym Gauntlet</span>
    <h2 id="challenge-intro-title">Your draft. Your team. Thirteen real battles.</h2>
    <p>Draft six Pokémon from Generation + Type offers, allocate training, finish legal sets, then face the Gym Leaders, Elite Four, and Champion.</p>
  </div>
  <div class="intro-facts">
    <span><i class="ph ph-coins" aria-hidden="true"></i><strong>Draft Credits</strong><small>Imported board prices; no tier conversion.</small></span>
    <span><i class="ph ph-barbell" aria-hidden="true"></i><strong>Training Budget</strong><small>EVs are allocated separately after drafting.</small></span>
    <span><i class="ph ph-scales" aria-hidden="true"></i><strong>Equal levels</strong><small>Both teams use the exact stage level.</small></span>
    <span><i class="ph ph-record" aria-hidden="true"></i><strong>Recorded matches</strong><small>Play yourself or use AI; every stage gets a replay.</small></span>
  </div>
  <details>
    <summary>How a Challenge works</summary>
    <ol>
      <li>Choose who drafts and who battles. These choices are independent.</li>
      <li>Spend Draft Credits on six deterministic, budget-safe offers.</li>
      <li>Allocate the shared EV budget and complete legal Showdown sets.</li>
      <li>Play every stage through the normal KoalaBattle match engine.</li>
    </ol>
  </details>
</section>

{#if pricingLoading}
  <section class="pricing-loading panel" role="status"><span class="spinner"></span><div><strong>Checking Draft pricing…</strong><p>Challenge history remains available while setup is checked.</p></div></section>
{:else if pricingError}
  <section class="setup panel" role="alert"><div><span class="eyebrow">Pricing status unavailable</span><h2>Challenge setup could not be checked</h2><p>{pricingError}</p></div><button class="button secondary" on:click={loadPricing}>Retry status check</button></section>
{:else if pricing && !pricing.ready}
  <section id="pricing-setup" class="setup panel" aria-labelledby="pricing-title">
    <div class="setup-heading"><div><span class="eyebrow">One-time operator setup</span><h2 id="pricing-title">Draft pricing is not configured yet</h2><p>Challenges need exact Pokémon prices from a locally imported Draft Board. KoalaBattle does not bundle that third-party dataset and never invents prices from OU/UU tiers.</p></div><i class="ph ph-database" aria-hidden="true"></i></div>
    <div class="next-step"><strong>Next step</strong><p>From the KoalaBattle repository, import a CSV, TSV, or XLSX copy you are permitted to use, then verify it:</p><pre>{setupCommands}</pre><button class="button secondary compact" on:click={copySetup}><i class={`ph ${copied ? 'ph-check' : 'ph-copy'}`} aria-hidden="true"></i>{copied ? 'Commands copied' : 'Copy commands'}</button></div>
    {#if pricing.errors.length}<div class="setup-errors" role="status">{#each pricing.errors as item}<p>{item}</p>{/each}</div>{/if}
    <details><summary>Google Sheets and data ownership</summary><p>An explicitly supplied public Google Sheets URL to your own copy is supported. The importer downloads it once; ordinary Challenge use is local and requires no pricing network access.</p><pre>.venv/bin/python scripts/setup_draft_prices.py import --url "https://docs.google.com/spreadsheets/d/.../edit" --board-name "My copy" --sheet Pokedex --price-column "SV NatDex"</pre></details>
  </section>
{:else if pricing}
  <section class="coverage panel" aria-labelledby="pricing-ready-title">
    <div><span class="eyebrow">Draft pricing ready</span><h2 id="pricing-ready-title">{pricing.board_name}</h2><p>{pricing.context} · imported {new Date(pricing.imported_at || '').toLocaleString()}</p></div>
    <div class="coverage-score"><strong>{pricing.priced_entries}</strong><span>priced matches</span><small>of {pricing.eligible_entries} pinned species/forms</small></div>
    <div class="verification" class:verified={pricing.source_verified}><i class={`ph ${pricing.source_verified ? 'ph-seal-check' : 'ph-warning'}`} aria-hidden="true"></i><span><strong>{pricing.source_verified ? 'Source verified' : 'Verification needed'}</strong><small>{pricing.verification_detail}</small></span></div>
    <dl><div><dt>Catalog</dt><dd><code>{pricing.catalog_hash?.slice(0, 12)}</code></dd></div><div><dt>Imported rows</dt><dd>{pricing.parsed_entries}</dd></div><div><dt>Banned</dt><dd>{pricing.banned_entries}</dd></div><div><dt>Missing price</dt><dd>{pricing.missing_entries}</dd></div><div><dt>Unsupported</dt><dd>{pricing.unsupported_entries}</dd></div></dl>
    <details><summary>Review {pricing.excluded_entries.length} excluded rows</summary><ul>{#each pricing.excluded_entries.slice(0, 100) as item}<li><b>{item.species}</b><span>{item.state} · {item.reason}</span></li>{/each}</ul>{#if pricing.excluded_entries.length > 100}<p>Showing the first 100 exclusions.</p>{/if}</details>
  </section>
{/if}

<section class="history" aria-labelledby="history-title">
  <header><div><span class="eyebrow">Durable run history</span><h2 id="history-title">Your Challenges</h2></div>{#if runs.length}<span>{runs.length} saved {runs.length === 1 ? 'run' : 'runs'}</span>{/if}</header>
  {#if historyLoading}<p class="lede" role="status">Loading Challenge history…</p>{:else if historyError}<section class="empty panel" role="alert"><h3>History could not be loaded</h3><p>{historyError}</p><button class="button secondary" on:click={loadHistory}>Retry</button></section>{:else if !runs.length}<section class="empty panel"><i class="ph ph-map-trifold" aria-hidden="true"></i><h3>No Challenges yet</h3><p>When pricing is ready, create a Kanto run. Your draft, stage matches, results, and replays will stay here.</p>{#if pricing?.ready}<a class="button" href="/challenges/new">Start the Kanto Gauntlet</a>{:else}<a class="button secondary" href="#pricing-setup">Finish pricing setup</a>{/if}</section>{:else}
    <div class="run-list">
      {#each runs as run}
        <a class="panel" href={`/challenges/${run.id}`}>
          <div class="run-name"><span class="eyebrow">{run.definition_name}</span><h3>{run.name}</h3><small>Updated {new Date(run.updated_at).toLocaleString()}</small></div>
          <div class="progress"><strong>{run.stages_cleared}/{run.stage_count}</strong><span>stages cleared</span></div>
          <div class="run-state"><span class={`status-pill ${run.status}`}>{challengeStatusLabel(run.status)}</span><small>{currentProgress(run)}</small></div>
          <i class="ph ph-caret-right" aria-hidden="true"></i>
        </a>
      {/each}
    </div>
  {/if}
</section>

<style>
  .challenge-head{margin-bottom:1rem}.challenge-head>div{max-width:720px}.challenge-head p,.panel p,.empty p{color:var(--muted);line-height:1.55}.mode-intro{display:grid;grid-template-columns:1.05fr 1.6fr;gap:1.25rem;padding:1.4rem;border-color:color-mix(in srgb,var(--accent) 35%,var(--border));background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 7%,var(--panel)),var(--panel))}.intro-copy h2{margin:.3rem 0;font-size:1.55rem}.intro-copy p{margin-bottom:0}.intro-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem}.intro-facts>span{display:grid;grid-template-columns:auto 1fr;gap:.12rem .55rem;padding:.7rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong)}.intro-facts i{grid-row:1/3;align-self:center;color:var(--accent);font-size:1.25rem}.intro-facts strong{font-size:.78rem}.intro-facts small{color:var(--muted);font:.62rem/1.35 var(--mono)}.mode-intro>details{grid-column:1/-1}.mode-intro ol{margin:.7rem 0 0;padding-left:1.2rem;color:var(--muted);font-size:.78rem;line-height:1.65}.pricing-loading,.setup{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-top:1rem;padding:1.3rem}.pricing-loading strong{display:block}.pricing-loading p{margin:.2rem 0}.spinner{width:1.4rem;aspect-ratio:1;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.setup{display:grid;border-color:color-mix(in srgb,var(--warning) 45%,var(--border))}.setup-heading{display:flex;justify-content:space-between;gap:1rem}.setup-heading h2,.coverage h2{margin:.3rem 0}.setup-heading>i{color:var(--warning);font-size:2.2rem}.next-step{position:relative;padding:1rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.next-step>p{margin:.3rem 0 .7rem}.next-step .button{margin-top:.65rem}.setup pre{overflow:auto;margin:0;padding:.85rem;border:1px solid var(--border);border-radius:.55rem;background:var(--bg);color:var(--accent);font:.66rem/1.55 var(--mono);white-space:pre-wrap}.setup-errors{padding:.75rem;border-radius:.55rem;background:color-mix(in srgb,var(--warning) 8%,transparent)}.setup-errors p{margin:.2rem 0;color:var(--warning)}.coverage{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:1rem;margin-top:1rem;padding:1.25rem}.coverage-score{display:grid;text-align:right}.coverage-score strong{color:var(--accent);font-size:2rem}.coverage-score span,.coverage-score small{color:var(--muted);font:.62rem var(--mono)}.verification{display:flex;align-items:center;gap:.55rem;padding:.7rem;border:1px solid color-mix(in srgb,var(--warning) 45%,var(--border));border-radius:.6rem}.verification.verified{border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}.verification i{color:var(--warning);font-size:1.25rem}.verification.verified i{color:var(--accent)}.verification span{display:grid}.verification small{max-width:190px;color:var(--muted);font:.58rem/1.35 var(--mono)}.coverage dl{grid-column:1/-1;display:grid;grid-template-columns:repeat(5,1fr);gap:1px;overflow:hidden;margin:0;border:1px solid var(--border);border-radius:.6rem;background:var(--border)}.coverage dl div{display:grid;padding:.65rem;background:var(--panel-strong)}.coverage dt{color:var(--muted);font:.58rem var(--mono)}.coverage dd{margin:.2rem 0 0;font-weight:700}.coverage details{grid-column:1/-1}.coverage ul{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.4rem;margin:.7rem 0 0;padding:0;list-style:none}.coverage li{display:grid;padding:.5rem;border:1px solid var(--border);border-radius:.5rem}.coverage li span{color:var(--muted);font:.62rem var(--mono)}.history{margin-top:1.5rem}.history>header{display:flex;align-items:end;justify-content:space-between;margin-bottom:.65rem}.history h2{margin:.25rem 0}.history>header>span{color:var(--muted);font:.65rem var(--mono)}.run-list{display:grid;gap:.65rem}.run-list>a{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(180px,auto) auto;align-items:center;gap:1.4rem;padding:1rem 1.2rem;box-shadow:none;transition:transform .16s ease,border-color .16s ease}.run-list>a:hover,.run-list>a:focus-visible{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}.run-name h3{margin:.25rem 0}.run-name small,.run-state small{display:block;color:var(--muted);font:.58rem var(--mono)}.progress{display:grid;text-align:right}.progress strong{font-size:1.2rem}.progress span{color:var(--muted);font:.58rem var(--mono)}.run-state{display:grid;justify-items:start;gap:.25rem}.empty{display:grid;place-items:center;padding:3rem;text-align:center}.empty>.ph{color:var(--accent);font-size:2rem}@media(max-width:850px){.page-head{align-items:stretch;flex-direction:column}.mode-intro{grid-template-columns:1fr}.intro-facts{grid-template-columns:1fr 1fr}.coverage{grid-template-columns:1fr 1fr}.coverage-score{text-align:left}.verification{grid-column:1/-1}.coverage dl{grid-template-columns:repeat(3,1fr)}.run-list>a{grid-template-columns:1fr auto}.run-list>a>.ph{display:none}.run-state{grid-column:1/-1}.progress{text-align:right}}@media(max-width:560px){.intro-facts,.coverage,.coverage dl,.run-list>a{grid-template-columns:1fr}.coverage-score,.progress{text-align:left}.setup-heading{align-items:flex-start}.setup pre{font-size:.58rem}.history>header{align-items:flex-start;flex-direction:column}}
</style>
