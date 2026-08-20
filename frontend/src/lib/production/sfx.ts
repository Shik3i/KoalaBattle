/** Semantic sample ids installed by scripts/setup_sfx.py. */
export const SFX_VARIANTS: Readonly<Record<string, readonly string[]>> = {
  action: ['action-01', 'action-02'],
  impact: ['impact-01', 'impact-02', 'impact-03'],
  critical: ['critical-01', 'critical-02'],
  heal: ['heal-01', 'heal-02'],
  miss: ['miss-01', 'miss-02'],
  result: ['result-01', 'result-02'],
  'result-sting': ['result-sting-01', 'result-sting-02'],
  switch: ['switch-01', 'switch-02'],
  faint: ['faint-01', 'faint-02'],
  status: ['status-01', 'status-02'],
  field: ['field-01', 'field-02']
};

/** Stable variant choice for live playback and deterministic exports. */
export function sfxVariantFor(kind: string, seed = ''): string | null {
  const variants = SFX_VARIANTS[kind];
  if (!variants?.length) return null;
  let hash = 2_166_136_261;
  for (const character of `${kind}:${seed}`) {
    hash ^= character.codePointAt(0) || 0;
    hash = Math.imul(hash, 16_777_619);
  }
  return variants[(hash >>> 0) % variants.length];
}
