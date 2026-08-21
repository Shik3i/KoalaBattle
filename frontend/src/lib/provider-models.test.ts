import assert from 'node:assert/strict';
import test from 'node:test';
import { DEEPSEEK_V4_MODELS, deepSeekModelLabel, knownProviderModels } from './provider-models.ts';

test('DeepSeek exposes both current V4 models with Flash first', () => {
  assert.deepEqual(DEEPSEEK_V4_MODELS, ['deepseek-v4-flash', 'deepseek-v4-pro']);
  assert.deepEqual(knownProviderModels('deepseek', []), [...DEEPSEEK_V4_MODELS]);
  assert.match(deepSeekModelLabel('deepseek-v4-flash'), /faster \/ lower cost/);
  assert.match(deepSeekModelLabel('deepseek-v4-pro'), /maximum capability/);
});

test('the backend catalog remains authoritative when it advertises models', () => {
  const statuses = [{ id: 'deepseek', known_models: ['future-model'] }] as never;
  assert.deepEqual(knownProviderModels('deepseek', statuses), ['future-model']);
});
