<script lang="ts">
  import { trainerAssetUrl } from './presentation/assets';

  export let trainerId: string | null = null;
  export let name: string;
  export let accent = '#7bf0a2';
  export let compact = false;
  export let decorative = false;
  let failed = false;
  let previousId = '';

  $: if ((trainerId || '') !== previousId) {
    previousId = trainerId || '';
    failed = false;
  }
</script>

<span class:compact class="trainer" style={`--trainer-accent:${accent}`} aria-hidden={decorative}>
  <span class="rings"></span>
  {#if trainerId && !failed}
    <img
      src={trainerAssetUrl(trainerId)}
      alt={decorative ? '' : `${name} trainer sprite`}
      loading="lazy"
      decoding="async"
      on:error={() => (failed = true)}
    />
  {:else}
    <span class="fallback" aria-label={decorative ? undefined : `${name} trainer portrait unavailable`}>
      <i class="ph ph-user" aria-hidden="true"></i><b>{name.slice(0, 2).toUpperCase()}</b>
    </span>
  {/if}
</span>

<style>
  .trainer{position:relative;display:grid;place-items:end center;isolation:isolate;width:190px;height:190px;overflow:hidden;border:1px solid color-mix(in srgb,var(--trainer-accent) 50%,var(--border));border-radius:1rem;background:radial-gradient(circle at 50% 66%,color-mix(in srgb,var(--trainer-accent) 20%,transparent),transparent 49%),linear-gradient(145deg,color-mix(in srgb,var(--trainer-accent) 12%,var(--panel-strong)),var(--panel));box-shadow:inset 0 1px rgba(255,255,255,.08),0 18px 34px rgba(0,0,0,.2)}
  .trainer::after{content:"";position:absolute;z-index:-1;bottom:4%;width:72%;height:14%;border-radius:50%;background:color-mix(in srgb,var(--trainer-accent) 35%,transparent);filter:blur(10px)}
  .rings{position:absolute;inset:20%;z-index:-2;border:1px solid color-mix(in srgb,var(--trainer-accent) 28%,transparent);border-radius:50%;animation:spin 14s linear infinite}
  .rings::before,.rings::after{content:"";position:absolute;border:1px solid color-mix(in srgb,var(--trainer-accent) 22%,transparent);border-radius:50%}.rings::before{inset:-34%}.rings::after{inset:22%}
  img{display:block;width:92%;height:94%;object-fit:contain;image-rendering:pixelated;filter:drop-shadow(0 10px 8px rgba(0,0,0,.35));animation:stance 3.1s ease-in-out infinite;transform-origin:50% 100%}
  .fallback{align-self:center;display:grid;place-items:center;width:55%;aspect-ratio:1;border-radius:50%;background:color-mix(in srgb,var(--trainer-accent) 16%,var(--surface));color:color-mix(in srgb,var(--trainer-accent) 50%,white)}
  .fallback i{font-size:3.2rem}.fallback b{font:.68rem var(--mono)}
  .compact{width:64px;height:64px;border-radius:.6rem}.compact img{width:96%;height:96%}.compact .fallback i{font-size:1.2rem}.compact .fallback b{font-size:.45rem}
  @keyframes stance{0%,100%{transform:translateY(0) rotate(-.25deg)}50%{transform:translateY(-4px) rotate(.25deg)}}
  @keyframes spin{to{transform:rotate(360deg)}}
  @media(prefers-reduced-motion:reduce){img,.rings{animation:none}}
</style>
