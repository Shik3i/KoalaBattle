/**
 * Readable labels for Showdown format ids.
 *
 * Stored matches only carry the id — `gen9koalabattlecanonicalnatdexdraft` — and match
 * cards and summaries printed it verbatim. The catalog endpoint knows the real display
 * name, but a list of a hundred cards should not need a round trip per row, so the label
 * is derived locally from the id itself.
 *
 * Showdown ids are lowercased with every separator stripped, so recovering words means
 * matching known vocabulary. Greedy longest-match: `natdexdraft` has to resolve as
 * "NatDex" + "Draft", never as "Nat" + "Dex" + "Draft".
 */

/** Longest first, so a longer term always wins over a prefix of itself. */
const TERMS: Array<[string, string]> = ([
  ['koalabattle', 'KoalaBattle'],
  ['anythinggoes', 'Anything Goes'],
  ['nationaldex', 'National Dex'],
  ['randombattle', 'Random Battle'],
  ['balancedhackmons', 'Balanced Hackmons'],
  ['littlecup', 'Little Cup'],
  ['multirandombattle', 'Multi Random Battle'],
  ['freeforall', 'Free-For-All'],
  ['challengecup', 'Challenge Cup'],
  ['computergenerated', 'Computer-Generated'],
  ['canonical', 'Canonical'],
  ['doubles', 'Doubles'],
  ['singles', 'Singles'],
  ['triples', 'Triples'],
  ['natdex', 'NatDex'],
  ['random', 'Random'],
  ['battle', 'Battle'],
  ['monotype', 'Monotype'],
  ['draft', 'Draft'],
  ['ubers', 'Ubers'],
  ['custom', 'Custom'],
  ['metronome', 'Metronome'],
  ['inheritance', 'Inheritance'],
  ['mixandmega', 'Mix and Mega'],
  ['almostanyability', 'Almost Any Ability'],
  ['stabmons', 'STABmons'],
  ['nfe', 'NFE'],
  ['vgc', 'VGC'],
  ['bss', 'BSS'],
  ['cap', 'CAP'],
  ['ou', 'OU'],
  ['uu', 'UU'],
  ['ru', 'RU'],
  ['nu', 'NU'],
  ['pu', 'PU'],
  ['zu', 'ZU'],
  ['lc', 'LC'],
  ['ag', 'AG'],
  ['1v1', '1v1'],
  ['2v2', '2v2']
] as Array<[string, string]>).sort((left, right) => right[0].length - left[0].length);

/** Splits the part after `genN` into known words, keeping anything it cannot place. */
function words(rest: string): string[] {
  const out: string[] = [];
  let index = 0;
  let unknown = '';
  while (index < rest.length) {
    const hit = TERMS.find(([term]) => rest.startsWith(term, index));
    if (hit) {
      if (unknown) {
        out.push(unknown);
        unknown = '';
      }
      out.push(hit[1]);
      index += hit[0].length;
      continue;
    }
    unknown += rest[index];
    index += 1;
  }
  if (unknown) out.push(unknown);
  return out;
}

/**
 * `gen9koalabattlecanonicalnatdexdraft` → `Gen 9 KoalaBattle Canonical NatDex Draft`.
 * An id that does not start with a generation, or that resolves to nothing readable, is
 * returned unchanged rather than mangled.
 */
export function formatLabel(formatId: string): string {
  const id = (formatId || '').trim();
  if (!id) return '';
  const match = /^gen(\d+)(.*)$/.exec(id.toLowerCase());
  if (!match) return id;
  const [, generation, rest] = match;
  const parts = words(rest);
  if (!parts.length) return `Gen ${generation}`;
  return `Gen ${generation} ${parts.join(' ')}`;
}

/**
 * Just the metagame part, with no generation prefix — for surfaces that already show the
 * generation separately. `gen5doublesou` → `Doubles OU`.
 */
export function formatTier(formatId: string): string {
  const match = /^gen(\d+)(.*)$/.exec((formatId || '').trim().toLowerCase());
  if (!match) return formatId;
  const parts = words(match[2]);
  return parts.length ? parts.join(' ') : `Gen ${match[1]}`;
}

/** Compact variant for dense rows: drops the generation, which is usually shown already. */
export function formatLabelShort(formatId: string): string {
  const full = formatLabel(formatId);
  return full.replace(/^Gen \d+\s*/, '') || full;
}
