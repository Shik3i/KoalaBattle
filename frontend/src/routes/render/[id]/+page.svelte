<script lang="ts">
  import { onMount, tick } from 'svelte';
  import BattleRenderer from '$lib/BattleRenderer.svelte';
  import CaptionOverlay from '$lib/production/CaptionOverlay.svelte';
  import { ProductionAudioEngine } from '$lib/production/audio-engine';
  import { renderNativeFrame, renderNativeProduction, type NativeRenderMetrics, type NativeRenderRequest } from '$lib/production/native-encoder';
  import {
    createProductionFrameRenderer,
    type ProductionFrameRenderer,
    type ProductionFrameState
  } from '$lib/production/frame-state';
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
  let frameRenderer: ProductionFrameRenderer | null = null;
  let nativeCanvas: HTMLCanvasElement;
  let nativeMode = false;

  type RenderWindow = Window & {
    __KOALABATTLE_RENDER_READY?: boolean;
    __KOALABATTLE_RENDER_AT?: (milliseconds: number) => Promise<boolean>;
    __KOALABATTLE_NATIVE_RENDER?: (request: NativeRenderRequest) => Promise<NativeRenderMetrics>;
  };

  onMount(() => {
    void load();
    return () => {
      const renderWindow = window as RenderWindow;
      delete renderWindow.__KOALABATTLE_RENDER_AT;
      delete renderWindow.__KOALABATTLE_RENDER_READY;
      delete renderWindow.__KOALABATTLE_NATIVE_RENDER;
      cancelAnimationFrame(animationFrame);
      audio?.destroy();
    };
  });

  async function load() {
    try {
      production = await getProduction(data.id);
      match = await getPresentationMatch(production.match_id);
      nativeMode = new URLSearchParams(location.search).get('engine') === 'native';
      config = defaultRendererConfig({
        preset: 'video',
        layout: production.profile.aspect_ratio === '9:16' ? 'standard-vertical' : 'standard-landscape',
        commentaryMode: 'latest',
        playbackSpeed: 1,
        transparentBackground: false,
        animatedSprites: true
      });
      frameRenderer = createProductionFrameRenderer(match, production);
      frame = frameRenderer.renderAt(0);
      const renderWindow = window as RenderWindow;
      if (nativeMode) {
        await tick();
        const renderParams = new URLSearchParams(location.search);
        const frameTime = Number(renderParams.get('frame'));
        if (renderParams.has('frame') && Number.isFinite(frameTime)) {
          const vertical = production.profile.aspect_ratio === '9:16';
          await renderNativeFrame(nativeCanvas, match, production, {
            width: vertical ? 1080 : 1920,
            height: vertical ? 1920 : 1080,
            timeMs: frameTime,
            assetApiBase: apiBase()
          });
          renderWindow.__KOALABATTLE_RENDER_READY = true;
          ready = true;
          return;
        }
        renderWindow.__KOALABATTLE_NATIVE_RENDER = (request) => {
          if (!match || !production || !nativeCanvas) throw new Error('native compositor is not initialized');
          return renderNativeProduction(nativeCanvas, match, production, request);
        };
        renderWindow.__KOALABATTLE_RENDER_READY = true;
        ready = true;
        return;
      }
      renderWindow.__KOALABATTLE_RENDER_AT = async (milliseconds: number) => {
        if (!frameRenderer) return false;
        frame = frameRenderer.renderAt(milliseconds);
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
  {#if nativeMode}
    <canvas bind:this={nativeCanvas} class="native-compositor" aria-label="Native production compositor"></canvas>
  {:else if frame && production}
    <BattleRenderer
      presentation={frame.presentation}
      {config}
      overlay
      deterministic
      logicalElapsedMs={frame.visualElapsedMs}
      visualProgress={frame.visualProgress}
      campaign={match?.config.campaign || null}
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
  /* Reset the application-wide `main` geometry; any inherited padding becomes letterboxing in
     screenshots and final video frames. */
  .render-shell{position:fixed;inset:0;width:100vw;max-width:none;height:100vh;margin:0;padding:0;overflow:hidden;background:#07120c}
  .native-compositor{display:block;width:100%;height:100%;object-fit:contain;background:#07120c}
  .render-error{display:grid;height:100%;place-items:center;padding:2rem;color:#fff;font-family:system-ui}
</style>
