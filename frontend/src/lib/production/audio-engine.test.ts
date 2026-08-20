import assert from 'node:assert/strict';
import test from 'node:test';
import { sfxVariantFor } from './sfx.ts';
import { stingRecipeFor } from './stings.ts';

test('SFX variant selection is deterministic for the same cue', () => {
  assert.equal(
    sfxVariantFor('impact', 'event-42-sfx'),
      sfxVariantFor('impact', 'event-42-sfx')
  );
});

test('broadcast stings are original deterministic note recipes', () => {
  const finale = stingRecipeFor('final-pokemon-sting');
  const result = stingRecipeFor('result-sting');
  assert.equal(finale?.length, 4);
  assert.equal(result?.length, 6);
  assert.equal(stingRecipeFor('impact'), null);
  assert.ok((result?.at(-1)?.offset || 0) + (result?.at(-1)?.duration || 0) >= 1);
});

test('SFX variant selection keeps variants inside the semantic registry', () => {
  assert.match(sfxVariantFor('critical', 'event-42-sfx') || '', /^critical-0[12]$/);
  assert.equal(sfxVariantFor('unknown', 'event-42-sfx'), null);
});
