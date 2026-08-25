<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { formatSummary, searchFormats } from './format-search';
  import type { FormatDescriptor, FormatGroup } from './types';

  export let groups: FormatGroup[] = [];
  export let value = 'gen9randombattle';
  export let loading = false;
  export let error = '';

  const dispatch = createEventDispatcher<{ change: FormatDescriptor }>();
  let query = '';
  let open = false;
  let listbox: HTMLDivElement | null = null;

  $: allFormats = groups.flatMap((group) => group.formats);
  $: selected = allFormats.find((format) => format.id === value) || null;
  $: matches = searchFormats(allFormats, query);
  $: visibleGroups = groups
    .map((group) => ({ ...group, formats: group.formats.filter((item) => matches.includes(item)) }))
    .filter((group) => group.formats.length);

  function choose(format: FormatDescriptor) {
    if (!format.supported) return;
    value = format.id;
    open = false;
    query = '';
    dispatch('change', format);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && open) {
      open = false;
      query = '';
    }
    if (event.key === 'Enter' && open && matches.length) {
      const first = matches.find((item) => item.supported);
      if (first) {
        event.preventDefault();
        choose(first);
      }
    }
  }
</script>

<svelte:window on:keydown={onKeydown} />

<div class="format-selector" class:open>
  <span class="field-label" id="format-selector-label">Battle format</span>
  <button
    type="button"
    class="trigger"
    aria-haspopup="listbox"
    aria-expanded={open}
    aria-labelledby="format-selector-label"
    on:click={() => (open = !open)}
  >
    {#if selected}
      <span class="trigger-name">{selected.display_name}</span>
      <span class="trigger-meta">{formatSummary(selected)}</span>
    {:else if loading}
      <span class="trigger-name">Loading formats…</span>
    {:else}
      <span class="trigger-name">{value}</span>
      <span class="trigger-meta">Unknown format</span>
    {/if}
    <i class="ph ph-caret-down" aria-hidden="true"></i>
  </button>

  {#if open}
    <div class="panel" bind:this={listbox}>
      <label class="search">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <input
          bind:value={query}
          placeholder="Search: gen 1, rby, random, ou…"
          aria-label="Search battle formats"
          autocomplete="off"
        />
      </label>
      <div class="results" role="listbox" aria-labelledby="format-selector-label" tabindex="-1">
        {#each visibleGroups as group (group.generation)}
          <div class="group">
            <p class="group-label">{group.label}</p>
            {#each group.formats as format (format.id)}
              <button
                type="button"
                role="option"
                aria-selected={format.id === value}
                class:selected={format.id === value}
                class:unsupported={!format.supported}
                disabled={!format.supported}
                title={format.unsupported_reason || format.name}
                on:click={() => choose(format)}
              >
                <span class="option-name">{format.display_name}</span>
                <span class="option-meta">{formatSummary(format)}</span>
                {#if !format.supported}
                  <span class="option-note">{format.unsupported_reason}</span>
                {/if}
              </button>
            {/each}
          </div>
        {/each}
        {#if !visibleGroups.length}
          <p class="empty">{loading ? 'Loading the Showdown format registry…' : `No format matches “${query}”.`}</p>
        {/if}
      </div>
      {#if error}<p class="selector-error">{error}</p>{/if}
    </div>
  {/if}
</div>

<style>
  .format-selector{position:relative;display:grid;gap:.45rem}
  .field-label{color:var(--muted);font-size:.78rem;font-weight:600}
  .trigger{display:grid;grid-template-columns:1fr auto;align-items:center;gap:.2rem .6rem;width:100%;min-height:56px;padding:.6rem .85rem;border:1px solid var(--border);border-radius:.65rem;background:var(--panel-strong);color:var(--text);text-align:left;cursor:pointer;transition:border-color .16s ease,box-shadow .16s ease}
  .trigger:hover{border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}
  .format-selector.open .trigger{border-color:var(--accent);box-shadow:var(--focus)}
  .trigger-name{grid-area:1/1;font-size:.95rem;font-weight:700}
  .trigger-meta{grid-area:2/1;color:var(--muted);font:0.72rem var(--mono);letter-spacing:.06em}
  .trigger .ph{grid-area:1/2/3/3;align-self:center;color:var(--muted);font-size:1.1rem;line-height:1;transition:transform .18s ease}
  .format-selector.open .trigger .ph{transform:rotate(180deg)}
  .panel{position:absolute;z-index:30;top:calc(100% + .35rem);right:0;left:0;overflow:hidden;border:1px solid var(--border);border-radius:.8rem;background:var(--panel);box-shadow:var(--shadow)}
  .search{display:flex;align-items:center;gap:.5rem;padding:.55rem .75rem;border-bottom:1px solid var(--border)}
  .search .ph{color:var(--muted)}
  .search input{min-height:34px;padding:0;border:0;background:transparent}
  .search input:focus{box-shadow:none}
  .results{max-height:min(52vh,420px);overflow-y:auto;padding:.35rem}
  .group+.group{margin-top:.35rem;padding-top:.35rem;border-top:1px solid var(--border)}
  .group-label{margin:.3rem .55rem .25rem;color:var(--accent);font:600 0.72rem var(--mono);letter-spacing:.1em;text-transform:uppercase}
  .results button{display:grid;gap:.1rem;width:100%;padding:.45rem .55rem;border:0;border-radius:.5rem;background:transparent;color:var(--text);text-align:left;cursor:pointer}
  .results button:hover:not(:disabled){background:var(--surface)}
  .results button.selected{background:var(--surface);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--accent) 45%,transparent)}
  .results button.unsupported{cursor:not-allowed;opacity:.55}
  .option-name{font-size:.85rem;font-weight:650}
  .option-meta{color:var(--muted);font:0.72rem var(--mono);letter-spacing:.05em}
  .option-note{color:var(--warning);font-size:0.72rem}
  .empty,.selector-error{margin:0;padding:.9rem;color:var(--muted);font-size:.78rem}
  .selector-error{color:var(--danger);border-top:1px solid var(--border)}
</style>
