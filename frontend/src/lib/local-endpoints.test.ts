import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CUSTOM_ENDPOINT_PRESET_ID,
  LOCAL_ENDPOINT_PRESETS,
  localEndpointPreset
} from './local-endpoints.ts';

test('local endpoint presets include the Docker-reachable LM Studio Gemma model', () => {
  assert.deepEqual(localEndpointPreset('lm-studio-gemma-4'), {
    id: 'lm-studio-gemma-4',
    label: 'LM Studio · Gemma 4 E4B',
    baseUrl: 'http://host.docker.internal:1234/v1',
    model: 'google/gemma-4-e4b',
    hint: 'Local Mac server · 300s timeout · one retry',
    timeoutSeconds: 300,
    maxRetries: 1
  });
});

test('every local endpoint preset has a selectable URL and model', () => {
  assert.ok(LOCAL_ENDPOINT_PRESETS.length >= 3);
  for (const preset of LOCAL_ENDPOINT_PRESETS) {
    assert.match(preset.baseUrl, /^http:\/\/host\.docker\.internal:\d+\/v1$/);
    assert.ok(preset.model.length > 0);
    assert.equal(preset.timeoutSeconds, 300);
    assert.equal(preset.maxRetries, 1);
  }
  assert.equal(CUSTOM_ENDPOINT_PRESET_ID, 'custom');
});
