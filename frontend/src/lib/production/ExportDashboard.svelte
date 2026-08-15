<script lang="ts">
  import { onMount } from 'svelte';
  import { apiBase, cancelVideoExport, createVideoExport, getVideoSetup, retryVideoExport } from '../api';
  import type { ExportBackend, ProductionTimeline, RendererCapabilities, VideoExportJob, VideoExportPreset } from '../types';

  export let matchId: string;
  export let productions: ProductionTimeline[] = [];
  export let selectedProduction: ProductionTimeline | null = null;

  let presets: VideoExportPreset[] = [];
  let capabilities: RendererCapabilities | null = null;
  let jobs: VideoExportJob[] = [];
  let backend: ExportBackend = 'offline';
  let presetId = 'youtube-1080p60';
  let encoder = 'auto';
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
    } catch (caught) {
      if (showError) error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function render() {
    if (!selectedProduction) return;
    busy = true;
    error = '';
    try {
      const job = await createVideoExport(selectedProduction.id, backend, presetId, outputName, encoder);
      jobs = [job, ...jobs.filter((item) => item.id !== job.id)];
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      busy = false;
    }
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
        job.production_id, job.backend, job.preset.id, job.output_name, job.encoder
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
</script>

<section class="export panel" aria-label="Video export">
  <div class="export-head">
    <div><span class="eyebrow">Video production</span><h2>Render & recording jobs</h2></div>
    {#if capabilities}<span class:ready={backend === 'offline' ? capabilities.offline_available : capabilities.obs_configured}>{backend === 'offline' ? (capabilities.offline_available ? 'Renderer ready' : 'Renderer unavailable') : (capabilities.obs_configured ? 'OBS configured' : 'OBS unavailable')}</span>{/if}
  </div>
  <div class="controls">
    <label>Production<select bind:value={selectedProduction}>{#each productions as item}<option value={item}>{item.profile.display_name} · r{item.revision} · {item.status}</option>{/each}</select></label>
    <label>Backend<select bind:value={backend}><option value="offline">Offline renderer</option><option value="obs">OBS recorder · realtime</option></select></label>
    <label>Preset<select bind:value={presetId}>{#each compatible as preset}<option value={preset.id}>{preset.display_name}</option>{/each}</select></label>
    <label>Encoder<select bind:value={encoder}><option value="auto">Auto</option><option value="software">Software H.264</option>{#if capabilities?.encoders.includes('h264_videotoolbox')}<option value="videotoolbox">VideoToolbox</option>{/if}{#if capabilities?.encoders.includes('h264_nvenc')}<option value="nvenc">NVENC</option>{/if}</select></label>
    <label>Output name<input bind:value={outputName} maxlength="120" placeholder="Auto-generated" /></label>
    <button class="render" on:click={render} disabled={busy || !selectedProduction || selectedProduction.status !== 'finalized'}>{backend === 'obs' ? 'Start recording' : 'Render video'}</button>
  </div>
  {#if capabilities}
    <details><summary>Capabilities & storage</summary><div class="capabilities"><span>FFmpeg {capabilities.ffmpeg_available ? '✓' : '—'}</span><span>Chromium {capabilities.chromium_available ? '✓' : '—'}</span><span>Playwright {capabilities.playwright_available ? '✓' : '—'}</span><span>Concurrency {capabilities.concurrency}</span><span>Storage {bytes(capabilities.storage_bytes)}</span><span>Free {bytes(capabilities.free_bytes)}</span>{#if backend === 'obs'}<span>Scene {capabilities.obs_scene}</span><span>10-minute video ≈ 10-minute recording</span>{/if}</div></details>
  {/if}
  <div class="jobs">
    {#each jobs as job}
      <article>
        <div><strong>{job.output_name}</strong><span>{job.preset.display_name} · {job.backend}</span></div>
        <div class="job-status"><b data-status={job.status}>{job.status}</b><span>{job.stage}</span></div>
        <progress max="100" value={job.progress}>{job.progress}%</progress>
        <output>{job.progress.toFixed(1)}%</output>
        <div class="actions">
          {#if ['queued','preparing','rendering','encoding','finalizing'].includes(job.status)}<button on:click={() => cancel(job)}>Cancel</button>{/if}
          {#if ['failed','cancelled'].includes(job.status)}<button on:click={() => retry(job)}>Retry</button>{/if}
          {#if job.status === 'completed'}<a href={`${apiBase()}/api/video/jobs/${job.id}/download`}>Open / Download</a><a href={`${apiBase()}/api/video/jobs/${job.id}/captions`}>SRT</a><button on:click={() => rerender(job)} disabled={busy}>Render again</button>{/if}
        </div>
        {#if job.status === 'completed'}<small>Video {seconds(job.video_duration_ms)} · render {seconds(job.render_duration_ms)} · {bytes(job.output_file_size)}</small>{/if}
        {#if job.error_detail}<p class="error">{job.error_category}: {job.error_detail}</p>{/if}
      </article>
    {:else}<p class="empty">No video exports for this match.</p>{/each}
  </div>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
  .export{display:grid;gap:1rem;margin-top:1rem;padding:1rem}.export-head,.controls,.capabilities{display:flex;align-items:center;justify-content:space-between;gap:.7rem;flex-wrap:wrap}.export-head h2{margin:.2rem 0 0}.export-head>span{padding:.35rem .55rem;border:1px solid var(--border);border-radius:999px;color:var(--muted);font:.62rem var(--mono)}.export-head>span.ready{border-color:var(--accent);color:var(--accent)}.controls{align-items:end}.controls label{min-width:145px;flex:1}.controls input,.controls select{min-height:42px}.controls .render{min-height:42px;border-color:var(--accent);background:var(--accent);color:var(--accent-ink);font-weight:800}.capabilities{justify-content:flex-start;margin-top:.7rem}.capabilities span{padding:.35rem .5rem;border:1px solid var(--border);border-radius:.4rem;font:.62rem var(--mono)}.jobs{display:grid;gap:.65rem}.jobs article{display:grid;grid-template-columns:minmax(180px,1.4fr) minmax(120px,.8fr) minmax(160px,1fr) 55px auto;align-items:center;gap:.8rem;padding:.8rem;border:1px solid var(--border);border-radius:.7rem;background:var(--panel-strong)}.jobs article>div:first-child,.job-status{display:grid;gap:.2rem}.jobs article span,.jobs article small{color:var(--muted);font:.62rem var(--mono)}.job-status b{text-transform:uppercase;font:.65rem var(--mono)}.job-status b[data-status='completed']{color:var(--accent)}.job-status b[data-status='failed']{color:var(--danger)}progress{width:100%}.actions{display:flex;gap:.4rem;flex-wrap:wrap}.actions a,.actions button{padding:.45rem .55rem;border:1px solid var(--border);border-radius:.4rem;background:transparent;color:var(--text);font:.62rem var(--mono);text-decoration:none}.jobs article>small,.jobs article>.error{grid-column:1/-1}.empty{color:var(--muted)}@media(max-width:900px){.jobs article{grid-template-columns:1fr 1fr}.jobs article progress{grid-column:1/-1}.jobs article output{display:none}.actions{justify-content:end}}@media(max-width:560px){.controls{display:grid;grid-template-columns:1fr}.controls label,.controls button{width:100%}.jobs article{grid-template-columns:1fr}.jobs article progress,.jobs article .actions{grid-column:1}.actions{justify-content:start}}
</style>
