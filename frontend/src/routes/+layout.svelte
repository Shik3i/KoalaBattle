<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import '../app.css';

  let theme: 'light' | 'dark' = 'dark';
  $: overlayRoute = $page.url.pathname.startsWith('/overlay/') || $page.url.pathname.startsWith('/render/');
  $: if (typeof document !== 'undefined') {
    document.documentElement.dataset.overlay = String(overlayRoute);
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

{#if overlayRoute}
  <div class="overlay-shell"><slot /></div>
{:else}
  <header class="app-header">
    <a class="brand" href="/" aria-label="KoalaBattle home"><span>KB</span>KoalaBattle</a>
    <nav aria-label="Primary navigation">
      <a class:active={$page.url.pathname.startsWith('/admin')} href="/admin">Dashboard</a>
      <a class:active={$page.url.pathname.startsWith('/matches') || $page.url.pathname.startsWith('/battle') || $page.url.pathname.startsWith('/replay')} href="/matches">Matches</a>
      <a class:active={$page.url.pathname.startsWith('/tournaments')} href="/tournaments">Tournaments</a>
      <a class:active={$page.url.pathname.startsWith('/teams')} href="/teams">Teams</a>
      <a class:active={$page.url.pathname.startsWith('/settings')} href="/settings">Settings</a>
    </nav>
    <div class="header-actions"><a class="button compact" href="/new">New match</a><button class="icon-button" on:click={toggleTheme} aria-label={`Use ${theme === 'dark' ? 'light' : 'dark'} application theme`}><span class:moon={theme === 'light'} class="theme-icon" aria-hidden="true"></span></button></div>
  </header>
  <main><slot /></main>
  <footer><span>KoalaBattle 0.10.0</span><span>Local-first · Auditable context · Event-sourced · No Pokémon assets included</span></footer>
{/if}
