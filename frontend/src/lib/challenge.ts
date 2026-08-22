import type { ChallengeStatus, DraftCandidate, EvSpread, PokemonBaseStats } from './types.ts';

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
    mega_selection: 'Final power-up',
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
