import assert from 'node:assert/strict';
import test from 'node:test';
import { createProductionScene, isKnockedOut, AUTHORITATIVE_IMPACT_PROGRESS } from './scene.ts';

const pokemon = (hp: number) => ({ id: 'pikachu', name: 'Pikachu', species: 'Pikachu', hp_fraction: hp, status: null, types: ['electric'], active: true, fainted: false });
const battle = (hp: number) => ({ turn: 3, player: { side: 'p1', active: pokemon(1), team: [pokemon(1)] }, opponent: { side: 'p2', active: pokemon(hp), team: [pokemon(hp)] }, weather: [], fields: [] });
const presentation = (hp: number) => ({ format: 'gen9ou', battle: battle(hp), players: { p1: { displayName: 'Alpha', providerLabel: 'A' }, p2: { displayName: 'Beta', providerLabel: 'B' } }, currentMove: 'Thunderbolt', currentMoveProfile: { type: 'electric', archetype: 'special', seed: 7 }, effect: 'impact', effectSide: 'p2', effectValue: -40, winnerName: null, finished: false });

test('scene delays authoritative target HP until projectile impact', () => {
  const frame = {
    timeMs: 1200,
    presentation: presentation(.6),
    priorPresentation: presentation(1),
    commentary: null, caption: null,
    director: null,
    visual: { id: 'damage', kind: 'damage', start_ms: 1000, duration_ms: 500, turn: 3 },
    event: { sequence: 4, payload: { actor: 'p1a: Pikachu', target: 'p2a: Pikachu' } },
    visualElapsedMs: 200,
    visualProgress: AUTHORITATIVE_IMPACT_PROGRESS - .01
  } as any;
  assert.equal(createProductionScene(frame, false, 'http://api').p2.active?.hp_fraction, 1);
  frame.visualProgress = AUTHORITATIVE_IMPACT_PROGRESS;
  const impacted = createProductionScene(frame, false, 'http://api');
  assert.equal(impacted.p2.active?.hp_fraction, .6);
  assert.equal(impacted.p2.previousHpFraction, 1);
});

test('scene sprite URLs force deterministic static local assets', () => {
  const frame = {
    timeMs: 0, presentation: presentation(1), priorPresentation: null, commentary: null, caption: null, director: null,
    visual: null, event: null, visualElapsedMs: 0, visualProgress: 0
  } as any;
  const scene = createProductionScene(frame, false, 'http://api');
  assert.match(scene.p1.spriteUrl || '', /animated=false/);
  assert.match(scene.p2.spriteUrl || '', /perspective=front/);
});

test('scene classifies authoritative move and field events without an LLM', () => {
  const frame = {
    timeMs: 200, presentation: presentation(1), priorPresentation: null, commentary: null, caption: null, director: null,
    visual: { id: 'move', kind: 'move_used', start_ms: 0, duration_ms: 500 },
    event: { sequence: 1, payload: { actor: 'p1a: Pikachu', target: 'p2a: Eevee' } },
    visualElapsedMs: 200, visualProgress: .4
  } as any;
  assert.equal(createProductionScene(frame, false, 'http://api').effect.archetype, 'beam');
  frame.visual.kind = 'side_condition_started';
  frame.event.payload.condition = 'move: Stealth Rock';
  assert.equal(createProductionScene(frame, false, 'http://api').effect.archetype, 'hazard');
});

test('scene does not replay the previous move during agent commentary', () => {
  const frame = {
    timeMs: 200, presentation: presentation(1), priorPresentation: null,
    commentary: { side: 'p1', payload: { text: 'I will pivot.' } }, caption: null, director: null,
    visual: { id: 'decision', kind: 'agent_decision', start_ms: 0, duration_ms: 500 },
    event: { sequence: 2, payload: { side: 'p1' } }, visualElapsedMs: 200, visualProgress: .4
  } as any;
  const scene = createProductionScene(frame, false, 'http://api');
  assert.equal(scene.effect.progress, 0);
  assert.equal(scene.effect.moveName, null);
  assert.equal(scene.commentary, 'I will pivot.');
});

test('a knocked out Pokemon stays down until it is replaced', () => {
  const standing = { active: { hp_fraction: 0.4, fainted: false } } as never;
  const fainted = { active: { hp_fraction: 0, fainted: true } } as never;
  // Showdown reports 0 HP before the faint line on some turns, so either signal counts.
  const zeroed = { active: { hp_fraction: 0, fainted: false } } as never;
  const empty = { active: null } as never;
  assert.equal(isKnockedOut(standing), false);
  assert.equal(isKnockedOut(fainted), true);
  assert.equal(isKnockedOut(zeroed), true);
  assert.equal(isKnockedOut(empty), false);
});
