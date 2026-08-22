import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter(),
    // Notice a redeploy while a tab is open and fall back to a full page navigation, so
    // the client never tries to fetch chunks from a build that no longer exists.
    version: { pollInterval: 60_000 }
  }
};
