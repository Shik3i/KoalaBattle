import { configureProvider } from '$lib/api';
import type { ProviderKind } from '$lib/types';

export interface StoredProviderSetting {
  apiKey: string;
  baseUrl: string;
}

const STORAGE_KEY = 'koalabattle-provider-settings-v1';

function isProviderKind(value: string): value is ProviderKind {
  return ['openai', 'gemini', 'anthropic', 'deepseek', 'openai-compatible', 'fake'].includes(value);
}

export function loadProviderSettings(): Partial<Record<ProviderKind, StoredProviderSetting>> {
  if (typeof localStorage === 'undefined') return {};
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(parsed).flatMap(([provider, value]) => {
        if (!isProviderKind(provider) || !value || typeof value !== 'object') return [];
        const item = value as Record<string, unknown>;
        return [[provider, {
          apiKey: typeof item.apiKey === 'string' ? item.apiKey : '',
          baseUrl: typeof item.baseUrl === 'string' ? item.baseUrl : ''
        }]];
      })
    ) as Partial<Record<ProviderKind, StoredProviderSetting>>;
  } catch {
    return {};
  }
}

export function saveProviderSetting(provider: ProviderKind, setting: StoredProviderSetting): void {
  if (typeof localStorage === 'undefined') return;
  const settings = loadProviderSettings();
  if (!setting.apiKey && !setting.baseUrl) delete settings[provider];
  else settings[provider] = setting;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export async function hydrateStoredProviderSettings(): Promise<void> {
  const settings = loadProviderSettings();
  await Promise.allSettled(
    Object.entries(settings).map(([provider, setting]) =>
      configureProvider(provider as ProviderKind, setting.apiKey, setting.baseUrl || null)
    )
  );
}
