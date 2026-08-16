import assert from 'node:assert/strict';
import test from 'node:test';

import { expandQuery, formatSummary, searchFormats } from '../format-search.ts';
import type { FormatDescriptor } from '../types.ts';

const format = (
  id: string,
  displayName: string,
  generation: number,
  overrides: Partial<FormatDescriptor> = {}
): FormatDescriptor => ({
  id,
  name: `[Gen ${generation}] ${displayName}`,
  display_name: displayName,
  generation,
  mod: `gen${generation}`,
  section: 'Test Section',
  game_type: 'singles',
  player_count: 2,
  team_source: 'custom',
  random_team: false,
  custom_team_required: true,
  challenge_visible: true,
  tournament_visible: true,
  search_visible: true,
  rated: true,
  best_of_default: null,
  mechanics: {
    items: generation >= 2,
    abilities: generation >= 3,
    physical_special_split: generation >= 4,
    mega_evolution: false,
    z_moves: false,
    dynamax: false,
    terastallization: generation >= 9,
    hidden_power_types: false,
    natures: generation >= 3,
    held_item_switching: generation >= 2
  },
  supported: true,
  unsupported_reason: null,
  ...overrides
});

const catalog: FormatDescriptor[] = [
  format('gen9randombattle', 'Random Battle', 9, { random_team: true, custom_team_required: false }),
  format('gen9ou', 'OU', 9),
  format('gen9doublesou', 'Doubles OU', 9, {
    game_type: 'doubles',
    supported: false,
    unsupported_reason: 'Not yet supported by KoalaBattle battle renderer (doubles)'
  }),
  format('gen8ou', 'OU', 8),
  format('gen4ou', 'OU', 4),
  format('gen1randombattle', 'Random Battle', 1, { random_team: true, custom_team_required: false }),
  format('gen1ou', 'OU', 1)
];

test('generation shorthand expands the way players type it', () => {
  assert.deepEqual(expandQuery('gen 1'), ['gen1']);
  assert.deepEqual(expandQuery('RBY'), ['gen1']);
  assert.deepEqual(expandQuery('dpp ou'), ['gen4', 'ou']);
  assert.deepEqual(expandQuery('   '), []);
});

test('search finds the formats the dogfooding pass called out', () => {
  assert.deepEqual(
    searchFormats(catalog, 'gen 1').map((item) => item.id),
    ['gen1randombattle', 'gen1ou']
  );
  assert.deepEqual(
    searchFormats(catalog, 'rby').map((item) => item.id),
    ['gen1randombattle', 'gen1ou']
  );
  assert.deepEqual(
    searchFormats(catalog, 'random').map((item) => item.id),
    ['gen9randombattle', 'gen1randombattle']
  );
  assert.deepEqual(searchFormats(catalog, 'gen1 ou').map((item) => item.id), ['gen1ou']);
});

test('prefix matching keeps "ou" away from "doubles"', () => {
  const hits = searchFormats(catalog, 'ou').map((item) => item.id);
  assert.ok(hits.includes('gen9ou'));
  assert.ok(hits.includes('gen9doublesou'), 'Doubles OU still matches on its own name');
  assert.ok(!searchFormats(catalog, 'ou').some((item) => item.id === 'gen9randombattle'));
});

test('an empty query keeps the full catalog', () => {
  assert.equal(searchFormats(catalog, '').length, catalog.length);
});

test('summary states generation, team source and game type', () => {
  assert.equal(formatSummary(catalog[0]), 'GEN 9 · RANDOM TEAMS · SINGLES');
  assert.equal(formatSummary(catalog[1]), 'GEN 9 · CUSTOM TEAM · SINGLES');
  assert.equal(formatSummary(catalog[2]), 'GEN 9 · CUSTOM TEAM · DOUBLES');
});
