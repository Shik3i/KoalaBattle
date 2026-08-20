<script lang="ts">
  import { onMount } from 'svelte';
  import { api, apiBase, configureProvider, uploadVoiceReference, wsBase } from '$lib/api';
  import { loadRendererConfig, saveRendererConfig } from '$lib/presentation/config';
  import { hydrateStoredProviderSettings, loadProviderSettings, saveProviderSetting, type StoredProviderSetting } from '$lib/provider-settings';
  import { defaultRendererConfig, type EffectQuality, type RendererConfig, type RendererTheme } from '$lib/presentation/types';
  import type { AssetResolution, AssetScanReport, MatchSummary, ProviderStatus, RendererCapabilities, SpeechProviderStatus, VoicePersona, VoicePreset } from '$lib/types';

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
  let personas: VoicePersona[] = [];
  let video: RendererCapabilities | null = null;
  let selectedMatch = '';
  let obsPreset: ObsPreset = 'youtube';
  let baseUrl = '';
  let copied = false;
  let assetQuery = 'Mr. Mime';
  let resolution: AssetResolution | null = null;
  let error = '';
  let providerDrafts: Record<string, StoredProviderSetting> = {};
  let savingProvider = '';
  let uploadingVoice = '';

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
      await hydrateStoredProviderSettings();
      const [nextAssets, nextMatches, nextProviders, nextSpeechProviders, nextVoices, nextPersonas, nextVideo] = await Promise.all([
        api<AssetScanReport>('/api/assets/status'),
        api<MatchSummary[]>('/api/matches?limit=100'),
        api<{ providers: ProviderStatus[] }>('/api/providers').then((result) => result.providers),
        api<{ providers: SpeechProviderStatus[] }>('/api/production/providers').then((result) => result.providers),
        api<VoicePreset[]>('/api/production/voices'),
        api<{ personas: VoicePersona[] }>('/api/production/personas').then((result) => result.personas),
        api<RendererCapabilities>('/api/video/capabilities')
      ]);
      const stored = loadProviderSettings();
      providerDrafts = Object.fromEntries(nextProviders.map((provider) => [
        provider.id,
        stored[provider.id] || {
          apiKey: '',
          baseUrl: provider.id === 'openai-compatible' ? provider.default_base_url || '' : ''
        }
      ]));
      assets = nextAssets;
      matches = nextMatches;
      providers = nextProviders;
      speechProviders = nextSpeechProviders;
      voices = nextVoices;
      personas = nextPersonas;
      video = nextVideo;
      selectedMatch ||= matches[0]?.id || '';
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function uploadReference(voice: VoicePreset, event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    uploadingVoice = voice.id;
    error = '';
    try {
      if (!file.name.toLowerCase().endsWith('.wav')) throw new Error('Qwen reference audio must be a WAV file.');
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error || new Error('Could not read the reference audio.'));
        reader.readAsDataURL(file);
      });
      const updated = await uploadVoiceReference(voice, dataUrl.split(',')[1] || '');
      voices = voices.map((item) => item.id === updated.id ? updated : item);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      uploadingVoice = '';
      input.value = '';
    }
  }

  function personaVoice(personaId: string): VoicePreset | undefined {
    return voices.find((voice) => voice.persona_id === personaId);
  }

  async function saveProvider(provider: ProviderStatus) {
    const draft = providerDrafts[provider.id] || { apiKey: '', baseUrl: '' };
    savingProvider = provider.id;
    error = '';
    try {
      saveProviderSetting(provider.id, draft);
      await configureProvider(provider.id, draft.apiKey, draft.baseUrl || null);
      providers = (await api<{ providers: ProviderStatus[] }>('/api/providers')).providers;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      savingProvider = '';
    }
  }

  async function clearProvider(provider: ProviderStatus) {
    providerDrafts = {
      ...providerDrafts,
      [provider.id]: { apiKey: '', baseUrl: '' }
    };
    await saveProvider({ ...provider, default_base_url: null });
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
    system: 'Edge Neural + system fallback', qwen_local: 'Qwen3-TTS · local', elevenlabs: 'ElevenLabs'
  })[id] || id.replaceAll('_', ' ');
</script>

<div class="page-head"><div><span class="eyebrow">Local production configuration</span><h1>Settings</h1></div></div>
{#if error}<p class="error">{error}</p>{/if}

<div class="settings-grid">
  <section class="panel providers"><span class="section-number"><i class="ph ph-plugs-connected" aria-hidden="true"></i> Providers</span><h2>Provider settings</h2><p>Keys stay in this browser's localStorage and in backend memory while it runs. They are never returned by the API, stored in matches, or written to the database. A backend restart requires this page to rehydrate them.</p><div class="provider-settings">{#each providers as provider}<article class:configured={provider.configured}><header><div><strong>{provider.label || providerLabel(provider.id)}</strong><small>{provider.configured ? `Configured · ${provider.source}` : provider.requires_api_key ? `Needs ${provider.environment_variable || 'API key'}` : 'Ready for a custom endpoint'}</small></div><span class:ready={provider.configured}>{provider.configured ? 'Ready' : 'Not configured'}</span></header><small>{provider.capabilities.structured_output ? 'Structured output' : 'Plain JSON'} · {provider.capabilities.model_listing ? 'model discovery' : 'custom model ID'} · default model <code>{provider.default_model}</code></small>{#if provider.requires_api_key}<label>API key<input type="password" autocomplete="off" placeholder={provider.configured ? 'Saved · leave unchanged to keep it' : `Paste ${provider.label} key`} bind:value={providerDrafts[provider.id].apiKey} /></label>{/if}{#if provider.id === 'openai-compatible'}<label>Base URL<input type="url" placeholder="http://host.docker.internal:1234/v1" bind:value={providerDrafts[provider.id].baseUrl} /></label>{/if}<div class="provider-actions"><button class="button" type="button" on:click={() => saveProvider(provider)} disabled={savingProvider === provider.id}>{savingProvider === provider.id ? 'Saving…' : 'Save provider'}</button>{#if provider.configured || providerDrafts[provider.id]?.apiKey || providerDrafts[provider.id]?.baseUrl}<button class="button secondary" type="button" on:click={() => clearProvider(provider)} disabled={savingProvider === provider.id}>Clear browser setting</button>{/if}</div></article>{/each}</div><a class="preview-link" href="/new"><i class="ph ph-sword" aria-hidden="true"></i>Choose a configured provider for a battle</a></section>
  <section class="panel providers"><span class="section-number"><i class="ph ph-waveform" aria-hidden="true"></i> Speech</span><h2>Audio providers & voice presets</h2><p>Edge Neural is the free natural default and sends public commentary to Microsoft's online speech service while production audio is prepared. Basic offline system voices remain available. Paid providers require separate configuration and approval.</p><div class="provider-cards">{#each speechProviders as provider}<article><span class:ready={provider.available}>{provider.available ? 'Available' : 'Unavailable'}</span><strong>{providerLabel(provider.id)}</strong><small>{provider.paid ? 'paid / explicit action' : 'zero-cost'} · {provider.supports_timestamps ? 'timestamps' : 'normalized caption timing'}</small><small>{provider.detail}</small></article>{/each}</div><p>{voices.length} persisted voice presets · generated media: <code>data/audio/</code></p></section>
  <section class="panel personas"><span class="section-number"><i class="ph ph-microphone-stage" aria-hidden="true"></i> Voice direction</span><h2>Fictional player personas</h2><p>Use fictional debate archetypes for parody formats such as a presidential debate. These profiles deliberately do not imitate or clone real people. Qwen reference-clone profiles become selectable after uploading a 1–30 second WAV reference.</p><div class="persona-cards">{#each personas as persona}<article><header><div><strong>{persona.display_name}</strong><small>{persona.delivery_profile}</small></div><span class="persona-mode">{persona.recommended_voice_mode}</span></header><p>{persona.description}</p><details><summary>Qwen instruction</summary><code>{persona.instructions}</code></details>{#if personaVoice(persona.id)}<small class:ready={personaVoice(persona.id)?.enabled}>{personaVoice(persona.id)?.enabled ? 'Ready for Player 1 / Player 2 selection' : 'Reference required before selection'}</small><label class="file-input">Upload WAV<input type="file" accept="audio/wav,.wav" on:change={(event) => uploadReference(personaVoice(persona.id)!, event)} disabled={uploadingVoice === personaVoice(persona.id)?.id} /></label>{/if}<small>{persona.disclosure_label}</small></article>{/each}</div></section>
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
  .settings-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem}.panel{position:relative;padding:1.5rem;box-shadow:none}.panel p{color:var(--muted);line-height:1.6}.section-number{color:var(--accent);font:.65rem var(--mono)}.panel h2{margin:.4rem 0}.providers,.personas{grid-column:1/-1}.provider-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem}.provider-cards article{display:grid;gap:.3rem;padding:1rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.provider-cards article>span{color:var(--muted);font:.62rem var(--mono);text-transform:uppercase}.provider-cards article>span.ready{color:var(--accent)}.provider-cards strong{text-transform:capitalize}.provider-cards small{color:var(--muted);font:.65rem var(--mono)}.persona-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem}.persona-cards article{display:grid;gap:.55rem;padding:1rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.persona-cards header{display:flex;align-items:start;justify-content:space-between;gap:.7rem}.persona-cards header div{display:grid;gap:.25rem}.persona-cards header small,.persona-mode{color:var(--muted);font:.62rem var(--mono);text-transform:uppercase}.persona-cards article>small{color:var(--muted);font:.65rem var(--mono);line-height:1.45}.persona-cards article>small.ready{color:var(--accent)}.persona-cards details{margin:0}.persona-cards details code{max-height:140px;overflow:auto}.file-input{display:grid;gap:.3rem;font-size:.72rem}.file-input input{font:.68rem var(--mono)}.theme-options{display:flex;gap:.7rem;margin-top:1.2rem}.theme-options button{flex:1;min-height:70px;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong);color:var(--text);cursor:pointer}.theme-options button.active{border-color:var(--accent);box-shadow:inset 0 0 0 2px var(--accent)}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}.toggles{display:flex;flex-wrap:wrap;gap:.8rem;margin-top:1rem}.toggles label{display:flex;align-items:center;gap:.45rem}.toggles input{width:18px;min-height:18px}.assets,.obs{grid-column:1/-1}.assets header{display:flex;justify-content:space-between;align-items:center;gap:1rem}.asset-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:1.2rem 0;overflow:hidden;border:1px solid var(--border);border-radius:.7rem;background:var(--border)}.asset-summary>div{display:grid;padding:1rem;background:var(--panel-strong)}.asset-summary strong{font-size:1.6rem}.asset-summary strong.ok{color:var(--accent)}.asset-summary span{color:var(--muted);font:.65rem var(--mono)}.asset-categories{display:grid;grid-template-columns:repeat(2,1fr);gap:.5rem}.asset-categories>div{display:grid;grid-template-columns:24px 1fr;align-items:center;padding:.7rem;border:1px solid var(--border);border-radius:.55rem}.asset-categories span{grid-row:1/3;color:var(--muted)}.asset-categories span.installed{color:var(--accent)}.asset-categories strong{font-size:.75rem;text-transform:capitalize}.asset-categories small{color:var(--muted);font:.58rem var(--mono)}details{margin-top:.8rem;padding:.8rem;border:1px solid var(--border);border-radius:.55rem}details code{display:block;margin-top:.6rem;overflow-wrap:anywhere}.asset-debug{display:grid;grid-template-columns:1fr auto;align-items:end;gap:.7rem;margin-top:1rem}.asset-debug code{grid-column:1/-1;padding:.8rem;border-radius:.5rem;background:var(--panel-strong);overflow-wrap:anywhere}.obs-spec{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:1rem 0;background:var(--border)}.obs-spec span{display:grid;padding:1rem;background:var(--panel-strong);color:var(--muted);font:.65rem var(--mono)}.obs-spec strong{color:var(--text);font:700 1rem var(--display)}.copy-row{display:grid;grid-template-columns:1fr auto;gap:.6rem}.copy-row input{font:.68rem var(--mono)}.preview-link{display:inline-block;margin-top:1rem;color:var(--accent);font-weight:700}.connection{grid-column:1/-1}dl{display:grid;grid-template-columns:auto 1fr;gap:.7rem}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere;font-family:var(--mono);font-size:.8rem}code{font-family:var(--mono);color:var(--accent)}@media(max-width:760px){.settings-grid,.form-grid,.asset-categories,.provider-cards,.persona-cards{grid-template-columns:1fr}.providers,.personas,.assets,.obs,.connection{grid-column:auto}.asset-summary,.obs-spec{grid-template-columns:1fr}.asset-debug{grid-template-columns:1fr}.copy-row{grid-template-columns:1fr}.assets header{align-items:start;flex-direction:column}}
  .section-number,.preview-link,.theme-options button{display:flex;align-items:center;gap:.4rem}.theme-options button{justify-content:center;transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}.theme-options button:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}.provider-cards article{transition:transform .18s ease,border-color .18s ease}.provider-cards article:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 30%,var(--border))}.provider-cards strong{text-transform:none}.provider-settings{display:grid;grid-template-columns:repeat(2,1fr);gap:.7rem}.provider-settings article{display:grid;gap:.6rem;padding:1rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.provider-settings article.configured{border-color:color-mix(in srgb,var(--accent) 50%,var(--border))}.provider-settings header{display:flex;justify-content:space-between;align-items:start;gap:.7rem}.provider-settings header div{display:grid;gap:.25rem}.provider-settings header span{color:var(--muted);font:.62rem var(--mono);text-transform:uppercase}.provider-settings header span.ready{color:var(--accent)}.provider-settings small{color:var(--muted);font:.65rem var(--mono);line-height:1.45}.provider-settings label{display:grid;gap:.3rem;font-size:.75rem}.provider-settings input{width:100%}.provider-actions{display:flex;flex-wrap:wrap;gap:.5rem}
</style>
