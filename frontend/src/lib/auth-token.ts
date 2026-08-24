/**
 * Operator API token storage, for backends started with `KOALABATTLE_API_TOKEN`.
 *
 * Deliberately kept in localStorage rather than a `PUBLIC_` build variable: the
 * frontend bundle is served to anyone who can reach its port, so a baked-in token
 * would hand the secret to exactly the clients the token exists to keep out. The
 * operator enters it once per browser instead, and an unauthenticated visitor can
 * still load the app shell but cannot mutate anything.
 *
 * This lives apart from `api.ts` so it can be tested without SvelteKit's `$env`
 * module, the same way `errors.ts` does.
 */
const API_TOKEN_STORAGE_KEY = 'koalabattle.api-token';

export function apiToken(): string {
  if (typeof localStorage === 'undefined') return '';
  try {
    return localStorage.getItem(API_TOKEN_STORAGE_KEY)?.trim() || '';
  } catch {
    return '';
  }
}

export function setApiToken(value: string): void {
  if (typeof localStorage === 'undefined') return;
  const token = value.trim();
  try {
    if (token) localStorage.setItem(API_TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(API_TOKEN_STORAGE_KEY);
  } catch {
    /* private-mode browsers simply keep running without a stored token */
  }
}

/** Authorization header for the stored token, or nothing when none is set. */
export function authHeaders(): Record<string, string> {
  const token = apiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Append the operator token to a WebSocket URL. Browsers cannot set headers on a
 * WebSocket handshake, so the backend accepts the token as a query parameter for
 * those routes only.
 */
export function withWebsocketToken(url: string): string {
  const token = apiToken();
  if (!token) return url;
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
}
