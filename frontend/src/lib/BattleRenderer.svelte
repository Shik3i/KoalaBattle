<script lang="ts">
  import { pokemonAssetUrl } from './presentation/assets';
  import {
    defaultRendererConfig,
    type AgentPresentationStatus,
    type BattlePresentationState,
    type RendererConfig
  } from './presentation/types';
  import type { BattleSide, Side } from './types';

  export let presentation: BattlePresentationState | null = null;
  export let config: RendererConfig = defaultRendererConfig();
  export let overlay = false;
  export let agentStatus: Partial<Record<Side, AgentPresentationStatus>> = {};

  let failedAssets = new Set<string>();
  let nearSide: Side = 'p1';
  let farSide: Side = 'p2';

  $: nearSide = config.nearSide;
  $: farSide = nearSide === 'p1' ? 'p2' : 'p1';
  $: near = presentation ? battleSide(presentation, nearSide) : null;
  $: far = presentation ? battleSide(presentation, farSide) : null;
  $: nearCommentary = commentary(presentation, nearSide, config.commentaryMode);
  $: farCommentary = commentary(presentation, farSide, config.commentaryMode);
  $: hpDuration =
    config.playbackSpeed === 'instant' || config.preset === 'instant'
      ? 0
      : Math.round(650 / Number(config.playbackSpeed));

  function battleSide(state: BattlePresentationState, side: Side): BattleSide | null {
    const battle = state.battle;
    if (!battle) return null;
    if (battle.player.side === side) return battle.player;
    return battle.opponent.side === side ? battle.opponent : null;
  }

  function commentary(
    state: BattlePresentationState | null,
    side: Side,
    mode: RendererConfig['commentaryMode']
  ) {
    if (!state || mode === 'hidden') return [];
    const items = state.players[side].commentary;
    if (mode === 'latest') return items.slice(-1);
    if (mode === 'last-3') return items.slice(-3);
    return items;
  }

  function assetKey(side: BattleSide, perspective: 'front' | 'back') {
    return `${side.active?.species}:${perspective}:${config.animatedSprites}`;
  }

  function onAssetError(key: string) {
    failedAssets = new Set([...failedAssets, key]);
  }

  function hpTone(fraction: number) {
    return fraction > 0.5 ? 'high' : fraction > 0.2 ? 'mid' : 'low';
  }
</script>

{#if presentation}
  <section
    class:overlay
    class:transparent={config.transparentBackground}
    class="battle-renderer"
    data-layout={config.layout}
    data-renderer-theme={config.theme}
    style={`--hp-duration:${hpDuration}ms`}
    aria-label="KoalaBattle production renderer"
  >
    <div class="ambient" aria-hidden="true"></div>
    <header class="scoreboard">
      <div class="brand-lockup"><span>KB</span><strong>KOALA BATTLE</strong></div>
      {#if config.showTurn}<div class="turn">TURN <strong>{presentation.battle?.turn ?? 0}</strong></div>{/if}
      <div class="format">GEN 9 · RANDOM BATTLE</div>
    </header>

    <div class="player-card player-far" data-side={farSide}>
      <div><span class="side">{farSide}</span><h2>{presentation.players[farSide].displayName}</h2></div>
      {#if config.showAgentState}<span class="agent-state">{agentStatus[farSide] || presentation.players[farSide].agentStatus}</span>{/if}
      <small>{presentation.players[farSide].providerLabel}</small>
      <div class="commentary" aria-live="polite">
        {#each farCommentary as item}<p>{item.commentary || `${item.actionName || item.action} selected.`}</p>{/each}
        {#if farCommentary.length === 0}<p class="muted">Awaiting public commentary…</p>{/if}
      </div>
    </div>

    <div class="player-card player-near" data-side={nearSide}>
      <div><span class="side">{nearSide}</span><h2>{presentation.players[nearSide].displayName}</h2></div>
      {#if config.showAgentState}<span class="agent-state">{agentStatus[nearSide] || presentation.players[nearSide].agentStatus}</span>{/if}
      <small>{presentation.players[nearSide].providerLabel}</small>
      <div class="commentary" aria-live="polite">
        {#each nearCommentary as item}<p>{item.commentary || `${item.actionName || item.action} selected.`}</p>{/each}
        {#if nearCommentary.length === 0}<p class="muted">Awaiting public commentary…</p>{/if}
      </div>
    </div>

    <div class="arena-stage">
      <div class="arena-grid" aria-hidden="true"></div>
      {#if far?.active}
        <article class="combatant combatant-far" aria-label={`${far.active.name}, ${Math.round(far.active.hp_fraction * 100)} percent health`}>
          <div class="identity"><span>{far.active.types.join(' · ')}</span><strong>{far.active.name}</strong></div>
          <div class="sprite-platform">
            {#key `${presentation.eventSequence}:${farSide}:${presentation.players[farSide].motion}`}
              <div class={`sprite ${presentation.players[farSide].motion}`}>
                {#if !failedAssets.has(assetKey(far, 'front'))}
                  <img src={pokemonAssetUrl(far.active.species, 'front', config.animatedSprites)} alt={far.active.name} on:error={() => onAssetError(assetKey(far!, 'front'))} />
                {:else}
                  <div class="placeholder"><span>{far.active.name.slice(0, 1)}</span><small>NO SPRITE</small></div>
                {/if}
              </div>
            {/key}
          </div>
          <div class="vitals"><div><strong>{far.active.name}</strong>{#if far.active.status}<span class="status">{far.active.status}</span>{/if}</div><span>{Math.round(far.active.hp_fraction * 100)}%</span></div>
          <div class="hp-track" data-tone={hpTone(far.active.hp_fraction)}><i style={`width:${far.active.hp_fraction * 100}%`}></i></div>
        </article>
      {/if}

      <div class="battle-center">
        <span class="pulse-ring"></span>
        {#if presentation.currentMove}<small>LAST ACTION</small><strong>{presentation.currentMove}</strong>{:else}<strong>VS</strong>{/if}
      </div>

      {#if near?.active}
        <article class="combatant combatant-near" aria-label={`${near.active.name}, ${Math.round(near.active.hp_fraction * 100)} percent health`}>
          <div class="identity"><span>{near.active.types.join(' · ')}</span><strong>{near.active.name}</strong></div>
          <div class="sprite-platform">
            {#key `${presentation.eventSequence}:${nearSide}:${presentation.players[nearSide].motion}`}
              <div class={`sprite ${presentation.players[nearSide].motion}`}>
                {#if !failedAssets.has(assetKey(near, 'back'))}
                  <img src={pokemonAssetUrl(near.active.species, 'back', config.animatedSprites)} alt={near.active.name} on:error={() => onAssetError(assetKey(near!, 'back'))} />
                {:else}
                  <div class="placeholder"><span>{near.active.name.slice(0, 1)}</span><small>NO SPRITE</small></div>
                {/if}
              </div>
            {/key}
          </div>
          <div class="vitals"><div><strong>{near.active.name}</strong>{#if near.active.status}<span class="status">{near.active.status}</span>{/if}</div><span>{Math.round(near.active.hp_fraction * 100)}%</span></div>
          <div class="hp-track" data-tone={hpTone(near.active.hp_fraction)}><i style={`width:${near.active.hp_fraction * 100}%`}></i></div>
        </article>
      {/if}

      {#key `${presentation.eventSequence}:${presentation.effect}`}
        {#if presentation.effect !== 'none'}<div class={`effect effect-${presentation.effect}`}><span>{presentation.effect.replace('-', ' ')}</span></div>{/if}
      {/key}
    </div>

    {#if config.showBattleLog}
      <aside class="battle-log" aria-label="Spectator battle feed" aria-live="polite">
        <header><span>LIVE FEED</span><small>EVENT #{presentation.eventSequence}</small></header>
        {#each presentation.log.slice(-5) as entry}
          <p data-emphasis={entry.emphasis}><span>{entry.turn}</span>{entry.text}</p>
        {/each}
        {#if presentation.log.length === 0}<p class="muted"><span>—</span>Battle feed ready.</p>{/if}
      </aside>
    {/if}

    {#if presentation.finished}
      <div class="winner-banner" role="status"><small>BATTLE COMPLETE</small><strong>{presentation.winnerName || presentation.battle?.result?.winner_name || 'DRAW'}</strong><span>{presentation.winner || '—'}</span></div>
    {/if}
  </section>
{:else}
  <section class="renderer-loading panel"><span class="eyebrow">Renderer ready</span><h2>Waiting for normalized battle state…</h2><p>No engine connection is required to draw this frame.</p></section>
{/if}

<style>
  .battle-renderer{--r-panel:rgba(10,21,14,.88);--r-text:#f5fff7;--r-muted:#96aa9b;--r-line:rgba(255,255,255,.12);--r-accent:#8cf2a7;--r-accent-ink:#06160b;--r-p1:#72e39a;--r-p2:#d09bff;position:relative;isolation:isolate;display:grid;grid-template-columns:minmax(220px,.78fr) minmax(480px,2fr) minmax(220px,.78fr);grid-template-rows:auto 1fr auto;gap:clamp(10px,1.2vw,22px);width:100%;aspect-ratio:16/9;min-height:520px;overflow:hidden;padding:clamp(18px,2.4vw,44px);border:1px solid var(--r-line);border-radius:clamp(18px,2vw,32px);background:radial-gradient(circle at 50% 40%,rgba(76,180,111,.16),transparent 35%),linear-gradient(145deg,#07120c,#0c1810 48%,#08100b);color:var(--r-text);box-shadow:0 40px 120px rgba(0,0,0,.35);font-family:var(--display)}
  .battle-renderer[data-renderer-theme='koala-light']{--r-panel:rgba(255,255,255,.88);--r-text:#132418;--r-muted:#617166;--r-line:rgba(24,58,35,.14);--r-accent:#187a40;--r-accent-ink:#fff;background:radial-gradient(circle at 50% 35%,rgba(57,181,100,.16),transparent 38%),linear-gradient(145deg,#f8fcf9,#e5f1e8 52%,#f3f7f4)}
  .battle-renderer.transparent{background:transparent!important;border-color:transparent;box-shadow:none}.ambient{position:absolute;z-index:-2;inset:0;background:linear-gradient(115deg,color-mix(in srgb,var(--r-p1) 8%,transparent),transparent 32%,color-mix(in srgb,var(--r-p2) 8%,transparent));pointer-events:none}.scoreboard{grid-column:1/-1;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding-bottom:clamp(8px,1vw,16px);border-bottom:1px solid var(--r-line);letter-spacing:.08em}.brand-lockup{display:flex;align-items:center;gap:.7rem;font-size:clamp(.66rem,.8vw,.82rem)}.brand-lockup span{display:grid;place-items:center;width:34px;aspect-ratio:1;border-radius:10px;background:var(--r-accent);color:var(--r-accent-ink);font:800 .68rem var(--mono)}.turn{text-align:center;color:var(--r-muted);font:600 clamp(.62rem,.8vw,.76rem) var(--mono)}.turn strong{margin-left:.35rem;color:var(--r-text);font-size:1.35em}.format{text-align:right;color:var(--r-muted);font:500 clamp(.55rem,.7vw,.7rem) var(--mono)}.player-card{position:relative;align-self:stretch;padding:clamp(14px,1.6vw,24px);border:1px solid var(--r-line);border-radius:18px;background:var(--r-panel);backdrop-filter:blur(16px)}.player-card[data-side='p1']{box-shadow:inset 3px 0 var(--r-p1)}.player-card[data-side='p2']{box-shadow:inset 3px 0 var(--r-p2)}.player-card h2{margin:.28rem 0;font-size:clamp(1rem,1.6vw,1.55rem);line-height:1}.side{color:var(--r-muted);font:600 .56rem var(--mono);text-transform:uppercase}.player-card small{color:var(--r-muted);font:.6rem var(--mono)}.agent-state{position:absolute;top:16px;right:16px;padding:.3rem .45rem;border:1px solid var(--r-line);border-radius:999px;color:var(--r-accent);font:600 .52rem var(--mono);text-transform:uppercase}.commentary{margin-top:1.1rem}.commentary p{margin:.45rem 0;color:var(--r-text);font-size:clamp(.65rem,.85vw,.85rem);line-height:1.5}.commentary .muted,.muted{color:var(--r-muted);font-style:italic}.player-far{grid-column:1;grid-row:2}.player-near{grid-column:3;grid-row:2}.arena-stage{position:relative;grid-column:2;grid-row:2;min-height:350px;overflow:hidden;border:1px solid var(--r-line);border-radius:22px;background:radial-gradient(ellipse at center bottom,rgba(120,255,163,.13),transparent 48%),linear-gradient(180deg,rgba(255,255,255,.035),rgba(0,0,0,.1))}.arena-grid{position:absolute;inset:0;opacity:.22;background-image:linear-gradient(var(--r-line) 1px,transparent 1px),linear-gradient(90deg,var(--r-line) 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(transparent,black 30%,black)}.combatant{position:absolute;width:min(45%,310px)}.combatant-far{top:5%;right:5%}.combatant-near{bottom:5%;left:5%}.identity{display:flex;justify-content:space-between;gap:.5rem;margin-bottom:.4rem;color:var(--r-muted);font:.54rem var(--mono);text-transform:uppercase}.identity strong{overflow:hidden;color:var(--r-text);text-overflow:ellipsis}.sprite-platform{position:relative;display:grid;place-items:center;aspect-ratio:1.6/1;border-radius:50%;background:radial-gradient(ellipse,rgba(255,255,255,.14),transparent 65%)}.sprite{display:grid;place-items:center;width:62%;height:85%;transform-origin:center bottom}.sprite img{display:block;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 16px 15px rgba(0,0,0,.38))}.placeholder{display:grid;place-items:center;width:100%;height:100%;border:1px solid var(--r-line);border-radius:50% 50% 44% 44%;background:radial-gradient(circle at 38% 30%,color-mix(in srgb,var(--r-accent) 22%,transparent),transparent 38%),var(--r-panel);box-shadow:inset 0 0 40px rgba(255,255,255,.04)}.placeholder span{font-size:clamp(2rem,5vw,5rem);font-weight:800;opacity:.9}.placeholder small{position:absolute;bottom:12%;color:var(--r-muted);font:.45rem var(--mono);letter-spacing:.15em}.vitals{display:flex;justify-content:space-between;gap:.5rem;margin-top:.4rem;font-size:clamp(.66rem,.9vw,.88rem)}.vitals>div{display:flex;align-items:center;gap:.45rem}.status{padding:.15rem .3rem;border:1px solid currentColor;border-radius:4px;color:#ffce62;font:.52rem var(--mono);text-transform:uppercase}.hp-track{height:7px;margin-top:.35rem;overflow:hidden;border-radius:999px;background:rgba(0,0,0,.34)}.hp-track i{display:block;width:0;height:100%;border-radius:inherit;background:#60dc84;transition:width var(--hp-duration) cubic-bezier(.2,.8,.2,1),background var(--hp-duration)}.hp-track[data-tone='mid'] i{background:#f0bc4f}.hp-track[data-tone='low'] i{background:#ff716c}.battle-center{position:absolute;top:50%;left:50%;display:grid;place-items:center;width:120px;aspect-ratio:1;transform:translate(-50%,-50%);text-align:center}.battle-center small{color:var(--r-muted);font:.5rem var(--mono);letter-spacing:.13em}.battle-center strong{z-index:1;max-width:120px;font-size:clamp(.72rem,1vw,1rem);line-height:1.15}.pulse-ring{position:absolute;inset:10%;border:1px solid var(--r-accent);border-radius:50%;opacity:.28;animation:pulse 2.8s infinite}.effect{position:absolute;z-index:8;inset:0;display:grid;place-items:center;pointer-events:none}.effect span{padding:.45rem .8rem;border:1px solid var(--r-line);border-radius:999px;background:var(--r-panel);color:var(--r-text);font:800 clamp(.65rem,1vw,.9rem) var(--mono);letter-spacing:.12em;text-transform:uppercase;animation:effect-pop .55s both}.effect-critical-hit span{border-color:#ffd262;color:#ffd262;box-shadow:0 0 50px rgba(255,202,85,.25)}.effect-healing span{color:#89f2a6}.effect-miss span{color:var(--r-muted)}.winner-banner{position:absolute;z-index:15;inset:0;display:grid;place-content:center;text-align:center;background:rgba(4,10,6,.78);color:#f5fff7;backdrop-filter:blur(12px);animation:winner-in .7s both}.winner-banner small{color:#8cf2a7;font:.62rem var(--mono);letter-spacing:.22em}.winner-banner strong{margin:.4rem 0;color:#f5fff7;font-size:clamp(2rem,6vw,6rem);line-height:.9;letter-spacing:-.06em}.winner-banner span{color:#b7c5ba;font:.7rem var(--mono);text-transform:uppercase}.battle-log{grid-column:1/-1;display:grid;grid-template-columns:1.2fr repeat(5,minmax(0,1fr));gap:1px;min-height:62px;overflow:hidden;border:1px solid var(--r-line);border-radius:14px;background:var(--r-line)}.battle-log>*{margin:0;padding:.7rem;background:var(--r-panel)}.battle-log header{display:grid;align-content:center}.battle-log header span{color:var(--r-accent);font:700 .57rem var(--mono);letter-spacing:.12em}.battle-log header small{margin-top:.25rem;color:var(--r-muted);font:.48rem var(--mono)}.battle-log p{display:flex;gap:.5rem;align-items:center;color:var(--r-muted);font-size:clamp(.5rem,.65vw,.65rem);line-height:1.3}.battle-log p span{color:var(--r-accent);font:.52rem var(--mono)}.battle-log p[data-emphasis='critical']{color:#ffd262}.battle-log p[data-emphasis='positive']{color:#8cf2a7}.battle-log p[data-emphasis='negative']{color:#ff9d98}.sprite.attacking{animation:attack .5s cubic-bezier(.2,.8,.2,1)}.combatant-near .sprite.attacking{animation-name:attack-near}.sprite.taking-damage{animation:hit .42s}.sprite.switching-in{animation:switch-in .62s}.sprite.switching-out{animation:switch-out .5s}.sprite.fainting{animation:faint .75s both}.sprite.status-flash{animation:status-flash .45s}.sprite.idle{animation:idle 3.4s ease-in-out infinite}
  .battle-renderer[data-layout='standard-vertical']{grid-template-columns:1fr;grid-template-rows:auto auto minmax(520px,1fr) auto auto;width:min(100%,620px);aspect-ratio:9/16;min-height:900px;margin-inline:auto;padding:24px}.battle-renderer[data-layout='standard-vertical'] .scoreboard{grid-column:1;grid-row:1}.battle-renderer[data-layout='standard-vertical'] .player-far{grid-column:1;grid-row:2;min-height:142px}.battle-renderer[data-layout='standard-vertical'] .arena-stage{grid-column:1;grid-row:3;min-height:520px}.battle-renderer[data-layout='standard-vertical'] .player-near{grid-column:1;grid-row:4;min-height:142px}.battle-renderer[data-layout='standard-vertical'] .battle-log{grid-column:1;grid-row:5;grid-template-columns:1fr}.battle-renderer[data-layout='standard-vertical'] .battle-log p{display:none}.battle-renderer[data-layout='standard-vertical'] .battle-log p:nth-last-child(-n+2){display:flex}.battle-renderer[data-layout='standard-vertical'] .combatant{width:54%}.battle-renderer[data-layout='standard-vertical'] .combatant-far{top:4%;right:3%}.battle-renderer[data-layout='standard-vertical'] .combatant-near{bottom:4%;left:3%}.battle-renderer[data-layout='standard-vertical'] .format{display:none}.battle-renderer[data-layout='standard-vertical'] .scoreboard{grid-template-columns:1fr auto}.battle-renderer[data-layout='standard-vertical'] .turn{text-align:right}.battle-renderer[data-layout='overlay-landscape']{border-radius:0}.battle-renderer.overlay{width:100vw;height:100vh;min-height:0;aspect-ratio:auto;border-radius:0}.battle-renderer.overlay[data-layout='standard-vertical']{width:100vw;max-width:none;height:100vh;min-height:0;margin:0}.renderer-loading{display:grid;place-content:center;min-height:420px;padding:2rem;text-align:center}.renderer-loading h2{margin:.5rem 0}.renderer-loading p{color:var(--muted)}
  @keyframes idle{50%{transform:translateY(-3%) scale(1.015)}}@keyframes attack{45%{transform:translate(-12%,-7%) scale(1.08)}}@keyframes attack-near{45%{transform:translate(12%,7%) scale(1.08)}}@keyframes hit{20%,60%{transform:translateX(-7%);filter:brightness(1.8)}40%,80%{transform:translateX(7%)}}@keyframes switch-in{from{opacity:0;transform:translateY(-15%) scale(.72);filter:blur(8px)}}@keyframes switch-out{to{opacity:0;transform:translateY(15%) scale(.72);filter:blur(8px)}}@keyframes faint{to{opacity:0;transform:translateY(25%) rotate(5deg) scale(.78);filter:grayscale(1) blur(5px)}}@keyframes status-flash{50%{filter:drop-shadow(0 0 22px #ffd05d) brightness(1.4)}}@keyframes pulse{50%{transform:scale(1.18);opacity:.08}}@keyframes effect-pop{from{opacity:0;transform:scale(.7)}35%{opacity:1;transform:scale(1.08)}to{opacity:0;transform:scale(1.2)}}@keyframes winner-in{from{opacity:0;clip-path:inset(50% 0)}to{opacity:1;clip-path:inset(0)}}
  @media(max-width:900px){.battle-renderer:not([data-layout='standard-vertical']){grid-template-columns:1fr 1fr;grid-template-rows:auto minmax(420px,1fr) auto auto;aspect-ratio:auto;min-height:760px}.battle-renderer:not([data-layout='standard-vertical']) .scoreboard{grid-column:1/-1}.battle-renderer:not([data-layout='standard-vertical']) .arena-stage{grid-column:1/-1;grid-row:2}.battle-renderer:not([data-layout='standard-vertical']) .player-far{grid-column:1;grid-row:3}.battle-renderer:not([data-layout='standard-vertical']) .player-near{grid-column:2;grid-row:3}.battle-renderer:not([data-layout='standard-vertical']) .battle-log{grid-column:1/-1;grid-row:4;grid-template-columns:1fr 1fr}.battle-renderer:not([data-layout='standard-vertical']) .battle-log p:nth-of-type(-n+3){display:none}}
  @media(max-width:560px){.battle-renderer{padding:14px;border-radius:16px}.battle-renderer:not([data-layout='standard-vertical']){grid-template-columns:1fr;grid-template-rows:auto 390px auto auto auto;min-height:850px}.battle-renderer:not([data-layout='standard-vertical']) .player-far{grid-column:1;grid-row:3}.battle-renderer:not([data-layout='standard-vertical']) .player-near{grid-column:1;grid-row:4}.battle-renderer:not([data-layout='standard-vertical']) .battle-log{grid-column:1;grid-row:5}.brand-lockup strong,.format{display:none}.combatant{width:52%}.arena-stage{min-height:390px}.commentary{margin-top:.6rem}.player-card{min-height:125px}}
  @media(prefers-reduced-motion:reduce){.sprite,.pulse-ring,.effect span,.winner-banner{animation-duration:.001ms!important;animation-iteration-count:1!important}.hp-track i{transition-duration:.001ms!important}}
</style>
