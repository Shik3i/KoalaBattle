import type { ChallengeStatus, EvSpread } from './types.ts';

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
  global: number;
  pokemon: number;
  stat: number;
}

export function legalEvValue(
  allocations: Record<string, EvSpread>,
  entryId: string,
  stat: EvStat,
  requested: number,
  limits: EvLimits
): number {
  const spread = allocations[entryId] || emptyEvSpread();
  const withoutCurrent = evAllocationTotal(allocations) - Number(spread[stat] || 0);
  const pokemonWithoutCurrent = evSpreadTotal(spread) - Number(spread[stat] || 0);
  const ceiling = Math.max(
    0,
    Math.min(limits.stat, limits.pokemon - pokemonWithoutCurrent, limits.global - withoutCurrent)
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
    return 'The roster cannot be completed with the current pool and Draft Credits. Start again with a larger budget or broader pricing coverage.';
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
  if (normalized.includes('decision request not pending')) {
    return 'That turn was already answered or replaced. Refreshing the current battle state…';
  }
  if (normalized.includes('pricing catalog changed')) {
    return 'Draft pricing changed while setup was open. Review the current catalog before starting.';
  }
  if (normalized.includes('draft pricing is unavailable')) {
    return 'Draft pricing is not configured. Import and verify a local Draft Board copy before creating a Challenge.';
  }
  if (normalized.includes('draft pricing verification failed') || normalized.includes('catalog hash mismatch')) {
    return 'Draft pricing failed its integrity check. Re-import the local Draft Board, then run the verify command before creating a Challenge.';
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
