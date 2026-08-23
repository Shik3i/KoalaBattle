'use strict';

const http = require('node:http');
const { Dex, Teams } = require('./dist/sim');
const { TeamValidator } = require('./dist/sim/team-validator');

const HOST = '0.0.0.0';
const PORT = Number(process.env.KOALABATTLE_TEAM_VALIDATOR_PORT || 8002);
const MAX_BODY_BYTES = 55_000;
const CATALOG_SCHEMA_VERSION = '1.2';
/**
 * The lowest level any campaign definition may assign to its first stage. Recommended sets
 * are built and validated at this level, not level 100: Showdown's move-legality check is
 * monotonic in level (a move learnable at level 25 stays learnable at every higher level), so
 * a set that is real-Showdown-legal here is guaranteed legal for the rest of the campaign.
 */
const CAMPAIGN_MIN_LEVEL = 10;

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
  // National Dex deliberately restores past mechanics while keeping the current-generation
  // mod. Generation alone therefore cannot describe whether a Mega Stone is actionable.
  const megaEvolution = (generation >= 6 && generation <= 7) || hasRule(rules, 'NatDex Mod');
  return {
    items: generation >= 2,
    abilities: generation >= 3,
    physical_special_split: generation >= 4,
    mega_evolution: megaEvolution,
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

/** A Random-Battle-generated set stores move IDs, not display names ("dazzlinggleam"). */
function resolvedMoveName(value) {
  const name = first(value);
  if (!name) return '';
  const move = Dex.moves.get(name);
  return move && move.exists !== false ? move.name : name;
}

function normalizedSet(entry, raw, level) {
  const evs = { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0, ...(raw.evs || {}) };
  // Showdown's validator requires the canonical one-EV marker for an intentional zero spread.
  if (!Object.values(evs).some(Number)) evs.hp = 1;
  return {
    name: entry.baseSpecies || entry.name,
    species: raw.species || entry.name,
    item: first(raw.item),
    ability: first(raw.ability),
    nature: first(raw.nature, 'Serious'),
    moves: (raw.moves || []).map(resolvedMoveName).filter(Boolean),
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
function showdownFactorySet(format, entry, validator, level) {
  for (const source of FACTORY_SET_SOURCES) {
    for (const [tier, entries] of Object.entries(source.tiers)) {
      const record = entries[entry.id];
      if (!record || !Array.isArray(record.sets)) continue;
      for (const raw of record.sets) {
        for (const alternative of factoryAlternatives(raw)) {
          const set = normalizedSet(entry, alternative, level);
          if (set.moves.length !== 4) continue;
          if ((validator.validateTeam([set]) || []).length) continue;
          return exportedSet('showdown-battle-factory', source.generation, tier, set);
        }
      }
    }
  }
  return null;
}

const NEUTRAL_NATURES = new Set(['Hardy', 'Docile', 'Serious', 'Bashful', 'Quirky']);

/** Older-generation random-battle data has no real EV curation: a flat, evenly-split spread
 *  at a neutral nature. Re-derive a role-appropriate spread rather than keep it. */
function isUncuratedSpread(set) {
  if (NEUTRAL_NATURES.has(set.nature)) return true;
  const values = Object.values(set.evs);
  return new Set(values.filter(Boolean)).size <= 1 && values.some(Boolean);
}

/** Generate a deterministic set with Showdown's own generation-specific RandomTeams code. */
function showdownRandomSet(format, entry, validator, level) {
  for (const source of RANDOM_SET_SOURCES) {
    if (!source.sets[entry.id]) continue;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        const generator = new source.Generator(
          `gen${source.generation}randombattle`,
          stableSeed(`${source.generation}:${entry.id}`, attempt)
        );
        const raw = generator.randomSet(entry.id, {}, false, false);
        let set = normalizedSet(entry, raw, level);
        if (!set.moves.length || set.moves.length > 4) continue;
        if (isUncuratedSpread(set)) {
          const role = statRole(entry);
          const tuned = { ...set, nature: recommendedNature(role), evs: recommendedEvs(role) };
          if (!(validator.validateTeam([tuned]) || []).length) set = tuned;
        }
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

/**
 * A coarse offense/bulk read of the species' own base stats, used only to pick a sane
 * default nature/EV spread/item when no curated competitive set exists. This is a fallback
 * heuristic, not a claim of competitive optimality — see docs/CHALLENGES.md.
 */
function statRole(entry) {
  const stats = entry.baseStats || {};
  const hp = Number(stats.hp || 0);
  const atk = Number(stats.atk || 0);
  const def = Number(stats.def || 0);
  const spa = Number(stats.spa || 0);
  const spd = Number(stats.spd || 0);
  const spe = Number(stats.spe || 0);
  const physical = atk >= spa;
  const offense = physical ? atk : spa;
  const bulk = hp + def + spd;
  const bestDefense = Math.max(def, spd);
  const isWall = bestDefense - offense >= 40 && bulk >= 260;
  const defenseIsPhysical = def >= spd;
  return { physical, offense, speed: spe, isWall, defenseIsPhysical };
}

function recommendedNature(role) {
  if (role.isWall) return role.defenseIsPhysical ? 'Bold' : 'Calm';
  if (role.physical) return role.speed >= 90 ? 'Jolly' : 'Adamant';
  return role.speed >= 90 ? 'Timid' : 'Modest';
}

function recommendedEvs(role) {
  if (role.isWall) {
    return role.defenseIsPhysical
      ? { hp: 252, atk: 0, def: 252, spa: 0, spd: 4, spe: 0 }
      : { hp: 252, atk: 0, def: 4, spa: 0, spd: 252, spe: 0 };
  }
  if (role.speed >= 90) {
    return role.physical
      ? { hp: 0, atk: 252, def: 0, spa: 0, spd: 4, spe: 252 }
      : { hp: 0, atk: 0, def: 0, spa: 252, spd: 4, spe: 252 };
  }
  return role.physical
    ? { hp: 252, atk: 252, def: 0, spa: 0, spd: 4, spe: 0 }
    : { hp: 252, atk: 0, def: 0, spa: 252, spd: 4, spe: 0 };
}

/** Not-fully-evolved species get Eviolite instead of a role item; everyone else gets one. */
function recommendedItem(role, isNfe) {
  if (isNfe) return 'Eviolite';
  if (role.isWall) return 'Leftovers';
  return role.speed >= 90 ? 'Life Orb' : 'Choice Band';
}

/**
 * Fill up to four moves, capping attacking moves to one per type until only the last slot
 * remains. A curated set never needs this; it is what keeps a fully generated fallback set
 * from being four same-type attacks (four Water moves on a Water starter, for example).
 */
function coverageMoves(formatDex, entry, validator, baseSet, requiredMoveName) {
  const moves = requiredMoveName ? [requiredMoveName] : [];
  const usedTypes = new Set();
  for (const name of moves) {
    const move = formatDex.moves.get(name);
    if (move && move.category !== 'Status') usedTypes.add(move.type);
  }
  const candidates = learnableMoves(formatDex, entry);
  const tryAdd = (move) => {
    if (moves.some((name) => Dex.toID(name) === move.id)) return false;
    const proposed = { ...baseSet, moves: moves.concat(move.name) };
    if ((validator.validateTeam([proposed]) || []).length) return false;
    moves.push(move.name);
    if (move.category !== 'Status') usedTypes.add(move.type);
    return true;
  };
  for (const move of candidates) {
    if (moves.length === 4) break;
    const isAttacking = move.category !== 'Status';
    const slotsLeft = 4 - moves.length;
    if (isAttacking && usedTypes.has(move.type) && slotsLeft > 1) continue;
    tryAdd(move);
  }
  // A move with no remaining type-diverse option is still better than an empty slot.
  for (const move of candidates) {
    if (moves.length === 4) break;
    tryAdd(move);
  }
  return moves;
}

/** Fill legal species absent from curated datasets using only pinned Dex and validator data. */
function showdownDexSet(formatDex, entry, validator, requiredItem, level) {
  const abilities = entry.requiredAbility
    ? [entry.requiredAbility]
    : [...new Set(['0', '1', 'H', 'S'].map((slot) => entry.abilities && entry.abilities[slot]).filter(Boolean))];
  const role = statRole(entry);
  const isNfe = Boolean(entry.evos && entry.evos.length);
  const requiredMoveName = (() => {
    if (!entry.requiredMove) return null;
    const move = formatDex.moves.get(entry.requiredMove);
    return move && move.exists !== false ? move.name : null;
  })();
  for (const ability of abilities) {
    const base = normalizedSet(entry, {
      species: entry.name,
      item: requiredItem || recommendedItem(role, isNfe),
      ability,
      nature: recommendedNature(role),
      moves: [],
      evs: recommendedEvs(role),
      ivs: { hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31 }
    }, level);
    const moves = coverageMoves(formatDex, entry, validator, base, requiredMoveName);
    const set = { ...base, moves };
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
  const allSpecies = formatDex.species.all();
  const species = allSpecies
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
      // An evolved species can be rejected by Showdown below its own evolution level even
      // when its moves are otherwise perfectly legal. Build reusable metadata at that
      // minimum; the campaign launcher applies the actual stage level later.
      const setLevel = Number.isFinite(entry.evoLevel)
        ? Math.max(CAMPAIGN_MIN_LEVEL, Number(entry.evoLevel))
        : CAMPAIGN_MIN_LEVEL;
      const competitiveSet = showdownFactorySet(format, entry, validator, setLevel) ||
        showdownRandomSet(format, entry, validator, setLevel) ||
        showdownDexSet(formatDex, entry, validator, requiredItem, setLevel);
      // Every species this one can evolve into, with the trigger for reaching it. A missing
      // `evoLevel` alongside any other evoType (item/trade/friendship/condition/etc.) has no
      // level of its own in the source games; the backend maps every such case to one fixed,
      // documented campaign milestone instead of a level, so evolution stays deterministic.
      const evolvesTo = (entry.evos || []).map((name) => {
        const next = formatDex.species.get(name);
        return {
          id: Dex.toID(name),
          name: next.name,
          trigger_level: typeof next.evoLevel === 'number' ? next.evoLevel : null,
          trigger_kind: next.evoLevel != null && !next.evoType ? 'level' : (next.evoType || 'other')
        };
      });
      const megaEvolutions = allSpecies
        .filter((candidate) => (
          String(candidate.forme || '').toLowerCase().startsWith('mega') &&
          candidate.baseSpecies === entry.name &&
          candidate.requiredItem
        ))
        .map((candidate) => ({
          id: candidate.id,
          species: candidate.name,
          required_item: candidate.requiredItem
        }))
        .sort((left, right) => left.id.localeCompare(right.id));
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
        is_gmax: String(entry.forme || '').toLowerCase() === 'gmax',
        prevo_id: entry.prevo ? Dex.toID(entry.prevo) : null,
        evolves_to: evolvesTo,
        mega_evolutions: megaEvolutions
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
  // Build the challenge catalog before health checks pass.  The first catalog request is
  // intentionally synchronous (it walks Showdown's pinned Dex and factory sets); doing that
  // lazily made the browser's first Quick Start request look stuck during a cold container start.
  speciesCatalog('gen9natdexdraft');
  process.stdout.write(`KoalaBattle Showdown tools listening on ${HOST}:${PORT}\n`);
});
