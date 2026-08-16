import type { FormatDescriptor } from './types.ts';

/**
 * Client-side format search. Mirrors the backend catalog's matching rules so the selector
 * filters the same way the API would, without a round trip per keystroke.
 */

/** Community shorthand players actually type. */
const ALIASES: Record<string, string[]> = {
  rby: ['gen1'], gsc: ['gen2'], adv: ['gen3'], rse: ['gen3'], dpp: ['gen4'],
  bw: ['gen5'], b2w2: ['gen5'], xy: ['gen6'], oras: ['gen6'], sm: ['gen7'],
  usum: ['gen7'], swsh: ['gen8'], sv: ['gen9'], rands: ['random'], randbats: ['randombattle']
};

export function expandQuery(query: string): string[] {
  const raw = query.toLowerCase().replace(/[-_]/g, ' ').split(/\s+/).filter(Boolean);
  const tokens: string[] = [];
  for (let index = 0; index < raw.length; index += 1) {
    const word = raw[index].replace(/[^a-z0-9]/g, '');
    if (!word) continue;
    // "gen 1" arrives as two words but means one token.
    if (word === 'gen' && /^\d+$/.test(raw[index + 1] || '')) {
      tokens.push(`gen${raw[index + 1]}`);
      index += 1;
      continue;
    }
    tokens.push(...(ALIASES[word] || [word]));
  }
  return tokens;
}

function indexTokens(format: FormatDescriptor): string[] {
  const words = `${format.display_name} ${format.section}`.toLowerCase().replace(/\//g, ' ');
  return [
    format.id,
    format.id.replace(new RegExp(`^gen${format.generation}`), ''),
    `gen${format.generation}`,
    format.game_type,
    ...words.split(/\s+/).map((word) => word.replace(/[^a-z0-9]/g, ''))
  ].filter(Boolean);
}

/** Every query token must prefix an indexed word, so "ou" never matches "doubles". */
export function searchFormats(formats: FormatDescriptor[], query: string): FormatDescriptor[] {
  const tokens = expandQuery(query);
  if (!tokens.length) return formats;
  return formats.filter((format) => {
    const indexed = indexTokens(format);
    return tokens.every((token) => indexed.some((word) => word.startsWith(token)));
  });
}

export function formatSummary(format: FormatDescriptor): string {
  const team = format.custom_team_required ? 'CUSTOM TEAM' : 'RANDOM TEAMS';
  return `GEN ${format.generation} · ${team} · ${format.game_type.toUpperCase()}`;
}
