/**
 * Turn an API error body into a sentence a person can act on.
 *
 * FastAPI reports its own request-schema failures as a list of `{loc, msg}` objects, while
 * application errors raise a plain string. Interpolating the list gave `[object Object]`, which
 * hid the one thing worth reading — which field was wrong and why.
 *
 * This lives apart from `api.ts` so it can be tested without SvelteKit's `$env` module.
 */
export function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        if (!item || typeof item !== 'object') return '';
        const entry = item as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(entry.loc)
          ? entry.loc.filter((step) => step !== 'body').join('.')
          : '';
        return field && entry.msg ? `${field}: ${entry.msg}` : entry.msg || '';
      })
      .filter(Boolean);
    if (parts.length) return parts.join('; ');
  }
  return `Request failed: ${status}`;
}
