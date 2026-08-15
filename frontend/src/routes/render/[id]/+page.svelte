<script lang="ts">
  import { onMount, tick } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import CaptionOverlay from '$lib/production/CaptionOverlay.svelte';
  import { ProductionAudioEngine } from '$lib/production/audio-engine';
  import { renderAt, type ProductionFrameState } from '$lib/production/frame-state';
  import { apiBase, getPresentationMatch, getProduction } from '$lib/api';
  import { defaultRendererConfig, type RendererConfig } from '$lib/presentation/types';
  import type { MatchArchive, ProductionTimeline } from '$lib/types';

  export let data: { id: string };

  let match: MatchArchive | null = null;
  let production: ProductionTimeline | null = null;
  let frame: ProductionFrameState | null = null;
  let config: RendererConfig = defaultRendererConfig({ preset: 'video' });
  let error = '';
  let ready = false;
  let audio: ProductionAudioEngine | null = null;
  let animationFrame = 0;

  type RenderWindow = Window & {
    __KOALABATTLE_RENDER_READY?: boolean;
    __KOALABATTLE_RENDER_AT?: (milliseconds: number) => Promise<boolean>;
  };

  onMount(() => {
    void load();
    return () => {
      const renderWindow = window as RenderWindow;
      delete renderWindow.__KOALABATTLE_RENDER_AT;
      delete renderWindow.__KOALABATTLE_RENDER_READY;
      cancelAnimationFrame(animationFrame);
      audio?.destroy();
    };
  });

  async function load() {
    try {
      production = await getProduction(data.id);
      match = await getPresentationMatch(production.match_id);
      config = defaultRendererConfig({
        preset: 'video',
        layout: production.profile.aspect_ratio === '9:16' ? 'standard-vertical' : 'standard-landscape',
        commentaryMode: 'latest',
        playbackSpeed: 1,
        transparentBackground: false,
        animatedSprites: true
      });
      frame = renderAt(match, production, 0);
      const renderWindow = window as RenderWindow;
      renderWindow.__KOALABATTLE_RENDER_AT = async (milliseconds: number) => {
        if (!match || !production) return false;
        frame = renderAt(match, production, milliseconds);
        await tick();
        await document.fonts.ready;
        await Promise.all(
          Array.from(document.images)
            .filter((image) => !image.complete)
            .map((image) => new Promise<void>((resolve) => {
              image.addEventListener('load', () => resolve(), { once: true });
              image.addEventListener('error', () => resolve(), { once: true });
            }))
        );
        return true;
      };
      await renderWindow.__KOALABATTLE_RENDER_AT(0);
      renderWindow.__KOALABATTLE_RENDER_READY = true;
      ready = true;
      if (new URLSearchParams(location.search).get('autoplay') === '1') {
        audio = new ProductionAudioEngine(apiBase());
        audio.load(production);
        await audio.enable().catch(() => undefined);
        audio.play();
        const origin = performance.now();
        const play = async (now: number) => {
          const elapsed = Math.min(production?.duration_ms || 0, now - origin);
          await renderWindow.__KOALABATTLE_RENDER_AT?.(elapsed);
          if (elapsed < (production?.duration_ms || 0)) animationFrame = requestAnimationFrame(play);
        };
        animationFrame = requestAnimationFrame(play);
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }
</script>

<svelte:head><title>KoalaBattle deterministic render</title></svelte:head>

<main class="render-shell" data-render-ready={ready ? 'true' : 'false'}>
  {#if frame && production}
    <BattleRenderer
      presentation={frame.presentation}
      {config}
      overlay
      deterministic
      logicalElapsedMs={frame.visualElapsedMs}
    />
    <CaptionOverlay
      cue={frame.caption}
      elapsedMs={frame.timeMs}
      vertical={production.profile.aspect_ratio === '9:16'}
    />
  {:else if error}
    <div class="render-error">{error}</div>
  {/if}
</main>

<style>
  :global(html),:global(body){width:100%;height:100%;margin:0;overflow:hidden;background:#07120c}
  :global(body>div){width:100%;height:100%}
  .render-shell{position:fixed;inset:0;width:100vw;height:100vh;overflow:hidden;background:#07120c}
  .render-error{display:grid;height:100%;place-items:center;padding:2rem;color:#fff;font-family:system-ui}
</style>
