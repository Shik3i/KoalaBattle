/**
 * Fullscreen helpers for the battle surfaces.
 *
 * Kept apart from any component so the arena, the battle view and the overlay can
 * share one behavior, and so the browser-quirk handling lives in a single place:
 * Safari still only exposes the webkit-prefixed API, and `requestFullscreen`
 * rejects rather than throwing when the gesture is not user-initiated.
 */
type FullscreenElement = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void> | void;
};

type FullscreenDocument = Document & {
  webkitFullscreenElement?: Element | null;
  webkitExitFullscreen?: () => Promise<void> | void;
};

export function fullscreenSupported(): boolean {
  if (typeof document === 'undefined') return false;
  const target = document.documentElement as FullscreenElement;
  return Boolean(target.requestFullscreen || target.webkitRequestFullscreen);
}

export function fullscreenElement(): Element | null {
  if (typeof document === 'undefined') return null;
  const target = document as FullscreenDocument;
  return document.fullscreenElement ?? target.webkitFullscreenElement ?? null;
}

export function isFullscreen(element?: HTMLElement | null): boolean {
  const current = fullscreenElement();
  if (!current) return false;
  return element ? current === element : true;
}

/** Enter fullscreen on `element`, or leave it when it is already showing. */
export async function toggleFullscreen(element: HTMLElement | null): Promise<boolean> {
  if (!element || typeof document === 'undefined') return false;
  const target = document as FullscreenDocument;
  try {
    if (fullscreenElement()) {
      await (document.exitFullscreen?.() ?? target.webkitExitFullscreen?.());
      return false;
    }
    const node = element as FullscreenElement;
    await (node.requestFullscreen?.() ?? node.webkitRequestFullscreen?.());
    return true;
  } catch {
    // Denied by the browser (no user gesture, or disallowed in an iframe). The
    // caller keeps its previous state rather than showing a half-applied mode.
    return isFullscreen(element);
  }
}

/** Subscribe to fullscreen changes; returns an unsubscribe function. */
export function onFullscreenChange(listener: () => void): () => void {
  if (typeof document === 'undefined') return () => {};
  document.addEventListener('fullscreenchange', listener);
  document.addEventListener('webkitfullscreenchange', listener);
  return () => {
    document.removeEventListener('fullscreenchange', listener);
    document.removeEventListener('webkitfullscreenchange', listener);
  };
}
