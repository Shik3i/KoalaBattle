import type { ProductionScene, ProductionSceneSide } from './scene.ts';

export interface Box { x: number; y: number; width: number; height: number }

/**
 * Where each side's HUD panel sits.
 *
 * The presets differ in composition, not decoration: a broadcast panel, a top-anchored
 * fighting bar, a quiet corner readout, a compact esports strip and a boxed retro plate
 * are genuinely different framings of the same information.
 *
 * Kept out of the compositor so it can be unit-tested — the compositor's constructor
 * parameter properties are not loadable by Node's type-stripping test runner.
 */
export function hudLayout(
  preset: string,
  vertical: boolean,
  width: number,
  height: number,
  scale: number
): Record<'p1' | 'p2', Box> {
  if (vertical) {
    const inset = 46 * scale;
    const panelWidth = width - inset * 2;
    const panelHeight = (preset === 'minimal' ? 130 : 190) * scale;
    return {
      p2: { x: inset, y: 144 * scale, width: panelWidth, height: panelHeight },
      p1: { x: inset, y: height - 190 * scale - panelHeight, width: panelWidth, height: panelHeight }
    };
  }
  if (preset === 'fighting') {
    const panelWidth = width * .43;
    return {
      p1: { x: 52 * scale, y: 46 * scale, width: panelWidth, height: 168 * scale },
      p2: { x: width - 52 * scale - panelWidth, y: 46 * scale, width: panelWidth, height: 168 * scale }
    };
  }
  if (preset === 'minimal') {
    const panelWidth = 560 * scale;
    return {
      p1: { x: 48 * scale, y: height - 160 * scale, width: panelWidth, height: 116 * scale },
      p2: { x: width - 48 * scale - panelWidth, y: 44 * scale, width: panelWidth, height: 116 * scale }
    };
  }
  if (preset === 'esports') {
    const panelWidth = width * .40;
    return {
      p1: { x: 40 * scale, y: 40 * scale, width: panelWidth, height: 176 * scale },
      p2: { x: width - 40 * scale - panelWidth, y: 40 * scale, width: panelWidth, height: 176 * scale }
    };
  }
  if (preset === 'retro') {
    const panelWidth = 660 * scale;
    return {
      p2: { x: 60 * scale, y: 64 * scale, width: panelWidth, height: 176 * scale },
      p1: { x: width - 60 * scale - panelWidth, y: height - 300 * scale, width: panelWidth, height: 176 * scale }
    };
  }
  return {
    p1: { x: 55 * scale, y: 102 * scale, width: 750 * scale, height: 190 * scale },
    p2: { x: width - 805 * scale, y: 102 * scale, width: 750 * scale, height: 190 * scale }
  };
}

/** The HP readout the style asks for, or an empty string when both toggles are off. */
export function hpReadout(
  side: ProductionSceneSide,
  hud: { show_hp_exact: boolean; show_hp_percent: boolean }
): string {
  const active = side.active;
  const hpFraction = active?.hp_fraction || 0;
  const currentHp = active?.current_hp;
  const maxHp = active?.max_hp;
  const exact = currentHp != null && maxHp && Math.abs(currentHp / maxHp - hpFraction) <= 0.01;
  if (hud.show_hp_exact && exact) return `${currentHp}/${maxHp}`;
  if (hud.show_hp_percent) return `${Math.round(hpFraction * 100)}%`;
  return '';
}

/**
 * The commentary panel's entrance, driven by the cue clock rather than wall time so the
 * same production time always produces the same frame.
 */
export function commentaryMotion(
  scene: ProductionScene,
  scale: number
): { alpha: number; dx: number; dy: number } {
  const animation = scene.style.commentary.animation;
  if (animation === 'none' || !scene.commentary) return { alpha: 1, dx: 0, dy: 0 };
  const durations: Record<string, number> = { fade: 260, slide: 300, punch: 220, minimal: 140 };
  const progress = clamp(scene.commentaryElapsedMs / (durations[animation] || 260));
  if (progress >= 1) return { alpha: 1, dx: 0, dy: 0 };
  const eased = easeOut(progress);
  const fromRight = scene.commentarySide === 'p2';
  if (animation === 'slide') {
    return { alpha: eased, dx: (1 - eased) * (fromRight ? 90 : -90) * scale, dy: 0 };
  }
  if (animation === 'punch') {
    // Overshoot then settle: the panel arrives with weight instead of drifting in.
    const overshoot = Math.sin(progress * Math.PI) * 14 * scale;
    return { alpha: Math.min(1, progress * 2.4), dx: 0, dy: (1 - eased) * 46 * scale - overshoot };
  }
  if (animation === 'minimal') return { alpha: Math.min(1, progress * 1.6), dx: 0, dy: 0 };
  return { alpha: eased, dx: 0, dy: (1 - eased) * 18 * scale };
}

export function channels(hex: string): [number, number, number] {
  const value = hex.replace('#', '');
  const full = value.length === 3 ? value.split('').map((item) => item + item).join('') : value;
  return [
    Number.parseInt(full.slice(0, 2), 16) || 0,
    Number.parseInt(full.slice(2, 4), 16) || 0,
    Number.parseInt(full.slice(4, 6), 16) || 0
  ];
}

export function mix(from: string, to: string, amount: number): string {
  const left = channels(from);
  const right = channels(to);
  const blend = left.map((value, index) => Math.round(value + (right[index] - value) * amount));
  return `rgb(${blend[0]},${blend[1]},${blend[2]})`;
}

export function withAlpha(hex: string, alpha: number): string {
  const [red, green, blue] = channels(hex);
  return `rgba(${red},${green},${blue},${alpha})`;
}

function clamp(value: number): number { return Math.max(0, Math.min(1, value)); }
function easeOut(value: number): number { return 1 - Math.pow(1 - value, 3); }
