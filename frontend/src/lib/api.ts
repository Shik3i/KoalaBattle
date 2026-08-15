import { env } from '$env/dynamic/public';
import type { MatchArchive } from './types';

export const apiBase = () => env.PUBLIC_API_URL || 'http://localhost:8001';
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
export const getPresentationMatch = (id: string) =>
  api<MatchArchive>(`/api/matches/${id}/presentation`);
