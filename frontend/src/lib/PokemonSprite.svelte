<script lang="ts">
  import { pokemonAssetUrl } from './presentation/assets';

  export let species: string;
  export let animated = true;
  export let size: 'small' | 'medium' | 'large' = 'medium';
  export let decorative = false;
  let failed = false;
  let previousSpecies = '';

  $: if (species !== previousSpecies) {
    previousSpecies = species;
    failed = false;
  }
</script>

<span class={`pokemon-sprite ${size}`} aria-hidden={decorative}>
  {#if !failed}
    <img
      src={pokemonAssetUrl(species, 'front', animated)}
      alt={decorative ? '' : `${species} sprite`}
      loading="lazy"
      decoding="async"
      on:error={() => (failed = true)}
    />
  {:else}
    <span class="fallback" aria-label={decorative ? undefined : `${species} sprite unavailable`}>
      <i class="ph ph-circle-dashed" aria-hidden="true"></i>
      <b>{species.slice(0, 1)}</b>
    </span>
  {/if}
</span>

<style>
  .pokemon-sprite{position:relative;display:grid;place-items:center;isolation:isolate;flex:0 0 auto;width:88px;height:78px}
  .pokemon-sprite::before{content:"";position:absolute;z-index:-1;bottom:5%;width:68%;height:17%;border-radius:50%;background:rgba(0,0,0,.25);filter:blur(5px);animation:shadow 2.4s ease-in-out infinite}
  img{position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:contain;image-rendering:pixelated;filter:drop-shadow(0 8px 8px rgba(0,0,0,.25));animation:idle 2.4s ease-in-out infinite;transform-origin:50% 100%}
  .small{width:50px;height:46px}.large{width:148px;height:132px}
  .fallback{display:grid;place-items:center;width:70%;aspect-ratio:1;border:1px solid color-mix(in srgb,var(--accent) 35%,var(--border));border-radius:50%;background:color-mix(in srgb,var(--accent) 8%,var(--surface));color:var(--muted)}
  .fallback i{font-size:1.7rem}.fallback b{position:absolute;font:.58rem var(--mono)}
  @keyframes idle{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-5px) scale(1.018)}}
  @keyframes shadow{0%,100%{transform:scale(1);opacity:.8}50%{transform:scale(.88);opacity:.55}}
  @media(prefers-reduced-motion:reduce){img,.pokemon-sprite::before{animation:none}}
</style>
