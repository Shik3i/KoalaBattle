<script lang="ts">
  import { pokemonAssetUrl } from '../presentation/assets';
  import type { AgentPresentationStatus, BattlePresentationState, RendererConfig } from '../presentation/types';
  import type { BattleSide, PokemonState, Side } from '../types';

  export let presentation: BattlePresentationState;
  export let config: RendererConfig;
  export let p1Side: BattleSide | null;
  export let p2Side: BattleSide | null;
  export let formatLabel: string;
  export let agentStatus: Partial<Record<Side, AgentPresentationStatus>> = {};
  export let deterministic = false;

  const TEAM_SIZE = 6;
  let failedAssets = new Set<string>();
  function slots(side: BattleSide | null) {
    const team = side?.team || [];
    return Array.from({ length: TEAM_SIZE }, (_, index) => team[index] || null);
  }
  function rosterLabel(side: BattleSide) {
    const standing = side.team.filter((member) => !member.fainted).length;
    const unrevealed = Math.max(0, TEAM_SIZE - side.team.length);
    return unrevealed ? `${standing} known Pokémon still standing · ${unrevealed} unrevealed team slots` : `${standing} of ${TEAM_SIZE} Pokémon still standing`;
  }
  function spriteUrl(species: string) {
    return pokemonAssetUrl(species, 'front', config.animatedSprites && !deterministic);
  }
  function hpTone(fraction: number) {
    return fraction > .5 ? 'high' : fraction > .2 ? 'mid' : 'low';
  }
  function hpPercent(member: PokemonState) {
    return Math.round(member.hp_fraction * 100);
  }
  function fail(species: string) {
    failedAssets = new Set([...failedAssets, species]);
  }
</script>

<header class="broadcast-bar">
  <div class="header-player header-p1" data-side="p1">
    <span class="player-name">{presentation.players.p1.displayName}</span>
    {#if config.showAgentState}<em class={`agent-state ${agentStatus.p1 || presentation.players.p1.agentStatus}`}>{agentStatus.p1 || presentation.players.p1.agentStatus}</em>{/if}
    {#if config.showTeamRoster && p1Side}
      <span class="team-strip" aria-label={rosterLabel(p1Side)}>
        {#each slots(p1Side) as member, index (index)}
          <i class:active={Boolean(member?.active)} class:fainted={Boolean(member?.fainted)} class:unrevealed={!member} title={member ? `${member.name}${member.fainted ? ' · fainted' : ` · ${hpPercent(member)}%`}` : 'Unrevealed Pokémon'}>
            {#if member && !failedAssets.has(member.species)}<img src={spriteUrl(member.species)} alt={member.name} on:error={() => fail(member.species)} />
            {:else if member}<b>{member.name.slice(0, 1)}</b>
            {:else}<span class="pokeball" aria-hidden="true"><i></i></span>{/if}
            {#if member && !member.fainted}<u style={`width:${Math.max(member.hp_fraction, 0) * 100}%`} data-tone={hpTone(member.hp_fraction)}></u>{/if}
          </i>
        {/each}
      </span>
    {/if}
  </div>
  <div class="header-center">
    <span class="brand"><img src="/koalabattle-mark.svg" alt="" /><b>KOALABATTLE</b></span>
    {#if config.showTurn}<span class="turn">TURN <b>{presentation.battle?.turn ?? 0}</b></span>{/if}
    <span class="format">{formatLabel}</span>
  </div>
  <div class="header-player header-p2" data-side="p2">
    {#if config.showTeamRoster && p2Side}
      <span class="team-strip" aria-label={rosterLabel(p2Side)}>
        {#each slots(p2Side) as member, index (index)}
          <i class:active={Boolean(member?.active)} class:fainted={Boolean(member?.fainted)} class:unrevealed={!member} title={member ? `${member.name}${member.fainted ? ' · fainted' : ` · ${hpPercent(member)}%`}` : 'Unrevealed Pokémon'}>
            {#if member && !failedAssets.has(member.species)}<img src={spriteUrl(member.species)} alt={member.name} on:error={() => fail(member.species)} />
            {:else if member}<b>{member.name.slice(0, 1)}</b>
            {:else}<span class="pokeball" aria-hidden="true"><i></i></span>{/if}
            {#if member && !member.fainted}<u style={`width:${Math.max(member.hp_fraction, 0) * 100}%`} data-tone={hpTone(member.hp_fraction)}></u>{/if}
          </i>
        {/each}
      </span>
    {/if}
    {#if config.showAgentState}<em class={`agent-state ${agentStatus.p2 || presentation.players.p2.agentStatus}`}>{agentStatus.p2 || presentation.players.p2.agentStatus}</em>{/if}
    <span class="player-name">{presentation.players.p2.displayName}</span>
  </div>
</header>

<style>
  .broadcast-bar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;height:clamp(46px,6cqh,64px);padding:0 clamp(10px,1.4cqw,24px);gap:.6rem;background:rgba(4,9,7,.95);border-bottom:1px solid var(--r-line);backdrop-filter:blur(10px)}
  .header-player{display:flex;align-items:center;gap:clamp(6px,.8cqw,12px);overflow:hidden}.header-p1{justify-content:flex-start;--side-color:var(--r-p1)}.header-p2{justify-content:flex-end;--side-color:var(--r-p2)}
  .header-center{display:flex;align-items:center;justify-content:center;gap:clamp(8px,1cqw,18px)}
  .player-name{overflow:hidden;font:800 calc(var(--hud-scale,1) * clamp(.75rem,1.05cqw,1.1rem))/1.1 var(--display);letter-spacing:-.01em;text-overflow:ellipsis;text-transform:uppercase;white-space:nowrap;color:#fff}.header-p1 .player-name{color:var(--r-p1)}.header-p2 .player-name{color:var(--r-p2)}
  .agent-state{display:inline-flex;align-items:center;gap:.28rem;min-height:1.3em;padding:.14rem .4rem;border-radius:4px;background:rgba(255,255,255,.1);font:800 calc(var(--hud-scale,1) * clamp(.62rem,.82cqw,.82rem)) var(--mono);font-style:normal;letter-spacing:.08em;text-transform:uppercase;text-shadow:0 1px 2px rgba(0,0,0,.8)}.agent-state::before{content:'•';font-size:1.35em;line-height:.5;color:currentColor}.agent-state.waiting::before,.agent-state.thinking::before{content:'◌'}.agent-state.finished::before{content:'✓'}.agent-state.error::before{content:'!'}.agent-state.thinking{background:rgba(242,193,95,.2);color:#ffd679}.agent-state.decided,.agent-state.executing{background:rgba(120,255,169,.16);color:var(--r-accent)}.agent-state.error{background:rgba(255,139,135,.18);color:#ff9d98}
  .team-strip{display:flex;gap:clamp(3px,.3cqw,5px)}.team-strip>i{position:relative;display:grid;place-items:center;width:calc(var(--hud-scale,1) * clamp(20px,2.1cqw,32px));aspect-ratio:1;overflow:hidden;border:1.5px solid color-mix(in srgb,var(--side-color) 62%,rgba(255,255,255,.3));border-radius:5px;background:rgba(255,255,255,.08);box-shadow:0 1px 3px rgba(0,0,0,.42)}
  .team-strip img{width:145%;height:145%;object-fit:contain;image-rendering:pixelated}.team-strip>i>b{color:var(--r-dim);font:800 .55rem var(--display)}.team-strip>i.unrevealed{border-color:rgba(255,255,255,.16);background:rgba(0,0,0,.24)}.team-strip>i.fainted{border-color:rgba(255,255,255,.12);background:rgba(0,0,0,.4);opacity:.38;filter:grayscale(1) brightness(.65)}.team-strip>i.fainted::after{content:'';position:absolute;width:132%;height:1px;background:rgba(255,255,255,.5);transform:rotate(-45deg)}.team-strip>i.active{border-color:#fff;background:color-mix(in srgb,var(--side-color) 26%,transparent);box-shadow:0 0 0 1px rgba(255,255,255,.5)}
  .team-strip u{position:absolute;right:1px;bottom:1px;left:1px;height:4px;min-width:2px;border:1px solid rgba(0,0,0,.72);border-radius:2px;background:var(--r-hp-high);box-shadow:0 0 0 1px rgba(255,255,255,.18),0 1px 2px rgba(0,0,0,.9);text-decoration:none}.team-strip u[data-tone='mid']{background:var(--r-hp-mid)}.team-strip u[data-tone='low']{background:var(--r-hp-low)}
  .pokeball{position:relative;display:block;width:58%;aspect-ratio:1;border:1.5px solid rgba(255,255,255,.72);border-radius:50%;background:linear-gradient(180deg,#e85d5d 0 46%,#1c2522 46% 54%,#f1f4ed 54%);box-shadow:0 1px 4px rgba(0,0,0,.5)}.pokeball i{position:absolute;top:50%;left:50%;width:30%;aspect-ratio:1;transform:translate(-50%,-50%);border:1px solid rgba(0,0,0,.8);border-radius:50%;background:#f5faf5}
  .brand{display:flex;align-items:center;gap:.35rem;color:var(--r-accent);font:900 clamp(.58rem,.8cqw,.8rem) var(--display);letter-spacing:.08em}.brand img{width:clamp(18px,1.8cqw,26px);height:auto}.turn,.format{color:var(--r-dim);font:700 clamp(.5rem,.66cqw,.68rem) var(--mono);white-space:nowrap}.turn b{color:#fff}
  @media(max-width:720px){.format,.brand b{display:none}.header-center{gap:5px}.team-strip>i{width:clamp(18px,4.1cqw,25px)}}
</style>
