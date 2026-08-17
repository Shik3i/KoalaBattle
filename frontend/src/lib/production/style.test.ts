import assert from 'node:assert/strict';
import test from 'node:test';
import {
  accentFor,
  assetUrl,
  brandingFor,
  defaultProductionStyle,
  fontFamily,
  formatDisplayName,
  generationOf,
  idleScale,
  intensityScale,
  styleToRendererConfig
} from './style.ts';
import { previewMarks } from './preview-marks.ts';

test('formats are shown by name, never as a Showdown id', () => {
  assert.equal(formatDisplayName('gen1ou'), 'Gen 1 · OU');
  assert.equal(formatDisplayName('gen9randombattle'), 'Gen 9 · Random Battle');
  assert.equal(formatDisplayName('gen3ou', false), 'OU');
  // Unknown ids still get a readable label rather than leaking the raw identifier shape.
  assert.equal(formatDisplayName('gen5doublesou'), 'Gen 5 · Doubles OU');
  assert.ok(!formatDisplayName('gen9randombattle').includes('gen9randombattle'));
});

test('generation detection drives the retro suggestion', () => {
  assert.equal(generationOf('gen1randombattle'), 1);
  assert.equal(generationOf('gen9ou'), 9);
  assert.equal(generationOf('customformat'), 9);
});

test('missing player branding falls back without throwing', () => {
  const style = defaultProductionStyle();
  assert.equal(brandingFor(style, 'p1').display_name, null);
  assert.equal(accentFor(style, 'p1'), '#6fffa8');
  assert.equal(accentFor(style, 'p2'), '#e36fff');
  style.players.p1 = {
    display_name: 'Gemini', short_name: null, logo_asset_id: null,
    logo_mark: 'gemini', accent: '#6fa8ff', secondary_accent: null
  };
  assert.equal(accentFor(style, 'p1'), '#6fa8ff');
});

test('font selection never depends on a remote stylesheet', () => {
  const style = defaultProductionStyle();
  for (const role of ['display', 'body', 'mono'] as const) {
    const stack = fontFamily(style, role);
    assert.ok(!/https?:|url\(/.test(stack), `${role} stack must be local: ${stack}`);
  }
  style.typography.display_asset_id = 'a'.repeat(32);
  assert.match(fontFamily(style, 'display'), /^"kb-font-a{32}", /);
});

test('brand asset URLs are derived from ids, never from a filename', () => {
  assert.equal(assetUrl('http://api', null), null);
  assert.equal(assetUrl('http://api', 'b'.repeat(32)), `http://api/api/branding/assets/${'b'.repeat(32)}/media`);
});

test('intensity and idle scales bottom out at zero when switched off', () => {
  assert.equal(intensityScale('off'), 0);
  assert.equal(idleScale('off'), 0);
  assert.ok(intensityScale('dramatic') > intensityScale('standard'));
  assert.ok(idleScale('subtle') < idleScale('full'));
});

test('one style drives the live DOM surface too, without a parallel theme system', () => {
  const style = defaultProductionStyle();
  const base = {
    version: 1, layout: 'overlay-landscape', theme: 'koala-dark', preset: 'video',
    playbackSpeed: 1, commentaryMode: 'latest', showBattleLog: false, showTurn: true,
    showAgentState: true, transparentBackground: true, animatedSprites: true,
    effects: 'standard', reducedMotion: false, showDamageNumbers: true, nearSide: 'p1'
  } as never;

  style.effect.intensity = 'dramatic';
  assert.equal(styleToRendererConfig(style, base).effects, 'high');
  style.effect.intensity = 'off';
  assert.equal(styleToRendererConfig(style, base).effects, 'off');
  style.effect.camera = 'static';
  assert.equal(styleToRendererConfig(style, base).reducedMotion, true);
  style.commentary.layout = 'off';
  assert.equal(styleToRendererConfig(style, base).commentaryMode, 'hidden');
  style.damage.show_damage = false;
  assert.equal(styleToRendererConfig(style, base).showDamageNumbers, false);
  // Anything the DOM renderer cannot express is carried through untouched.
  assert.equal(styleToRendererConfig(style, base).layout, 'overlay-landscape');
  assert.equal(styleToRendererConfig(style, base).theme, 'koala-dark');
});

test('preview shortcuts only appear for cues the production really has', () => {
  const production = {
    duration_ms: 10_000,
    cues: [
      { id: 'a', track: 'director', kind: 'match-intro', start_ms: 0, duration_ms: 2000, turn: null },
      { id: 'b', track: 'visual', kind: 'move_used', start_ms: 2000, duration_ms: 800, turn: 1 },
      { id: 'c', track: 'commentary', kind: 'agent-intent', start_ms: 2100, duration_ms: 1200, turn: 1 }
    ]
  } as never;
  const marks = previewMarks(production);
  const ids = marks.map((mark) => mark.id);
  assert.deepEqual(ids.sort(), ['attack', 'commentary', 'intro', 'neutral']);
  // No damage, switch or victory cue exists, so no shortcut fabricates one.
  assert.ok(!ids.includes('damage'));
  assert.ok(!ids.includes('victory'));
  assert.ok(marks.every((mark) => mark.timeMs >= 0 && mark.timeMs <= 10_000));
});
