<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { beforeNavigate, goto } from '$app/navigation';
  import {
    apiBase,
    brandAssetUrl,
    deleteBrandAsset,
    deleteStylePreset,
    duplicateProduction,
    getBrandAssets,
    getPresentationMatch,
    getProduction,
    getProductions,
    getStylePresets,
    getVideoPreflight,
    saveStylePreset,
    updateProduction,
    uploadBrandAsset
  } from '$lib/api';
  import { ProductionCompositor } from '$lib/production/compositor';
  import { createProductionFrameRenderer, type ProductionFrameRenderer } from '$lib/production/frame-state';
  import { createProductionScene } from '$lib/production/scene';
  import { previewMarks, type PreviewMark } from '$lib/production/preview-marks';
  import { formatDisplayName } from '$lib/production/style';
  import type {
    BrandAsset,
    BrandAssetKind,
    ExportPreflight,
    MatchArchive,
    ProductionStyle,
    ProductionTimeline,
    StylePreset
  } from '$lib/types';

  export let data: { id: string };

  let production: ProductionTimeline | null = null;
  let match: MatchArchive | null = null;
  let siblings: ProductionTimeline[] = [];
  let presets: StylePreset[] = [];
  let assets: BrandAsset[] = [];
  let preflight: ExportPreflight | null = null;
  let style: ProductionStyle | null = null;
  let savedStyle = '';
  let title = '';
  let savedTitle = '';
  let error = '';
  let notice = '';
  let saving = false;

  let canvas: HTMLCanvasElement;
  let compositor: ProductionCompositor | null = null;
  let frames: ProductionFrameRenderer | null = null;
  let timeMs = 0;
  let playing = false;
  let animation = 0;
  let marks: PreviewMark[] = [];
  let verticalPreview = false;
  let safeAreas = false;
  let fullscreen = false;
  let open: Record<string, boolean> = { style: true, intro: true, players: true, arena: false, hud: false, commentary: false, captions: false, effects: false, result: false, advanced: false };

  $: dirty = Boolean(style) && (JSON.stringify(style) !== savedStyle || title !== savedTitle);
  $: previewWidth = verticalPreview ? 1080 : 1920;
  $: previewHeight = verticalPreview ? 1920 : 1080;

  onMount(() => {
    void load();
    const guard = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', guard);
    return () => {
      window.removeEventListener('beforeunload', guard);
      cancelAnimationFrame(animation);
    };
  });

  // Seeking and playback are harmless; only real edits are worth interrupting a user over.
  beforeNavigate((navigation) => {
    if (!dirty) return;
    if (!confirm('Discard unsaved production settings?')) navigation.cancel();
  });

  async function load() {
    try {
      production = await getProduction(data.id);
      match = await getPresentationMatch(production.match_id);
      style = structuredClone(production.style);
      savedStyle = JSON.stringify(style);
      title = production.title || '';
      savedTitle = title;
      verticalPreview = production.profile.aspect_ratio === '9:16';
      marks = previewMarks(production);
      frames = createProductionFrameRenderer(match, production);
      [presets, assets, siblings] = await Promise.all([
        getStylePresets(),
        getBrandAssets().then((library) => library.assets),
        getProductions(production.match_id)
      ]);
      preflight = await getVideoPreflight(production.id, 'offline').catch(() => null);
      // t=0 is the intro's very first fade frame: an empty stage with no Pokemon yet.
      // Opening on the first real beat shows the user something worth judging.
      timeMs = marks.find((mark) => mark.id === 'commentary')?.timeMs ?? marks[0]?.timeMs ?? 0;
      await tick();
      await draw();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function draw() {
    if (!canvas || !frames || !production || !style || !match) return;
    if (canvas.width !== previewWidth || canvas.height !== previewHeight) {
      canvas.width = previewWidth;
      canvas.height = previewHeight;
      compositor = null;
    }
    if (!compositor) compositor = new ProductionCompositor(canvas, apiBase());
    const frame = frames.renderAt(timeMs);
    await compositor.render(
      createProductionScene(frame, previewHeight > previewWidth, apiBase(), style, title || null)
    );
  }

  // Every edit repaints the current frame, so customization is judged on the real
  // compositor rather than on an approximation that would disagree with the export.
  $: if (style && canvas) void redraw(style, title, verticalPreview);

  let redrawQueued = false;
  async function redraw(..._dependencies: unknown[]) {
    if (redrawQueued) return;
    redrawQueued = true;
    await tick();
    redrawQueued = false;
    await draw();
  }

  function play() {
    if (!production) return;
    playing = true;
    const origin = performance.now() - timeMs;
    const step = async (now: number) => {
      if (!playing || !production) return;
      timeMs = Math.min(production.duration_ms, now - origin);
      await draw();
      if (timeMs >= production.duration_ms) { playing = false; return; }
      animation = requestAnimationFrame(step);
    };
    animation = requestAnimationFrame(step);
  }

  function pause() {
    playing = false;
    cancelAnimationFrame(animation);
  }

  async function seek(value: number) {
    pause();
    timeMs = Math.max(0, Math.min(production?.duration_ms || 0, value));
    await draw();
  }

  function turnCue(direction: 1 | -1) {
    if (!production) return;
    const turns = production.cues
      .filter((cue) => cue.track === 'visual' && cue.turn !== null)
      .sort((left, right) => left.start_ms - right.start_ms);
    const current = turns.filter((cue) => (direction === 1 ? cue.start_ms > timeMs + 5 : cue.start_ms < timeMs - 5));
    const target = direction === 1 ? current[0] : current[current.length - 1];
    void seek(target ? target.start_ms : direction === 1 ? production.duration_ms : 0);
  }

  function patch<K extends keyof ProductionStyle>(section: K, value: Partial<ProductionStyle[K]>) {
    if (!style) return;
    style = { ...style, [section]: { ...(style[section] as object), ...value } } as ProductionStyle;
  }

  function setStyleValue<K extends keyof ProductionStyle>(key: K, value: ProductionStyle[K]) {
    if (!style) return;
    style = { ...style, [key]: value };
  }

  function patchBackground(value: Partial<ProductionStyle['stage']['background']>) {
    if (!style) return;
    patch('stage', { background: { ...style.stage.background, ...value } });
  }

  function patchPlayer(side: 'p1' | 'p2', value: Partial<ProductionStyle['players'][string]>) {
    if (!style) return;
    const existing = style.players[side] || {
      display_name: null, short_name: null, logo_asset_id: null, logo_mark: null, accent: null, secondary_accent: null
    };
    style = { ...style, players: { ...style.players, [side]: { ...existing, ...value } } };
  }

  function patchSeries(value: Partial<ProductionStyle['series']>) {
    if (!style) return;
    style = { ...style, series: { ...style.series, ...value } };
  }

  async function applyPreset(presetId: string) {
    const preset = presets.find((item) => item.id === presetId);
    if (!preset || !style) return;
    // Player branding belongs to this match, not to the preset, so it survives the swap.
    style = { ...structuredClone(preset.style), players: style.players, series: style.series, title: style.title };
    await redraw();
  }

  function resetSection(section: keyof ProductionStyle) {
    const preset = presets.find((item) => item.id === style?.id) || presets[0];
    if (!preset || !style) return;
    style = { ...style, [section]: structuredClone(preset.style[section]) } as ProductionStyle;
  }

  function resetAll() {
    if (!production) return;
    style = structuredClone(production.style);
    title = production.title || '';
  }

  async function save() {
    if (!production || !style) return;
    saving = true;
    error = '';
    try {
      production = await updateProduction(production.id, {
        style,
        title: title.trim() || null,
        clearTitle: !title.trim()
      });
      style = structuredClone(production.style);
      savedStyle = JSON.stringify(style);
      savedTitle = production.title || '';
      title = savedTitle;
      preflight = await getVideoPreflight(production.id, 'offline').catch(() => null);
      notice = 'Production settings saved.';
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      saving = false;
    }
  }

  async function saveAsPreset() {
    if (!style) return;
    const name = prompt('Preset name', `${style.display_name} custom`);
    if (!name) return;
    try {
      const preset = await saveStylePreset(name, '', style);
      presets = [...presets.filter((item) => item.id !== preset.id), preset];
      notice = `Saved preset “${preset.display_name}”.`;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function removePreset(presetId: string) {
    if (!confirm('Delete this saved style preset?')) return;
    await deleteStylePreset(presetId).catch(() => undefined);
    presets = presets.filter((item) => item.id !== presetId);
  }

  async function duplicate() {
    if (!production) return;
    const copy = await duplicateProduction(production.id, { title: `${title || 'Production'} copy` });
    await goto(`/studio/${copy.id}`);
    location.reload();
  }

  async function upload(kind: BrandAssetKind, input: HTMLInputElement) {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const buffer = new Uint8Array(await file.arrayBuffer());
      let binary = '';
      for (let index = 0; index < buffer.length; index += 0x8000) {
        binary += String.fromCharCode(...buffer.subarray(index, index + 0x8000));
      }
      const asset = await uploadBrandAsset(kind, file.name.replace(/\.[^.]+$/, ''), btoa(binary));
      assets = [asset, ...assets];
      notice = `Uploaded ${asset.display_name}.`;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      input.value = '';
    }
  }

  async function removeAsset(id: string) {
    if (!confirm('Delete this asset? Productions still using it fall back to the generated mark.')) return;
    try {
      await deleteBrandAsset(id);
      assets = assets.filter((asset) => asset.id !== id);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  function assetsOf(kind: BrandAssetKind) {
    return assets.filter((asset) => asset.kind === kind);
  }

  // Read the element's own state instead of flipping ours: writing the negation back into
  // the bound `open` attribute fought the browser and left every section collapsed.
  function toggle(section: string, event: Event) {
    const details = event.currentTarget as HTMLDetailsElement;
    if (open[section] !== details.open) open = { ...open, [section]: details.open };
  }
</script>

<svelte:head><title>Video Studio · KoalaBattle</title></svelte:head>

{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="notice" role="status">{notice}</p>{/if}

{#if production && style && match}
  <header class="studio-head">
    <div>
      <span class="eyebrow">Video Studio</span>
      <h1>{match.config.players[0].display_name} vs {match.config.players[1].display_name}</h1>
      <p class="meta">
        {formatDisplayName(match.config.format)} · {production.profile.display_name} ·
        {(production.duration_ms / 1000).toFixed(1)}s · revision {production.revision}
      </p>
    </div>
    <div class="head-actions">
      <a class="button ghost" href={`/replay/${production.match_id}`}>Back to replay</a>
      <button class="ghost" on:click={duplicate}>Duplicate</button>
      <button class="ghost" on:click={resetAll} disabled={!dirty}>Discard</button>
      <button class="primary" on:click={save} disabled={!dirty || saving}>{saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}</button>
    </div>
  </header>

  <div class="studio" class:fullscreen>
    <section class="stage-column" aria-label="Live preview">
      <div class="preview" class:vertical={verticalPreview}>
        <canvas bind:this={canvas} width={previewWidth} height={previewHeight} aria-label="Production preview"></canvas>
        {#if safeAreas}
          <div class="safe-area" aria-hidden="true"><span class="safe-caption"></span><span class="safe-title"></span></div>
        {/if}
      </div>

      <div class="transport">
        <div class="buttons">
          <button on:click={() => seek(0)} aria-label="Restart preview">⏮</button>
          <button on:click={() => turnCue(-1)}>Prev turn</button>
          <button class="play" on:click={() => (playing ? pause() : play())}>{playing ? 'Pause' : 'Play'}</button>
          <button on:click={() => turnCue(1)}>Next turn</button>
        </div>
        <label class="scrub">
          <span class="sr-only">Timeline</span>
          <input type="range" min="0" max={production.duration_ms} value={timeMs} on:input={(event) => seek(Number(event.currentTarget.value))} />
          <output>{(timeMs / 1000).toFixed(1)}s</output>
        </label>
        <div class="jumps">
          {#each marks as mark (mark.id)}
            <button class="chip" on:click={() => seek(mark.timeMs)}>{mark.label}</button>
          {/each}
          {#if !marks.length}<span class="hint">This production has no cue-based preview points.</span>{/if}
        </div>
        <div class="view-options">
          <label><input type="checkbox" bind:checked={verticalPreview} /> 9:16 framing</label>
          <label><input type="checkbox" bind:checked={safeAreas} /> Safe areas</label>
          <label><input type="checkbox" bind:checked={fullscreen} /> Fullscreen preview</label>
        </div>
      </div>
    </section>

    <aside class="settings" aria-label="Production settings">
      <details open={open.style} on:toggle={(event) => toggle('style', event)}>
        <summary>Style</summary>
        <div class="fields">
          <label>Preset
            <select value={style.id} on:change={(event) => applyPreset(event.currentTarget.value)}>
              {#each presets as preset (preset.id)}<option value={preset.id}>{preset.display_name}{preset.builtin ? '' : ' (saved)'}</option>{/each}
            </select>
          </label>
          <p class="hint">{presets.find((item) => item.id === style?.id)?.description || 'Customized from a built-in preset.'}</p>
          <label>Video title <input type="text" maxlength="90" bind:value={title} placeholder="Optional — does not rename the match" /></label>
          <label class="check"><input type="checkbox" checked={style.show_format} on:change={(event) => setStyleValue('show_format', event.currentTarget.checked)} /> Show format</label>
          <label class="check"><input type="checkbox" checked={style.show_generation} on:change={(event) => setStyleValue('show_generation', event.currentTarget.checked)} /> Show generation</label>
          <label class="check"><input type="checkbox" checked={style.show_koala_branding} on:change={(event) => setStyleValue('show_koala_branding', event.currentTarget.checked)} /> Show KoalaBattle branding</label>
          <div class="row">
            <button class="ghost" on:click={saveAsPreset}>Save as preset</button>
            {#if !presets.find((item) => item.id === style?.id)?.builtin}
              <button class="ghost danger" on:click={() => removePreset(style?.id || '')}>Delete preset</button>
            {/if}
          </div>
        </div>
      </details>

      <details open={open.intro} on:toggle={(event) => toggle('intro', event)}>
        <summary>Intro</summary>
        <div class="fields">
          <label class="check"><input type="checkbox" checked={style.intro.enabled} on:change={(event) => patch('intro', { enabled: event.currentTarget.checked })} /> Show match intro</label>
          <label>Length
            <select value={style.intro.length} on:change={(event) => patch('intro', { length: event.currentTarget.value as 'quick' })}>
              <option value="quick">Quick</option><option value="standard">Standard</option><option value="dramatic">Dramatic</option>
            </select>
          </label>
          <label class="check"><input type="checkbox" checked={style.intro.show_player_logos} on:change={(event) => patch('intro', { show_player_logos: event.currentTarget.checked })} /> Player logos</label>
          <label class="check"><input type="checkbox" checked={style.intro.show_player_names} on:change={(event) => patch('intro', { show_player_names: event.currentTarget.checked })} /> Player names</label>
          <label class="check"><input type="checkbox" checked={style.intro.show_format} on:change={(event) => patch('intro', { show_format: event.currentTarget.checked })} /> Format</label>
          <label class="check"><input type="checkbox" checked={style.intro.show_game_number} on:change={(event) => patch('intro', { show_game_number: event.currentTarget.checked })} /> Game number / best-of</label>
          <label class="check"><input type="checkbox" checked={style.intro.show_series_score} on:change={(event) => patch('intro', { show_series_score: event.currentTarget.checked })} /> Series score</label>
          <label class="check"><input type="checkbox" checked={style.intro.show_tournament_round} on:change={(event) => patch('intro', { show_tournament_round: event.currentTarget.checked })} /> Tournament round</label>
          <div class="grid2">
            <label>Tournament <input type="text" maxlength="60" value={style.series.tournament_name || ''} on:input={(event) => patchSeries({ tournament_name: event.currentTarget.value || null })} /></label>
            <label>Round <input type="text" maxlength="40" value={style.series.round_name || ''} on:input={(event) => patchSeries({ round_name: event.currentTarget.value || null })} /></label>
            <label>Game <input type="number" min="1" max="99" value={style.series.game_number ?? ''} on:input={(event) => patchSeries({ game_number: Number(event.currentTarget.value) || null })} /></label>
            <label>Best of <input type="number" min="1" max="99" value={style.series.best_of ?? ''} on:input={(event) => patchSeries({ best_of: Number(event.currentTarget.value) || null })} /></label>
            <label>Score P1 <input type="number" min="0" max="99" value={style.series.score_p1 ?? ''} on:input={(event) => patchSeries({ score_p1: event.currentTarget.value === '' ? null : Number(event.currentTarget.value) })} /></label>
            <label>Score P2 <input type="number" min="0" max="99" value={style.series.score_p2 ?? ''} on:input={(event) => patchSeries({ score_p2: event.currentTarget.value === '' ? null : Number(event.currentTarget.value) })} /></label>
          </div>
          <button class="ghost" on:click={() => resetSection('intro')}>Reset section</button>
        </div>
      </details>

      <details open={open.players} on:toggle={(event) => toggle('players', event)}>
        <summary>Player branding</summary>
        <div class="fields">
          {#each ['p1', 'p2'] as const as side (side)}
            <fieldset>
              <legend>{side.toUpperCase()} · {match.config.players[side === 'p1' ? 0 : 1].display_name}</legend>
              <label>Display name <input type="text" maxlength="40" value={style.players[side]?.display_name || ''} on:input={(event) => patchPlayer(side, { display_name: event.currentTarget.value || null })} /></label>
              <label>Short name <input type="text" maxlength="12" value={style.players[side]?.short_name || ''} on:input={(event) => patchPlayer(side, { short_name: event.currentTarget.value || null })} /></label>
              <label>Accent <input type="color" value={style.players[side]?.accent || '#7dffae'} on:input={(event) => patchPlayer(side, { accent: event.currentTarget.value })} /></label>
              <label>Generated mark
                <select value={style.players[side]?.logo_mark || 'local'} on:change={(event) => patchPlayer(side, { logo_mark: event.currentTarget.value })}>
                  {#each ['gpt', 'gemini', 'claude', 'deepseek', 'local', 'manual', 'random', 'koala'] as mark (mark)}<option value={mark}>{mark.toUpperCase()}</option>{/each}
                </select>
              </label>
              <label>Logo image
                <select value={style.players[side]?.logo_asset_id || ''} on:change={(event) => patchPlayer(side, { logo_asset_id: event.currentTarget.value || null })}>
                  <option value="">Generated mark (no file)</option>
                  {#each assetsOf('logo') as asset (asset.id)}<option value={asset.id}>{asset.display_name}</option>{/each}
                </select>
              </label>
              {#if style.players[side]?.logo_asset_id}
                <div class="thumb"><img src={brandAssetUrl(style.players[side]?.logo_asset_id || '')} alt="" /><button class="ghost" on:click={() => patchPlayer(side, { logo_asset_id: null })}>Remove</button></div>
              {/if}
            </fieldset>
          {/each}
          <label class="upload">Upload logo (PNG / WebP / JPEG)
            <input type="file" accept="image/png,image/webp,image/jpeg" on:change={(event) => upload('logo', event.currentTarget)} />
          </label>
          <p class="hint">KoalaBattle bundles no third-party provider logos. Uploaded files stay in local media storage and are never committed.</p>
        </div>
      </details>

      <details open={open.arena} on:toggle={(event) => toggle('arena', event)}>
        <summary>Arena</summary>
        <div class="fields">
          <label>Background
            <select value={style.stage.background.kind} on:change={(event) => patchBackground({ kind: event.currentTarget.value as 'arena' })}>
              <option value="arena">Built-in arena</option><option value="solid">Solid</option><option value="gradient">Gradient</option><option value="image">Custom image</option>
            </select>
          </label>
          <div class="grid2">
            <label>Primary <input type="color" value={style.stage.background.color} on:input={(event) => patchBackground({ color: event.currentTarget.value })} /></label>
            <label>Secondary <input type="color" value={style.stage.background.secondary_color} on:input={(event) => patchBackground({ secondary_color: event.currentTarget.value })} /></label>
          </div>
          {#if style.stage.background.kind === 'image'}
            <label>Image
              <select value={style.stage.background.asset_id || ''} on:change={(event) => patchBackground({ asset_id: event.currentTarget.value || null })}>
                <option value="">None selected</option>
                {#each assetsOf('background') as asset (asset.id)}<option value={asset.id}>{asset.display_name} ({asset.width}×{asset.height})</option>{/each}
              </select>
            </label>
            <label class="upload">Upload background
              <input type="file" accept="image/png,image/webp,image/jpeg" on:change={(event) => upload('background', event.currentTarget)} />
            </label>
            <div class="grid2">
              <label>Fit <select value={style.stage.background.fit} on:change={(event) => patchBackground({ fit: event.currentTarget.value as 'cover' })}><option value="cover">Cover</option><option value="contain">Contain</option></select></label>
              <label>Position <select value={style.stage.background.position} on:change={(event) => patchBackground({ position: event.currentTarget.value as 'center' })}>{#each ['center', 'top', 'bottom', 'left', 'right'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
            </div>
            <label>Brightness <input type="range" min="0.2" max="1.6" step="0.05" value={style.stage.background.brightness} on:input={(event) => patchBackground({ brightness: Number(event.currentTarget.value) })} /></label>
            <label>Contrast <input type="range" min="0.5" max="1.8" step="0.05" value={style.stage.background.contrast} on:input={(event) => patchBackground({ contrast: Number(event.currentTarget.value) })} /></label>
            <label>Blur <input type="range" min="0" max="40" step="1" value={style.stage.background.blur} on:input={(event) => patchBackground({ blur: Number(event.currentTarget.value) })} /></label>
            <label>Overlay <input type="range" min="0" max="0.9" step="0.05" value={style.stage.background.overlay_opacity} on:input={(event) => patchBackground({ overlay_opacity: Number(event.currentTarget.value) })} /></label>
          {/if}
          <label>Vignette <input type="range" min="0" max="1" step="0.05" value={style.stage.background.vignette} on:input={(event) => patchBackground({ vignette: Number(event.currentTarget.value) })} /></label>
          <label>Arena treatment
            <select value={style.stage.arena} on:change={(event) => patch('stage', { arena: event.currentTarget.value as 'grid' })}>
              <option value="none">None</option><option value="stadium">Stadium</option><option value="platform">Platform</option><option value="minimal-floor">Minimal floor</option><option value="grid">Grid</option>
            </select>
          </label>
          <label>Accent <input type="color" value={style.stage.accent} on:input={(event) => patch('stage', { accent: event.currentTarget.value })} /></label>
          <label class="check"><input type="checkbox" checked={style.stage.floor_visible} on:change={(event) => patch('stage', { floor_visible: event.currentTarget.checked })} /> Floor visible</label>
          <label class="check"><input type="checkbox" checked={style.stage.ground_shadow} on:change={(event) => patch('stage', { ground_shadow: event.currentTarget.checked })} /> Ground shadow</label>
          <label class="check"><input type="checkbox" checked={style.stage.background_motion} on:change={(event) => patch('stage', { background_motion: event.currentTarget.checked })} /> Background motion</label>
          <label>Stage lighting <input type="range" min="0" max="1" step="0.05" value={style.stage.stage_lighting} on:input={(event) => patch('stage', { stage_lighting: Number(event.currentTarget.value) })} /></label>
          <label>Ambient <input type="range" min="0" max="1" step="0.05" value={style.stage.ambient_intensity} on:input={(event) => patch('stage', { ambient_intensity: Number(event.currentTarget.value) })} /></label>
          <button class="ghost" on:click={() => resetSection('stage')}>Reset section</button>
        </div>
      </details>

      <details open={open.hud} on:toggle={(event) => toggle('hud', event)}>
        <summary>HUD</summary>
        <div class="fields">
          <label>HUD style
            <select value={style.hud.preset} on:change={(event) => patch('hud', { preset: event.currentTarget.value as 'broadcast' })}>
              <option value="broadcast">Broadcast</option><option value="fighting">Fighting game</option><option value="minimal">Minimal</option><option value="esports">Esports</option><option value="retro">Retro</option>
            </select>
          </label>
          <div class="grid2">
            <label>HP shape <select value={style.hud.hp_shape} on:change={(event) => patch('hud', { hp_shape: event.currentTarget.value as 'slash' })}>{#each ['slash', 'rounded', 'square', 'pill'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
            <label>HP thickness <input type="range" min="8" max="54" step="1" value={style.hud.hp_thickness} on:input={(event) => patch('hud', { hp_thickness: Number(event.currentTarget.value) })} /></label>
          </div>
          <label class="check"><input type="checkbox" checked={style.hud.damage_ghost} on:change={(event) => patch('hud', { damage_ghost: event.currentTarget.checked })} /> Damage ghost bar</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_hp_exact} on:change={(event) => patch('hud', { show_hp_exact: event.currentTarget.checked })} /> Exact HP when known</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_hp_percent} on:change={(event) => patch('hud', { show_hp_percent: event.currentTarget.checked })} /> HP percentage</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_player_name} on:change={(event) => patch('hud', { show_player_name: event.currentTarget.checked })} /> Player name</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_provider} on:change={(event) => patch('hud', { show_provider: event.currentTarget.checked })} /> Provider / model</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_logo} on:change={(event) => patch('hud', { show_logo: event.currentTarget.checked })} /> Player logo</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_player_slot} on:change={(event) => patch('hud', { show_player_slot: event.currentTarget.checked })} /> P1 / P2 label</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_types} on:change={(event) => patch('hud', { show_types: event.currentTarget.checked })} /> Type chips</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_status} on:change={(event) => patch('hud', { show_status: event.currentTarget.checked })} /> Status badge</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_level} on:change={(event) => patch('hud', { show_level: event.currentTarget.checked })} /> Level</label>
          <label class="check"><input type="checkbox" checked={style.hud.show_turn} on:change={(event) => patch('hud', { show_turn: event.currentTarget.checked })} /> Turn / format header</label>
          <label>Team indicators
            <select value={style.hud.team_indicators} on:change={(event) => patch('hud', { team_indicators: event.currentTarget.value as 'full' })}>
              <option value="full">Full team</option><option value="revealed">Revealed only</option><option value="fainted-only">Fainted only</option><option value="hidden">Hidden</option>
            </select>
          </label>
          <p class="hint">Indicators can only narrow what a spectator sees. Hidden information stays hidden regardless of this setting.</p>
          <button class="ghost" on:click={() => resetSection('hud')}>Reset section</button>
        </div>
      </details>

      <details open={open.commentary} on:toggle={(event) => toggle('commentary', event)}>
        <summary>Commentary</summary>
        <div class="fields">
          <label>Layout
            <select value={style.commentary.layout} on:change={(event) => patch('commentary', { layout: event.currentTarget.value as 'fighter-card' })}>
              <option value="fighter-card">Fighter card</option><option value="side-panel">Side panel</option><option value="lower-third">Lower third</option><option value="bubble">Rounded panel</option><option value="caption">Captions only</option><option value="off">Off</option>
            </select>
          </label>
          <label>Motion
            <select value={style.commentary.animation} on:change={(event) => patch('commentary', { animation: event.currentTarget.value as 'fade' })}>
              {#each ['fade', 'slide', 'punch', 'minimal', 'none'] as value (value)}<option {value}>{value}</option>{/each}
            </select>
          </label>
          <label class="check"><input type="checkbox" checked={style.commentary.show_agent_name} on:change={(event) => patch('commentary', { show_agent_name: event.currentTarget.checked })} /> Agent name</label>
          <label class="check"><input type="checkbox" checked={style.commentary.show_logo} on:change={(event) => patch('commentary', { show_logo: event.currentTarget.checked })} /> Logo</label>
          <label class="check"><input type="checkbox" checked={style.commentary.show_label} on:change={(event) => patch('commentary', { show_label: event.currentTarget.checked })} /> “Fighter intent” label</label>
          <p class="hint">Only viewer-safe public commentary is ever rendered. Private strategy memory is not available to any production surface.</p>
          <button class="ghost" on:click={() => resetSection('commentary')}>Reset section</button>
        </div>
      </details>

      <details open={open.captions} on:toggle={(event) => toggle('captions', event)}>
        <summary>Captions</summary>
        <div class="fields">
          <label>Preset
            <select value={style.caption.preset} on:change={(event) => patch('caption', { preset: event.currentTarget.value as 'broadcast' })}>
              <option value="broadcast">Broadcast</option><option value="minimal">Minimal</option><option value="high-contrast">High contrast</option><option value="vertical">Vertical</option><option value="off">Off</option>
            </select>
          </label>
          <label>Position <select value={style.caption.position} on:change={(event) => patch('caption', { position: event.currentTarget.value as 'bottom' })}><option value="bottom">Bottom</option><option value="center">Center</option><option value="top">Top</option></select></label>
          <label>Size <input type="range" min="0.7" max="1.5" step="0.05" value={style.caption.size_scale} on:input={(event) => patch('caption', { size_scale: Number(event.currentTarget.value) })} /></label>
          <label>Background <input type="range" min="0" max="1" step="0.05" value={style.caption.background_opacity} on:input={(event) => patch('caption', { background_opacity: Number(event.currentTarget.value) })} /></label>
          <label class="check"><input type="checkbox" checked={style.caption.outline} on:change={(event) => patch('caption', { outline: event.currentTarget.checked })} /> Outline</label>
          <label class="check"><input type="checkbox" checked={style.caption.show_speaker} on:change={(event) => patch('caption', { show_speaker: event.currentTarget.checked })} /> Speaker name</label>
          <button class="ghost" on:click={() => resetSection('caption')}>Reset section</button>
        </div>
      </details>

      <details open={open.effects} on:toggle={(event) => toggle('effects', event)}>
        <summary>Effects</summary>
        <div class="fields">
          <label>Intensity <select value={style.effect.intensity} on:change={(event) => patch('effect', { intensity: event.currentTarget.value as 'standard' })}>{#each ['off', 'minimal', 'standard', 'dramatic'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
          <label>Camera <select value={style.effect.camera} on:change={(event) => patch('effect', { camera: event.currentTarget.value as 'subtle' })}><option value="static">Static</option><option value="subtle">Subtle</option><option value="dynamic">Dynamic</option></select></label>
          <label>Idle motion <select value={style.effect.idle_motion} on:change={(event) => patch('effect', { idle_motion: event.currentTarget.value as 'full' })}><option value="full">Full</option><option value="subtle">Subtle</option><option value="off">Off</option></select></label>
          <label>Pacing <select value={style.effect.pacing} on:change={(event) => patch('effect', { pacing: event.currentTarget.value as 'standard' })}><option value="cinematic">Cinematic</option><option value="standard">Standard</option><option value="fast">Fast</option></select></label>
          <label class="check"><input type="checkbox" checked={style.effect.impact_flash} on:change={(event) => patch('effect', { impact_flash: event.currentTarget.checked })} /> Impact flash</label>
          <label class="check"><input type="checkbox" checked={style.effect.trails} on:change={(event) => patch('effect', { trails: event.currentTarget.checked })} /> Projectile trails</label>
          <p class="hint">Pacing changes visual transition timing only. Battle outcome, ordering and recorded history are unchanged.</p>
          <button class="ghost" on:click={() => resetSection('effect')}>Reset section</button>
        </div>
      </details>

      <details open={open.result} on:toggle={(event) => toggle('result', event)}>
        <summary>Result &amp; watermark</summary>
        <div class="fields">
          <label class="check"><input type="checkbox" checked={style.result.enabled} on:change={(event) => patch('result', { enabled: event.currentTarget.checked })} /> Show result card</label>
          <label class="check"><input type="checkbox" checked={style.result.show_winner} on:change={(event) => patch('result', { show_winner: event.currentTarget.checked })} /> Winner</label>
          <label class="check"><input type="checkbox" checked={style.result.show_logos} on:change={(event) => patch('result', { show_logos: event.currentTarget.checked })} /> Logos</label>
          <label class="check"><input type="checkbox" checked={style.result.show_format} on:change={(event) => patch('result', { show_format: event.currentTarget.checked })} /> Format</label>
          <label class="check"><input type="checkbox" checked={style.result.show_series} on:change={(event) => patch('result', { show_series: event.currentTarget.checked })} /> Series progression</label>
          <label>Duration <input type="range" min="800" max="12000" step="200" value={style.result.duration_ms} on:input={(event) => patch('result', { duration_ms: Number(event.currentTarget.value) })} /></label>
          <hr />
          <label class="check"><input type="checkbox" checked={style.watermark.enabled} on:change={(event) => patch('watermark', { enabled: event.currentTarget.checked })} /> Watermark</label>
          {#if style.watermark.enabled}
            <label>Image
              <select value={style.watermark.asset_id || ''} on:change={(event) => patch('watermark', { asset_id: event.currentTarget.value || null })}>
                <option value="">Text only</option>
                {#each assetsOf('watermark') as asset (asset.id)}<option value={asset.id}>{asset.display_name}</option>{/each}
              </select>
            </label>
            <label class="upload">Upload watermark<input type="file" accept="image/png,image/webp,image/jpeg" on:change={(event) => upload('watermark', event.currentTarget)} /></label>
            <label>Text <input type="text" maxlength="40" value={style.watermark.text || ''} on:input={(event) => patch('watermark', { text: event.currentTarget.value || null })} /></label>
            <label>Position <select value={style.watermark.position} on:change={(event) => patch('watermark', { position: event.currentTarget.value as 'bottom-right' })}>{#each ['top-left', 'top-right', 'bottom-left', 'bottom-right'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
            <label>Opacity <input type="range" min="0.05" max="1" step="0.05" value={style.watermark.opacity} on:input={(event) => patch('watermark', { opacity: Number(event.currentTarget.value) })} /></label>
            <label>Size <input type="range" min="0.5" max="2" step="0.1" value={style.watermark.size} on:input={(event) => patch('watermark', { size: Number(event.currentTarget.value) })} /></label>
          {/if}
        </div>
      </details>

      <details open={open.advanced} on:toggle={(event) => toggle('advanced', event)}>
        <summary>Advanced</summary>
        <div class="fields">
          <h3>Typography</h3>
          <div class="grid2">
            <label>Display <select value={style.typography.display} on:change={(event) => patch('typography', { display: event.currentTarget.value as 'system' })}>{#each ['system', 'geometric', 'grotesk', 'serif', 'mono', 'pixel'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
            <label>Body <select value={style.typography.body} on:change={(event) => patch('typography', { body: event.currentTarget.value as 'system' })}>{#each ['system', 'geometric', 'grotesk', 'serif', 'mono', 'pixel'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
          </div>
          <label>Custom display font
            <select value={style.typography.display_asset_id || ''} on:change={(event) => patch('typography', { display_asset_id: event.currentTarget.value || null })}>
              <option value="">Use built-in stack</option>
              {#each assetsOf('font') as asset (asset.id)}<option value={asset.id}>{asset.display_name}</option>{/each}
            </select>
          </label>
          <label class="upload">Upload font (WOFF2 / TTF / OTF)<input type="file" accept=".woff2,.ttf,.otf" on:change={(event) => upload('font', event.currentTarget)} /></label>
          <p class="hint">You are responsible for the licence of any font you add. KoalaBattle never redistributes fonts.</p>
          <label>Text scale <input type="range" min="0.8" max="1.3" step="0.02" value={style.typography.scale} on:input={(event) => patch('typography', { scale: Number(event.currentTarget.value) })} /></label>
          <label>Display weight <input type="range" min="400" max="950" step="50" value={style.typography.display_weight} on:input={(event) => patch('typography', { display_weight: Number(event.currentTarget.value) })} /></label>
          <label>Letter spacing <input type="range" min="-2" max="6" step="0.5" value={style.typography.letter_spacing} on:input={(event) => patch('typography', { letter_spacing: Number(event.currentTarget.value) })} /></label>
          <label class="check"><input type="checkbox" checked={style.typography.uppercase} on:change={(event) => patch('typography', { uppercase: event.currentTarget.checked })} /> Uppercase headings</label>
          <label class="check"><input type="checkbox" checked={style.typography.outline} on:change={(event) => patch('typography', { outline: event.currentTarget.checked })} /> Outline</label>
          <label class="check"><input type="checkbox" checked={style.typography.shadow} on:change={(event) => patch('typography', { shadow: event.currentTarget.checked })} /> Shadow</label>

          <h3>Move callout</h3>
          <label>Layout <select value={style.move.layout} on:change={(event) => patch('move', { layout: event.currentTarget.value as 'banner' })}>{#each ['banner', 'impact', 'minimal', 'lower-third', 'centered', 'off'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
          <label class="check"><input type="checkbox" checked={style.move.show_type} on:change={(event) => patch('move', { show_type: event.currentTarget.checked })} /> Show type</label>
          <label class="check"><input type="checkbox" checked={style.move.show_archetype} on:change={(event) => patch('move', { show_archetype: event.currentTarget.checked })} /> Show archetype</label>

          <h3>Damage callouts</h3>
          <label>Intensity <select value={style.damage.intensity} on:change={(event) => patch('damage', { intensity: event.currentTarget.value as 'standard' })}>{#each ['off', 'minimal', 'standard', 'dramatic'] as value (value)}<option {value}>{value}</option>{/each}</select></label>
          <label class="check"><input type="checkbox" checked={style.damage.show_damage} on:change={(event) => patch('damage', { show_damage: event.currentTarget.checked })} /> Damage %</label>
          <label class="check"><input type="checkbox" checked={style.damage.show_healing} on:change={(event) => patch('damage', { show_healing: event.currentTarget.checked })} /> Healing %</label>
          <label class="check"><input type="checkbox" checked={style.damage.show_effectiveness} on:change={(event) => patch('damage', { show_effectiveness: event.currentTarget.checked })} /> Effectiveness</label>
          <label class="check"><input type="checkbox" checked={style.damage.show_critical} on:change={(event) => patch('damage', { show_critical: event.currentTarget.checked })} /> Critical</label>
          <label class="check"><input type="checkbox" checked={style.damage.show_miss} on:change={(event) => patch('damage', { show_miss: event.currentTarget.checked })} /> Miss</label>
          <label class="check"><input type="checkbox" checked={style.damage.show_immune} on:change={(event) => patch('damage', { show_immune: event.currentTarget.checked })} /> Immune</label>

          <h3>Assets</h3>
          <ul class="asset-list">
            {#each assets as asset (asset.id)}
              <li><span>{asset.display_name}</span><small>{asset.kind} · {(asset.byte_size / 1024).toFixed(0)} KB</small><button class="ghost danger" on:click={() => removeAsset(asset.id)}>Delete</button></li>
            {:else}
              <li class="hint">No uploaded assets yet.</li>
            {/each}
          </ul>
        </div>
      </details>

      <details>
        <summary>Export</summary>
        <div class="fields">
          {#if preflight}
            <ul class="preflight">
              {#each Object.entries(preflight.checks) as [key, value] (key)}
                <li><span>{key.replaceAll('_', ' ')}</span><code>{value}</code></li>
              {/each}
            </ul>
            {#each preflight.warnings as warning (warning)}<p class="hint">{warning}</p>{/each}
          {/if}
          <p class="hint">Save first — exports render the saved production, not unsaved edits.</p>
          <a class="button" href={`/replay/${production.match_id}#exports`}>Open export dashboard</a>
        </div>
      </details>

      <details>
        <summary>Productions for this match ({siblings.length})</summary>
        <ul class="siblings">
          {#each siblings as item (item.id)}
            <li class:current={item.id === production.id}>
              <span>{item.title || item.style.display_name}</span>
              <small>{item.profile.aspect_ratio === '9:16' ? '1080×1920' : '1920×1080'} · {item.style.id}</small>
              {#if item.id !== production.id}<a href={`/studio/${item.id}`}>Edit</a>{/if}
            </li>
          {/each}
        </ul>
      </details>
    </aside>
  </div>
{:else if !error}
  <p>Loading Video Studio…</p>
{/if}

<style>
  .studio-head{display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;margin-bottom:1rem}
  .studio-head h1{margin:.3rem 0 0;font-size:clamp(1.4rem,3vw,2.2rem)}
  .studio-head .meta{margin:.3rem 0 0;color:var(--muted);font:.75rem var(--mono)}
  .head-actions{display:flex;gap:.5rem;flex-wrap:wrap}
  .head-actions button,.head-actions .button{min-height:40px;padding:.5rem .9rem;border-radius:.55rem;border:1px solid var(--border);background:var(--panel-strong);color:var(--text);cursor:pointer}
  .head-actions .primary{border-color:var(--accent);background:var(--accent);color:var(--accent-ink);font-weight:800}
  .head-actions button:disabled{opacity:.45;cursor:not-allowed}
  .studio{display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:1.25rem;align-items:start}
  .studio.fullscreen{grid-template-columns:minmax(0,1fr)}
  .studio.fullscreen .settings{display:none}
  .stage-column{display:grid;gap:.9rem;min-width:0}
  .preview{position:relative;background:#05070a;border:1px solid var(--border);border-radius:.8rem;overflow:hidden;aspect-ratio:16/9}
  .preview.vertical{aspect-ratio:9/16;max-width:min(100%,520px);margin-inline:auto}
  .preview canvas{display:block;width:100%;height:100%;object-fit:contain}
  .safe-area{position:absolute;inset:5%;border:1px dashed rgba(255,255,255,.35);pointer-events:none}
  .safe-area .safe-caption{position:absolute;left:0;right:0;bottom:0;height:18%;border-top:1px dashed rgba(255,209,102,.5)}
  .safe-area .safe-title{position:absolute;inset:8%;border:1px dashed rgba(125,255,174,.35)}
  .transport{display:grid;gap:.7rem;padding:.9rem;border:1px solid var(--border);border-radius:.8rem;background:var(--panel)}
  .transport .buttons{display:flex;gap:.4rem;flex-wrap:wrap}
  .transport button{min-height:40px;padding:.5rem .8rem;border:1px solid var(--border);border-radius:.55rem;background:var(--panel-strong);color:var(--text);cursor:pointer}
  .transport .play{min-width:92px;border-color:var(--accent);background:var(--accent);color:var(--accent-ink);font-weight:800}
  .scrub{display:grid;grid-template-columns:1fr auto;gap:.6rem;align-items:center}
  .scrub input{width:100%;accent-color:var(--accent)}
  .scrub output{font:.72rem var(--mono);min-width:4rem;text-align:right}
  .jumps{display:flex;gap:.35rem;flex-wrap:wrap}
  .chip{font:0.72rem var(--mono);padding:.35rem .6rem!important;min-height:32px!important}
  .view-options{display:flex;gap:1.1rem;flex-wrap:wrap;font-size:.8rem}
  .view-options label{display:flex;align-items:center;gap:.4rem}
  .view-options input{width:16px;height:16px;accent-color:var(--accent)}
  .settings{display:grid;gap:.5rem;position:sticky;top:1rem;max-height:calc(100vh - 2rem);overflow-y:auto}
  .settings details{border:1px solid var(--border);border-radius:.7rem;background:var(--panel)}
  .settings summary{padding:.7rem .9rem;cursor:pointer;font-weight:700}
  .fields{display:grid;gap:.6rem;padding:0 .9rem .9rem}
  .fields label{display:grid;gap:.25rem;font-size:.8rem}
  .fields label.check{display:flex;align-items:center;justify-content:flex-start;gap:.55rem;text-align:left}
  .fields input[type=checkbox]{flex:none;width:17px;height:17px;margin:0;accent-color:var(--accent)}
  .fields input[type=text],.fields input[type=number],.fields select{min-height:38px;padding:.4rem .5rem;border:1px solid var(--border);border-radius:.45rem;background:var(--panel-strong);color:var(--text)}
  .fields input[type=color]{width:100%;height:34px;padding:0;border:1px solid var(--border);border-radius:.45rem;background:none}
  .fields fieldset{border:1px solid var(--border);border-radius:.55rem;padding:.6rem;display:grid;gap:.5rem}
  .fields legend{font:0.72rem var(--mono);padding:0 .3rem}
  .fields .grid2{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
  .fields h3{margin:.6rem 0 0;font-size:.85rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
  .fields button{min-height:36px;padding:.4rem .7rem;border:1px solid var(--border);border-radius:.5rem;background:var(--panel-strong);color:var(--text);cursor:pointer}
  .fields .danger{border-color:#a8464f;color:#ffb0b6}
  .fields .row{display:flex;gap:.5rem}
  .thumb{display:flex;align-items:center;gap:.5rem}
  .thumb img{width:48px;height:48px;object-fit:contain;background:#0c1014;border-radius:.4rem}
  .hint{margin:0;color:var(--muted);font-size:.74rem;line-height:1.4}
  .asset-list,.siblings,.preflight{list-style:none;margin:0;padding:0 .9rem .9rem;display:grid;gap:.4rem;font-size:.78rem}
  .asset-list li,.siblings li{display:flex;align-items:center;gap:.5rem;justify-content:space-between}
  .asset-list small,.siblings small{color:var(--muted);font:0.72rem var(--mono)}
  .siblings li.current{font-weight:800}
  .preflight li{display:flex;justify-content:space-between;gap:.5rem}
  .preflight code{font:0.72rem var(--mono);color:var(--muted)}
  .sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
  .notice{color:var(--accent)}
  @media(max-width:1180px){.studio{grid-template-columns:minmax(0,1fr)}.settings{position:static;max-height:none}}
  @media(max-width:640px){.fields .grid2{grid-template-columns:1fr}.head-actions{width:100%}}
</style>
