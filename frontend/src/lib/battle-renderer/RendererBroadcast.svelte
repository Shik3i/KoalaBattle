<script lang="ts">
  import { pokemonAssetUrl } from '../presentation/assets';
  import type { RendererConfig } from '../presentation/types';
  import type { BattleSide, PokemonState } from '../types';

  export let config: RendererConfig;
  export let p1Side: BattleSide | null;
  export let p2Side: BattleSide | null;
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

<footer class="broadcast-bar" aria-label="Battle team rosters">
  <div class="header-player header-p1" data-side="p1">
    {#if p1Side}
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
  <div class="header-player header-p2" data-side="p2">
    {#if p2Side}
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
  </div>
</footer>

<style>
  .broadcast-bar{display:grid;grid-template-columns:1fr 1fr;align-items:center;min-height:clamp(62px,8cqh,84px);padding:clamp(7px,1cqh,11px) clamp(12px,1.8cqw,28px);gap:1rem;background:rgba(4,9,7,.97);border-top:1px solid var(--r-line);backdrop-filter:blur(10px)}
  .header-player{display:flex;align-items:center;gap:clamp(6px,.8cqw,12px);overflow:hidden}.header-p1{justify-content:flex-start;--side-color:var(--r-p1)}.header-p2{justify-content:flex-end;--side-color:var(--r-p2)}
  .team-strip{display:flex;gap:clamp(5px,.5cqw,8px)}.team-strip>i{position:relative;display:grid;place-items:center;width:calc(var(--hud-scale,1) * clamp(34px,3.2cqw,50px));aspect-ratio:1;overflow:hidden;border:2px solid color-mix(in srgb,var(--side-color) 62%,rgba(255,255,255,.3));border-radius:7px;background:rgba(255,255,255,.08);box-shadow:0 2px 5px rgba(0,0,0,.48)}
  .team-strip img{width:145%;height:145%;object-fit:contain;image-rendering:pixelated}.team-strip>i>b{color:var(--r-dim);font:800 0.72rem var(--display)}.team-strip>i.unrevealed{border-color:rgba(255,255,255,.16);background:rgba(0,0,0,.24)}.team-strip>i.fainted{border-color:rgba(255,255,255,.12);background:rgba(0,0,0,.4);opacity:.38;filter:grayscale(1) brightness(.65)}.team-strip>i.fainted::after{content:'';position:absolute;width:132%;height:1px;background:rgba(255,255,255,.5);transform:rotate(-45deg)}.team-strip>i.active{border-color:#fff;background:color-mix(in srgb,var(--side-color) 26%,transparent);box-shadow:0 0 0 1px rgba(255,255,255,.5)}
  .team-strip u{position:absolute;right:1px;bottom:1px;left:1px;height:4px;min-width:2px;border:1px solid rgba(0,0,0,.72);border-radius:2px;background:var(--r-hp-high);box-shadow:0 0 0 1px rgba(255,255,255,.18),0 1px 2px rgba(0,0,0,.9);text-decoration:none}.team-strip u[data-tone='mid']{background:var(--r-hp-mid)}.team-strip u[data-tone='low']{background:var(--r-hp-low)}
  .pokeball{position:relative;display:block;width:58%;aspect-ratio:1;border:1.5px solid rgba(255,255,255,.72);border-radius:50%;background:linear-gradient(180deg,#e85d5d 0 46%,#1c2522 46% 54%,#f1f4ed 54%);box-shadow:0 1px 4px rgba(0,0,0,.5)}.pokeball i{position:absolute;top:50%;left:50%;width:30%;aspect-ratio:1;transform:translate(-50%,-50%);border:1px solid rgba(0,0,0,.8);border-radius:50%;background:#f5faf5}
  @media(max-width:720px){.broadcast-bar{gap:.5rem;padding-inline:8px}.team-strip{gap:3px}.team-strip>i{width:clamp(28px,6cqw,38px)}}
</style>
