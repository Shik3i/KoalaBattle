<script lang="ts">
  import { pokemonAssetUrl } from '../presentation/assets';
  import type { BattlePresentationState, RendererConfig } from '../presentation/types';
  import type { BattleSide, Side } from '../types';

  export let presentation: BattlePresentationState;
  export let config: RendererConfig;
  export let formatLabel: string;
  export let deterministic = false;

  let failedAssets = new Set<string>();
  function battleSide(side: Side): BattleSide | null {
    if (!presentation.battle) return null;
    return presentation.battle.player.side === side ? presentation.battle.player : presentation.battle.opponent.side === side ? presentation.battle.opponent : null;
  }
  function spriteUrl(species: string) {
    return pokemonAssetUrl(species, 'front', config.animatedSprites && !deterministic);
  }
  function fail(species: string) {
    failedAssets = new Set([...failedAssets, species]);
  }
  $: champion = presentation.winner ? battleSide(presentation.winner) : null;
</script>

{#if presentation.finished}
  <div class:deterministic class="winner-banner" role="status" data-side={presentation.winner || ''}>
    <small>BATTLE COMPLETE</small><strong>{presentation.winnerName || presentation.battle?.result?.winner_name || 'DRAW'}</strong>
    {#if presentation.winner}
      <span class="winner-meta"><b class="winner-side">{presentation.winner.toUpperCase()}</b><em>{presentation.players[presentation.winner].providerLabel}</em>{#if champion}<i class="winner-score">{champion.team.filter((member) => !member.fainted).length}/{champion.team.length} standing</i>{/if}</span>
      {#if champion?.team.length}<span class="winner-team">{#each champion.team as member (member.id || member.species)}<i class:fainted={member.fainted} title={member.name}>{#if !failedAssets.has(member.species)}<img src={spriteUrl(member.species)} alt={member.name} on:error={() => fail(member.species)} />{:else}<b>{member.name.slice(0, 1)}</b>{/if}</i>{/each}</span>{/if}
    {:else}<span class="winner-meta"><em>No winner recorded</em></span>{/if}
  </div>
{/if}

{#if presentation.eventIndex === 0 && !presentation.finished}
  <div class="director-card director-intro" role="status" aria-label="Match introduction"><span class="director-mark"><img src="/koalabattle-mark.svg" alt="" /></span><small>KOALABATTLE // MAIN EVENT</small><strong>{presentation.players.p1.displayName} <i>VS</i> {presentation.players.p2.displayName}</strong><span>{formatLabel}</span></div>
{:else if presentation.finished}
  <div class="director-card director-result" role="status" aria-label="Match result"><small>KOALABATTLE // FINAL</small><strong>{presentation.winnerName || presentation.battle?.result?.winner_name || 'DRAW'}{presentation.winner ? ' WINS' : ''}</strong><span>{formatLabel} · TURN {presentation.battle?.turn ?? 0}</span></div>
{/if}

<style>
  .winner-banner{position:absolute;z-index:40;inset:0;display:grid;place-content:center;justify-items:center;gap:.5rem;padding:2rem;--champion:var(--r-accent);background:radial-gradient(ellipse at 50% 45%,color-mix(in srgb,var(--champion) 22%,transparent),rgba(4,10,7,.93) 62%),rgba(4,10,7,.9);text-align:center;backdrop-filter:blur(9px);animation:winner-in .7s both}.winner-banner.deterministic{animation:none}.winner-banner[data-side='p1']{--champion:var(--r-p1)}.winner-banner[data-side='p2']{--champion:var(--r-p2)}
  .winner-banner small{display:flex;align-items:center;gap:.7rem;color:var(--champion);font:900 calc(var(--hud-scale,1) * clamp(.7rem,.95cqw,.98rem)) var(--mono);letter-spacing:.34em}.winner-banner small::before,.winner-banner small::after{content:'';width:clamp(24px,4cqw,72px);height:1px;background:linear-gradient(90deg,transparent,var(--champion))}.winner-banner small::after{background:linear-gradient(90deg,var(--champion),transparent)}
  .winner-banner strong{margin:.1rem 0 .2rem;background:linear-gradient(180deg,#fff 26%,color-mix(in srgb,var(--champion) 82%,#fff));-webkit-background-clip:text;background-clip:text;color:transparent;font-size:calc(var(--hud-scale,1) * clamp(2.6rem,8.4cqw,7.5rem));font-weight:900;line-height:.9;letter-spacing:-.055em;text-transform:uppercase;filter:drop-shadow(0 6px 26px color-mix(in srgb,var(--champion) 55%,transparent))}
  .winner-meta{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:.55rem}.winner-side{padding:.22rem .7rem;border-radius:999px;background:var(--champion);color:#04100a;font:900 calc(var(--hud-scale,1) * clamp(.82rem,1.05cqw,1.1rem)) var(--mono);letter-spacing:.1em}.winner-meta em{color:#e6f2ea;font:700 calc(var(--hud-scale,1) * clamp(.82rem,1.05cqw,1.1rem)) var(--display);font-style:normal;text-transform:uppercase}.winner-score{color:var(--r-dim);font:600 calc(var(--hud-scale,1) * clamp(.72rem,.9cqw,.95rem)) var(--mono);font-style:normal}
  .winner-team{display:flex;flex-wrap:wrap;justify-content:center;gap:.45rem;margin-top:.9rem}.winner-team i{display:grid;place-items:center;width:calc(var(--hud-scale,1) * clamp(38px,4.2cqw,66px));aspect-ratio:1;overflow:hidden;border:1px solid color-mix(in srgb,var(--champion) 55%,transparent);border-radius:9px;background:rgba(255,255,255,.06)}.winner-team img{width:145%;height:145%;object-fit:contain}.winner-team i b{color:var(--r-dim);font:800 1rem var(--display)}.winner-team i.fainted{opacity:.32;filter:grayscale(1) brightness(.6)}
  .director-card{position:absolute;z-index:50;inset:0;display:grid;place-content:center;justify-items:center;gap:.65rem;padding:2rem;background:#020408;text-align:center;pointer-events:none}.director-card::before,.director-card::after{content:'';position:absolute;inset:0}.director-card::before{background:linear-gradient(112deg,rgba(95,227,154,.23) 0 38%,transparent 38% 62%,rgba(201,140,255,.2) 62%)}.director-card::after{background:repeating-linear-gradient(112deg,transparent 0 15%,rgba(255,255,255,.06) 15.1% 15.5%,transparent 15.6% 28%);mix-blend-mode:screen}.director-card>*{position:relative;z-index:1}.director-card small{color:#baf8ca;font:900 calc(var(--hud-scale,1) * clamp(.62rem,1cqw,1rem)) var(--mono);letter-spacing:.28em}.director-card strong{max-width:90%;color:#fff;font:900 calc(var(--hud-scale,1) * clamp(2rem,5.5cqw,5.8rem))/1 var(--display);text-transform:uppercase;text-shadow:0 8px 32px rgba(0,0,0,.75)}.director-card strong i{font-style:normal;color:#ffd262;font-size:.48em}.director-card span:not(.director-mark){color:rgba(240,246,242,.86);font:800 calc(var(--hud-scale,1) * clamp(.68rem,1.05cqw,1.05rem)) var(--mono);text-transform:uppercase}.director-mark{display:grid;place-items:center;width:clamp(50px,7cqw,92px);aspect-ratio:1;border:1px solid rgba(255,255,255,.22);border-radius:18px;background:rgba(0,0,0,.25)}.director-mark img{width:62%}.director-result::before{background:linear-gradient(112deg,rgba(255,217,106,.25) 0 38%,transparent 38% 62%,rgba(255,152,76,.22) 62%)}.director-result small{color:#ffd96a}
  @keyframes winner-in{from{opacity:0;clip-path:inset(50% 0)}to{opacity:1;clip-path:inset(0)}}
</style>
