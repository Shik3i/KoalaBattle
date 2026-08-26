<script lang="ts">
  import { pokemonAssetUrl, trainerAssetUrl } from '../presentation/assets';
  import type { BattlePresentationState, RecapEntry, RendererConfig } from '../presentation/types';
  import type { BattleSide, CampaignBadge, Side } from '../types';

  export let presentation: BattlePresentationState;
  export let config: RendererConfig;
  export let formatLabel: string;
  export let campaign: CampaignBadge | null = null;
  export let deterministic = false;

  let failedAssets = new Set<string>();
  let failedTrainer = false;

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
  /** Best performers first: knockouts, then raw damage. Only Pokemon that entered count. */
  function ranked(side: Side): RecapEntry[] {
    return presentation.recap
      .filter((entry) => entry.side === side && entry.entered)
      .sort((left, right) => right.knockouts - left.knockouts || right.damageDealt - left.damageDealt);
  }
  $: champion = presentation.winner ? battleSide(presentation.winner) : null;
  $: mvp = presentation.winner ? ranked(presentation.winner).find((entry) => entry.knockouts || entry.damageDealt) || null : null;
  // Bars compare Pokemon against the hardest hitter in this battle, not against a fixed
  // 100%: cumulative damage across several targets routinely goes past one full HP bar.
  $: peakDamage = Math.max(1, ...presentation.recap.map((entry) => entry.damageDealt));
  $: introTrainer = campaign?.trainer_asset_id && !failedTrainer ? trainerAssetUrl(campaign.trainer_asset_id) : null;
  $: accent = campaign?.visual_accent || null;
</script>

{#if presentation.finished}
  <!-- The end card is the payoff: who won, who carried it, and what every Pokemon did. -->
  <div class:deterministic class="winner-banner" role="status" data-side={presentation.winner || ''} style={accent ? `--stage-accent:${accent}` : undefined}>
    <small>{campaign ? `${campaign.definition_name} · Battle ${campaign.stage_index + 1}/${campaign.stage_count}` : 'BATTLE COMPLETE'}</small>
    {#if !(campaign && presentation.winner === 'p1')}
      <strong>{presentation.winnerName || presentation.battle?.result?.winner_name || 'DRAW'}</strong>
    {/if}
    {#if presentation.winner}
      <span class="winner-meta"><b class="winner-side">{presentation.winner.toUpperCase()}</b>{#if !campaign}<em>{presentation.players[presentation.winner].providerLabel}</em>{/if}{#if champion}<i class="winner-score">{champion.team.filter((member) => !member.fainted).length}/{champion.team.length} standing</i>{/if}</span>
      {#if mvp}<span class="winner-mvp"><b>MVP</b><em>{mvp.name}</em><i>{mvp.knockouts} KO{mvp.knockouts === 1 ? '' : 's'} · {mvp.damageDealt}% HP dealt</i></span>{/if}
      {#if champion?.team.length}<span class="winner-team">{#each champion.team as member (member.id || member.species)}<i class:fainted={member.fainted} title={member.name}>{#if !failedAssets.has(member.species)}<img src={spriteUrl(member.species)} alt={member.name} on:error={() => fail(member.species)} />{:else}<b>{member.name.slice(0, 1)}</b>{/if}</i>{/each}</span>{/if}
    {:else}<span class="winner-meta"><em>No winner recorded</em></span>{/if}
    <span class="winner-format">{formatLabel} · Turn {presentation.battle?.turn ?? 0}</span>

    {#if presentation.recap.some((entry) => entry.entered)}
      <div class="recap" aria-label="Battle recap">
        {#each ['p1', 'p2'] as Side[] as side (side)}
          {@const rows = ranked(side)}
          {#if rows.length}
            <section class:champion={presentation.winner === side} data-side={side}>
              <header><b>{presentation.players[side].displayName}</b><span>{rows.length} used · {rows.filter((row) => row.fainted).length} down</span></header>
              <ol>
                {#each rows as row (row.id)}
                  <li class:fainted={row.fainted}>
                    <span class="recap-mon">{#if !failedAssets.has(row.species)}<img src={spriteUrl(row.species)} alt="" on:error={() => fail(row.species)} />{:else}<b>{row.name.slice(0, 1)}</b>{/if}</span>
                    <b>{row.name}</b>
                    <span class="recap-bar"><i style={`width:${Math.round((row.damageDealt / peakDamage) * 100)}%`}></i></span>
                    <em>{row.damageDealt}%</em>
                    {#if row.knockouts}<u>{row.knockouts} KO</u>{/if}
                  </li>
                {/each}
              </ol>
            </section>
          {/if}
        {/each}
      </div>
    {/if}
  </div>
{/if}

{#if presentation.eventIndex === 0 && !presentation.finished}
  <div class="director-card director-intro" role="status" aria-label="Match introduction" style={accent ? `--stage-accent:${accent}` : undefined}>
    {#if campaign}
      <small>{campaign.definition_name} // Battle {campaign.stage_index + 1} of {campaign.stage_count}</small>
      <div class="versus">
        <span class="versus-side"><span class="versus-avatar challenger"><img src="/koalabattle-mark.svg" alt="" /></span><b>{presentation.players.p1.displayName}</b><i>Lv {campaign.player_level}</i></span>
        <span class="versus-mark">VS</span>
        <span class="versus-side">
          <span class="versus-avatar">{#if introTrainer}<img class="trainer" src={introTrainer} alt="" on:error={() => (failedTrainer = true)} />{:else}<b>{campaign.stage_name.slice(0, 2).toUpperCase()}</b>{/if}</span>
          <b>{campaign.stage_name}</b><i>{campaign.specialty ? `${campaign.specialty} · ` : ''}Lv {campaign.opponent_level}</i>
        </span>
      </div>
      <span>{campaign.stage_title} · {formatLabel}</span>
    {:else}
      <span class="director-mark"><img src="/koalabattle-mark.svg" alt="" /></span>
      <small>KOALABATTLE // MAIN EVENT</small>
      <strong>{presentation.players.p1.displayName} <i>VS</i> {presentation.players.p2.displayName}</strong>
      <span>{formatLabel}</span>
    {/if}
  </div>
{/if}

<style>
  .winner-banner{position:absolute;z-index:60;inset:0;display:grid;place-content:center;justify-items:center;gap:.5rem;padding:2rem;--champion:var(--r-accent);background:radial-gradient(ellipse at 50% 45%,color-mix(in srgb,var(--champion) 22%,transparent),rgba(4,10,7,.93) 62%),rgba(4,10,7,.9);text-align:center;backdrop-filter:blur(9px);animation:winner-in .7s both}.winner-banner.deterministic{animation:none}.winner-banner[data-side='p1']{--champion:var(--r-p1)}.winner-banner[data-side='p2']{--champion:var(--r-p2)}
  .winner-banner small{display:flex;align-items:center;gap:.7rem;color:var(--champion);font:900 calc(var(--hud-scale,1) * clamp(0.72rem,.95cqw,0.98rem)) var(--mono);letter-spacing:.34em}.winner-banner small::before,.winner-banner small::after{content:'';width:clamp(24px,4cqw,72px);height:1px;background:linear-gradient(90deg,transparent,var(--champion))}.winner-banner small::after{background:linear-gradient(90deg,var(--champion),transparent)}
  .winner-banner strong{margin:.1rem 0 .2rem;background:linear-gradient(180deg,#fff 26%,color-mix(in srgb,var(--champion) 82%,#fff));-webkit-background-clip:text;background-clip:text;color:transparent;font-size:calc(var(--hud-scale,1) * clamp(2.2rem,6.6cqw,5.6rem));font-weight:900;line-height:.9;letter-spacing:-.055em;text-transform:uppercase;filter:drop-shadow(0 6px 26px color-mix(in srgb,var(--champion) 55%,transparent))}
  .winner-meta{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:.55rem}.winner-side{padding:.22rem .7rem;border-radius:999px;background:var(--champion);color:#04100a;font:900 calc(var(--hud-scale,1) * clamp(.82rem,1.05cqw,1.1rem)) var(--mono);letter-spacing:.1em}.winner-meta em{color:#e6f2ea;font:700 calc(var(--hud-scale,1) * clamp(.82rem,1.05cqw,1.1rem)) var(--display);font-style:normal;text-transform:uppercase}.winner-score{color:var(--r-dim);font:600 calc(var(--hud-scale,1) * clamp(.72rem,.9cqw,.95rem)) var(--mono);font-style:normal}
  .winner-format{color:var(--r-dim);font:600 calc(var(--hud-scale,1) * clamp(0.72rem,.78cqw,0.82rem)) var(--mono);letter-spacing:.12em;text-transform:uppercase}
  .winner-mvp{display:flex;align-items:center;gap:.5rem;padding:.28rem .8rem;border:1px solid color-mix(in srgb,var(--champion) 45%,transparent);border-radius:999px;background:color-mix(in srgb,var(--champion) 12%,transparent);animation:mvp-pop .5s .55s both}
  .winner-mvp b{color:var(--champion);font:900 calc(var(--hud-scale,1) * clamp(0.72rem,.85cqw,0.9rem)) var(--mono);letter-spacing:.2em}
  .winner-mvp em{color:#fff;font:800 calc(var(--hud-scale,1) * clamp(.86rem,1.1cqw,1.15rem)) var(--display);font-style:normal}
  .winner-mvp i{color:var(--r-dim);font:600 calc(var(--hud-scale,1) * clamp(0.72rem,.85cqw,0.9rem)) var(--mono);font-style:normal}
  .winner-team{display:flex;flex-wrap:wrap;justify-content:center;gap:.45rem;margin-top:.7rem}.winner-team i{display:grid;place-items:center;width:calc(var(--hud-scale,1) * clamp(34px,3.6cqw,56px));aspect-ratio:1;overflow:hidden;border:1px solid color-mix(in srgb,var(--champion) 55%,transparent);border-radius:9px;background:rgba(255,255,255,.06)}.winner-team img{width:145%;height:145%;object-fit:contain;image-rendering:crisp-edges;image-rendering:pixelated}.winner-team i b{color:var(--r-dim);font:800 1rem var(--display)}.winner-team i.fainted{opacity:.32;filter:grayscale(1) brightness(.6)}

  /* Recap: who actually did the work, in one glance, per side. */
  .recap{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem;width:min(96%,64cqw);margin-top:.9rem;text-align:left;animation:recap-in .55s .3s both}
  .recap section{padding:.5rem .6rem;border:1px solid rgba(255,255,255,.1);border-radius:.7rem;background:rgba(255,255,255,.04)}
  .recap section.champion{border-color:color-mix(in srgb,var(--champion) 45%,transparent);background:color-mix(in srgb,var(--champion) 8%,rgba(255,255,255,.03))}
  .recap header{display:flex;align-items:baseline;justify-content:space-between;gap:.5rem;margin-bottom:.35rem}
  .recap header b{overflow:hidden;color:#fff;font:800 calc(var(--hud-scale,1) * clamp(0.72rem,.92cqw,0.95rem)) var(--display);text-overflow:ellipsis;white-space:nowrap}
  .recap header span{color:var(--r-dim);font:600 calc(var(--hud-scale,1) * clamp(0.72rem,.74cqw,0.8rem)) var(--mono)}
  .recap ol{display:grid;gap:.18rem;margin:0;padding:0;list-style:none}
  .recap li{display:grid;grid-template-columns:auto minmax(0,1fr) minmax(28px,3.4cqw) auto auto;align-items:center;gap:.35rem}
  .recap li.fainted{opacity:.45}
  .recap-mon{display:grid;place-items:center;width:calc(var(--hud-scale,1) * clamp(18px,2cqw,30px));aspect-ratio:1;overflow:hidden}
  .recap-mon img{width:150%;height:150%;object-fit:contain;image-rendering:crisp-edges;image-rendering:pixelated}
  .recap-mon b{color:var(--r-dim);font:800 0.72rem var(--display)}
  .recap li>b{overflow:hidden;color:#eaf4ee;font:700 calc(var(--hud-scale,1) * clamp(0.72rem,.78cqw,0.82rem)) var(--display);text-overflow:ellipsis;white-space:nowrap}
  .recap-bar{overflow:hidden;height:4px;border-radius:999px;background:rgba(255,255,255,.12)}
  .recap-bar i{display:block;height:100%;border-radius:inherit;background:var(--champion);animation:recap-bar .6s .45s both}
  .recap li em{color:var(--r-dim);font:600 calc(var(--hud-scale,1) * clamp(0.72rem,.72cqw,0.8rem)) var(--mono);font-style:normal}
  .recap li u{padding:.04rem .3rem;border-radius:4px;background:color-mix(in srgb,var(--champion) 26%,transparent);color:#fff;font:800 calc(var(--hud-scale,1) * clamp(0.72rem,.68cqw,0.8rem)) var(--mono);text-decoration:none}

  .director-card{position:absolute;z-index:50;inset:0;display:grid;place-content:center;justify-items:center;gap:.65rem;padding:2rem;background:#020408;text-align:center;pointer-events:none}.director-card::before,.director-card::after{content:'';position:absolute;inset:0}.director-card::before{background:linear-gradient(112deg,rgba(95,227,154,.23) 0 38%,transparent 38% 62%,rgba(201,140,255,.2) 62%)}.director-card::after{background:repeating-linear-gradient(112deg,transparent 0 15%,rgba(255,255,255,.06) 15.1% 15.5%,transparent 15.6% 28%);mix-blend-mode:screen}.director-card>*{position:relative;z-index:1}.director-card small{color:#baf8ca;font:900 calc(var(--hud-scale,1) * clamp(0.72rem,1cqw,1.0rem)) var(--mono);letter-spacing:.28em}.director-card strong{max-width:90%;color:#fff;font:900 calc(var(--hud-scale,1) * clamp(2rem,5.5cqw,5.8rem))/1 var(--display);text-transform:uppercase;text-shadow:0 8px 32px rgba(0,0,0,.75)}.director-card strong i{font-style:normal;color:#ffd262;font-size:.48em}.director-card span:not(.director-mark){color:rgba(240,246,242,.86);font:800 calc(var(--hud-scale,1) * clamp(0.72rem,1.05cqw,1.05rem)) var(--mono);text-transform:uppercase}.director-mark{display:grid;place-items:center;width:clamp(50px,7cqw,92px);aspect-ratio:1;border:1px solid rgba(255,255,255,.22);border-radius:18px;background:rgba(0,0,0,.25)}.director-mark img{width:62%}
  .director-card[style*='--stage-accent']::before{background:linear-gradient(112deg,color-mix(in srgb,var(--stage-accent) 26%,transparent) 0 38%,transparent 38% 62%,color-mix(in srgb,var(--stage-accent) 22%,transparent) 62%)}
  .director-card[style*='--stage-accent'] small{color:color-mix(in srgb,var(--stage-accent) 72%,white)}

  /* Campaign intro: the trainer you are about to fight, not a generic name plate. */
  .versus{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:clamp(0.72rem,2.4cqw,2.4rem);width:min(94%,58cqw)}
  .versus-side{display:grid;justify-items:center;gap:.3rem}
  .versus-side:first-child{animation:versus-left .6s cubic-bezier(.2,.8,.2,1) both}
  .versus-side:last-child{animation:versus-right .6s cubic-bezier(.2,.8,.2,1) both}
  .versus-avatar{display:grid;place-items:center;width:calc(var(--hud-scale,1) * clamp(64px,11cqw,168px));aspect-ratio:1;overflow:hidden;border:1px solid color-mix(in srgb,var(--stage-accent,#7bf0a2) 55%,transparent);border-radius:20px;background:radial-gradient(circle at 50% 70%,color-mix(in srgb,var(--stage-accent,#7bf0a2) 26%,transparent),rgba(0,0,0,.35) 62%)}
  .versus-avatar.challenger{border-color:rgba(255,255,255,.24);background:rgba(0,0,0,.3)}
  .versus-avatar img{width:60%}
  .versus-avatar img.trainer{width:92%;height:94%;object-fit:contain;image-rendering:pixelated;filter:drop-shadow(0 10px 12px rgba(0,0,0,.5));animation:stance 2.6s ease-in-out infinite;transform-origin:50% 100%}
  .versus-avatar b{color:#fff;font:900 clamp(1.1rem,2.4cqw,2.2rem) var(--display)}
  .versus-side>b{max-width:100%;overflow:hidden;color:#fff;font:900 calc(var(--hud-scale,1) * clamp(1rem,2.6cqw,2.6rem))/1.05 var(--display);text-overflow:ellipsis;text-transform:uppercase;white-space:nowrap}
  .versus-side>i{color:rgba(240,246,242,.72);font:700 calc(var(--hud-scale,1) * clamp(0.72rem,.9cqw,0.95rem)) var(--mono);font-style:normal;text-transform:uppercase}
  .versus-mark{color:#ffd262;font:900 calc(var(--hud-scale,1) * clamp(1.4rem,3.4cqw,3.4rem)) var(--display);animation:versus-clash .5s .25s cubic-bezier(.2,1.6,.3,1) both}

  @keyframes winner-in{from{opacity:0;clip-path:inset(50% 0)}to{opacity:1;clip-path:inset(0)}}
  @keyframes mvp-pop{from{opacity:0;transform:scale(.86)}to{opacity:1;transform:scale(1)}}
  @keyframes recap-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  @keyframes recap-bar{from{width:0}}
  @keyframes versus-left{from{opacity:0;transform:translateX(-14%)}to{opacity:1;transform:none}}
  @keyframes versus-right{from{opacity:0;transform:translateX(14%)}to{opacity:1;transform:none}}
  @keyframes versus-clash{from{opacity:0;transform:scale(2.4) rotate(-8deg)}to{opacity:1;transform:none}}
  @keyframes stance{50%{transform:translateY(-3%) scale(1.012)}}
  .deterministic .recap,.deterministic .winner-mvp,.deterministic .recap-bar i{animation:none}
  @media(prefers-reduced-motion:reduce){
    .winner-banner,.winner-mvp,.recap,.recap-bar i,.versus-side,.versus-mark{animation:none}
    .versus-avatar img.trainer{animation:none}
  }
</style>
