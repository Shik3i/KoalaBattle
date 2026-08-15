<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import '../app.css';

  let theme: 'light' | 'dark' = 'dark';
  $: overlayRoute = $page.url.pathname.startsWith('/overlay/');
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
      <a href="/admin">Admin</a>
      <a href="/new">New battle</a>
      <a href="/tournaments">Tournaments</a>
      <a href="/matches">Matches</a>
      <a href="/settings">Settings</a>
    </nav>
    <button class="icon-button" on:click={toggleTheme} aria-label="Toggle color theme">{theme === 'dark' ? '☀' : '☾'}</button>
  </header>
  <main><slot /></main>
  <footer><span>KoalaBattle 0.4</span><span>Local-first · Concurrent · Event-sourced · No Pokémon assets included</span></footer>
{/if}
