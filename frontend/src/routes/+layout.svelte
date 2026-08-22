<script lang="ts">
  import { beforeNavigate } from '$app/navigation';
  import { page, updated } from '$app/stores';
  import { onMount } from 'svelte';
  import '../app.css';

  let theme: 'light' | 'dark' = 'dark';
  /**
   * Routes that render the battle and nothing else. `/watch` joined this list so the
   * viewer/stream workflow has no navigation, no controls and no page scroll.
   */
  const CLEAN_ROUTES = ['/overlay/', '/render/', '/watch/'];
  $: cleanRoute = CLEAN_ROUTES.some((prefix) => $page.url.pathname.startsWith(prefix));
  /**
   * Game screens keep their own chrome to a minimum so the battle viewport is
   * substantially visible without scrolling on a normal laptop viewport.
   */
  $: focusRoute = $page.url.pathname.startsWith('/battle/') ||
    /^\/challenges\/[^/]+$/.test($page.url.pathname);
  $: if (typeof document !== 'undefined') {
    document.documentElement.dataset.overlay = String(cleanRoute);
  }
  // A redeploy renames every content-hashed chunk, so a tab that outlived it 404s on the
  // ones it still remembers and the whole app looks broken. Once a new version is detected,
  // send the next navigation through the server to pick the current build up.
  beforeNavigate((navigation) => {
    if ($updated && navigation.willUnload === false && navigation.to?.url) {
      navigation.cancel();
      location.href = navigation.to.url.href;
    }
  });

  onMount(() => {
    theme = (localStorage.getItem('koalabattle-theme') as 'light' | 'dark') ||
      (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    document.documentElement.dataset.theme = theme;
  });

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('koalabattle-theme', theme);
  }

  let utilityMenu: HTMLDetailsElement | null = null;
  function closeUtilityMenu(event: Event) {
    if (utilityMenu?.open && !utilityMenu.contains(event.target as Node)) utilityMenu.open = false;
  }
</script>

<svelte:head><title>KoalaBattle</title><meta name="description" content="Local-first AI battle production" /></svelte:head>

<svelte:window on:pointerdown={closeUtilityMenu} />

{#if cleanRoute}
  <div class="overlay-shell"><slot /></div>
{:else}
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="app-header">
    <a class="brand" href="/" aria-label="KoalaBattle home"><img src="/koalabattle-mark.svg" alt="" /><span>KoalaBattle</span></a>
    <!--
      Three primary destinations only: Home, Battle (matches, tournaments, replays) and
      Draft. Everything else — the operator dashboard, teams, settings — is one tap away in
      the utility menu instead of a permanent header row.
    -->
    <nav aria-label="Primary navigation">
      <a class:active={$page.url.pathname === '/'} href="/"><i class="ph ph-house" aria-hidden="true"></i><span>Home</span></a>
      <a class:active={$page.url.pathname.startsWith('/matches') || $page.url.pathname.startsWith('/battle') || $page.url.pathname.startsWith('/replay') || $page.url.pathname.startsWith('/tournaments') || $page.url.pathname.startsWith('/new')} href="/matches"><i class="ph ph-sword" aria-hidden="true"></i><span>Battle</span></a>
      <a class:active={$page.url.pathname.startsWith('/challenges')} href="/challenges"><i class="ph ph-map-trifold" aria-hidden="true"></i><span>Draft</span></a>
    </nav>
    <div class="header-actions">
      <details bind:this={utilityMenu} class="utility-menu">
        <summary title="More" aria-label="More"><i class="ph ph-sliders-horizontal" aria-hidden="true"></i></summary>
        <div class="utility-menu-panel" role="none" on:click={() => utilityMenu && (utilityMenu.open = false)}>
          <a class:active={$page.url.pathname.startsWith('/admin')} href="/admin"><i class="ph ph-squares-four" aria-hidden="true"></i>Dashboard</a>
          <a class:active={$page.url.pathname.startsWith('/tournaments')} href="/tournaments"><i class="ph ph-trophy" aria-hidden="true"></i>Tournaments</a>
          <a class:active={$page.url.pathname.startsWith('/teams')} href="/teams"><i class="ph ph-users-three" aria-hidden="true"></i>Teams</a>
          <a class:active={$page.url.pathname.startsWith('/settings')} href="/settings"><i class="ph ph-sliders-horizontal" aria-hidden="true"></i>Settings</a>
        </div>
      </details>
      <button class="icon-button" on:click={toggleTheme} aria-label={`Use ${theme === 'dark' ? 'light' : 'dark'} application theme`}><i class={`ph ${theme === 'dark' ? 'ph-sun' : 'ph-moon'}`} aria-hidden="true"></i></button>
    </div>
  </header>
  <main id="main-content" class:focus-route={focusRoute}><slot /></main>
  <footer class="app-footer"><span class="footer-brand"><img src="/koalabattle-mark.svg" alt="" />KoalaBattle 0.11.0</span><span>Local-first · Auditable context · Event-sourced · No Pokémon assets included</span></footer>
{/if}

<style>
  .utility-menu{position:relative}
  .utility-menu>summary{list-style:none;cursor:pointer}
  .utility-menu>summary::-webkit-details-marker{display:none}
  .utility-menu-panel{position:absolute;z-index:60;top:calc(100% + .5rem);right:0;display:grid;gap:.15rem;width:min(13rem,80vw);padding:.4rem;border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--panel);box-shadow:var(--shadow)}
  .utility-menu-panel a{display:flex;align-items:center;gap:.55rem;min-height:44px;padding:.5rem .6rem;border-radius:.5rem;color:var(--muted);font:600 .82rem var(--display)}
  .utility-menu-panel a:hover,.utility-menu-panel a.active{background:var(--surface);color:var(--text)}
  .utility-menu-panel .ph{font-size:1rem}
</style>
