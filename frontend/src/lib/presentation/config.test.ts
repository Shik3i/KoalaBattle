import assert from 'node:assert/strict';
import test from 'node:test';

import { configFromQuery, sanitizeRendererConfig } from './config.ts';

test('renderer configuration rejects unknown declarative values', () => {
  const config = sanitizeRendererConfig({
    layout: 'javascript:alert(1)',
    theme: 'arbitrary-code',
    playbackSpeed: 9000,
    effects: 'unbounded',
    transparentBackground: 'yes'
  });
  assert.equal(config.layout, 'standard-landscape');
  assert.equal(config.theme, 'koala-dark');
  assert.equal(config.playbackSpeed, 1);
  assert.equal(config.transparentBackground, false);
  assert.equal(config.effects, 'standard');
  assert.equal(config.version, '2.0');
});

test('overlay query accepts only supported renderer choices', () => {
  const config = configFromQuery(
    new URLSearchParams(
      'layout=standard-vertical&theme=koala-light&transparent=1&log=0&near=p2&effects=high&reducedMotion=1&damageNumbers=0'
    )
  );
  assert.equal(config.layout, 'standard-vertical');
  assert.equal(config.theme, 'koala-light');
  assert.equal(config.transparentBackground, true);
  assert.equal(config.showBattleLog, false);
  assert.equal(config.nearSide, 'p2');
  assert.equal(config.effects, 'high');
  assert.equal(config.reducedMotion, true);
  assert.equal(config.showDamageNumbers, false);
});
