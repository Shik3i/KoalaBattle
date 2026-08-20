import assert from 'node:assert/strict';
import test from 'node:test';

import { moveEffectAssetUrl, normalizeMoveId, resolveMoveEffect } from './move-effects.ts';

test('iconic moves resolve to stable distinct recipes', () => {
  assert.equal(resolveMoveEffect('Earthquake', 'ground', 'physical').family, 'quake');
  assert.equal(resolveMoveEffect('Thunderbolt', 'electric', 'special').family, 'lightning');
  assert.equal(resolveMoveEffect('Ice Beam', 'ice', 'special').family, 'ice');
  assert.equal(resolveMoveEffect('Protect', 'normal', 'status').family, 'barrier');
  assert.equal(resolveMoveEffect('Shadow Ball', 'ghost', 'special').assetId, 'shadowball');
});

test('unknown moves always receive a metadata-based procedural fallback', () => {
  assert.equal(resolveMoveEffect('A Brand New Move', 'fire', 'special', 'procedural').family, 'fire');
  assert.equal(resolveMoveEffect('A Brand New Move', 'fire', 'special', 'procedural').assetId, null);
  assert.equal(resolveMoveEffect('A Brand New Punch', 'fighting', 'physical').family, 'contact');
});

test('move and asset ids are normalized and URL encoded', () => {
  assert.equal(normalizeMoveId('King’s Shield!'), 'kingsshield');
  assert.equal(moveEffectAssetUrl('shadowball', 'http://localhost:3001/'), 'http://localhost:3001/api/assets/effects/shadowball');
});
