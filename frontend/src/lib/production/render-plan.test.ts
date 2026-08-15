import assert from 'node:assert/strict';
import test from 'node:test';
import { createRenderPlan } from './render-plan.ts';

const production = {
  duration_ms: 3000,
  cues: [
    { id: 'visual', track: 'visual', kind: 'damage', start_ms: 1000, duration_ms: 400, payload: {} },
    { id: 'caption', track: 'captions', kind: 'agent-commentary', start_ms: 1600, duration_ms: 600, payload: {} }
  ]
} as any;

test('render plan keeps exact CFR output while holding static raster frames', () => {
  const plan = createRenderPlan(production, 0, 3000, 60);
  assert.equal(plan.outputFrames, 180);
  assert.ok(plan.plannedUniqueRenders < plan.outputFrames);
  assert.ok(plan.plannedStaticHeldFrames > 100);
  assert.equal(plan.plannedUniqueRenders + plan.plannedStaticHeldFrames, plan.outputFrames);
  assert.equal(plan.frames[0].reason, 'initial');
});

test('render plan marks each active deterministic animation frame', () => {
  const plan = createRenderPlan(production, 0, 3000, 60);
  const damage = plan.frames.filter((frame) => frame.logicalTimeMs >= 1000 && frame.logicalTimeMs < 1400);
  assert.ok(damage.every((frame) => frame.render && frame.animated));
});

test('render plan rejects invalid output clocks', () => {
  assert.throws(() => createRenderPlan(production, 1000, 1000, 60), /non-empty/);
  assert.throws(() => createRenderPlan(production, 0, 1000, 120), /between 1 and 60/);
});
