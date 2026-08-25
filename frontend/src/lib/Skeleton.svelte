<script lang="ts">
  /**
   * Placeholder rows shown while a list loads.
   *
   * The pages this replaces each printed a line of prose — "Loading archive…",
   * "Loading tournaments…" — which gives no sense of how much is coming and makes the
   * page jump when it arrives. The placeholder holds roughly the shape of the rows that
   * will land instead.
   *
   * It is `aria-hidden` and paired with a visually hidden status line, so a screen reader
   * hears "Loading …" once rather than reading out a stack of empty boxes.
   */
  export let rows = 3;
  /** Announced to assistive technology while the placeholder is on screen. */
  export let label = 'Loading…';
  /** `row` for list items, `card` for taller panels. */
  export let variant: 'row' | 'card' = 'row';
</script>

<p class="visually-hidden" role="status">{label}</p>
<div class={`skeleton-stack ${variant}`} aria-hidden="true">
  {#each Array(rows) as _}
    <div class="skeleton-row panel">
      <span class="line wide"></span>
      <span class="line"></span>
    </div>
  {/each}
</div>

<style>
  .skeleton-stack{display:grid;gap:.65rem}
  .skeleton-row{display:grid;gap:.55rem;padding:1.1rem 1.2rem;box-shadow:none}
  .card .skeleton-row{padding:1.6rem 1.4rem}
  .line{height:.75rem;border-radius:999px;background:var(--surface)}
  .line.wide{width:min(38%,16rem);height:1rem}
  .line:not(.wide){width:min(72%,32rem)}
  @media(prefers-reduced-motion:no-preference){
    .line{animation:skeleton-pulse 1.4s ease-in-out infinite}
    .skeleton-row:nth-child(2) .line{animation-delay:.12s}
    .skeleton-row:nth-child(3) .line{animation-delay:.24s}
    .skeleton-row:nth-child(4) .line{animation-delay:.36s}
  }
  @keyframes skeleton-pulse{50%{opacity:.45}}
</style>
