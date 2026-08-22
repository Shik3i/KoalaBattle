import type { HandleClientError } from '@sveltejs/kit';

/**
 * Recover a tab that outlived a deployment.
 *
 * A rebuilt frontend gets new content-hashed chunk names, so a page still running the old
 * bundle asks for files that no longer exist. SvelteKit surfaces that as "Failed to fetch
 * dynamically imported module" and the app looks completely broken — navigation dies and
 * the stale page keeps talking to an API it no longer matches. Reloading once picks up the
 * current build. The flag stops a genuinely offline browser from reloading in a loop.
 */
const RELOAD_FLAG = 'koalabattle:stale-bundle-reload';

export const handleError: HandleClientError = ({ error }) => {
  const message = error instanceof Error ? error.message : String(error);
  const staleBundle =
    message.includes('dynamically imported module') ||
    message.includes('Importing a module script failed');
  if (staleBundle && typeof sessionStorage !== 'undefined') {
    if (!sessionStorage.getItem(RELOAD_FLAG)) {
      sessionStorage.setItem(RELOAD_FLAG, '1');
      location.reload();
      return { message: 'Loading the latest version…' };
    }
    return { message: 'This page is out of date. Reload to get the latest version.' };
  }
  return { message };
};

if (typeof sessionStorage !== 'undefined') {
  // A load that got this far is running the current bundle, so arm the guard again.
  sessionStorage.removeItem(RELOAD_FLAG);
}
