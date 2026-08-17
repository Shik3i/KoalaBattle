import type { RendererConfig } from '../presentation/types.ts';
import type {
  BrandAsset,
  FontFamilyId,
  ParticipantBranding,
  ProductionStyle,
  Side
} from '../types.ts';

/**
 * Font stacks the renderer is allowed to use.
 *
 * These are local families only. Fetching a webfont at render time would make an export
 * depend on the network, and shipping font files would mean redistributing typefaces this
 * project has no licence to. A user who needs an exact typeface uploads it as a font
 * asset; see `docs/ASSETS.md` for the licensing responsibility that carries.
 */
export const FONT_STACKS: Record<Exclude<FontFamilyId, 'custom'>, string> = {
  system: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  geometric: '"Avenir Next", "Century Gothic", Futura, "Trebuchet MS", system-ui, sans-serif',
  grotesk: '"Helvetica Neue", Helvetica, Arial, system-ui, sans-serif',
  serif: '"Iowan Old Style", Georgia, "Times New Roman", serif',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  // No pixel typeface is bundled, so Retro leans on a blocky monospace stack. Uploading a
  // real pixel font as a display asset replaces this without any code change.
  pixel: 'Monaco, "Andale Mono", "Courier New", ui-monospace, monospace'
};

export const P1_FALLBACK = '#6fffa8';
export const P2_FALLBACK = '#e36fff';

/** Neutral generated marks. KoalaBattle bundles no third-party logo files. */
export const MARK_LABELS: Record<string, string> = {
  gpt: 'GPT',
  gemini: 'GEMINI',
  claude: 'CLAUDE',
  deepseek: 'DEEPSEEK',
  local: 'LOCAL',
  manual: 'MANUAL',
  random: 'RANDOM',
  koala: 'KOALA'
};

/**
 * The Koala Broadcast defaults, mirroring `koalabattle.production.style_presets`.
 *
 * The API always sends a style, so this is a safety net for a stale cached response or a
 * hand-constructed timeline — not a second source of truth to edit presets in.
 */
export function defaultProductionStyle(): ProductionStyle {
  return {
    schema_version: '1.0',
    id: 'koala-broadcast',
    display_name: 'Koala Broadcast',
    version: '1.0',
    builtin: true,
    title: null,
    show_format: true,
    show_generation: true,
    show_koala_branding: true,
    stage: {
      background: {
        kind: 'arena', color: '#0b1f24', secondary_color: '#06090f', asset_id: null,
        fit: 'cover', position: 'center', brightness: 1, contrast: 1, blur: 0,
        overlay_opacity: 0, vignette: 0.35
      },
      arena: 'grid', floor_visible: true, ground_shadow: true, stage_lighting: 0.6,
      ambient_intensity: 0.6, background_motion: true, accent: '#7dffae'
    },
    hud: {
      preset: 'broadcast', hp_shape: 'slash', hp_thickness: 31, damage_ghost: true,
      show_hp_percent: true, show_hp_exact: true, show_level: false, show_types: true,
      show_status: true, show_player_name: true, show_provider: true, show_logo: true,
      show_player_slot: false, team_indicators: 'full', show_turn: true, show_weather: true
    },
    typography: {
      display: 'system', body: 'system', mono: 'mono', display_asset_id: null,
      body_asset_id: null, scale: 1, display_weight: 950, letter_spacing: 0,
      uppercase: true, outline: false, shadow: true
    },
    move: { layout: 'banner', show_type: true, show_archetype: true, duration_scale: 1 },
    damage: {
      show_damage: true, show_healing: true, show_effectiveness: true, show_critical: true,
      show_miss: true, show_immune: true, intensity: 'standard'
    },
    commentary: {
      layout: 'fighter-card', show_agent_name: true, show_logo: true, show_label: true,
      animation: 'fade'
    },
    caption: {
      preset: 'broadcast', show_speaker: false, background_opacity: 0.88, outline: false,
      size_scale: 1, position: 'bottom'
    },
    effect: {
      intensity: 'standard', camera: 'subtle', idle_motion: 'full', pacing: 'standard',
      impact_flash: true, trails: true
    },
    intro: {
      enabled: true, length: 'standard', show_player_logos: true, show_player_names: true,
      show_format: true, show_generation: true, show_game_number: false,
      show_series_score: false, show_tournament_round: false
    },
    result: {
      enabled: true, show_winner: true, show_logos: true, show_final_score: false,
      show_format: true, show_series: false, duration_ms: 3600
    },
    watermark: {
      enabled: false, asset_id: null, text: null, position: 'bottom-right',
      opacity: 0.55, size: 1
    },
    players: {},
    series: {
      tournament_name: null, round_name: null, game_number: null, best_of: null,
      score_p1: null, score_p2: null
    }
  };
}

export function assetUrl(apiBase: string, assetId: string | null | undefined): string | null {
  return assetId ? `${apiBase}/api/branding/assets/${assetId}/media` : null;
}

export function fontFamily(
  style: ProductionStyle,
  role: 'display' | 'body' | 'mono'
): string {
  const typography = style.typography;
  const custom = role === 'display' ? typography.display_asset_id : role === 'body' ? typography.body_asset_id : null;
  const stack = FONT_STACKS[(typography[role] === 'custom' ? 'system' : typography[role]) as Exclude<FontFamilyId, 'custom'>];
  // A missing custom font must fall back visibly-but-sanely rather than silently
  // rendering one face in the preview and another in the export.
  return custom ? `"${customFontName(custom)}", ${stack}` : stack;
}

export function customFontName(assetId: string): string {
  return `kb-font-${assetId}`;
}

const registered = new Map<string, Promise<boolean>>();

/**
 * Register every custom font this style needs and wait for it.
 *
 * Called before the first frame is composited so a font can never load half way through a
 * render, which would make an export non-deterministic.
 */
export async function ensureStyleFonts(style: ProductionStyle, apiBase: string): Promise<string[]> {
  const wanted = [style.typography.display_asset_id, style.typography.body_asset_id].filter(
    (value): value is string => Boolean(value)
  );
  const results = await Promise.all(wanted.map((assetId) => loadFont(assetId, apiBase)));
  return wanted.filter((_, index) => !results[index]);
}

async function loadFont(assetId: string, apiBase: string): Promise<boolean> {
  const key = `${apiBase}|${assetId}`;
  let pending = registered.get(key);
  if (!pending) {
    pending = (async () => {
      if (typeof FontFace !== 'function' || typeof document === 'undefined') return false;
      try {
        const face = new FontFace(customFontName(assetId), `url(${assetUrl(apiBase, assetId)})`);
        await face.load();
        document.fonts.add(face);
        return true;
      } catch {
        return false;
      }
    })();
    registered.set(key, pending);
  }
  return pending;
}

export function brandingFor(style: ProductionStyle, side: Side): ParticipantBranding {
  return (
    style.players[side] || {
      display_name: null,
      short_name: null,
      logo_asset_id: null,
      logo_mark: null,
      accent: null,
      secondary_accent: null
    }
  );
}

export function accentFor(style: ProductionStyle, side: Side): string {
  return brandingFor(style, side).accent || (side === 'p1' ? P1_FALLBACK : P2_FALLBACK);
}

/** `Gen 9 · Random Battle`, never the raw `gen9randombattle` id. */
export function formatDisplayName(formatId: string, showGeneration = true): string {
  const normalized = formatId.toLowerCase().replaceAll('_', '').replaceAll('-', '');
  const parsed = normalized.match(/^gen(\d+)(.+)$/);
  if (!parsed) return titleCase(formatId.replaceAll('_', ' ').replaceAll('-', ' '));
  const tiers: Record<string, string> = {
    randombattle: 'Random Battle',
    randomdoublesbattle: 'Random Doubles',
    ou: 'OU',
    uu: 'UU',
    ru: 'RU',
    nu: 'NU',
    pu: 'PU',
    lc: 'LC',
    ubers: 'Ubers',
    monotype: 'Monotype',
    doublesou: 'Doubles OU',
    vgc2024: 'VGC 2024'
  };
  const tier = tiers[parsed[2]] || titleCase(parsed[2]);
  return showGeneration ? `Gen ${parsed[1]} · ${tier}` : tier;
}

export function generationOf(formatId: string): number {
  const parsed = formatId.toLowerCase().match(/^gen(\d)/);
  return parsed ? Number(parsed[1]) : 9;
}

function titleCase(value: string): string {
  return value.replace(/\b[a-z]/g, (character) => character.toUpperCase());
}

/** How much a style's motion settings scale visual intensity. */
export function intensityScale(value: string): number {
  return { off: 0, minimal: 0.4, standard: 1, dramatic: 1.45 }[value] ?? 1;
}

export function idleScale(value: string): number {
  return { off: 0, subtle: 0.45, full: 1 }[value] ?? 1;
}

export function cameraScale(value: string): number {
  return { static: 0, subtle: 1, dynamic: 1.9 }[value] ?? 1;
}

export function assetById(assets: BrandAsset[], id: string | null): BrandAsset | null {
  return id ? assets.find((asset) => asset.id === id) || null : null;
}

/**
 * Project a ProductionStyle onto the live DOM renderer's settings.
 *
 * There is one style model, not one per surface. The offline compositor consumes the
 * whole style; the live `/watch` and `/overlay` surfaces are a DOM renderer with a
 * smaller vocabulary, so the style is *mapped* here rather than reimplemented. Anything
 * the DOM renderer cannot express is simply not applied — it is never approximated with
 * a second set of settings.
 */
export function styleToRendererConfig(
  style: ProductionStyle,
  base: RendererConfig
): RendererConfig {
  const effects =
    style.effect.intensity === 'off'
      ? 'off'
      : style.effect.intensity === 'minimal'
        ? 'low'
        : style.effect.intensity === 'dramatic'
          ? 'high'
          : 'standard';
  return {
    ...base,
    effects,
    reducedMotion: style.effect.idle_motion === 'off' || style.effect.camera === 'static',
    showDamageNumbers: style.damage.show_damage,
    showTurn: style.hud.show_turn,
    commentaryMode: style.commentary.layout === 'off' ? 'hidden' : base.commentaryMode
  };
}
