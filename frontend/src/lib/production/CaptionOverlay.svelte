<script lang="ts">
  import type { ProductionCue } from '../types';
  export let cue: ProductionCue | null = null;
  export let elapsedMs = 0;
  export let vertical = false;
  $: relative = cue ? elapsedMs - cue.start_ms : 0;
  $: segments = (cue?.payload.segments || []) as Array<{ text: string; start_ms: number; end_ms: number }>;
  $: active = segments.find((segment) => segment.start_ms <= relative && segment.end_ms > relative);
</script>

{#if active}
  <div class:vertical class="caption-safe" aria-live="polite" aria-atomic="true">
    <span><i>LIVE CAPTION</i>{active.text}</span>
  </div>
{/if}

<style>
  .caption-safe{position:absolute;z-index:24;left:11%;right:11%;bottom:8%;display:flex;justify-content:center;pointer-events:none}.caption-safe span{position:relative;max-width:70rem;padding:.65rem 1.25rem .7rem;border:1px solid rgba(124,255,173,.45);border-radius:0;background:rgba(2,5,8,.92);box-shadow:0 12px 32px rgba(0,0,0,.45);clip-path:polygon(2% 0,100% 0,98% 100%,0 100%);color:white;font:850 clamp(1rem,2.05vw,1.9rem)/1.2 system-ui;text-align:center;text-wrap:balance}.caption-safe i{display:block;margin-bottom:.22rem;color:#79ffa9;font:900 .38em/1 ui-monospace,monospace;font-style:normal;letter-spacing:.16em}.caption-safe.vertical{left:6%;right:6%;bottom:8%}.caption-safe.vertical span{max-width:30rem;font-size:clamp(1.15rem,4.3vw,2.25rem)}@media(prefers-reduced-motion:reduce){.caption-safe{transition:none}}
</style>
