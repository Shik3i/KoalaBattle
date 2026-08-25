<script lang="ts">
  import { pokemonTypeColor } from './challenge';

  export let types: string[];
  export let compact = false;
</script>

<span class:compact class="type-list" aria-label={`Types: ${types.join(', ')}`}>
  {#each types as type}
    <span class="type" style={`--type-color:${pokemonTypeColor(type)}`}>{type}</span>
  {/each}
</span>

<style>
  .type-list{display:flex;flex-wrap:wrap;gap:.35rem}
  .type{display:inline-flex;align-items:center;min-height:24px;padding:.25rem .55rem;border:1px solid color-mix(in srgb,var(--type-color) 82%,#20242a);border-radius:999px;background:linear-gradient(135deg,color-mix(in srgb,var(--type-color) 78%,white),color-mix(in srgb,var(--type-color) 58%,white));color:#14181d;font:800 0.72rem var(--mono);letter-spacing:.055em;text-transform:uppercase;box-shadow:inset 0 1px rgba(255,255,255,.35),0 2px 8px color-mix(in srgb,var(--type-color) 18%,transparent)}
  .compact{gap:.22rem}.compact .type{min-height:22px;padding:.2rem .45rem;font-size:0.72rem}
</style>
