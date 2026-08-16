<script lang="ts">
  import { onMount } from 'svelte';
  import { apiBase, cancelVideoExport, createVideoExport, getVideoPreflight, getVideoSetup, retryVideoExport } from '../api';
  import type { ExportBackend, ExportPreflight, ProductionTimeline, RenderEngine, RendererCapabilities, VideoExportJob, VideoExportPreset } from '../types';

  export let matchId: string;
  export let productions: ProductionTimeline[] = [];
  export let selectedProduction: ProductionTimeline | null = null;

  let presets: VideoExportPreset[] = [];
  let capabilities: RendererCapabilities | null = null;
  let jobs: VideoExportJob[] = [];
  let preflight: ExportPreflight | null = null;
  let backend: ExportBackend = 'offline';
  let presetId = 'youtube-1080p60';
  let encoder = 'auto';
  let renderEngine: RenderEngine = 'native';
  let outputName = '';
  let busy = false;
  let error = '';
  let poll: ReturnType<typeof setInterval> | null = null;

  $: compatible = presets.filter((preset) => preset.layout === selectedProduction?.profile.aspect_ratio);
  $: if (compatible.length && !compatible.some((preset) => preset.id === presetId)) presetId = compatible[0].id;

  onMount(() => {
    void load();
    poll = setInterval(() => {
      if (jobs.some((job) => !['completed', 'failed', 'cancelled'].includes(job.status))) void load(false);
    }, 1000);
    return () => { if (poll) clearInterval(poll); };
  });

  async function load(showError = true) {
    try {
      const setup = await getVideoSetup(matchId);
      presets = setup.presets;
      capabilities = setup.capabilities;
      jobs = setup.jobs;
      await refreshPreflight();
    } catch (caught) {
      if (showError) error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function render() {
    if (!selectedProduction) return;
    busy = true;
    error = '';
    try {
      await refreshPreflight();
      if (!preflight?.ready) throw new Error('Export preflight is not ready. Resolve the checks below.');
      const job = await createVideoExport(selectedProduction.id, backend, presetId, outputName, encoder, renderEngine);
      jobs = [job, ...jobs.filter((item) => item.id !== job.id)];
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      busy = false;
    }
  }

  async function refreshPreflight() {
    preflight = selectedProduction
      ? await getVideoPreflight(selectedProduction.id, backend, renderEngine)
      : null;
  }

  async function cancel(job: VideoExportJob) {
    const value = await cancelVideoExport(job.id);
    jobs = jobs.map((item) => item.id === value.id ? value : item);
  }

  async function retry(job: VideoExportJob) {
    try {
      const value = await retryVideoExport(job.id);
      jobs = [value, ...jobs];
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function rerender(job: VideoExportJob) {
    busy = true;
    error = '';
    try {
      const value = await createVideoExport(
        job.production_id, job.backend, job.preset.id, job.output_name, job.encoder, job.render_engine
      );
      jobs = [value, ...jobs];
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      busy = false;
    }
  }

  const bytes = (value: number | null) => value === null ? '—' : `${(value / 1024 / 1024).toFixed(1)} MB`;
  const seconds = (value: number | null) => value === null ? '—' : `${(value / 1000).toFixed(1)}s`;
  const duration = (milliseconds: number) => {
    const total = Math.max(0, Math.round(milliseconds / 1000));
    return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
  };
  const checkReady = (name: string, value: string) => {
    const normalized = value.toLowerCase();
    if (['music', 'sound_pack'].includes(name)) return normalized.includes('optional');
    if (name === 'speech') {
      const match = normalized.match(/^(\d+)\/(\d+) cached$/);
      return Boolean(match && match[1] === match[2]);
    }
    if (name === 'voice_quality') return !normalized.includes('basic offline');
    if (name === 'sprites') return normalized.includes('local asset provider');
    if (name === 'disk') return normalized.includes('bytes free');
    if (name === 'render_engine') return true;
    return ['ready', 'available', 'configured', 'finalized', 'partial', 'native'].includes(normalized);
  };
</script>

<section class="export panel" aria-label="Video export">
  <div class="export-head">
    <div><span class="eyebrow">Video production</span><h2>Render & recording jobs</h2></div>
    {#if capabilities}<span class:ready={backend === 'offline' ? capabilities.offline_available : capabilities.obs_configured}>{backend === 'offline' ? (capabilities.offline_available ? 'Renderer ready' : 'Renderer unavailable') : (capabilities.obs_configured ? 'OBS configured' : 'OBS unavailable')}</span>{/if}
  </div>
  <div class="controls">
    <label>Production<select bind:value={selectedProduction} on:change={refreshPreflight}>{#each productions as item}<option value={item}>{item.profile.display_name} · r{item.revision} · {item.status}</option>{/each}</select></label>
    <label>Backend<select bind:value={backend} on:change={refreshPreflight}><option value="offline">Offline renderer</option><option value="obs">OBS recorder · realtime</option></select></label>
    {#if backend === 'offline'}<label>Render engine<select bind:value={renderEngine} on:change={refreshPreflight}><option value="native">Native Canvas + WebCodecs</option><option value="legacy">Legacy screenshots · debug</option></select></label>{/if}
    <label>Preset<select bind:value={presetId}>{#each compatible as preset}<option value={preset.id}>{preset.display_name}</option>{/each}</select></label>
    <label>Encoder<select bind:value={encoder}><option value="auto">Auto</option><option value="software">Software H.264</option>{#if capabilities?.encoders.includes('h264_videotoolbox')}<option value="videotoolbox">VideoToolbox</option>{/if}{#if capabilities?.encoders.includes('h264_nvenc')}<option value="nvenc">NVENC</option>{/if}</select></label>
    <label>Output name<input bind:value={outputName} maxlength="120" placeholder="Auto-generated" /></label>
    <button class:loading={busy} class="button render" on:click={render} disabled={busy || !selectedProduction || !['finalized','ready','partial'].includes(selectedProduction.status)}><i class={`ph ${backend === 'obs' ? 'ph-record' : 'ph-film-reel'}`} aria-hidden="true"></i>{backend === 'obs' ? 'Start recording' : 'Render video'}</button>
  </div>
  {#if capabilities && preflight}
    <section class="preflight" aria-label="Export preflight"><header><div><span class="eyebrow">Preflight</span><strong><i class={`ph ${preflight.ready ? 'ph-check-circle' : 'ph-warning-circle'}`} aria-hidden="true"></i>{preflight.ready ? 'Ready to render' : 'Action required'}</strong></div><button class="button ghost compact" on:click={refreshPreflight}><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>Refresh checks</button></header><div>{#each Object.entries(preflight.checks) as [name, value]}<span data-ready={checkReady(name, value)}><small>{name.replaceAll('_', ' ')}</small><strong>{value}</strong></span>{/each}<span data-ready={capabilities.free_bytes > 0}><small>Disk free</small><strong>{bytes(capabilities.free_bytes)}</strong></span><span data-ready={true}><small>Encoder</small><strong>{encoder === 'auto' ? (capabilities.encoders[0] || 'Auto') : encoder}</strong></span></div>{#if preflight.warnings.length}<p>{preflight.warnings.join(' · ')}</p>{/if}</section>
  {/if}
  <div class="jobs">
    {#each jobs as job}
      <article>
        <div><strong>{job.output_name}</strong><span>{job.preset.display_name} · {job.backend} · {job.render_engine}</span></div>
        <div class="job-status"><b data-status={job.status}>{job.status}</b><span>{job.stage}</span>{#if ['rendering','encoding','finalizing'].includes(job.status)}<small>Video duration {duration(job.end_ms - job.start_ms)} · rendered {duration((job.end_ms - job.start_ms) * job.progress / 100)}</small>{/if}</div>
        <progress max="100" value={job.progress}>{job.progress}%</progress>
        <output>{job.progress.toFixed(1)}%</output>
        <div class="actions">
          {#if ['queued','preparing','rendering','encoding','finalizing'].includes(job.status)}<button on:click={() => cancel(job)}>Cancel</button>{/if}
          {#if ['failed','cancelled'].includes(job.status)}<button on:click={() => retry(job)}>Retry</button>{/if}
          {#if job.status === 'completed'}<a href={`${apiBase()}/api/video/jobs/${job.id}/download`}>Open / Download</a><a href={`${apiBase()}/api/video/jobs/${job.id}/captions`}>SRT</a><button on:click={() => rerender(job)} disabled={busy}>Render again</button>{/if}
        </div>
        {#if job.status === 'completed'}<small>Video {seconds(job.video_duration_ms)} · total export {seconds(job.render_duration_ms)} · end-to-end {job.render_duration_ms ? (((job.end_ms - job.start_ms) / job.render_duration_ms).toFixed(2)) : '—'}× · {bytes(job.output_file_size)}</small>{/if}
        {#if job.status === 'completed' && job.output_frame_count}<details><summary>Advanced render metrics</summary><small>Output {job.output_frame_count.toLocaleString()} frames · unique {job.unique_rendered_frames?.toLocaleString() || '—'} · static held {job.static_held_frames !== null ? `${(job.static_held_frames / job.output_frame_count * 100).toFixed(1)}%` : '—'} · animated {job.animated_frames?.toLocaleString() || '—'} · encoder {job.selected_encoder || '—'} · {job.renderer_transport || job.backend}</small></details>{/if}
        {#if job.error_detail}<p class="error">{job.error_category}: {job.error_detail}</p>{/if}
      </article>
    {:else}<div class="empty"><strong>No video exports yet</strong><span>Choose a production and preset above, run preflight, then start the first render.</span></div>{/each}
  </div>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
  .preflight header strong{display:flex;align-items:center;gap:.4rem}.preflight header strong .ph{color:var(--accent);font-size:1.1rem}
  .export{display:grid;gap:1rem;margin-top:1rem;padding:1rem}.export-head,.controls{display:flex;align-items:center;justify-content:space-between;gap:.7rem;flex-wrap:wrap}.export-head h2{margin:.2rem 0 0}.export-head>span{padding:.35rem .55rem;border:1px solid var(--border);border-radius:999px;color:var(--muted);font:.62rem var(--mono)}.export-head>span.ready{border-color:var(--accent);color:var(--accent)}.controls{align-items:end}.controls label{min-width:145px;flex:1}.controls input,.controls select{min-height:42px}.preflight{padding:1rem;border:1px solid var(--border);border-radius:var(--radius);background:var(--panel-strong)}.preflight header{display:flex;align-items:center;justify-content:space-between}.preflight header div{display:grid;gap:.2rem}.preflight>div{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:1px;margin-top:.8rem;overflow:hidden;border:1px solid var(--border);border-radius:.6rem;background:var(--border)}.preflight>div span{display:grid;gap:.25rem;padding:.7rem;background:var(--panel)}.preflight small{color:var(--muted);font:.56rem var(--mono);text-transform:uppercase}.preflight span strong{color:var(--warning);font-size:.72rem;text-transform:capitalize}.preflight span[data-ready='true'] strong{color:var(--accent)}.preflight p{margin:.7rem 0 0;color:var(--warning);font-size:.72rem}.jobs{display:grid;gap:.65rem}.jobs article{display:grid;grid-template-columns:minmax(180px,1.4fr) minmax(180px,.9fr) minmax(160px,1fr) 55px auto;align-items:center;gap:.8rem;padding:.8rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.jobs article>div:first-child,.job-status{display:grid;gap:.2rem}.jobs article span,.jobs article small{color:var(--muted);font:.62rem var(--mono)}.job-status b{text-transform:uppercase;font:.65rem var(--mono)}.job-status b[data-status='completed']{color:var(--accent)}.job-status b[data-status='failed']{color:var(--danger)}progress{width:100%;accent-color:var(--accent)}.actions{display:flex;gap:.4rem;flex-wrap:wrap}.actions a,.actions button{padding:.45rem .55rem;border:1px solid var(--border);border-radius:.4rem;background:transparent;color:var(--text);font:.62rem var(--mono);text-decoration:none}.jobs article>small,.jobs article>.error,.jobs article>details{grid-column:1/-1}.jobs details{padding:.55rem .65rem;border:1px solid var(--border);border-radius:.45rem}.jobs summary{cursor:pointer;color:var(--muted);font:.62rem var(--mono)}.jobs details small{display:block;margin-top:.45rem}.empty{display:grid;gap:.3rem;padding:1rem;border:1px dashed var(--border);border-radius:.7rem;color:var(--muted)}.empty strong{color:var(--text)}@media(max-width:900px){.jobs article{grid-template-columns:1fr 1fr}.jobs article progress{grid-column:1/-1}.jobs article output{display:none}.actions{justify-content:end}}@media(max-width:560px){.controls{display:grid;grid-template-columns:1fr}.controls label,.controls button{width:100%}.jobs article{grid-template-columns:1fr}.jobs article progress,.jobs article .actions{grid-column:1}.actions{justify-content:start}}
</style>
