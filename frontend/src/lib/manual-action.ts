import type { BattleAction } from './types.ts';

export interface ActionPreview {
  impact: string;
  tempo: string;
}

export function actionPreview(action: BattleAction): ActionPreview {
  if (action.type === 'switch') {
    const hp = action.hp_fraction == null ? 'HP unknown' : `${Math.round(action.hp_fraction * 100)}% HP`;
    return { impact: hp, tempo: action.status ? `Status: ${action.status.toUpperCase()}` : 'Clean switch-in' };
  }
  const power = action.power ?? 0;
  const impact = power <= 0
    ? 'Status / utility'
    : power < 60
      ? `Light hit · ${power} BP`
      : power < 90
        ? `Solid hit · ${power} BP`
        : power < 120
          ? `Heavy hit · ${power} BP`
          : `Finisher power · ${power} BP`;
  const priority = action.priority ?? 0;
  const tempo = priority > 0
    ? `Acts early · priority +${priority}`
    : priority < 0
      ? `Acts late · priority ${priority}`
      : 'Normal priority · Speed decides';
  return { impact, tempo };
}

export function shortcutFor(index: number): string | null {
  return index >= 0 && index < 9 ? String(index + 1) : null;
}

export function actionIndexForKey(key: string): number | null {
  return /^[1-9]$/.test(key) ? Number(key) - 1 : null;
}
