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

function recommendedMoves(formatDex, validator, entry, abilityName, requiredItem) {
  const unreliable = new Set([
    'belch', 'bide', 'counter', 'dreameater', 'electroball', 'endeavor', 'eruption',
    'flail', 'focuspunch', 'frustration', 'grassknot', 'gyroball', 'heavyslam',
    'lastresort', 'lowkick', 'mirrorcoat', 'poltergeist', 'present', 'return',
    'reversal', 'storedpower', 'trumpcard', 'waterspout'
  ]);
  const moveSources = new Map();
  for (const { learnset } of formatDex.species.getFullLearnset(entry.id)) {
    for (const [moveId, sources] of Object.entries(learnset || {})) {
      const existing = moveSources.get(moveId) || [];
      moveSources.set(moveId, existing.concat(sources || []));
    }
  }
  const candidates = [...moveSources.entries()]
    .filter(([, sources]) => sources.some((source) => {
      if (source.charAt(1) === 'S') return false;
      if (source.charAt(1) !== 'L') return true;
      return Number.parseInt(source.slice(2), 10) <= 50;
    }))
    .map(([moveId]) => formatDex.moves.get(moveId))
    .filter((move) => move && move.exists !== false &&
      (!move.isNonstandard || move.isNonstandard === 'Past') && !unreliable.has(move.id))
    .sort((left, right) => {
      const leftDamaging = left.category !== 'Status' && Number(left.basePower) > 0 ? 1 : 0;
      const rightDamaging = right.category !== 'Status' && Number(right.basePower) > 0 ? 1 : 0;
      const leftStab = entry.types.includes(left.type) ? 1 : 0;
      const rightStab = entry.types.includes(right.type) ? 1 : 0;
      const leftReliablePower = Number(left.basePower || 0) * Number(left.accuracy === true ? 100 : left.accuracy || 0);
      const rightReliablePower = Number(right.basePower || 0) * Number(right.accuracy === true ? 100 : right.accuracy || 0);
      const leftPenalty = left.selfdestruct || left.recoil || left.hasCrashDamage ? 1 : 0;
      const rightPenalty = right.selfdestruct || right.recoil || right.hasCrashDamage ? 1 : 0;
      return rightDamaging - leftDamaging || rightStab - leftStab || leftPenalty - rightPenalty ||
        rightReliablePower - leftReliablePower || left.name.localeCompare(right.name);
    });
  const selected = [];
  for (const move of candidates) {
    const heading = entry.name + (requiredItem ? ` @ ${requiredItem}` : '');
    const team = [
      heading,
      'Level: 50',
      ...(abilityName ? [`Ability: ${abilityName}`] : []),
      'EVs: 1 HP',
      `- ${move.name}`
    ].join('\n');
    if (!(validator.validateTeam(Teams.import(team)) || []).length) {
      selected.push(move.name);
      if (selected.length === 4) break;
    }
  }
  return selected;
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
        abilities,
        recommended_moves: recommendedMoves(formatDex, validator, entry, abilities[0] && abilities[0].name, requiredItem),
        required_item: requiredItem,
        battle_only: Boolean(entry.battleOnly),
        cosmetic: Boolean(base.cosmeticFormes && base.cosmeticFormes.includes(entry.name)),
        unavailable: Boolean(entry.isNonstandard && entry.isNonstandard !== 'Past'),
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
