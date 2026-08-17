import { env } from '$env/dynamic/public';
import type { BrandAsset, BrandAssetKind, BrandAssetLibrary, ExportBackend, ExportPreflight, FormatCatalog, FormatDescriptor, FormatGroup, MatchArchive, ProductionProfile, ProductionStyle, ProductionTimeline, RenderEngine, RendererCapabilities, StylePreset, VideoExportJob, VideoExportPreset, VoicePreset } from './types';

export const apiBase = () => {
  const fallback = env.PUBLIC_API_URL || 'http://localhost:8001';
  if (typeof location === 'undefined' || !location.pathname.startsWith('/render/')) return fallback;
  const hostBrowser = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  return hostBrowser ? fallback : env.PUBLIC_RENDER_API_URL || fallback;
};
export const wsBase = () => env.PUBLIC_WS_URL || apiBase().replace(/^http/, 'ws');

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const getMatch = (id: string) => api<MatchArchive>(`/api/matches/${id}`);
/** The Showdown format registry, served by the pinned local Showdown build. */
export const getFormatCatalog = (signal?: AbortSignal) =>
  api<FormatCatalog>('/api/formats', { signal });
export const getFormatGroups = (supportedOnly = false, signal?: AbortSignal) =>
  api<FormatGroup[]>(`/api/formats/groups?supported_only=${supportedOnly}`, { signal });
export const getFormat = (id: string) => api<FormatDescriptor>(`/api/formats/${id}`);
export const getPresentationMatch = (id: string) =>
  api<MatchArchive>(`/api/matches/${id}/presentation`);
export const getProductions = (matchId: string) =>
  api<ProductionTimeline[]>(`/api/matches/${matchId}/productions`);
export const getProduction = (id: string) => api<ProductionTimeline>(`/api/productions/${id}`);
export const createProduction = (
  matchId: string,
  profileId: string,
  voiceAssignments: Record<string, string>,
  options: { styleId?: string; title?: string | null } = {}
) =>
  api<ProductionTimeline>(`/api/matches/${matchId}/productions`, {
    method: 'POST',
    body: JSON.stringify({
      profile_id: profileId,
      voice_assignments: voiceAssignments,
      style_id: options.styleId || null,
      title: options.title || null
    })
  });
/** Saves presentation settings only; the recorded battle is never modified. */
export const updateProduction = (id: string, patch: { style?: ProductionStyle; title?: string | null; clearTitle?: boolean }) =>
  api<ProductionTimeline>(`/api/productions/${id}/update`, {
    method: 'POST',
    body: JSON.stringify({ style: patch.style ?? null, title: patch.title ?? null, clear_title: patch.clearTitle ?? false })
  });
export const duplicateProduction = (id: string, options: { title?: string | null; styleId?: string | null } = {}) =>
  api<ProductionTimeline>(`/api/productions/${id}/duplicate`, {
    method: 'POST',
    body: JSON.stringify({ title: options.title || null, style_id: options.styleId || null })
  });
export const deleteProduction = (id: string) =>
  api<{ deleted: boolean }>(`/api/productions/${id}/delete`, { method: 'POST' });
export const getStylePresets = () => api<StylePreset[]>('/api/production/styles');
export const saveStylePreset = (displayName: string, description: string, style: ProductionStyle) =>
  api<StylePreset>('/api/production/styles', {
    method: 'POST',
    body: JSON.stringify({ display_name: displayName, description, style })
  });
export const deleteStylePreset = (presetId: string) =>
  api<{ deleted: boolean }>(`/api/production/styles/${presetId}/delete`, { method: 'POST' });
export const getBrandAssets = () => api<BrandAssetLibrary>('/api/branding/assets');
export const uploadBrandAsset = (kind: BrandAssetKind, displayName: string, dataBase64: string) =>
  api<BrandAsset>('/api/branding/assets', {
    method: 'POST',
    body: JSON.stringify({ kind, display_name: displayName, data_base64: dataBase64 })
  });
export const deleteBrandAsset = (id: string, force = false) =>
  api<{ deleted: boolean }>(`/api/branding/assets/${id}/delete?force=${force}`, { method: 'POST' });
export const brandAssetUrl = (id: string) => `${apiBase()}/api/branding/assets/${id}/media`;
export const previewVoice = (presetId: string) =>
  api<{ media_url: string }>('/api/production/voices/preview', {
    method: 'POST',
    body: JSON.stringify({ preset_id: presetId, text: 'KoalaBattle voice preview.', allow_paid: false })
  });
export const prepareProduction = (id: string, allowPaid = false) =>
  api<ProductionTimeline>(`/api/productions/${id}/prepare`, {
    method: 'POST',
    body: JSON.stringify({ force: false, allow_paid: allowPaid })
  });
export const directProduction = (id: string, command: string, clientId?: string) =>
  api<ProductionTimeline>(`/api/productions/${id}/director`, {
    method: 'POST',
    body: JSON.stringify({ command, client_id: clientId || null })
  });
export const getProductionSetup = async () => {
  const [profiles, voices] = await Promise.all([
    api<{ profiles: ProductionProfile[] }>('/api/production/profiles'),
    api<VoicePreset[]>('/api/production/voices')
  ]);
  return { profiles: profiles.profiles, voices };
};
export const getVideoSetup = async (matchId: string) => {
  const [presets, capabilities, jobs] = await Promise.all([
    api<VideoExportPreset[]>('/api/video/presets'),
    api<RendererCapabilities>('/api/video/capabilities'),
    api<VideoExportJob[]>(`/api/video/jobs?match_id=${encodeURIComponent(matchId)}`)
  ]);
  return { presets, capabilities, jobs };
};
export const getVideoPreflight = (productionId: string, backend: ExportBackend, renderEngine: RenderEngine = 'native') =>
  api<ExportPreflight>(`/api/productions/${productionId}/video-preflight?backend=${backend}&render_engine=${renderEngine}`);
export const createVideoExport = (
  productionId: string,
  backend: ExportBackend,
  presetId: string,
  outputName: string,
  encoder: string,
  renderEngine: RenderEngine = 'native'
) => api<VideoExportJob>('/api/video/jobs', {
  method: 'POST',
  body: JSON.stringify({ production_id: productionId, backend, preset_id: presetId, output_name: outputName || null, encoder, render_engine: renderEngine })
});
export const cancelVideoExport = (id: string) =>
  api<VideoExportJob>(`/api/video/jobs/${id}/cancel`, { method: 'POST' });
export const retryVideoExport = (id: string) =>
  api<VideoExportJob>(`/api/video/jobs/${id}/retry`, { method: 'POST' });
