import type { ProviderKind, ProviderStatus } from '$lib/types';

export const DEEPSEEK_V4_MODELS = ['deepseek-v4-flash', 'deepseek-v4-pro'] as const;

export function knownProviderModels(
  provider: ProviderKind,
  statuses: ProviderStatus[]
): string[] {
  const advertised = statuses.find((status) => status.id === provider)?.known_models || [];
  if (advertised.length) return advertised;
  return provider === 'deepseek' ? [...DEEPSEEK_V4_MODELS] : [];
}

export function deepSeekModelLabel(model: string): string {
  if (model === 'deepseek-v4-flash') return 'DeepSeek V4 Flash · faster / lower cost';
  if (model === 'deepseek-v4-pro') return 'DeepSeek V4 Pro · maximum capability';
  return model;
}
