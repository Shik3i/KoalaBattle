'use strict';

const http = require('node:http');
const { Dex, Teams } = require('./dist/sim');
const { TeamValidator } = require('./dist/sim/team-validator');

const HOST = '0.0.0.0';
const PORT = Number(process.env.KOALABATTLE_TEAM_VALIDATOR_PORT || 8002);
const MAX_BODY_BYTES = 55_000;
const CATALOG_SCHEMA_VERSION = '1.0';

function reply(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store'
  });
  response.end(body);
}

/** Strip the leading "[Gen N] " marker Showdown puts in front of every format name. */
function shortName(name) {
  return name.replace(/^\[[^\]]*\]\s*/, '').trim() || name;
}

function ruleTable(format) {
  try {
    return Dex.formats.getRuleTable(format);
  } catch {
    return null;
  }
}

function hasRule(rules, name) {
  return Boolean(rules && rules.has(Dex.toID(name)));
}

/**
 * Report which battle mechanics actually exist in a format. Generation availability is the
 * floor; the format's own rule table can still remove a mechanic (for example Dynamax Clause).
 */
function mechanics(format, generation) {
  const rules = ruleTable(format);
  const megaEvolution = generation >= 6 && generation <= 7;
  return {
    items: generation >= 2,
    abilities: generation >= 3,
    physical_special_split: generation >= 4,
    mega_evolution: megaEvolution && !hasRule(rules, 'Mega Rayquaza Clause'),
    z_moves: generation === 7,
    dynamax: generation === 8 && !hasRule(rules, 'Dynamax Clause'),
    terastallization: generation >= 9 && !hasRule(rules, 'Terastal Clause'),
    hidden_power_types: generation >= 2 && generation <= 7,
    natures: generation >= 3,
    held_item_switching: generation >= 2
  };
}

function teamType(format) {
  if (typeof format.team === 'string' && format.team.length) return format.team;
  return 'custom';
}

function describe(format) {
  const generation = Dex.forFormat(format).gen;
  const team = teamType(format);
  return {
    id: format.id,
    name: format.name,
    display_name: shortName(format.name),
    generation,
    mod: format.mod,
    section: format.section || 'Other',
    game_type: format.gameType || 'singles',
    player_count: format.playerCount || 2,
    team_source: team,
    random_team: team !== 'custom',
    custom_team_required: team === 'custom',
    challenge_visible: format.challengeShow !== false,
    tournament_visible: format.tournamentShow !== false,
    search_visible: format.searchShow !== false,
    rated: Boolean(format.rated),
    best_of_default: format.bestOfDefault || null,
    mechanics: mechanics(format, generation)
  };
}

let cachedNames = null;

/**
 * Display names for abilities and items. Showdown stores these as IDs on a battle request
 * ("ironfist"), and only the Dex knows they read as "Iron Fist".
 */
function dexNames() {
  if (cachedNames) return cachedNames;
  const collect = (entries) => {
    const result = {};
    for (const entry of entries) {
      if (entry && entry.exists !== false && entry.id && entry.name) result[entry.id] = entry.name;
    }
    return result;
  };
  cachedNames = {
    schema_version: CATALOG_SCHEMA_VERSION,
    abilities: collect(Dex.abilities.all()),
    items: collect(Dex.items.all())
  };
  return cachedNames;
}

let cachedCatalog = null;
const cachedSpecies = new Map();

const FACTORY_SET_GENERATIONS = [9, 8, 7, 6];
const RANDOM_SET_GENERATIONS = [9, 8, 7, 6, 5, 4, 3, 2];

function first(value, fallback = '') {
  return Array.isArray(value) ? (value[0] ?? fallback) : (value ?? fallback);
}

function factorySetSources() {
  return FACTORY_SET_GENERATIONS.flatMap((generation) => {
    try {
      return [{
        generation,
        tiers: require(`./dist/data/random-battles/gen${generation}/factory-sets.json`)
      }];
    } catch {
      return [];
    }
  });
}

const FACTORY_SET_SOURCES = factorySetSources();

function randomSetSources() {
  return RANDOM_SET_GENERATIONS.flatMap((generation) => {
    try {
      const teams = require(`./dist/data/random-battles/gen${generation}/teams`);
      return [{
        generation,
        Generator: teams.default,
        sets: require(`./dist/data/random-battles/gen${generation}/sets.json`)
      }];
    } catch {
      return [];
    }
  });
}

const RANDOM_SET_SOURCES = randomSetSources();

function stableSeed(value, attempt = 0) {
  let hash = (2166136261 ^ attempt) >>> 0;
  for (const character of value) {
    hash ^= character.codePointAt(0);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  return [hash, (hash ^ 0x9e3779b9) >>> 0, Math.imul(hash || 1, 2654435761) >>> 0, (hash + attempt + 1) >>> 0];
}

function normalizedSet(entry, raw, level = 100) {
  const evs = { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0, ...(raw.evs || {}) };
  // Showdown's validator requires the canonical one-EV marker for an intentional zero spread.
  if (!Object.values(evs).some(Number)) evs.hp = 1;
  return {
    name: entry.baseSpecies || entry.name,
    species: raw.species || entry.name,
    item: first(raw.item),
    ability: first(raw.ability),
    nature: first(raw.nature, 'Serious'),
    moves: (raw.moves || []).map((move) => first(move)).filter(Boolean),
    evs,
    ivs: { hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31, ...(raw.ivs || {}) },
    level,
    teraType: first(raw.teraType) || undefined
  };
}

function exportedSet(source, generation, tier, set) {
  return {
    source,
    source_generation: generation,
    source_tier: tier,
    species: set.species,
    item: set.item,
    ability: set.ability,
    nature: set.nature,
    moves: set.moves,
    evs: set.evs,
    ivs: set.ivs,
    tera_type: set.teraType || null
  };
}

function alternatives(value, fallback = '') {
  const values = Array.isArray(value) ? value : [value ?? fallback];
  return values.length ? values : [fallback];
}

function factoryAlternatives(raw) {
  const fields = [
    alternatives(raw.item),
    alternatives(raw.ability),
    alternatives(raw.nature, 'Serious'),
    ...(raw.moves || []).map((move) => alternatives(move)),
    alternatives(raw.teraType, '')
  ];
  let combinations = [[]];
  for (const values of fields) {
    combinations = combinations.flatMap((combination) => values.map((value) => combination.concat(value)));
    if (combinations.length > 512) combinations = combinations.slice(0, 512);
  }
  return combinations.map((combination) => ({
    ...raw,
    item: combination[0],
    ability: combination[1],
    nature: combination[2],
    moves: combination.slice(3, 3 + (raw.moves || []).length),
    teraType: combination[3 + (raw.moves || []).length]
  }));
}

/**
 * Resolve one complete competitive set from Showdown's own pinned Battle Factory data.
 * Older generations are considered only when the current data has no set for that species;
 * the final set is still checked by the requested format's current TeamValidator.
 */
function showdownFactorySet(format, entry, validator) {
  for (const source of FACTORY_SET_SOURCES) {
    for (const [tier, entries] of Object.entries(source.tiers)) {
      const record = entries[entry.id];
      if (!record || !Array.isArray(record.sets)) continue;
      for (const raw of record.sets) {
        for (const alternative of factoryAlternatives(raw)) {
          const set = normalizedSet(entry, alternative);
          if (set.moves.length !== 4) continue;
          if ((validator.validateTeam([set]) || []).length) continue;
          return exportedSet('showdown-battle-factory', source.generation, tier, set);
        }
      }
    }
  }
  return null;
}

/** Generate a deterministic set with Showdown's own generation-specific RandomTeams code. */
function showdownRandomSet(format, entry, validator) {
  for (const source of RANDOM_SET_SOURCES) {
    if (!source.sets[entry.id]) continue;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        const generator = new source.Generator(
          `gen${source.generation}randombattle`,
          stableSeed(`${source.generation}:${entry.id}`, attempt)
        );
        const raw = generator.randomSet(entry.id, {}, false, false);
        const set = normalizedSet(entry, raw);
        if (!set.moves.length || set.moves.length > 4) continue;
        if ((validator.validateTeam([set]) || []).length) continue;
        return exportedSet(
          'showdown-random-battle',
          source.generation,
          raw.role || 'Random Battle',
          set
        );
      } catch {
        // Continue with the next deterministic attempt or pinned generation.
      }
    }
  }
  return null;
}

function learnableMoves(formatDex, entry) {
  const moveIds = new Set();
  for (const { learnset } of formatDex.species.getFullLearnset(entry.id)) {
    for (const moveId of Object.keys(learnset || {})) moveIds.add(moveId);
  }
  const preferredCategory = Number(entry.baseStats.atk || 0) >= Number(entry.baseStats.spa || 0)
    ? 'Physical'
    : 'Special';
  const score = (move) => {
    const stab = entry.types.includes(move.type) ? 1000 : 0;
    const category = move.category === preferredCategory ? 400 : move.category === 'Status' ? 0 : 100;
    const accuracy = move.accuracy === true ? 100 : Number(move.accuracy || 0);
    return stab + category + Number(move.basePower || 0) * accuracy / 100;
  };
  return [...moveIds]
    .map((moveId) => formatDex.moves.get(moveId))
    .filter((move) => move && move.exists !== false && (!move.isNonstandard || move.isNonstandard === 'Past'))
    .sort((left, right) => score(right) - score(left) || left.name.localeCompare(right.name));
}

/** Fill legal species absent from curated datasets using only pinned Dex and validator data. */
function showdownDexSet(formatDex, entry, validator, requiredItem) {
  const abilities = entry.requiredAbility
    ? [entry.requiredAbility]
    : [...new Set(['0', '1', 'H', 'S'].map((slot) => entry.abilities && entry.abilities[slot]).filter(Boolean))];
  for (const ability of abilities) {
    const set = normalizedSet(entry, {
      species: entry.name,
      item: requiredItem || '',
      ability,
      nature: 'Serious',
      moves: [],
      evs: { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 },
      ivs: { hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31 }
    });
    if (entry.requiredMove) {
      const requiredMove = formatDex.moves.get(entry.requiredMove);
      if (requiredMove && requiredMove.exists !== false) set.moves.push(requiredMove.name);
    }
    for (const move of learnableMoves(formatDex, entry)) {
      if (set.moves.length === 4) break;
      if (set.moves.some((name) => Dex.toID(name) === move.id)) continue;
      const proposed = {...set, moves: set.moves.concat(move.name)};
      if (!(validator.validateTeam([proposed]) || []).length) set.moves.push(move.name);
    }
    if (set.moves.length && !(validator.validateTeam([set]) || []).length) {
      return exportedSet('showdown-dex-validated', formatDex.gen, 'Format legal', set);
    }
  }
  return null;
}

/** Draft metadata comes directly from the same pinned Dex that validates the final team. */
function speciesCatalog(formatId) {
  if (cachedSpecies.has(formatId)) return cachedSpecies.get(formatId);
  const format = knownFormat(formatId);
  if (!format) return null;
  const formatDex = Dex.forFormat(format);
  const validator = TeamValidator.get(format.id);
  const formatGeneration = formatDex.gen;
  const abilitiesSupported = mechanics(format, formatGeneration).abilities;
  const species = formatDex.species
    .all()
    .filter((entry) => entry.exists !== false && Number(entry.num) > 0)
    .map((entry) => {
      const base = formatDex.species.get(entry.baseSpecies || entry.name);
      const abilities = abilitiesSupported
        ? ['0', '1', 'H', 'S'].flatMap((slot) => {
            const abilityName = entry.abilities && entry.abilities[slot];
            if (!abilityName) return [];
            const ability = formatDex.abilities.get(abilityName);
            if (!ability || ability.exists === false) return [];
            return [{ slot, id: ability.id, name: ability.name, hidden: slot === 'H' }];
          })
        : [];
      const requiredItem = entry.requiredItem || (entry.requiredItems && entry.requiredItems[0]) || null;
      const competitiveSet = showdownFactorySet(format, entry, validator) ||
        showdownRandomSet(format, entry, validator) ||
        showdownDexSet(formatDex, entry, validator, requiredItem);
      return {
        id: entry.id,
        name: entry.name,
        base_species_id: Dex.toID(entry.baseSpecies || entry.name),
        national_dex_number: Number(entry.num),
        introduction_generation: Number(entry.gen),
        types: entry.types || [],
        base_stat_total: Object.values(entry.baseStats || {}).reduce((total, value) => total + Number(value || 0), 0) || null,
        base_stats: entry.baseStats ? {
          hp: Number(entry.baseStats.hp),
          atk: Number(entry.baseStats.atk),
          defense: Number(entry.baseStats.def),
          spa: Number(entry.baseStats.spa),
          spd: Number(entry.baseStats.spd),
          spe: Number(entry.baseStats.spe)
        } : null,
        max_hp: entry.maxHP == null ? null : Number(entry.maxHP),
        abilities,
        recommended_moves: competitiveSet ? competitiveSet.moves : [],
        showdown_set: competitiveSet,
        required_item: requiredItem,
        battle_only: Boolean(entry.battleOnly),
        cosmetic: Boolean(base.cosmeticFormes && base.cosmeticFormes.includes(entry.name)),
        unavailable: Boolean(entry.isNonstandard && entry.isNonstandard !== 'Past') || !competitiveSet,
        is_mega: String(entry.forme || '').toLowerCase().startsWith('mega'),
        is_gmax: String(entry.forme || '').toLowerCase() === 'gmax'
      };
    })
    .sort((left, right) => left.national_dex_number - right.national_dex_number || left.id.localeCompare(right.id));
  const result = {
    schema_version: CATALOG_SCHEMA_VERSION,
    showdown_version: process.env.KOALABATTLE_SHOWDOWN_VERSION || 'pinned-local-build',
    format: format.id,
    format_generation: formatGeneration,
    abilities_supported: abilitiesSupported,
    species_count: species.length,
    species
  };
  cachedSpecies.set(formatId, result);
  return result;
}

function catalog() {
  if (cachedCatalog) return cachedCatalog;
  const formats = Dex.formats
    .all()
    .filter((format) => format.effectType === 'Format')
    .map(describe)
    .sort((left, right) => right.generation - left.generation || left.id.localeCompare(right.id));
  cachedCatalog = {
    schema_version: CATALOG_SCHEMA_VERSION,
    showdown_version: process.env.KOALABATTLE_SHOWDOWN_VERSION || 'pinned-local-build',
    format_count: formats.length,
    formats
  };
  return cachedCatalog;
}

function knownFormat(formatId) {
  if (typeof formatId !== 'string' || !formatId) return null;
  const format = Dex.formats.get(formatId);
  return format && format.exists && format.effectType === 'Format' ? format : null;
}

function validate(payload) {
  const format = knownFormat(payload && payload.format);
  if (!format || typeof (payload && payload.team) !== 'string') {
    return { status: 422, body: { detail: 'format must be a known Showdown format and team must be text' } };
  }
  if (!payload.team || Buffer.byteLength(payload.team, 'utf8') > 50_000) {
    return { status: 413, body: { detail: 'team must be 1-50000 UTF-8 bytes' } };
  }
  const team = Teams.import(payload.team);
  const errors = TeamValidator.get(format.id).validateTeam(team) || [];
  if (errors.length) {
    return {
      status: 200,
      body: { schema_version: '1.0', format: format.id, valid: false, errors }
    };
  }
  return {
    status: 200,
    body: {
      schema_version: '1.0',
      format: format.id,
      valid: true,
      errors: [],
      normalized_export: Teams.export(team),
      packed_team: Teams.pack(team),
      structured_team: team
    }
  };
}

const server = http.createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/healthz') {
    reply(response, 200, { status: 'ok', format_count: catalog().format_count });
    return;
  }
  if (request.method === 'GET' && request.url === '/formats') {
    reply(response, 200, catalog());
    return;
  }
  if (request.method === 'GET' && request.url === '/dex-names') {
    reply(response, 200, dexNames());
    return;
  }
  const requestUrl = new URL(request.url, `http://${request.headers.host || 'localhost'}`);
  if (request.method === 'GET' && requestUrl.pathname === '/dex-species') {
    const formatId = requestUrl.searchParams.get('format') || 'gen9natdexdraft';
    const result = speciesCatalog(formatId);
    reply(response, result ? 200 : 422, result || { detail: 'format must be a known Showdown format' });
    return;
  }
  if (request.method !== 'POST' || request.url !== '/validate') {
    reply(response, 404, { detail: 'not found' });
    return;
  }
  const chunks = [];
  let size = 0;
  request.on('data', (chunk) => {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) request.destroy();
    else chunks.push(chunk);
  });
  request.on('end', () => {
    try {
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      const result = validate(payload);
      reply(response, result.status, result.body);
    } catch {
      reply(response, 400, { detail: 'invalid JSON' });
    }
  });
  request.on('error', () => {
    if (!response.headersSent) reply(response, 413, { detail: 'request body too large' });
  });
});

server.listen(PORT, HOST, () => {
  process.stdout.write(`KoalaBattle Showdown tools listening on ${HOST}:${PORT}\n`);
});
