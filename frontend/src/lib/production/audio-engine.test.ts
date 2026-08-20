import assert from 'node:assert/strict';
import test from 'node:test';
import { sfxVariantFor } from './sfx.ts';

test('SFX variant selection is deterministic for the same cue', () => {
  assert.equal(
    sfxVariantFor('impact', 'event-42-sfx'),
      sfxVariantFor('impact', 'event-42-sfx')
  );
});

test('SFX variant selection keeps variants inside the semantic registry', () => {
  assert.match(sfxVariantFor('critical', 'event-42-sfx') || '', /^critical-0[12]$/);
  assert.equal(sfxVariantFor('unknown', 'event-42-sfx'), null);
});
