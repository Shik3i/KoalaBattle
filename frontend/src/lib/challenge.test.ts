import assert from 'node:assert/strict';
import test from 'node:test';

import {
  campaignBattleLabel,
  challengeErrorMessage,
  challengeStatusLabel,
  draftChoiceIndexForKey,
  draftRollFrames,
  draftRollTransitionMode,
  DRAFT_ROLL_DURATION_MS,
  emptyEvSpread,
  evAllocationTotal,
  evSpreadTotal,
  formatDuration,
  generationRomanNumeral,
  legalEvValue,
  pokemonTypeColor,
  recommendedEvPresets
} from './challenge.ts';

test('empty EV spreads are independent zeroed records', () => {
  const first = emptyEvSpread();
  const second = emptyEvSpread();
  first.hp = 252;

  assert.equal(second.hp, 0);
  assert.equal(evSpreadTotal(second), 0);
});

test('EV recommendations follow each Pokemon pinned base stats', () => {
  const alakazam = recommendedEvPresets({
    base_stats: { hp: 55, atk: 50, defense: 45, spa: 135, spd: 95, spe: 120 }
  });
  const blastoise = recommendedEvPresets({
    base_stats: { hp: 79, atk: 83, defense: 100, spa: 85, spd: 105, spe: 78 }
  });
  const farfetchd = recommendedEvPresets({
    base_stats: { hp: 52, atk: 90, defense: 55, spa: 58, spd: 62, spe: 60 }
  });

  assert.equal(alakazam[0].id, 'fast-special');
  assert.equal(alakazam[0].recommended, true);
  assert.equal(blastoise[0].id, 'special-wall');
  assert.equal(new Set(blastoise.map((entry) => entry.id)).size, blastoise.length);
  assert.deepEqual(farfetchd.map((entry) => entry.id), ['bulky-physical', 'special-wall', 'fast-physical']);
});

test('type presentation uses stable canonical colors and a safe fallback', () => {
  assert.equal(pokemonTypeColor('Water'), '#6890F0');
  assert.equal(pokemonTypeColor('Unknown'), '#7f8c9a');
});

test('spread totals include all six stats', () => {
  assert.equal(
    evSpreadTotal({ hp: 4, atk: 252, def: 0, spa: 0, spd: 0, spe: 252 }),
    508
  );
});

test('allocation totals report training across independently capped Pokemon', () => {
  assert.equal(
    evAllocationTotal({
      pikachu: { hp: 0, atk: 252, def: 0, spa: 0, spd: 4, spe: 252 },
      blastoise: { hp: 252, atk: 0, def: 0, spa: 252, spd: 4, spe: 0 }
    }),
    1016
  );
});

test('EV editing caps only the selected Pokemon and stat', () => {
  const allocations = {
    pikachu: { hp: 252, atk: 0, def: 0, spa: 0, spd: 0, spe: 252 },
    blastoise: { hp: 252, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 }
  };
  const limits = { pokemon: 510, stat: 252 };

  assert.equal(legalEvValue(allocations, 'pikachu', 'spd', 252, limits), 6);
  assert.equal(legalEvValue(allocations, 'blastoise', 'def', 999, limits), 252);
  assert.equal(legalEvValue(allocations, 'blastoise', 'hp', -20, limits), 0);
});

test('Challenge errors turn stale state, pool exhaustion, abilities, and AI failures into recovery guidance', () => {
  assert.match(challengeErrorMessage('stale challenge revision: current 7'), /latest saved state/);
  assert.match(challengeErrorMessage('agent draft provider timed out'), /take over manually/);
  assert.match(challengeErrorMessage('Showdown rejected the team: bad move'), /Fix the listed/);
  assert.match(challengeErrorMessage('no generation+type bucket can complete the roster'), /remaining unseen species/);
  assert.match(challengeErrorMessage('illegal ability levitate for rotomwash'), /exact Pokémon form/);
});

test('draft shortcuts accept only visible one-based choice keys', () => {
  assert.equal(draftChoiceIndexForKey('1'), 0);
  assert.equal(draftChoiceIndexForKey('8'), 7);
  assert.equal(draftChoiceIndexForKey('0'), null);
  assert.equal(draftChoiceIndexForKey('9'), null);
});

test('draft roll animation distinguishes automatic, type, generation, and Pokemon rerolls', () => {
  assert.equal(draftRollTransitionMode(undefined, true), 'both');
  assert.equal(draftRollTransitionMode('picked'), 'both');
  assert.equal(draftRollTransitionMode('type_rerolled'), 'type');
  assert.equal(draftRollTransitionMode('generation_rerolled'), 'generation');
  assert.equal(draftRollTransitionMode('pokemon_rerolled'), null);
  assert.equal(draftRollTransitionMode(undefined, false), null);
  assert.equal(draftRollTransitionMode('picked', false, true), null);
});

test('draft roll frames settle quickly on authoritative Roman generation and type', () => {
  const both = draftRollFrames(3, 'Water', 'both');
  const typeOnly = draftRollFrames(3, 'Water', 'type');
  const generationOnly = draftRollFrames(3, 'Water', 'generation');

  assert.equal(generationRomanNumeral(3), 'III');
  assert.equal(both.generations.at(-1), 3);
  assert.equal(both.types.at(-1), 'water');
  assert.deepEqual(typeOnly.generations, [3]);
  assert.equal(typeOnly.types.length, 8);
  assert.equal(generationOnly.generations.length, 8);
  assert.deepEqual(generationOnly.types, ['water']);
  assert.ok(DRAFT_ROLL_DURATION_MS >= 400 && DRAFT_ROLL_DURATION_MS <= 800);
});

test('campaign position is one-based and capped at the final battle', () => {
  assert.equal(campaignBattleLabel(3, 13, 'Erika'), 'Battle 4 of 13 · Erika');
  assert.equal(campaignBattleLabel(13, 13, 'Champion Blue'), 'Battle 13 of 13 · Champion Blue');
});

test('status and duration labels are user-facing', () => {
  assert.equal(challengeStatusLabel('team_review'), 'Team review');
  assert.equal(challengeStatusLabel('completed'), 'Draft run complete');
  assert.equal(formatDuration(0), '0s');
  assert.equal(formatDuration(3670), '1h 1m');
});
