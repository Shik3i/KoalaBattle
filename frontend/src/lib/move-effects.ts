import type { MoveEffectSkin, MoveVisualArchetype, PokemonType } from './presentation/types.ts';
export type MoveEffectFamily =
  | 'contact' | 'projectile' | 'beam' | 'fire' | 'water' | 'lightning' | 'ice'
  | 'psychic' | 'shadow' | 'quake' | 'rock' | 'poison' | 'leaf' | 'heal'
  | 'barrier' | 'dance' | 'explosion' | 'wind' | 'status';

export interface MoveEffectRecipe {
  id: string;
  family: MoveEffectFamily;
  durationMs: number;
  impactProgress: number;
  assetId: string | null;
  color: string;
  secondary: string;
}

const COLORS: Record<PokemonType, string> = {
  normal: '#d9d7ca', fire: '#ff633f', water: '#3cc8ff', electric: '#ffe148', grass: '#79f05d',
  ice: '#82f4f1', fighting: '#ff714f', poison: '#de64e8', ground: '#e3a44d', flying: '#8ec7ff',
  psychic: '#ff5bac', bug: '#b9e744', rock: '#cfb56f', ghost: '#a17cff', dragon: '#766dff',
  dark: '#8a7772', steel: '#b5cbd6', fairy: '#ff96d2'
};

const FAMILY_ASSET: Partial<Record<MoveEffectFamily, string>> = {
  projectile: 'energyball', fire: 'fireball', water: 'waterwisp', psychic: 'mistball',
  shadow: 'shadowball', poison: 'poisonwisp', leaf: 'leaf1', contact: 'impact'
};

const GROUPS: Array<[MoveEffectFamily, string[]]> = [
  ['quake', ['earthquake', 'earthpower', 'magnitude', 'bulldoze', 'fissure', 'landswrath', 'precipiceblades', 'stompingtantrum']],
  ['fire', ['ember', 'flamethrower', 'fireblast', 'heatwave', 'overheat', 'eruption', 'burnup', 'inferno', 'sacredfire', 'blueflare']],
  ['water', ['watergun', 'hydropump', 'surf', 'muddywater', 'bubblebeam', 'scald', 'waterspout', 'aquajet', 'liquidation', 'wavecrash']],
  ['lightning', ['thundershock', 'thunderbolt', 'thunder', 'discharge', 'voltswitch', 'wildcharge', 'electroweb', 'zapcannon', 'paraboliccharge']],
  ['ice', ['icebeam', 'blizzard', 'freezedry', 'iceshard', 'iciclespear', 'iciclecrash', 'avalanche', 'tripleaxel']],
  ['psychic', ['psychic', 'confusion', 'psybeam', 'psyshock', 'storedpower', 'expandingforce', 'future sight', 'futuresight']],
  ['shadow', ['shadowball', 'shadowclaw', 'shadowpunch', 'phantomforce', 'hex', 'nightshade', 'poltergeist']],
  ['beam', ['solarbeam', 'hyperbeam', 'aurorabeam', 'signalbeam', 'flashcannon', 'dragonpulse', 'darkpulse', 'focusblast', 'moongeistbeam']],
  ['rock', ['rockthrow', 'rockslide', 'stoneedge', 'stealthrock', 'powergem', 'rockblast', 'meteorbeam', 'diamondstorm']],
  ['poison', ['toxic', 'sludge', 'sludgebomb', 'sludgewave', 'gunkshot', 'poisonjab', 'venoshock', 'toxicspikes']],
  ['leaf', ['razorleaf', 'leafblade', 'leafstorm', 'magicalleaf', 'seedbomb', 'energyball', 'petalblizzard', 'powerwhip']],
  ['heal', ['recover', 'roost', 'softboiled', 'milkdrink', 'synthesis', 'moonlight', 'morningsun', 'healorder', 'slackoff', 'lifedew']],
  ['barrier', ['protect', 'detect', 'kingsshield', 'spikyshield', 'banefulbunker', 'wideguard', 'quickguard', 'substitute', 'reflect', 'lightscreen']],
  ['dance', ['swordsdance', 'dragondance', 'quiverdance', 'victorydance', 'nastyplot', 'calmmind', 'bulkup', 'shellsmash', 'agility']],
  ['explosion', ['explosion', 'selfdestruct', 'mistyexplosion', 'mindblown', 'chloroblast']],
  ['wind', ['gust', 'hurricane', 'airslash', 'aircutter', 'twister', 'whirlwind', 'razorwind', 'bleakwindstorm']],
  ['contact', ['tackle', 'scratch', 'slash', 'cut', 'quickattack', 'extremespeed', 'closecombat', 'brickbreak', 'megakick', 'megapunch', 'headbutt', 'bodyslam', 'doubleedge', 'knockoff', 'playrough', 'uturn']]
];

const MOVE_FAMILIES = new Map<string, MoveEffectFamily>(
  GROUPS.flatMap(([family, moves]) => moves.map((move) => [normalizeMoveId(move), family] as const))
);

export function normalizeMoveId(value: string): string {
  return value.normalize('NFKD').toLowerCase().replace(/[^a-z0-9]/g, '');
}

export function resolveMoveEffect(
  moveName: string,
  type: PokemonType,
  archetype: MoveVisualArchetype | null,
  skin: MoveEffectSkin = 'broadcast'
): MoveEffectRecipe {
  const id = normalizeMoveId(moveName) || 'unknownmove';
  const family = MOVE_FAMILIES.get(id) || defaultFamily(type, archetype);
  const assetId = skin === 'procedural' ? null : FAMILY_ASSET[family] || null;
  return {
    id,
    family,
    durationMs: family === 'quake' || family === 'explosion' ? 920 : family === 'dance' || family === 'heal' ? 820 : 680,
    impactProgress: family === 'beam' || family === 'lightning' ? .68 : family === 'barrier' || family === 'dance' ? .5 : .72,
    assetId,
    color: COLORS[type] || COLORS.normal,
    secondary: skin === 'retro' ? '#ffffff' : mixHex(COLORS[type] || COLORS.normal, '#ffffff', .42)
  };
}

export function moveEffectAssetUrl(assetId: string, base = ''): string {
  return `${base.replace(/\/$/, '')}/api/assets/effects/${encodeURIComponent(assetId)}`;
}

function defaultFamily(type: PokemonType, archetype: MoveVisualArchetype | null): MoveEffectFamily {
  if (archetype === 'status') return 'status';
  if (archetype === 'physical') return 'contact';
  return ({ fire: 'fire', water: 'water', electric: 'lightning', ice: 'ice', psychic: 'psychic',
    ghost: 'shadow', ground: 'quake', rock: 'rock', poison: 'poison', grass: 'leaf', flying: 'wind'
  } as Partial<Record<PokemonType, MoveEffectFamily>>)[type] || 'projectile';
}

function mixHex(a: string, b: string, amount: number): string {
  const channel = (offset: number) => Math.round(parseInt(a.slice(offset, offset + 2), 16) * (1 - amount) + parseInt(b.slice(offset, offset + 2), 16) * amount).toString(16).padStart(2, '0');
  return `#${channel(1)}${channel(3)}${channel(5)}`;
}
