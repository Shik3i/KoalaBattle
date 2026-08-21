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
    training: 'Training Camp',
    team_review: 'Team review',
    ready: 'Ready for the first stage',
    battle_queued: 'Battle queued',
    battling: 'Battle in progress',
    stage_result: 'Stage result',
    completed: 'Challenge complete',
    failed: 'Challenge failed',
    cancelled: 'Challenge cancelled',
    abandoned: 'Challenge abandoned'
  };
  return labels[status];
}

export function challengeErrorMessage(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes('stale challenge revision') || normalized.includes('draft offer is stale')) {
    return 'This Challenge changed in another tab or while the request was running. The latest saved state has been restored.';
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
