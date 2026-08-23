import assert from 'node:assert/strict';
import test from 'node:test';
import type { ChallengeDefinitionSummary } from './types.ts';

import {
  campaignBattleLabel,
  challengeErrorMessage,
  challengeStatusLabel,
  draftChoiceIndexForKey,
  draftEvolutionChoices,
  draftRollFrames,
  draftRollTransitionMode,
  DRAFT_POKEMON_ROLL_DURATION_MS,
  DRAFT_REEL_FRAMES,
  DRAFT_ROLL_DURATION_MS,
  difficultyLabel,
  draftRollDuration,
  opponentStageLevel,
  emptyEvSpread,
  evAllocationTotal,
  evSpreadTotal,
  formatDuration,
  generationRomanNumeral,
  legalEvValue,
  pokemonTypeColor,
  recommendedEvPresets,
  STANDARD_CHALLENGE_SETTINGS,
  standardChallengeDefinition,
  standardChallengePayload
} from './challenge.ts';

test('one-click Draft uses the visible standard settings and complete saved rules', () => {
  const payload = standardChallengePayload(20260823);

  assert.equal(payload.seed, 20260823);
  assert.equal(payload.battle_controller.agent_type, STANDARD_CHALLENGE_SETTINGS.battleType);
  assert.equal(payload.opponent_controller.agent_type, 'tactical-auto');
  assert.equal(payload.battle_experience, 'fast-watch');
  assert.equal(payload.difficulty, 'normal');
  assert.equal(payload.opponent_team_mode, 'original');
  assert.equal(payload.draft_rules.choice_count, 3);
  assert.equal(payload.draft_rules.roster_size, 6);
  assert.equal(payload.draft_rules.rerolls, 0);
  assert.equal(payload.draft_rules.type_rerolls, 1);
  assert.equal(payload.draft_rules.generation_rerolls, 1);
  assert.equal(payload.draft_rules.draft_pool_mode, 'base-forms-only');
  assert.notEqual(payload.battle_controller.configuration, payload.opponent_controller.configuration);
});

test('standard route selection is regional and seed-stable instead of always Kanto', () => {
  const definitions: ChallengeDefinitionSummary[] = [
    { id: 'all-generations-gauntlet', name: 'All Generations', campaign_kind: 'multi-generation' as const, generation: 1 },
    { id: 'kanto-gym-gauntlet', name: 'Kanto', campaign_kind: 'regional' as const, generation: 1 },
    { id: 'johto-gym-gauntlet', name: 'Johto', campaign_kind: 'regional' as const, generation: 2 }
  ].map((item) => ({ ...item, description: '', region: item.name, stage_count: 1, stage_count_label: '1 stage', specialties: [] }));
  const first = standardChallengeDefinition(definitions, 1);
  const second = standardChallengeDefinition(definitions, 2);

  assert.equal(first?.id, 'johto-gym-gauntlet');
  assert.equal(second?.id, 'kanto-gym-gauntlet');
  assert.notEqual(first?.id, 'all-generations-gauntlet');
});

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

test('draft evolution choices follow a single-step prefix to Pichus future branch', () => {
  const trigger = (id: string, name: string) => ({ id, name, trigger_level: null, trigger_kind: 'useItem' });
  const pichu = { showdown_id: 'pichu', evolves_to: [trigger('pikachu', 'Pikachu')] };
  const pikachu = {
    showdown_id: 'pikachu',
    evolves_to: [trigger('raichu', 'Raichu'), trigger('raichualola', 'Raichu-Alola')]
  };

  assert.deepEqual(
    draftEvolutionChoices(pichu, [pichu, pikachu]).map((choice) => choice.id),
    ['raichu', 'raichualola']
  );
});

test('draft evolution choices stay empty for a deterministic evolution line', () => {
  const trigger = (id: string, name: string) => ({ id, name, trigger_level: 20, trigger_kind: 'level' });
  const first = { showdown_id: 'first', evolves_to: [trigger('second', 'Second')] };
  const second = { showdown_id: 'second', evolves_to: [trigger('final', 'Final')] };
  const final = { showdown_id: 'final', evolves_to: [] };

  assert.deepEqual(draftEvolutionChoices(first, [first, second, final]), []);
});

test('draft roll animation distinguishes automatic, type, generation, and Pokemon rerolls', () => {
  assert.equal(draftRollTransitionMode(undefined, true), 'both');
  assert.equal(draftRollTransitionMode('picked'), 'both');
  assert.equal(draftRollTransitionMode('type_rerolled'), 'type');
  assert.equal(draftRollTransitionMode('generation_rerolled'), 'generation');
  assert.equal(draftRollTransitionMode('pokemon_rerolled'), 'pokemon');
  assert.equal(draftRollTransitionMode('rerolled'), 'pokemon');
});

test('a restored offer replays nothing and reduced motion disables every reel', () => {
  // Refresh/reconnect: no first-roll marker and no fingerprint change.
  assert.equal(draftRollTransitionMode(undefined, false), null);
  assert.equal(draftRollTransitionMode('picked', false, true), null);
  assert.equal(draftRollTransitionMode('type_rerolled', false, true), null);
  assert.equal(draftRollTransitionMode('generation_rerolled', false, true), null);
  assert.equal(draftRollTransitionMode('pokemon_rerolled', false, true), null);
  assert.equal(draftRollTransitionMode(undefined, true, true), null);
});

test('a Pokemon reroll locks both reels and only replays the candidate cards', () => {
  const pokemonOnly = draftRollFrames(5, 'Steel', 'pokemon');

  assert.deepEqual(pokemonOnly.generations, [5]);
  assert.deepEqual(pokemonOnly.types, ['steel']);
  assert.ok(draftRollDuration('pokemon') < draftRollDuration('both'));
  assert.equal(draftRollDuration('pokemon'), DRAFT_POKEMON_ROLL_DURATION_MS);
  assert.equal(draftRollDuration('generation'), DRAFT_ROLL_DURATION_MS);
});

test('difficulty labels and derived opponent levels never touch the player level', () => {
  assert.equal(difficultyLabel('normal'), 'Normal');
  assert.equal(difficultyLabel(undefined), 'Normal');
  assert.ok(difficultyLabel('nightmare').includes('15'));
  assert.equal(opponentStageLevel(75, 'normal'), 75);
  assert.equal(opponentStageLevel(75, 'hard'), 80);
  assert.equal(opponentStageLevel(75, 'expert'), 85);
  assert.equal(opponentStageLevel(75, 'nightmare'), 90);
  assert.equal(opponentStageLevel(95, 'nightmare'), 100);
});

test('draft roll frames settle quickly on authoritative Roman generation and type', () => {
  const both = draftRollFrames(3, 'Water', 'both');
  const typeOnly = draftRollFrames(3, 'Water', 'type');
  const generationOnly = draftRollFrames(3, 'Water', 'generation');

  assert.equal(generationRomanNumeral(3), 'III');
  assert.equal(both.generations.at(-1), 3);
  assert.equal(both.types.at(-1), 'water');
  assert.deepEqual(typeOnly.generations, [3]);
  assert.equal(typeOnly.types.length, DRAFT_REEL_FRAMES);
  assert.equal(both.generations.length, DRAFT_REEL_FRAMES);
  assert.equal(generationOnly.generations.length, DRAFT_REEL_FRAMES);
  assert.deepEqual(generationOnly.types, ['water']);
  assert.ok(DRAFT_ROLL_DURATION_MS >= 400 && DRAFT_ROLL_DURATION_MS <= 800);
});

test('campaign position is one-based and capped at the final battle', () => {
  assert.equal(campaignBattleLabel(3, 13, 'Erika'), 'Battle 4 of 13 · Erika');
  assert.equal(campaignBattleLabel(13, 13, 'Champion Blue'), 'Battle 13 of 13 · Champion Blue');
});

test('status and duration labels are user-facing', () => {
  assert.equal(challengeStatusLabel('team_review'), 'Team review');
  assert.equal(challengeStatusLabel('mega_selection'), 'Mega unlocked');
  assert.equal(challengeStatusLabel('completed'), 'Draft run complete');
  assert.equal(formatDuration(0), '0s');
  assert.equal(formatDuration(3670), '1h 1m');
});
