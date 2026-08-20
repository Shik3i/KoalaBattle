export interface StingNote {
  frequency: number;
  offset: number;
  duration: number;
  type: OscillatorType;
  gain: number;
  glideTo?: number;
}

/**
 * Original, code-generated broadcast stings. No third-party recording or game audio is used.
 * Keeping the score declarative makes it deterministic, testable and safe for MIT releases.
 */
export function stingRecipeFor(kind: string): readonly StingNote[] | null {
  if (kind === 'final-pokemon-sting') {
    return [
      { frequency: 110, glideTo: 82, offset: 0, duration: 0.55, type: 'sawtooth', gain: 0.075 },
      { frequency: 440, offset: 0.08, duration: 0.16, type: 'square', gain: 0.045 },
      { frequency: 554.37, offset: 0.27, duration: 0.18, type: 'square', gain: 0.05 },
      { frequency: 659.25, offset: 0.48, duration: 0.42, type: 'triangle', gain: 0.065 }
    ];
  }
  if (kind === 'result-sting') {
    return [
      { frequency: 196, offset: 0, duration: 0.52, type: 'triangle', gain: 0.045 },
      { frequency: 392, offset: 0, duration: 0.24, type: 'triangle', gain: 0.06 },
      { frequency: 493.88, offset: 0.12, duration: 0.28, type: 'triangle', gain: 0.065 },
      { frequency: 587.33, offset: 0.25, duration: 0.34, type: 'triangle', gain: 0.07 },
      { frequency: 783.99, offset: 0.42, duration: 0.7, type: 'sine', gain: 0.08 },
      { frequency: 987.77, offset: 0.5, duration: 0.6, type: 'sine', gain: 0.04 }
    ];
  }
  return null;
}
