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
    <span>{active.text}</span>
  </div>
{/if}

<style>
  .caption-safe{position:absolute;z-index:24;left:10%;right:10%;bottom:8%;display:flex;justify-content:center;pointer-events:none}.caption-safe span{max-width:70rem;padding:.45rem .8rem;border-radius:.45rem;background:rgba(0,0,0,.82);box-shadow:0 2px 14px rgba(0,0,0,.45);color:white;font:800 clamp(1rem,2.2vw,2rem)/1.25 system-ui;text-align:center;text-wrap:balance}.caption-safe.vertical{left:7%;right:7%;bottom:14%}.caption-safe.vertical span{font-size:clamp(1.1rem,4.4vw,2.2rem);max-width:28rem}@media(prefers-reduced-motion:reduce){.caption-safe{transition:none}}
</style>
