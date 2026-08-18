export interface LocalEndpointPreset {
  id: string;
  label: string;
  baseUrl: string;
  model: string;
  hint: string;
  timeoutSeconds: number;
  maxRetries: number;
}

/** Provider calls originate in the backend container, so local Mac services use this hostname. */
export const LOCAL_ENDPOINT_PRESETS: readonly LocalEndpointPreset[] = [
  {
    id: 'lm-studio-gemma-4',
    label: 'LM Studio · Gemma 4 E4B',
    baseUrl: 'http://host.docker.internal:1234/v1',
    model: 'google/gemma-4-e4b',
    hint: 'Local Mac server · 300s timeout · one retry',
    timeoutSeconds: 300,
    maxRetries: 1
  },
  {
    id: 'lm-studio',
    label: 'LM Studio · another loaded model',
    baseUrl: 'http://host.docker.internal:1234/v1',
    model: 'local-model',
    hint: 'Use Discover models · 300s timeout · one retry',
    timeoutSeconds: 300,
    maxRetries: 1
  },
  {
    id: 'ollama',
    label: 'Ollama · local',
    baseUrl: 'http://host.docker.internal:11434/v1',
    model: 'llama3.2',
    hint: 'Common Ollama endpoint · 300s timeout · one retry',
    timeoutSeconds: 300,
    maxRetries: 1
  },
  {
    id: 'llama-cpp',
    label: 'llama.cpp server · local',
    baseUrl: 'http://host.docker.internal:8080/v1',
    model: 'local-model',
    hint: 'Common llama.cpp endpoint · 300s timeout · one retry',
    timeoutSeconds: 300,
    maxRetries: 1
  }
];

export const CUSTOM_ENDPOINT_PRESET_ID = 'custom';

export function localEndpointPreset(id: string): LocalEndpointPreset | undefined {
  return LOCAL_ENDPOINT_PRESETS.find((preset) => preset.id === id);
}
