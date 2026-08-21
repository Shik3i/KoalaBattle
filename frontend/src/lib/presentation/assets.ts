import { apiBase } from '../api';

export function pokemonAssetUrl(
  species: string,
  perspective: 'front' | 'back',
  animated: boolean
): string {
  const query = new URLSearchParams({ perspective, animated: String(animated) });
  return `${apiBase()}/api/assets/pokemon/${encodeURIComponent(species)}?${query}`;
}

export function trainerAssetUrl(trainerId: string): string {
  return `${apiBase()}/api/assets/trainers/${encodeURIComponent(trainerId)}`;
}
