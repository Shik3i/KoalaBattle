<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import '../app.css';

  let theme: 'light' | 'dark' = 'dark';
  /**
   * Routes that render the battle and nothing else. `/watch` joined this list so the
   * viewer/stream workflow has no navigation, no controls and no page scroll.
   */
  const CLEAN_ROUTES = ['/overlay/', '/render/', '/watch/'];
  $: cleanRoute = CLEAN_ROUTES.some((prefix) => $page.url.pathname.startsWith(prefix));
  $: if (typeof document !== 'undefined') {
    document.documentElement.dataset.overlay = String(cleanRoute);
  }
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
</script>

<svelte:head><title>KoalaBattle</title><meta name="description" content="Local-first AI battle production" /></svelte:head>

{#if cleanRoute}
  <div class="overlay-shell"><slot /></div>
{:else}
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="app-header">
    <a class="brand" href="/" aria-label="KoalaBattle home"><img src="/koalabattle-mark.svg" alt="" /><span>KoalaBattle</span></a>
    <nav aria-label="Primary navigation">
      <a class:active={$page.url.pathname.startsWith('/admin')} href="/admin"><i class="ph ph-squares-four" aria-hidden="true"></i><span>Dashboard</span></a>
      <a class:active={$page.url.pathname.startsWith('/matches') || $page.url.pathname.startsWith('/battle') || $page.url.pathname.startsWith('/replay')} href="/matches"><i class="ph ph-sword" aria-hidden="true"></i><span>Matches</span></a>
      <a class:active={$page.url.pathname.startsWith('/tournaments')} href="/tournaments"><i class="ph ph-trophy" aria-hidden="true"></i><span>Tournaments</span></a>
      <a class:active={$page.url.pathname.startsWith('/teams')} href="/teams"><i class="ph ph-users-three" aria-hidden="true"></i><span>Teams</span></a>
      <a class:active={$page.url.pathname.startsWith('/settings')} href="/settings"><i class="ph ph-sliders-horizontal" aria-hidden="true"></i><span>Settings</span></a>
    </nav>
    <div class="header-actions"><a class="button compact" href="/new"><i class="ph ph-plus" aria-hidden="true"></i>New match</a><button class="icon-button" on:click={toggleTheme} aria-label={`Use ${theme === 'dark' ? 'light' : 'dark'} application theme`}><i class={`ph ${theme === 'dark' ? 'ph-sun' : 'ph-moon'}`} aria-hidden="true"></i></button></div>
  </header>
  <main id="main-content"><slot /></main>
  <footer><span class="footer-brand"><img src="/koalabattle-mark.svg" alt="" />KoalaBattle 0.11.0</span><span>Local-first · Auditable context · Event-sourced · No Pokémon assets included</span></footer>
{/if}
