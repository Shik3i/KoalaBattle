<script lang="ts">
  import { onMount } from 'svelte';
  import { api, apiBase, wsBase } from '$lib/api';
  import { loadRendererConfig, saveRendererConfig } from '$lib/presentation/config';
  import { defaultRendererConfig, type EffectQuality, type RendererConfig, type RendererTheme } from '$lib/presentation/types';
  import type { AssetResolution, AssetScanReport, MatchSummary, ProviderStatus, RendererCapabilities, SpeechProviderStatus, VoicePreset } from '$lib/types';

  type ObsPreset = 'youtube' | 'twitch' | 'vertical';
  const presets: Record<ObsPreset, { label: string; width: number; height: number; layout: RendererConfig['layout']; fps: number }> = {
    youtube: { label: 'YouTube 1080p', width: 1920, height: 1080, layout: 'overlay-landscape', fps: 60 },
    twitch: { label: 'Twitch 1080p', width: 1920, height: 1080, layout: 'overlay-landscape', fps: 60 },
    vertical: { label: 'Vertical 1080×1920', width: 1080, height: 1920, layout: 'standard-vertical', fps: 60 }
  };

  let appTheme: 'light' | 'dark' = 'dark';
  let renderer: RendererConfig = defaultRendererConfig();
  let assets: AssetScanReport | null = null;
  let matches: MatchSummary[] = [];
  let providers: ProviderStatus[] = [];
  let speechProviders: SpeechProviderStatus[] = [];
  let voices: VoicePreset[] = [];
  let video: RendererCapabilities | null = null;
  let selectedMatch = '';
  let obsPreset: ObsPreset = 'youtube';
  let baseUrl = '';
  let copied = false;
  let assetQuery = 'Mr. Mime';
  let resolution: AssetResolution | null = null;
  let error = '';

  $: preset = presets[obsPreset];
  $: overlayUrl = selectedMatch
    ? `${baseUrl}/overlay/${selectedMatch}?layout=${preset.layout}&theme=${renderer.theme}&transparent=${renderer.transparentBackground ? '1' : '0'}&commentary=${renderer.commentaryMode}&log=${renderer.showBattleLog ? '1' : '0'}&near=${renderer.nearSide}&effects=${renderer.effects}&reducedMotion=${renderer.reducedMotion ? '1' : '0'}&damageNumbers=${renderer.showDamageNumbers ? '1' : '0'}`
    : 'Select a recorded match';

  onMount(() => {
    baseUrl = location.origin;
    appTheme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
    renderer = loadRendererConfig();
    void loadData();
  });

  async function loadData() {
    try {
      [assets, matches, providers, speechProviders, voices, video] = await Promise.all([
        api<AssetScanReport>('/api/assets/status'),
        api<MatchSummary[]>('/api/matches?limit=100'),
        api<{ providers: ProviderStatus[] }>('/api/providers').then((result) => result.providers),
        api<{ providers: SpeechProviderStatus[] }>('/api/production/providers').then((result) => result.providers),
        api<VoicePreset[]>('/api/production/voices'),
        api<RendererCapabilities>('/api/video/capabilities')
      ]);
      selectedMatch ||= matches[0]?.id || '';
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  function setAppTheme(value: 'light' | 'dark') {
    appTheme = value;
    document.documentElement.dataset.theme = value;
    localStorage.setItem('koalabattle-theme', value);
  }

  function updateRenderer(patch: Partial<RendererConfig>) {
    renderer = { ...renderer, ...patch };
    saveRendererConfig(renderer);
  }

  async function rescan() {
    error = '';
    try {
      assets = await api<AssetScanReport>('/api/assets/rescan', { method: 'POST' });
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function resolveAsset() {
    error = '';
    try {
      const query = new URLSearchParams({
        perspective: renderer.nearSide === 'p1' ? 'back' : 'front',
        animated: String(renderer.animatedSprites)
      });
      resolution = await api<AssetResolution>(`/api/assets/resolve/pokemon/${encodeURIComponent(assetQuery)}?${query}`);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function copyOverlay() {
    if (!selectedMatch) return;
    await navigator.clipboard.writeText(overlayUrl);
    copied = true;
    setTimeout(() => (copied = false), 1200);
  }

  const providerLabel = (id: string) => ({
    openai: 'OpenAI', anthropic: 'Anthropic', gemini: 'Gemini', deepseek: 'DeepSeek',
    openai_compatible: 'OpenAI-compatible', fake: 'Fake · test only',
    system: 'Edge Neural + system fallback', elevenlabs: 'ElevenLabs'
  })[id] || id.replaceAll('_', ' ');
</script>

<div class="page-head"><div><span class="eyebrow">Local production configuration</span><h1>Settings</h1></div></div>
{#if error}<p class="error">{error}</p>{/if}

<div class="settings-grid">
  <section class="panel providers"><span class="section-number"><i class="ph ph-plugs-connected" aria-hidden="true"></i> Providers</span><h2>Server-side credentials</h2><p>Keys are read from backend environment variables only. Their values are never returned to this browser.</p><div class="provider-cards">{#each providers as provider}<article><span class:ready={provider.configured}>{provider.configured ? 'Configured' : 'Not configured'}</span><strong>{providerLabel(provider.id)}</strong><small>{provider.capabilities.structured_output ? 'Structured output' : 'Plain JSON'} · {provider.capabilities.model_listing ? 'model discovery' : 'custom model ID'}</small></article>{/each}</div><a class="preview-link" href="/new"><i class="ph ph-sword" aria-hidden="true"></i>Configure a battle</a></section>
  <section class="panel providers"><span class="section-number"><i class="ph ph-waveform" aria-hidden="true"></i> Speech</span><h2>Audio providers & voice presets</h2><p>Edge Neural is the free natural default and sends public commentary to Microsoft's online speech service while production audio is prepared. Basic offline system voices remain available. Paid providers require separate configuration and approval.</p><div class="provider-cards">{#each speechProviders as provider}<article><span class:ready={provider.available}>{provider.available ? 'Available' : 'Unavailable'}</span><strong>{providerLabel(provider.id)}</strong><small>{provider.paid ? 'paid / explicit action' : 'zero-cost'} · {provider.supports_timestamps ? 'timestamps' : 'normalized caption timing'}</small><small>{provider.detail}</small></article>{/each}</div><p>{voices.length} persisted voice presets · generated media: <code>data/audio/</code></p></section>
  <section class="panel providers"><span class="section-number">Video</span><h2>Renderer & recording capabilities</h2><p>Native exports use deterministic Canvas frames with WebCodecs or bounded raw-frame FFmpeg fallback. OBS remains realtime.</p>{#if video}<div class="provider-cards"><article><span class:ready={video.offline_available}>{video.offline_available ? 'Ready' : 'Unavailable'}</span><strong>Native compositor</strong><small>Canvas2D {video.native_compositor_available ? '✓' : '—'} · WebCodecs {video.webcodecs_available ? '✓' : '—'} · H.264 {video.webcodecs_h264 ? '✓' : '—'} · VP9 {video.webcodecs_vp9 ? '✓' : '—'} · Raw {video.raw_frame_available ? '✓' : '—'}</small><small>Default {video.default_render_engine} · legacy {video.legacy_renderer_available ? 'available' : 'unavailable'}</small></article><article><span class:ready={video.obs_configured}>{video.obs_configured ? 'Configured' : 'Unavailable'}</span><strong>OBS WebSocket v5</strong><small>{video.obs_host}:{video.obs_port} · scene {video.obs_scene}</small><small>Realtime recording; password remains server-side.</small></article><article><span class:ready={video.output_writable}>{video.output_writable ? 'Writable' : 'Unavailable'}</span><strong>Video storage</strong><small>{(video.storage_bytes / 1024 / 1024 / 1024).toFixed(2)} GB used · {(video.free_bytes / 1024 / 1024 / 1024).toFixed(1)} GB free</small><small>{video.output_root} · concurrency {video.concurrency}</small></article></div>{#if video.detail.length}<ul>{#each video.detail as detail}<li>{detail}</li>{/each}</ul>{/if}{/if}</section>
  <section class="panel"><span class="section-number"><i class="ph ph-palette" aria-hidden="true"></i> 01</span><h2>Application theme</h2><p>Dashboard styling, separate from renderer output.</p><div class="theme-options"><button class:active={appTheme === 'light'} on:click={() => setAppTheme('light')}><i class="ph ph-sun" aria-hidden="true"></i>Koala Light</button><button class:active={appTheme === 'dark'} on:click={() => setAppTheme('dark')}><i class="ph ph-moon" aria-hidden="true"></i>Koala Dark</button></div></section>

  <section class="panel">
    <span class="section-number">02</span><h2>Renderer defaults</h2>
    <p>Versioned declarative settings. Existing battle data is never changed.</p>
    <div class="form-grid">
      <label>Production theme<select value={renderer.theme} on:change={(event) => updateRenderer({ theme: event.currentTarget.value as RendererTheme })}><option value="koala-dark">Koala Dark</option><option value="koala-light">Koala Light</option></select></label>
      <label>Default layout<select value={renderer.layout} on:change={(event) => updateRenderer({ layout: event.currentTarget.value as RendererConfig['layout'] })}><option value="standard-landscape">Landscape 16:9</option><option value="standard-vertical">Vertical 9:16</option><option value="overlay-landscape">Overlay landscape</option></select></label>
      <label>Presentation preset<select value={renderer.preset} on:change={(event) => updateRenderer({ preset: event.currentTarget.value as RendererConfig['preset'] })}><option value="live">Live</option><option value="video">Video</option><option value="fast">Fast</option><option value="instant">Instant</option></select></label>
      <label>Commentary history<select value={renderer.commentaryMode} on:change={(event) => updateRenderer({ commentaryMode: event.currentTarget.value as RendererConfig['commentaryMode'] })}><option value="latest">Latest</option><option value="last-3">Last 3</option><option value="full">Full</option><option value="hidden">Hidden</option></select></label>
      <label>Effect quality<select value={renderer.effects} on:change={(event) => updateRenderer({ effects: event.currentTarget.value as EffectQuality })}><option value="off">Off</option><option value="low">Low</option><option value="standard">Standard</option><option value="high">High</option></select></label>
    </div>
    <div class="toggles">
      <label><input type="checkbox" checked={renderer.showBattleLog} on:change={(event) => updateRenderer({ showBattleLog: event.currentTarget.checked })} />Battle log</label>
      <label><input type="checkbox" checked={renderer.animatedSprites} on:change={(event) => updateRenderer({ animatedSprites: event.currentTarget.checked })} />Animated sprites</label>
      <label><input type="checkbox" checked={renderer.showDamageNumbers} on:change={(event) => updateRenderer({ showDamageNumbers: event.currentTarget.checked })} />Damage numbers</label>
      <label><input type="checkbox" checked={renderer.reducedMotion} on:change={(event) => updateRenderer({ reducedMotion: event.currentTarget.checked })} />Reduced motion</label>
      <label><input type="checkbox" checked={renderer.transparentBackground} on:change={(event) => updateRenderer({ transparentBackground: event.currentTarget.checked })} />Transparent overlay</label>
    </div>
  </section>

  <section class="panel assets"><header><div><span class="section-number">03</span><h2>Local assets</h2></div><button class="button secondary" on:click={rescan}>Rescan assets</button></header><p>Optional user-installed media under <code>{assets?.root || 'data/assets'}</code>. KoalaBattle never downloads or bundles Pokémon media.</p>{#if assets}<div class="asset-summary"><div><strong>{assets.pokemon_species}</strong><span>Pokémon species</span></div><div><strong class:ok={assets.valid}>{assets.valid ? 'VALID' : 'CHECK'}</strong><span>Directory status</span></div><div><strong>{assets.unresolved_species.length}</strong><span>Missing requests</span></div></div><div class="asset-categories">{#each Object.entries(assets.categories) as [name, category]}<div><span class:installed={category.installed}>{category.installed ? '✓' : '—'}</span><strong>{name.replaceAll('_', ' ')}</strong><small>{category.files} files · {category.directory}</small></div>{/each}</div>{#if assets.unresolved_species.length}<details><summary>Missing asset identifiers ({assets.unresolved_species.length})</summary><code>{assets.unresolved_species.join(', ')}</code></details>{/if}{#if assets.invalid_files.length}<details open><summary>Unsupported files</summary><code>{assets.invalid_files.join(', ')}</code></details>{/if}{/if}<div class="asset-debug"><label>Resolve species<input bind:value={assetQuery} placeholder="Mr. Mime" /></label><button class="button secondary" on:click={resolveAsset}>Resolve path</button>{#if resolution}<code>{resolution.found ? resolution.resolved_path : `${resolution.species_id}: polished placeholder`}</code>{/if}</div></section>

  <section class="panel obs"><span class="section-number">04</span><h2>OBS Browser Source</h2><p>Read-only overlay URL. No API keys, secrets, or engine controls.</p><div class="form-grid"><label>Match<select bind:value={selectedMatch}>{#each matches as match}<option value={match.id}>{match.config.players[0].display_name} vs {match.config.players[1].display_name}</option>{/each}</select></label><label>Preset<select bind:value={obsPreset}><option value="youtube">YouTube 1080p</option><option value="twitch">Twitch 1080p</option><option value="vertical">Vertical 1080×1920</option></select></label></div><div class="obs-spec"><span><strong>{preset.width}×{preset.height}</strong>browser source</span><span><strong>{preset.fps} FPS</strong>recommended</span><span><strong>{renderer.transparentBackground ? 'ON' : 'OFF'}</strong>transparency</span></div><label>Overlay URL<div class="copy-row"><input readonly value={overlayUrl} /><button class="button" on:click={copyOverlay} disabled={!selectedMatch}>{copied ? 'Copied' : 'Copy URL'}</button></div></label>{#if selectedMatch}<a class="preview-link" href={overlayUrl}>Open overlay preview →</a>{/if}</section>

  <section class="panel connection"><span class="section-number">05</span><h2>Connection</h2><dl><dt>API</dt><dd>{apiBase()}</dd><dt>WebSocket</dt><dd>{wsBase()}</dd><dt>Renderer config</dt><dd>v{renderer.version}</dd></dl></section>
</div>

<style>
  .settings-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem}.panel{position:relative;padding:1.5rem;box-shadow:none}.panel p{color:var(--muted);line-height:1.6}.section-number{color:var(--accent);font:.65rem var(--mono)}.panel h2{margin:.4rem 0}.providers{grid-column:1/-1}.provider-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem}.provider-cards article{display:grid;gap:.3rem;padding:1rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.provider-cards article>span{color:var(--muted);font:.62rem var(--mono);text-transform:uppercase}.provider-cards article>span.ready{color:var(--accent)}.provider-cards strong{text-transform:capitalize}.provider-cards small{color:var(--muted);font:.65rem var(--mono)}.theme-options{display:flex;gap:.7rem;margin-top:1.2rem}.theme-options button{flex:1;min-height:70px;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong);color:var(--text);cursor:pointer}.theme-options button.active{border-color:var(--accent);box-shadow:inset 0 0 0 2px var(--accent)}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}.toggles{display:flex;flex-wrap:wrap;gap:.8rem;margin-top:1rem}.toggles label{display:flex;align-items:center;gap:.45rem}.toggles input{width:18px;min-height:18px}.assets,.obs{grid-column:1/-1}.assets header{display:flex;justify-content:space-between;align-items:center;gap:1rem}.asset-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:1.2rem 0;overflow:hidden;border:1px solid var(--border);border-radius:.7rem;background:var(--border)}.asset-summary>div{display:grid;padding:1rem;background:var(--panel-strong)}.asset-summary strong{font-size:1.6rem}.asset-summary strong.ok{color:var(--accent)}.asset-summary span{color:var(--muted);font:.65rem var(--mono)}.asset-categories{display:grid;grid-template-columns:repeat(2,1fr);gap:.5rem}.asset-categories>div{display:grid;grid-template-columns:24px 1fr;align-items:center;padding:.7rem;border:1px solid var(--border);border-radius:.55rem}.asset-categories span{grid-row:1/3;color:var(--muted)}.asset-categories span.installed{color:var(--accent)}.asset-categories strong{font-size:.75rem;text-transform:capitalize}.asset-categories small{color:var(--muted);font:.58rem var(--mono)}details{margin-top:.8rem;padding:.8rem;border:1px solid var(--border);border-radius:.55rem}details code{display:block;margin-top:.6rem;overflow-wrap:anywhere}.asset-debug{display:grid;grid-template-columns:1fr auto;align-items:end;gap:.7rem;margin-top:1rem}.asset-debug code{grid-column:1/-1;padding:.8rem;border-radius:.5rem;background:var(--panel-strong);overflow-wrap:anywhere}.obs-spec{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:1rem 0;background:var(--border)}.obs-spec span{display:grid;padding:1rem;background:var(--panel-strong);color:var(--muted);font:.65rem var(--mono)}.obs-spec strong{color:var(--text);font:700 1rem var(--display)}.copy-row{display:grid;grid-template-columns:1fr auto;gap:.6rem}.copy-row input{font:.68rem var(--mono)}.preview-link{display:inline-block;margin-top:1rem;color:var(--accent);font-weight:700}.connection{grid-column:1/-1}dl{display:grid;grid-template-columns:auto 1fr;gap:.7rem}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere;font-family:var(--mono);font-size:.8rem}code{font-family:var(--mono);color:var(--accent)}@media(max-width:760px){.settings-grid,.form-grid,.asset-categories,.provider-cards{grid-template-columns:1fr}.providers,.assets,.obs,.connection{grid-column:auto}.asset-summary,.obs-spec{grid-template-columns:1fr}.asset-debug{grid-template-columns:1fr}.copy-row{grid-template-columns:1fr}.assets header{align-items:start;flex-direction:column}}
  .section-number,.preview-link,.theme-options button{display:flex;align-items:center;gap:.4rem}.theme-options button{justify-content:center;transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}.theme-options button:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}.provider-cards article{transition:transform .18s ease,border-color .18s ease}.provider-cards article:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 30%,var(--border))}.provider-cards strong{text-transform:none}
</style>
