import assert from 'node:assert/strict';
import test from 'node:test';

import { configFromQuery, sanitizeRendererConfig } from './config.ts';

test('renderer configuration rejects unknown declarative values', () => {
  const config = sanitizeRendererConfig({
    layout: 'javascript:alert(1)',
    theme: 'arbitrary-code',
    playbackSpeed: 9000,
    effects: 'unbounded',
    moveEffectSkin: 'licensed-rom',
    transparentBackground: 'yes'
  });
  assert.equal(config.layout, 'standard-landscape');
  assert.equal(config.theme, 'pokemon-route');
  assert.equal(config.playbackSpeed, 1);
  assert.equal(config.transparentBackground, false);
  assert.equal(config.effects, 'standard');
  assert.equal(config.moveEffectSkin, 'broadcast');
  assert.equal(config.version, '2.0');
});

test('overlay query accepts only supported renderer choices', () => {
  const config = configFromQuery(
    new URLSearchParams(
      'layout=standard-vertical&theme=koala-light&transparent=1&log=0&near=p2&effects=high&moveEffects=retro&reducedMotion=1&damageNumbers=0'
    )
  );
  assert.equal(config.layout, 'standard-vertical');
  assert.equal(config.theme, 'koala-light');
  assert.equal(config.transparentBackground, true);
  assert.equal(config.showBattleLog, false);
  assert.equal(config.nearSide, 'p2');
  assert.equal(config.effects, 'high');
  assert.equal(config.moveEffectSkin, 'retro');
  assert.equal(config.reducedMotion, true);
  assert.equal(config.showDamageNumbers, false);
});

test('the roster and HUD scale survive the overlay query', () => {
  const config = configFromQuery(new URLSearchParams('roster=0&hudScale=1.25'));
  assert.equal(config.showTeamRoster, false);
  assert.equal(config.hudScale, 1.25);
});

test('HUD scale is clamped to a range the renderer can actually lay out', () => {
  assert.equal(sanitizeRendererConfig({ hudScale: 12 }).hudScale, 1.6);
  assert.equal(sanitizeRendererConfig({ hudScale: 0.1 }).hudScale, 0.8);
  assert.equal(sanitizeRendererConfig({ hudScale: 'huge' }).hudScale, 1);
  assert.equal(sanitizeRendererConfig({ hudScale: Number.NaN }).hudScale, 1);
  assert.equal(sanitizeRendererConfig({}).showTeamRoster, true);
});
