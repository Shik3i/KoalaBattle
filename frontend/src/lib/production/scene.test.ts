import assert from 'node:assert/strict';
import test from 'node:test';
import { createProductionScene, damageCallout, directorCard, isKnockedOut, AUTHORITATIVE_IMPACT_PROGRESS } from './scene.ts';
import { defaultProductionStyle } from './style.ts';

const style = () => defaultProductionStyle();

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
  assert.equal(createProductionScene(frame, false, 'http://api', style()).p2.active?.hp_fraction, 1);
  frame.visualProgress = AUTHORITATIVE_IMPACT_PROGRESS;
  const impacted = createProductionScene(frame, false, 'http://api', style());
  assert.equal(impacted.p2.active?.hp_fraction, .6);
  assert.equal(impacted.p2.previousHpFraction, 1);
});

test('scene sprite URLs force deterministic static local assets', () => {
  const frame = {
    timeMs: 0, presentation: presentation(1), priorPresentation: null, commentary: null, caption: null, director: null,
    visual: null, event: null, visualElapsedMs: 0, visualProgress: 0
  } as any;
  const scene = createProductionScene(frame, false, 'http://api', style());
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
  assert.equal(createProductionScene(frame, false, 'http://api', style()).effect.archetype, 'beam');
  frame.visual.kind = 'side_condition_started';
  frame.event.payload.condition = 'move: Stealth Rock';
  assert.equal(createProductionScene(frame, false, 'http://api', style()).effect.archetype, 'hazard');
});

test('scene does not replay the previous move during agent commentary', () => {
  const frame = {
    timeMs: 200, presentation: presentation(1), priorPresentation: null,
    commentary: { side: 'p1', payload: { text: 'I will pivot.' } }, caption: null, director: null,
    visual: { id: 'decision', kind: 'agent_decision', start_ms: 0, duration_ms: 500 },
    event: { sequence: 2, payload: { side: 'p1' } }, visualElapsedMs: 200, visualProgress: .4
  } as any;
  const scene = createProductionScene(frame, false, 'http://api', style());
  assert.equal(scene.effect.progress, 0);
  assert.equal(scene.effect.moveName, null);
  assert.equal(scene.commentary, 'I will pivot.');
});

test('only an authoritative move cue can draw an attack', () => {
  const base = {
    timeMs: 300,
    presentation: presentation(1),
    priorPresentation: presentation(1),
    commentary: null,
    caption: null,
    director: null,
    visualElapsedMs: 300,
    visualProgress: .5
  } as any;
  const switched = createProductionScene({
    ...base,
    visual: { id: 'switch', kind: 'pokemon_switched', start_ms: 0, duration_ms: 600 },
    event: { sequence: 2, payload: { side: 'p1a: Tauros' } }
  }, false, 'http://api', style());
  assert.equal(switched.effect.attack, false);

  const damaged = createProductionScene({
    ...base,
    visual: { id: 'damage', kind: 'damage', start_ms: 0, duration_ms: 500 },
    event: { sequence: 3, payload: { actor: 'p1a: Tauros', target: 'p2a: Alakazam' } }
  }, false, 'http://api', style());
  assert.equal(damaged.effect.attack, false);

  const move = createProductionScene({
    ...base,
    visual: { id: 'move', kind: 'move_used', start_ms: 0, duration_ms: 520 },
    event: { sequence: 4, payload: { actor: 'p1a: Tauros', target: 'p2a: Alakazam' } }
  }, false, 'http://api', style());
  assert.equal(move.effect.attack, true);
});

test('special and status moves receive distinct effect categories', () => {
  const special = createProductionScene({
    timeMs: 200,
    presentation: presentation(1),
    priorPresentation: null,
    commentary: null,
    caption: null,
    director: null,
    visual: { id: 'move', kind: 'move_used', start_ms: 0, duration_ms: 500 },
    event: { sequence: 1, payload: { actor: 'p1a: Tauros', target: 'p2a: Alakazam' } },
    visualElapsedMs: 200,
    visualProgress: .4
  } as any, false, 'http://api', style());
  assert.equal(special.effect.category, 'special');
  assert.equal(special.effect.archetype, 'beam');

  const statusPresentation = {
    ...presentation(1),
    currentMoveProfile: { type: 'electric', archetype: 'status', seed: 9 }
  };
  const status = createProductionScene({
    timeMs: 200,
    presentation: statusPresentation,
    priorPresentation: null,
    commentary: null,
    caption: null,
    director: null,
    visual: { id: 'move', kind: 'move_used', start_ms: 0, duration_ms: 500 },
    event: { sequence: 1, payload: { actor: 'p1a: Tauros', target: 'p2a: Alakazam' } },
    visualElapsedMs: 200,
    visualProgress: .4
  } as any, false, 'http://api', style());
  assert.equal(status.effect.category, 'status');
  assert.equal(status.effect.archetype, 'status');
});

test('move ids stay available for move-specific production animation recipes', () => {
  const earthquake = createProductionScene({
    timeMs: 200,
    presentation: {
      ...presentation(1),
      currentMove: 'Earthquake',
      currentMoveProfile: { type: 'ground', archetype: 'physical', seed: 11 }
    },
    priorPresentation: null,
    commentary: null,
    caption: null,
    director: null,
    visual: { id: 'move', kind: 'move_used', start_ms: 0, duration_ms: 500 },
    event: { sequence: 1, payload: { actor: 'p1a: Tauros', target: 'p2a: Alakazam' } },
    visualElapsedMs: 200,
    visualProgress: .4
  } as any, false, 'http://api', style());
  assert.equal(earthquake.effect.moveId, 'earthquake');
  assert.equal(earthquake.effect.attack, true);
});

const sceneAt = (overrides: Record<string, unknown>) => {
  const frame = {
    timeMs: 0, presentation: presentation(1), priorPresentation: null,
    commentary: null, caption: null, director: null, visual: null, event: null,
    visualElapsedMs: 0, visualProgress: 0,
    ...overrides
  } as any;
  return createProductionScene(frame, false, 'http://api', (overrides.style as any) || style());
};

test('the result card renders while the result cue is on screen', () => {
  const director = { id: 'director-result', track: 'director', kind: 'result', start_ms: 10_000, duration_ms: 1800, payload: {} };
  const finished = { ...presentation(0), winnerName: 'Alpha', finished: true };
  const card = directorCard(sceneAt({ timeMs: 10_900, director, presentation: finished }));
  assert.ok(card, 'a result cue in range must produce a card');
  assert.equal(card?.kind, 'result');
  assert.equal(card?.headline, 'Alpha WINS');
  assert.equal(card?.opacity, 1);
  // Once the cue has elapsed the overlay must disappear rather than linger at full opacity.
  assert.equal(directorCard(sceneAt({ timeMs: 12_500, director, presentation: finished })), null);
});

test('intro and result cards obey their style switches', () => {
  const intro = { id: 'director-intro', track: 'director', kind: 'match-intro', start_ms: 0, duration_ms: 3000, payload: {} };
  const shown = directorCard(sceneAt({ timeMs: 1500, director: intro }));
  assert.equal(shown?.kind, 'intro');
  assert.equal(shown?.headline, 'Alpha  VS  Beta');
  assert.match(shown?.subtitle || '', /Gen 9/);

  const off = style();
  off.intro.enabled = false;
  assert.equal(directorCard(sceneAt({ timeMs: 1500, director: intro, style: off })), null);

  const anonymous = style();
  anonymous.intro.show_player_names = false;
  anonymous.intro.show_format = false;
  const bare = directorCard(sceneAt({ timeMs: 1500, director: intro, style: anonymous }));
  assert.equal(bare?.headline, 'VS');
  assert.equal(bare?.subtitle, null);
});

test('series metadata only appears when the style asks for it', () => {
  const intro = { id: 'director-intro', track: 'director', kind: 'match-intro', start_ms: 0, duration_ms: 3000, payload: {} };
  const series = style();
  series.intro.show_game_number = true;
  series.intro.show_series_score = true;
  series.series = { ...series.series, game_number: 2, best_of: 3, score_p1: 1, score_p2: 0 };
  const card = directorCard(sceneAt({ timeMs: 1500, director: intro, style: series }));
  assert.match(card?.subtitle || '', /GAME 2/);
  assert.match(card?.subtitle || '', /BEST OF 3/);
  assert.match(card?.subtitle || '', /SERIES 1–0/);
});

test('damage callouts report the recorded HP change and respect toggles', () => {
  const visual = { id: 'damage', kind: 'damage', start_ms: 0, duration_ms: 1000, turn: 1 };
  const event = { sequence: 4, payload: { actor: 'p1a: Pikachu', target: 'p2a: Pikachu' } };
  const impact = { timeMs: 900, visual, event, visualElapsedMs: 900, visualProgress: .9, presentation: presentation(.6), priorPresentation: presentation(1) };
  const callout = damageCallout(sceneAt(impact));
  assert.equal(callout?.tone, 'damage');
  assert.equal(callout?.text, '40%');

  const quiet = style();
  quiet.damage.show_damage = false;
  assert.equal(damageCallout(sceneAt({ ...impact, style: quiet })), null);

  const missed = { ...impact, visual: { ...visual, kind: 'move_missed' } };
  assert.equal(damageCallout(sceneAt(missed))?.text, 'MISS');
  const noMiss = style();
  noMiss.damage.show_miss = false;
  assert.equal(damageCallout(sceneAt({ ...missed, style: noMiss })), null);
});

test('style customization never reaches the recorded battle', () => {
  const branded = style();
  branded.players.p1 = {
    display_name: 'CHATGPT', short_name: 'GPT', logo_asset_id: null,
    logo_mark: 'gpt', accent: '#5fe6b0', secondary_accent: null
  };
  const scene = sceneAt({ style: branded });
  // The presentation still knows the real player; only the on-screen identity changed.
  assert.equal(scene.p1.displayName, 'CHATGPT');
  assert.equal(scene.p1.markLabel, 'GPT');
  assert.equal(scene.p1.active?.species, 'Pikachu');
  assert.equal(scene.turn, 3);
  assert.equal(presentation(1).players.p1.displayName, 'Alpha');
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
