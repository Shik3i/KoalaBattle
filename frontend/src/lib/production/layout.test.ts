import assert from 'node:assert/strict';
import test from 'node:test';
import { commentaryMotion, hpReadout, hudLayout, mix, withAlpha } from './layout.ts';
import { defaultProductionStyle } from './style.ts';

const side = (values: Record<string, unknown>) => ({ active: values }) as never;

test('HUD presets produce genuinely different compositions', () => {
  const boxes = ['broadcast', 'fighting', 'minimal', 'esports', 'retro'].map((preset) =>
    JSON.stringify(hudLayout(preset, false, 1920, 1080, 1))
  );
  assert.equal(new Set(boxes).size, boxes.length, 'each preset must lay the HUD out differently');
});

test('minimal HUD keeps the near player low and the far player high', () => {
  const layout = hudLayout('minimal', false, 1920, 1080, 1);
  assert.ok(layout.p1.y > layout.p2.y);
});

test('vertical framing stacks both panels regardless of preset', () => {
  for (const preset of ['broadcast', 'fighting', 'retro']) {
    const layout = hudLayout(preset, true, 1080, 1920, 1);
    assert.ok(layout.p2.y < layout.p1.y);
    assert.equal(layout.p1.x, layout.p2.x);
  }
});

test('HP readout honours the style toggles without inventing a value', () => {
  const known = side({ hp_fraction: 0.5, current_hp: 100, max_hp: 200 });
  const percentOnly = side({ hp_fraction: 0.5 });
  assert.equal(hpReadout(known, { show_hp_exact: true, show_hp_percent: true }), '100/200');
  assert.equal(hpReadout(known, { show_hp_exact: false, show_hp_percent: true }), '50%');
  assert.equal(hpReadout(known, { show_hp_exact: false, show_hp_percent: false }), '');
  // Exact HP is unknown for the opponent, so the exact toggle must fall back, not lie.
  assert.equal(hpReadout(percentOnly, { show_hp_exact: true, show_hp_percent: true }), '50%');
});

test('commentary entrance is deterministic and settles', () => {
  const style = defaultProductionStyle();
  style.commentary.animation = 'slide';
  const scene = (elapsed: number) =>
    ({ style, commentary: 'text', commentarySide: 'p2', commentaryElapsedMs: elapsed }) as never;
  const early = commentaryMotion(scene(0), 1);
  assert.ok(early.dx > 0, 'p2 commentary slides in from the right');
  assert.deepEqual(commentaryMotion(scene(120), 1), commentaryMotion(scene(120), 1));
  assert.deepEqual(commentaryMotion(scene(9000), 1), { alpha: 1, dx: 0, dy: 0 });
  style.commentary.animation = 'none';
  assert.deepEqual(commentaryMotion(scene(0), 1), { alpha: 1, dx: 0, dy: 0 });
});

test('colour helpers accept both hex forms and never emit raw CSS', () => {
  assert.equal(withAlpha('#fff', 0.5), 'rgba(255,255,255,0.5)');
  assert.equal(withAlpha('#7dffae', 1), 'rgba(125,255,174,1)');
  assert.equal(mix('#000000', '#ffffff', 0.5), 'rgb(128,128,128)');
});
