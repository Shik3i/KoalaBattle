import type { CampaignBadge, ChallengeDefinitionSummary, ChallengeStatus, DraftCandidate, EvolutionTrigger, EvSpread, PokemonBaseStats } from './types.ts';

export const STANDARD_CHALLENGE_SETTINGS = {
  battleType: 'tactical-auto',
  battleExperience: 'fast-watch',
  difficulty: 'normal',
  choiceCount: 3,
  // Quick Start keeps the draft focused: type and generation can each be
  // rerolled once, while the offer itself cannot be rerolled.
  pokemonRerolls: 0,
  typeRerolls: 1,
  generationRerolls: 1,
  draftPoolMode: 'base-forms-only',
  opponentTeamMode: 'original'
} as const;

function standardControllerConfiguration() {
  return {
    timeout_seconds: 300,
    max_retries: 1,
    fallback: 'random',
    temperature: null,
    max_output_tokens: 2048,
    reasoning_effort: null,
    base_url: null,
    maximum_cost: null,
    fake_scenario: 'valid'
  };
}

/** The one-click Draft contract. Keep it shared with the detailed setup defaults. */
export function standardChallengeDefinition(
  definitions: ChallengeDefinitionSummary[],
  seed: number
): ChallengeDefinitionSummary | null {
  const regional = definitions.filter((definition) => definition.campaign_kind === 'regional');
  if (!regional.length) return definitions.find((definition) => definition.campaign_kind === 'multi-generation') || null;

  // Pick the region first. This keeps every region equally likely even if one region
  // gains multiple route variants in the future.
  const byRegion = new Map<string, ChallengeDefinitionSummary[]>();
  for (const definition of regional) {
    const key = definition.region.trim().toLocaleLowerCase();
    byRegion.set(key, [...(byRegion.get(key) || []), definition]);
  }
  const regions = [...byRegion.entries()].sort(([leftKey, left], [rightKey, right]) =>
    Math.min(...left.map((route) => route.generation)) - Math.min(...right.map((route) => route.generation))
    || leftKey.localeCompare(rightKey)
  );
  const normalizedSeed = Number.isFinite(seed) ? Math.abs(Math.trunc(seed)) : 0;
  const regionRoutes = regions[normalizedSeed % regions.length][1]
    .sort((left, right) => left.generation - right.generation || left.id.localeCompare(right.id));
  return regionRoutes[Math.floor(normalizedSeed / regions.length) % regionRoutes.length];
}

export function standardChallengePayload(
  seed: number,
  name = 'Draft Gauntlet',
  definitionId = 'all-generations-gauntlet',
  battleMode: 'singles' | 'doubles' = 'singles'
) {
  return {
    name,
    definition_id: definitionId,
    seed,
    draft_controller: {
      kind: 'human' as const,
      provider: null,
      model: null,
      configuration: standardControllerConfiguration()
    },
    battle_controller: {
      agent_type: STANDARD_CHALLENGE_SETTINGS.battleType,
      provider: null,
      model: null,
      configuration: standardControllerConfiguration()
    },
    opponent_controller: {
      agent_type: 'tactical-auto' as const,
      provider: null,
      model: null,
      configuration: standardControllerConfiguration()
    },
    battle_experience: STANDARD_CHALLENGE_SETTINGS.battleExperience,
    difficulty: STANDARD_CHALLENGE_SETTINGS.difficulty,
    opponent_team_mode: STANDARD_CHALLENGE_SETTINGS.opponentTeamMode,
    battle_mode: battleMode,
    draft_rules: {
      roster_size: 6,
      rerolls: STANDARD_CHALLENGE_SETTINGS.pokemonRerolls,
      type_rerolls: STANDARD_CHALLENGE_SETTINGS.typeRerolls,
      generation_rerolls: STANDARD_CHALLENGE_SETTINGS.generationRerolls,
      choice_count: STANDARD_CHALLENGE_SETTINGS.choiceCount,
      species_clause: true,
      draft_pool_mode: STANDARD_CHALLENGE_SETTINGS.draftPoolMode
    }
  };
}

export const EV_STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'] as const;
export type EvStat = (typeof EV_STATS)[number];

export const emptyEvSpread = (): EvSpread => ({
  hp: 0,
  atk: 0,
  def: 0,
  spa: 0,
  spd: 0,
  spe: 0
});

export function evSpreadTotal(spread: EvSpread): number {
  return Object.values(spread).reduce((total, value) => total + Number(value || 0), 0);
}

export function evAllocationTotal(allocations: Record<string, EvSpread>): number {
  return Object.values(allocations).reduce(
    (total, spread) => total + evSpreadTotal(spread),
    0
  );
}

export function draftChoiceIndexForKey(key: string): number | null {
  return /^[1-8]$/.test(key) ? Number(key) - 1 : null;
}

export function campaignOpponentHeading(campaign: CampaignBadge): string {
  const title = campaign.stage_title;
  const role = title.endsWith('Gym Leaders')
    ? 'Gym Leaders'
    : title.endsWith('Gym Leader')
      ? 'Gym Leader'
      : title.includes('Grand Trial')
        ? 'Grand Trial'
        : title;
  const specialty = campaign.specialty && campaign.specialty !== 'Mixed' && !role.includes('Champion')
    ? `${campaign.specialty} `
    : '';
  return `${campaign.stage_name} · ${specialty}${role}`;
}

/** Find the first choice in a candidate's full evolution line, not only its next step. */
export function draftEvolutionChoices(
  candidate: Pick<DraftCandidate, 'showdown_id' | 'evolves_to'> & Partial<Pick<DraftCandidate, 'evolution_choices'>>,
  pool: Array<Pick<DraftCandidate, 'showdown_id' | 'evolves_to'>>
): EvolutionTrigger[] {
  if (candidate.evolution_choices?.length) return candidate.evolution_choices;
  const byId = new Map(pool.map((species) => [species.showdown_id, species]));
  const visited = new Set<string>();
  let current = candidate;

  while (current.evolves_to.length === 1) {
    if (visited.has(current.showdown_id)) return [];
    visited.add(current.showdown_id);
    const next = byId.get(current.evolves_to[0].id);
    if (!next) return [];
    current = next;
  }

  return current.evolves_to.length > 1 ? current.evolves_to : [];
}

/**
 * `pokemon` keeps both reels locked and only replays the candidate reveal, so a Pokemon
 * reroll is visually distinct from a Type or Generation reroll.
 */
export type DraftRollMode = 'both' | 'type' | 'generation' | 'pokemon';
export const DRAFT_ROLL_DURATION_MS = 620;
export const DRAFT_POKEMON_ROLL_DURATION_MS = 260;
/** Frames per reel while spinning; the last frame is always the locked result. */
export const DRAFT_REEL_FRAMES = 12;
export const DRAFT_REEL_FRAME_HEIGHT = 42;

export function draftRollDuration(mode: DraftRollMode): number {
  return mode === 'pokemon' ? DRAFT_POKEMON_ROLL_DURATION_MS : DRAFT_ROLL_DURATION_MS;
}

const GENERATION_ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX'] as const;

export function generationRomanNumeral(generation: number): string {
  return GENERATION_ROMAN[generation - 1] || String(generation);
}

export function draftRollTransitionMode(
  outcome: 'picked' | 'rerolled' | 'pokemon_rerolled' | 'type_rerolled' | 'generation_rerolled' | undefined,
  firstRoll = false,
  reducedMotion = false
): DraftRollMode | null {
  if (reducedMotion) return null;
  if (firstRoll || outcome === 'picked') return 'both';
  if (outcome === 'type_rerolled') return 'type';
  if (outcome === 'generation_rerolled') return 'generation';
  if (outcome === 'pokemon_rerolled' || outcome === 'rerolled') return 'pokemon';
  return null;
}

export function campaignBattleLabel(index: number, total: number, opponent: string): string {
  return `Battle ${Math.min(total, Math.max(1, index + 1))} of ${total} · ${opponent}`;
}

export interface EvLimits {
  pokemon: number;
  stat: number;
}

export interface EvPreset {
  id: string;
  label: string;
  reason: string;
  spread: EvSpread;
  recommended: boolean;
}

const PHYSICAL_FAST: EvSpread = { hp: 0, atk: 252, def: 0, spa: 0, spd: 4, spe: 252 };
const SPECIAL_FAST: EvSpread = { hp: 0, atk: 0, def: 0, spa: 252, spd: 4, spe: 252 };
const PHYSICAL_BULKY: EvSpread = { hp: 252, atk: 252, def: 0, spa: 0, spd: 4, spe: 0 };
const SPECIAL_BULKY: EvSpread = { hp: 252, atk: 0, def: 0, spa: 252, spd: 4, spe: 0 };
const PHYSICAL_WALL: EvSpread = { hp: 252, atk: 0, def: 252, spa: 0, spd: 4, spe: 0 };
const SPECIAL_WALL: EvSpread = { hp: 252, atk: 0, def: 4, spa: 0, spd: 252, spe: 0 };

function preset(id: string, label: string, reason: string, spread: EvSpread): EvPreset {
  return { id, label, reason, spread, recommended: false };
}

export function recommendedEvPresets(candidate: Pick<DraftCandidate, 'base_stats'>): EvPreset[] {
  const stats: PokemonBaseStats | null = candidate.base_stats;
  if (!stats) {
    return [
      preset('fast-physical', 'Fast physical', 'Older run: per-stat data unavailable', PHYSICAL_FAST),
      preset('fast-special', 'Fast special', 'Older run: per-stat data unavailable', SPECIAL_FAST),
      preset('physical-wall', 'Physical wall', 'Older run: per-stat data unavailable', PHYSICAL_WALL)
    ].map((entry, index) => ({ ...entry, recommended: index === 0 }));
  }

  const physical = stats.atk >= stats.spa;
  const offense = physical ? stats.atk : stats.spa;
  const defensive = Math.max(stats.defense, stats.spd);
  const isFast = stats.spe >= 90 || stats.spe >= defensive;
  const wall = stats.defense >= stats.spd
    ? preset('physical-wall', 'Physical wall', `Def ${stats.defense} is its stronger defense`, PHYSICAL_WALL)
    : preset('special-wall', 'Special wall', `SpD ${stats.spd} is its stronger defense`, SPECIAL_WALL);
  const main = defensive > offense + 10
    ? wall
    : physical
      ? preset(isFast ? 'fast-physical' : 'bulky-physical', isFast ? 'Fast physical' : 'Bulky physical', `Atk ${stats.atk} · Spe ${stats.spe}`, isFast ? PHYSICAL_FAST : PHYSICAL_BULKY)
      : preset(isFast ? 'fast-special' : 'bulky-special', isFast ? 'Fast special' : 'Bulky special', `SpA ${stats.spa} · Spe ${stats.spe}`, isFast ? SPECIAL_FAST : SPECIAL_BULKY);
  const fast = physical
    ? preset('fast-physical', 'Fast physical', `Atk ${stats.atk} · Spe ${stats.spe}`, PHYSICAL_FAST)
    : preset('fast-special', 'Fast special', `SpA ${stats.spa} · Spe ${stats.spe}`, SPECIAL_FAST);
  const bulky = physical
    ? preset('bulky-physical', 'Bulky physical', `HP ${stats.hp} · Atk ${stats.atk}`, PHYSICAL_BULKY)
    : preset('bulky-special', 'Bulky special', `HP ${stats.hp} · SpA ${stats.spa}`, SPECIAL_BULKY);
  const choices = [main, wall, main.id === fast.id ? bulky : fast, bulky].filter(
    (entry, index, all) => all.findIndex((other) => other.id === entry.id) === index
  ).slice(0, 3);
  return choices.map((entry, index) => ({ ...entry, recommended: index === 0 }));
}

const TYPE_COLORS: Record<string, string> = {
  normal: '#A8A878', fire: '#F08030', water: '#6890F0', electric: '#F8D030',
  grass: '#78C850', ice: '#98D8D8', fighting: '#C03028', poison: '#A040A0',
  ground: '#E0C068', flying: '#A890F0', psychic: '#F85888', bug: '#A8B820',
  rock: '#B8A038', ghost: '#705898', dragon: '#7038F8', dark: '#705848',
  steel: '#B8B8D0', fairy: '#EE99AC'
};

export function draftRollFrames(
  generation: number,
  type: string,
  mode: DraftRollMode
): { generations: number[]; types: string[] } {
  const spin = DRAFT_REEL_FRAMES - 1;
  const generations = Array.from({ length: spin }, (_, index) => ((generation + index + 2) % 9) + 1);
  generations.push(generation);
  const types = Object.keys(TYPE_COLORS);
  const targetIndex = Math.max(0, types.indexOf(type.toLowerCase()));
  const typeFrames = Array.from(
    { length: spin },
    (_, index) => types[(targetIndex + index * 5 + 3) % types.length]
  );
  typeFrames.push(type.toLowerCase());
  const generationSpins = mode === 'both' || mode === 'generation';
  const typeSpins = mode === 'both' || mode === 'type';
  return {
    generations: generationSpins ? generations : [generation],
    types: typeSpins ? typeFrames : [type.toLowerCase()]
  };
}

const DIFFICULTY_LABELS: Record<string, string> = {
  normal: 'Normal',
  hard: 'Hard · opponent +5 levels',
  expert: 'Expert · opponent +10 levels',
  nightmare: 'Nightmare · opponent +15 levels'
};

// Difficulty only ever raises the opponent above the campaign's own level curve; the
// player always follows that curve, so their own levelling and evolution are never undone.
export const DIFFICULTY_LEVEL_MODIFIERS: Record<string, number> = {
  normal: 0,
  hard: 5,
  expert: 10,
  nightmare: 15
};

export function difficultyLabel(difficulty: string | undefined): string {
  return DIFFICULTY_LABELS[difficulty || 'normal'] || 'Normal';
}

export function opponentStageLevel(stageLevel: number, difficulty: string | undefined): number {
  const modifier = DIFFICULTY_LEVEL_MODIFIERS[difficulty || 'normal'] ?? 0;
  return Math.max(1, Math.min(100, stageLevel + modifier));
}

export function pokemonTypeColor(type: string): string {
  return TYPE_COLORS[type.toLowerCase()] || '#7f8c9a';
}

/**
 * Readable ink for text sitting on `background`.
 *
 * The canonical type colours are recognisable and must not change, but several of
 * them are far too light for white text: white on Grass or Normal measures about
 * 1.45:1, well under the 4.5:1 WCAG AA needs at badge size. Choosing the ink per
 * background keeps the type colour and makes the label legible.
 */
export function readableInk(background: string): string {
  const hex = background.replace('#', '').trim();
  const full = hex.length === 3 ? hex.split('').map((part) => part + part).join('') : hex;
  if (full.length !== 6) return '#ffffff';
  const channels = [0, 2, 4].map((offset) => {
    const value = Number.parseInt(full.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  // Contrast against black is (L+0.05)/0.05; against white 1.05/(L+0.05). They cross
  // at L ≈ 0.179, so this picks whichever side actually has more headroom. Pure black
  // rather than a near-black: the mid-luminance types (Dark, Dragon) have so little
  // headroom that even #101614 leaves them just under 4.5:1.
  return luminance > 0.179 ? '#000000' : '#ffffff';
}

export function legalEvValue(
  allocations: Record<string, EvSpread>,
  entryId: string,
  stat: EvStat,
  requested: number,
  limits: EvLimits
): number {
  const spread = allocations[entryId] || emptyEvSpread();
  const pokemonWithoutCurrent = evSpreadTotal(spread) - Number(spread[stat] || 0);
  const ceiling = Math.max(
    0,
    Math.min(limits.stat, limits.pokemon - pokemonWithoutCurrent)
  );
  return Math.min(ceiling, Math.max(0, Math.floor(Number(requested) || 0)));
}

export function challengeStatusLabel(status: ChallengeStatus): string {
  const labels: Record<ChallengeStatus, string> = {
    drafting: 'Draft in progress',
    preparing: 'Preparing team',
    training: 'EV review',
    team_review: 'Team review',
    ready: 'Ready for the first stage',
    battle_queued: 'Battle queued',
    battling: 'Battle in progress',
    stage_result: 'Stage result',
    mega_selection: 'Mega unlocked',
    completed: 'Draft run complete',
    failed: 'Draft run failed',
    cancelled: 'Draft run cancelled',
    abandoned: 'Draft run retired'
  };
  return labels[status];
}

export function challengeErrorMessage(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes('stale challenge revision') || normalized.includes('draft offer is stale')) {
    return 'This Draft run changed in another tab or while the request was running. The latest saved state has been restored.';
  }
  if (normalized.includes('draft controller changed')) {
    return 'The draft was taken over manually before that AI decision finished. The late AI response was ignored.';
  }
  if (normalized.includes('no generation+type') || normalized.includes('cannot be completed')) {
    return 'The roster cannot be completed from the remaining unseen species. Start a new run with a larger or broader draft pool.';
  }
  if (normalized.includes('showdown rejected the team')) {
    return 'Showdown found problems in the team. Fix the listed set details and validate again.';
  }
  if (normalized.includes('final team evs')) {
    return 'The EVs in the Showdown export do not match Training Camp. Copy the saved allocation exactly, then validate again.';
  }
  if (normalized.includes('species/forms do not exactly match')) {
    return 'The final team must contain each drafted Pokémon form exactly once.';
  }
  if (normalized.includes('ability selections must exactly match')) {
    return 'Choose one legal ability for every drafted Pokémon before locking the team.';
  }
  if (normalized.includes('illegal ability') || normalized.includes('ability does not match')) {
    return 'One selected ability is not legal for that exact Pokémon form and format. Review the ability selectors and try again.';
  }
  if (normalized.includes('decision request not pending')) {
    return 'That turn was already answered or replaced. Refreshing the current battle state…';
  }
  if (normalized.includes('provider') || normalized.includes('agent draft')) {
    return `The AI could not complete this decision. Retry it or take over manually. Details: ${message}`;
  }
  return message;
}

export function formatDuration(seconds: number): string {
  const rounded = Math.max(0, Math.round(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${remainder}s`;
  return `${remainder}s`;
}
