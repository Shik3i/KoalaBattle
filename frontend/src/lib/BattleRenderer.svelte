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
  export let deterministic = false;
  export let logicalElapsedMs = 0;
  export let visualProgress = 0;

  let failedAssets = new Set<string>();
  let nearSide: Side = 'p1';
  let farSide: Side = 'p2';
  const particleIndexes = Array.from({ length: 12 }, (_, index) => index);

  $: nearSide = config.nearSide;
  $: farSide = nearSide === 'p1' ? 'p2' : 'p1';
  $: near = presentation ? battleSide(presentation, nearSide) : null;
  $: far = presentation ? battleSide(presentation, farSide) : null;
  $: nearCommentary = commentary(presentation, nearSide, config.commentaryMode);
  $: farCommentary = commentary(presentation, farSide, config.commentaryMode);
  $: attackerSide = presentation
    ? (['p1', 'p2'] as Side[]).find((side) => presentation?.players[side].motion === 'attacking') || null
    : null;
  $: moveProfile = attackerSide ? presentation?.currentMoveProfile || null : null;
  $: strongImpact = Boolean(
    presentation && ['impact', 'critical-hit', 'super-effective'].includes(presentation.effect)
  );
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

  function previousHp(side: Side, fraction: number) {
    if (!presentation || presentation.effectSide !== side || presentation.effectValue === null) return fraction;
    return Math.max(0, Math.min(1, fraction - presentation.effectValue / 100));
  }

  function particleStyle(index: number, seed: number) {
    const angle = ((seed % 360) + index * 137.508) * Math.PI / 180;
    const distance = 42 + ((seed >>> (index % 16)) % 54);
    const x = Math.round(Math.cos(angle) * distance);
    const y = Math.round(Math.sin(angle) * distance);
    if (!deterministic) return `--particle-x:${x}px;--particle-y:${y}px;--particle-delay:${index * -23}ms`;
    const progress = Math.max(0, Math.min(1, visualProgress));
    return `--particle-x:${x}px;--particle-y:${y}px;transform:translate(${x * progress}px,${y * progress}px) rotate(${150 * progress}deg) scale(${1 - progress * .85});opacity:${1 - progress}`;
  }

  function spriteStyle(motion: string, near: boolean) {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const pulse = Math.sin(progress * Math.PI);
    if (motion === 'idle') {
      const idle = Math.sin(logicalElapsedMs / 3400 * Math.PI * 2);
      return `transform:translateY(${idle * -3}%) scale(${1 + Math.max(0, idle) * .015})`;
    }
    if (motion === 'attacking') return `transform:translate(${(near ? 12 : -12) * pulse}%,${(near ? 7 : -7) * pulse}%) scale(${1 + .08 * pulse})`;
    if (motion === 'taking-damage') return `transform:translateX(${Math.sin(progress * Math.PI * 8) * (1 - progress) * 7}%);filter:brightness(${1 + pulse * .8})`;
    if (motion === 'switching-in') return `opacity:${progress};transform:translateY(${(1 - progress) * -15}%) scale(${.72 + progress * .28})`;
    if (motion === 'switching-out') return `opacity:${1 - progress};transform:translateY(${progress * 15}%) scale(${1 - progress * .28})`;
    if (motion === 'fainting') return `opacity:${1 - progress};transform:translateY(${progress * 25}%) rotate(${progress * 5}deg) scale(${1 - progress * .22});filter:grayscale(${progress})`;
    if (motion === 'status-flash') return `filter:brightness(${1 + pulse * .45}) drop-shadow(0 0 ${pulse * 22}px #ffd05d)`;
    return '';
  }

  function projectileStyle(direction: 'near-to-far' | 'far-to-near') {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const nearToFar = direction === 'near-to-far';
    const origin = nearToFar ? [27, 72] : [73, 29];
    const target = nearToFar ? [73, 29] : [27, 72];
    const x = origin[0] + (target[0] - origin[0]) * progress;
    const y = origin[1] + (target[1] - origin[1]) * progress;
    return `left:${x}%;top:${y}%;opacity:${Math.sin(progress * Math.PI)};transform:translate(-50%,-50%) scale(${.45 + progress * .9})`;
  }

  function arenaStyle() {
    if (!deterministic || !strongImpact || config.reducedMotion) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const strength = (1 - progress) * Math.sin(progress * Math.PI * 8) * .45;
    return `transform:translate(${strength}%,${strength * -.55}%)`;
  }

  function transientStyle() {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const opacity = progress < .18 ? progress / .18 : Math.max(0, 1 - (progress - .62) / .38);
    return `opacity:${opacity};transform:scale(${.78 + progress * .38})`;
  }

  function chargeStyle() {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    return `opacity:${Math.sin(progress * Math.PI)};transform:translate(-50%,-50%) scale(${1.45 - progress})`;
  }

  function beamStyle(direction: 'near-to-far' | 'far-to-near') {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const angle = direction === 'near-to-far' ? -43 : 137;
    return `opacity:${Math.sin(progress * Math.PI)};transform:rotate(${angle}deg) scaleX(${Math.min(1, progress * 3)})`;
  }

  function readableStatus(status: string) {
    const labels: Record<string, string> = {
      brn: 'Burned', par: 'Paralyzed', psn: 'Poisoned', tox: 'Badly poisoned',
      slp: 'Asleep', frz: 'Frozen'
    };
    return labels[status.toLowerCase()] || status;
  }
</script>

{#if presentation}
  <section
    class:overlay
    class:transparent={config.transparentBackground}
    class:deterministic
    class:reduced-motion={config.reducedMotion}
    class="battle-renderer"
    data-layout={config.layout}
    data-renderer-theme={config.theme}
    style={`--hp-duration:${hpDuration}ms;--logical-elapsed:-${logicalElapsedMs}ms`}
    aria-label="KoalaBattle production renderer"
  >
    <div class="ambient" aria-hidden="true"></div>
    <header class="scoreboard">
      <div class="brand-lockup"><span>KB</span><strong>KOALA BATTLE</strong></div>
      {#if config.showTurn}<div class="turn">TURN <strong>{presentation.battle?.turn ?? 0}</strong></div>{/if}
      <div class="format">{presentation.format === 'gen9ou' ? 'GEN 9 · OU' : 'GEN 9 · RANDOM BATTLE'}</div>
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

    <div style={arenaStyle()} class:arena-shake={strongImpact && config.effects !== 'off' && !config.reducedMotion} class="arena-stage">
      <div class="arena-grid" aria-hidden="true"></div>
      {#if presentation.battle?.weather.length}
        <div class="weather-layer" data-weather={presentation.battle.weather[0]} aria-hidden="true"><i></i><i></i><i></i></div>
      {/if}
      {#if presentation.battle?.fields.length}
        <div class="terrain-layer" data-terrain={presentation.battle.fields[0]} aria-hidden="true"></div>
      {/if}
      <div class="field-state field-far" aria-label={`${farSide} field conditions`}>
        {#each far?.side_conditions || [] as condition}<span>{condition.replaceAll('_', ' ')}</span>{/each}
      </div>
      <div class="field-state field-near" aria-label={`${nearSide} field conditions`}>
        {#each near?.side_conditions || [] as condition}<span>{condition.replaceAll('_', ' ')}</span>{/each}
      </div>
      {#if far?.active}
        <article class="combatant combatant-far" aria-label={`${far.active.name}, ${Math.round(far.active.hp_fraction * 100)} percent health`}>
          <div class="identity"><span>{far.active.types.join(' · ')}</span><strong>{far.active.name}</strong></div>
          <div class="sprite-platform">
            {#key `${presentation.eventSequence}:${farSide}:${presentation.players[farSide].motion}`}
              <div style={spriteStyle(presentation.players[farSide].motion, false)} class={`sprite ${presentation.players[farSide].motion}`}>
                {#if !failedAssets.has(assetKey(far, 'front'))}
                  <img src={pokemonAssetUrl(far.active.species, 'front', config.animatedSprites)} alt={far.active.name} on:error={() => onAssetError(assetKey(far!, 'front'))} />
                {:else}
                  <div class="placeholder"><span>{far.active.name.slice(0, 1)}</span><small>NO SPRITE</small></div>
                {/if}
              </div>
            {/key}
          </div>
          <div class="vitals"><div><strong>{far.active.name}</strong>{#if far.active.status}<span class="status" title={readableStatus(far.active.status)}>{far.active.status}<small>{readableStatus(far.active.status)}</small></span>{/if}</div><span>{Math.round(far.active.hp_fraction * 100)}%</span></div>
          <div class="hp-track" data-tone={hpTone(far.active.hp_fraction)}><b style={`width:${previousHp(farSide, far.active.hp_fraction) * 100}%`}></b><i style={`width:${far.active.hp_fraction * 100}%`}></i></div>
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
              <div style={spriteStyle(presentation.players[nearSide].motion, true)} class={`sprite ${presentation.players[nearSide].motion}`}>
                {#if !failedAssets.has(assetKey(near, 'back'))}
                  <img src={pokemonAssetUrl(near.active.species, 'back', config.animatedSprites)} alt={near.active.name} on:error={() => onAssetError(assetKey(near!, 'back'))} />
                {:else}
                  <div class="placeholder"><span>{near.active.name.slice(0, 1)}</span><small>NO SPRITE</small></div>
                {/if}
              </div>
            {/key}
          </div>
          <div class="vitals"><div><strong>{near.active.name}</strong>{#if near.active.status}<span class="status" title={readableStatus(near.active.status)}>{near.active.status}<small>{readableStatus(near.active.status)}</small></span>{/if}</div><span>{Math.round(near.active.hp_fraction * 100)}%</span></div>
          <div class="hp-track" data-tone={hpTone(near.active.hp_fraction)}><b style={`width:${previousHp(nearSide, near.active.hp_fraction) * 100}%`}></b><i style={`width:${near.active.hp_fraction * 100}%`}></i></div>
        </article>
      {/if}

      {#if moveProfile && config.effects !== 'off'}
        <div
          class="move-visual"
          data-archetype={moveProfile.archetype}
          data-move-type={moveProfile.type}
          data-direction={attackerSide === nearSide ? 'near-to-far' : 'far-to-near'}
          data-quality={config.effects}
          aria-hidden="true"
        >
          <div style={chargeStyle()} class="charge-ring"></div><div style={projectileStyle(attackerSide === nearSide ? 'near-to-far' : 'far-to-near')} class="move-projectile"></div><div style={beamStyle(attackerSide === nearSide ? 'near-to-far' : 'far-to-near')} class="move-beam"></div>
        </div>
      {/if}

      {#key `${presentation.eventSequence}:${presentation.effect}`}
        {#if presentation.effect !== 'none'}
          <div class={`effect effect-${presentation.effect}`} data-side={presentation.effectSide || ''} data-move-type={presentation.currentMoveProfile?.type || 'normal'}>
            {#if config.effects !== 'off'}<div class="impact-burst" aria-hidden="true">{#each particleIndexes.slice(0, config.effects === 'low' ? 6 : config.effects === 'high' ? 12 : 9) as index}<i style={particleStyle(index, presentation.currentMoveProfile?.seed || presentation.eventSequence)}></i>{/each}</div>{/if}
            <span style={transientStyle()}>{presentation.effect === 'super-effective' ? 'SUPER EFFECTIVE' : presentation.effect === 'resisted' ? 'NOT VERY EFFECTIVE' : presentation.effect === 'immune' ? 'NO EFFECT' : presentation.effect.replace('-', ' ')}</span>
            {#if config.showDamageNumbers && presentation.effectValue !== null}<strong style={transientStyle()} class:positive={presentation.effectValue > 0}>{presentation.effectValue > 0 ? '+' : ''}{presentation.effectValue}%</strong>{/if}
          </div>
        {/if}
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
  .battle-renderer.deterministic .sprite,.battle-renderer.deterministic .pulse-ring,.battle-renderer.deterministic .effect span,.battle-renderer.deterministic .effect strong,.battle-renderer.deterministic .impact-burst i,.battle-renderer.deterministic .move-projectile,.battle-renderer.deterministic .move-beam,.battle-renderer.deterministic .charge-ring,.battle-renderer.deterministic .arena-shake,.battle-renderer.deterministic .weather-layer,.battle-renderer.deterministic .winner-banner{animation:none!important}.battle-renderer.deterministic .hp-track i{transition:none!important}
  .battle-renderer.transparent{background:transparent!important;border-color:transparent;box-shadow:none}.ambient{position:absolute;z-index:-2;inset:0;background:linear-gradient(115deg,color-mix(in srgb,var(--r-p1) 8%,transparent),transparent 32%,color-mix(in srgb,var(--r-p2) 8%,transparent));pointer-events:none}.scoreboard{grid-column:1/-1;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding-bottom:clamp(8px,1vw,16px);border-bottom:1px solid var(--r-line);letter-spacing:.08em}.brand-lockup{display:flex;align-items:center;gap:.7rem;font-size:clamp(.66rem,.8vw,.82rem)}.brand-lockup span{display:grid;place-items:center;width:34px;aspect-ratio:1;border-radius:10px;background:var(--r-accent);color:var(--r-accent-ink);font:800 .68rem var(--mono)}.turn{text-align:center;color:var(--r-muted);font:600 clamp(.62rem,.8vw,.76rem) var(--mono)}.turn strong{margin-left:.35rem;color:var(--r-text);font-size:1.35em}.format{text-align:right;color:var(--r-muted);font:500 clamp(.55rem,.7vw,.7rem) var(--mono)}.player-card{position:relative;align-self:stretch;padding:clamp(14px,1.6vw,24px);border:1px solid var(--r-line);border-radius:18px;background:var(--r-panel);backdrop-filter:blur(16px)}.player-card[data-side='p1']{box-shadow:inset 3px 0 var(--r-p1)}.player-card[data-side='p2']{box-shadow:inset 3px 0 var(--r-p2)}.player-card h2{margin:.28rem 0;font-size:clamp(1rem,1.6vw,1.55rem);line-height:1}.side{color:var(--r-muted);font:600 .56rem var(--mono);text-transform:uppercase}.player-card small{color:var(--r-muted);font:.6rem var(--mono)}.agent-state{position:absolute;top:16px;right:16px;padding:.3rem .45rem;border:1px solid var(--r-line);border-radius:999px;color:var(--r-accent);font:600 .52rem var(--mono);text-transform:uppercase}.commentary{margin-top:1.1rem}.commentary p{margin:.45rem 0;color:var(--r-text);font-size:clamp(.65rem,.85vw,.85rem);line-height:1.5}.commentary .muted,.muted{color:var(--r-muted);font-style:italic}.player-far{grid-column:1;grid-row:2}.player-near{grid-column:3;grid-row:2}.arena-stage{position:relative;grid-column:2;grid-row:2;min-height:350px;overflow:hidden;border:1px solid var(--r-line);border-radius:22px;background:radial-gradient(ellipse at center bottom,rgba(120,255,163,.13),transparent 48%),linear-gradient(180deg,rgba(255,255,255,.035),rgba(0,0,0,.1))}.arena-grid{position:absolute;inset:0;opacity:.22;background-image:linear-gradient(var(--r-line) 1px,transparent 1px),linear-gradient(90deg,var(--r-line) 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(transparent,black 30%,black)}.combatant{position:absolute;width:min(45%,310px)}.combatant-far{top:5%;right:5%}.combatant-near{bottom:5%;left:5%}.identity{display:flex;justify-content:space-between;gap:.5rem;margin-bottom:.4rem;color:var(--r-muted);font:.54rem var(--mono);text-transform:uppercase}.identity strong{overflow:hidden;color:var(--r-text);text-overflow:ellipsis}.sprite-platform{position:relative;display:grid;place-items:center;aspect-ratio:1.6/1;border-radius:50%;background:radial-gradient(ellipse,rgba(255,255,255,.14),transparent 65%)}.sprite{display:grid;place-items:center;width:62%;height:85%;transform-origin:center bottom}.sprite img{display:block;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 16px 15px rgba(0,0,0,.38))}.placeholder{display:grid;place-items:center;width:100%;height:100%;border:1px solid var(--r-line);border-radius:50% 50% 44% 44%;background:radial-gradient(circle at 38% 30%,color-mix(in srgb,var(--r-accent) 22%,transparent),transparent 38%),var(--r-panel);box-shadow:inset 0 0 40px rgba(255,255,255,.04)}.placeholder span{font-size:clamp(2rem,5vw,5rem);font-weight:800;opacity:.9}.placeholder small{position:absolute;bottom:12%;color:var(--r-muted);font:.45rem var(--mono);letter-spacing:.15em}.vitals{display:flex;justify-content:space-between;gap:.5rem;margin-top:.4rem;font-size:clamp(.66rem,.9vw,.88rem)}.vitals>div{display:flex;align-items:center;gap:.45rem}.status{padding:.15rem .3rem;border:1px solid currentColor;border-radius:4px;color:#ffce62;font:.52rem var(--mono);text-transform:uppercase}.hp-track{height:7px;margin-top:.35rem;overflow:hidden;border-radius:999px;background:rgba(0,0,0,.34)}.hp-track i{display:block;width:0;height:100%;border-radius:inherit;background:#60dc84;transition:width var(--hp-duration) cubic-bezier(.2,.8,.2,1),background var(--hp-duration)}.hp-track[data-tone='mid'] i{background:#f0bc4f}.hp-track[data-tone='low'] i{background:#ff716c}.battle-center{position:absolute;top:50%;left:50%;display:grid;place-items:center;width:120px;aspect-ratio:1;transform:translate(-50%,-50%);text-align:center}.battle-center small{color:var(--r-muted);font:.5rem var(--mono);letter-spacing:.13em}.battle-center strong{z-index:1;max-width:120px;font-size:clamp(.72rem,1vw,1rem);line-height:1.15}.pulse-ring{position:absolute;inset:10%;border:1px solid var(--r-accent);border-radius:50%;opacity:.28;animation:pulse 2.8s infinite}.effect{position:absolute;z-index:8;inset:0;display:grid;place-items:center;pointer-events:none}.effect span{padding:.45rem .8rem;border:1px solid var(--r-line);border-radius:999px;background:var(--r-panel);color:var(--r-text);font:800 clamp(.65rem,1vw,.9rem) var(--mono);letter-spacing:.12em;text-transform:uppercase;animation:effect-pop .55s both}.effect-critical-hit span{border-color:#ffd262;color:#ffd262;box-shadow:0 0 50px rgba(255,202,85,.25)}.effect-healing span{color:#89f2a6}.effect-miss span{color:var(--r-muted)}.winner-banner{position:absolute;z-index:15;inset:0;display:grid;place-content:center;text-align:center;background:rgba(4,10,6,.78);color:#f5fff7;backdrop-filter:blur(12px);animation:winner-in .7s both}.winner-banner small{color:#8cf2a7;font:.62rem var(--mono);letter-spacing:.22em}.winner-banner strong{margin:.4rem 0;color:#f5fff7;font-size:clamp(2rem,6vw,6rem);line-height:.9;letter-spacing:-.06em}.winner-banner span{color:#b7c5ba;font:.7rem var(--mono);text-transform:uppercase}.battle-log{grid-column:1/-1;display:grid;grid-template-columns:1.2fr repeat(5,minmax(0,1fr));gap:1px;min-height:62px;overflow:hidden;border:1px solid var(--r-line);border-radius:14px;background:var(--r-line)}.battle-log>*{margin:0;padding:.7rem;background:var(--r-panel)}.battle-log header{display:grid;align-content:center}.battle-log header span{color:var(--r-accent);font:700 .57rem var(--mono);letter-spacing:.12em}.battle-log header small{margin-top:.25rem;color:var(--r-muted);font:.48rem var(--mono)}.battle-log p{display:flex;gap:.5rem;align-items:center;color:var(--r-muted);font-size:clamp(.5rem,.65vw,.65rem);line-height:1.3}.battle-log p span{color:var(--r-accent);font:.52rem var(--mono)}.battle-log p[data-emphasis='critical']{color:#ffd262}.battle-log p[data-emphasis='positive']{color:#8cf2a7}.battle-log p[data-emphasis='negative']{color:#ff9d98}.sprite.attacking{animation:attack .5s cubic-bezier(.2,.8,.2,1)}.combatant-near .sprite.attacking{animation-name:attack-near}.sprite.taking-damage{animation:hit .42s}.sprite.switching-in{animation:switch-in .62s}.sprite.switching-out{animation:switch-out .5s}.sprite.fainting{animation:faint .75s both}.sprite.status-flash{animation:status-flash .45s}.sprite.idle{animation:idle 3.4s ease-in-out infinite}
  .hp-track{position:relative}.hp-track b,.hp-track i{position:absolute;inset:0 auto 0 0;display:block;border-radius:inherit}.hp-track b{background:#fff1a8;opacity:.78;transition:width calc(var(--hp-duration) * 1.45) ease-out}.hp-track i{z-index:1}.status{display:inline-flex;align-items:center;gap:.25rem}.status small{display:none}
  .field-state{position:absolute;z-index:5;display:flex;flex-wrap:wrap;gap:.25rem;max-width:42%}.field-state span{padding:.22rem .38rem;border:1px solid color-mix(in srgb,var(--r-accent) 45%,var(--r-line));border-radius:999px;background:var(--r-panel);color:var(--r-muted);font:600 .42rem var(--mono);text-transform:uppercase}.field-far{top:2.5%;left:2.5%}.field-near{right:2.5%;bottom:2.5%;justify-content:flex-end}
  .terrain-layer{position:absolute;inset:48% 5% 3%;border-radius:50%;background:radial-gradient(ellipse,color-mix(in srgb,var(--type-color,#78e09a) 20%,transparent),transparent 68%);opacity:.8}.weather-layer{position:absolute;z-index:1;inset:0;overflow:hidden;opacity:.34;pointer-events:none}.weather-layer[data-weather*='rain']{background:repeating-linear-gradient(105deg,transparent 0 27px,rgba(156,211,255,.55) 28px 29px,transparent 30px 58px);animation:weather-drift .7s linear infinite}.weather-layer[data-weather*='sun']{background:radial-gradient(circle at 78% 8%,rgba(255,215,107,.5),transparent 35%)}.weather-layer[data-weather*='sand']{background:repeating-linear-gradient(170deg,transparent 0 36px,rgba(226,188,117,.28) 38px 41px);animation:weather-drift 1.4s linear infinite}.weather-layer[data-weather*='snow'],.weather-layer[data-weather*='hail']{background-image:radial-gradient(circle,#fff 0 2px,transparent 3px);background-size:38px 38px;animation:weather-fall 2s linear infinite}
  .arena-shake{animation:arena-shake .42s cubic-bezier(.2,.8,.2,1) both}.move-visual{--type-color:#e9f2ea;position:absolute;z-index:7;inset:0;pointer-events:none}.move-visual[data-direction='near-to-far']{--origin-x:27%;--origin-y:72%;--target-x:73%;--target-y:29%;--beam-angle:-43deg}.move-visual[data-direction='far-to-near']{--origin-x:73%;--origin-y:29%;--target-x:27%;--target-y:72%;--beam-angle:137deg}.move-projectile{position:absolute;top:var(--origin-y);left:var(--origin-x);width:clamp(18px,3vw,44px);aspect-ratio:1;border:2px solid color-mix(in srgb,var(--type-color) 80%,white);border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff,var(--type-color) 28%,transparent 70%);box-shadow:0 0 18px var(--type-color);animation:projectile-flight .52s cubic-bezier(.22,.7,.2,1) both}.move-beam{position:absolute;top:var(--origin-y);left:var(--origin-x);width:62%;height:6px;transform-origin:left center;transform:rotate(var(--beam-angle)) scaleX(0);border-radius:999px;background:linear-gradient(90deg,#fff,var(--type-color),transparent);box-shadow:0 0 14px var(--type-color);opacity:0;animation:beam-fire .48s ease-out both}.charge-ring{position:absolute;top:var(--origin-y);left:var(--origin-x);width:74px;aspect-ratio:1;transform:translate(-50%,-50%);border:2px solid var(--type-color);border-radius:50%;opacity:0;animation:charge-ring .52s ease-out both}.move-visual[data-archetype='physical'] .move-projectile,.move-visual[data-archetype='physical'] .move-beam{display:none}.move-visual[data-archetype='status'] .move-projectile,.move-visual[data-archetype='status'] .move-beam{display:none}.move-visual[data-archetype='status'] .charge-ring{top:50%;left:50%;width:34%;animation:status-aura .52s ease-out both}.move-visual[data-move-type='electric'] .move-beam,.move-visual[data-move-type='psychic'] .move-beam,.move-visual[data-move-type='dragon'] .move-beam{opacity:1}.move-visual[data-quality='low'] .charge-ring{display:none}
  .impact-burst{position:absolute;top:50%;left:50%;width:1px;height:1px}.effect[data-side='p1'] .impact-burst{top:70%;left:29%}.effect[data-side='p2'] .impact-burst{top:31%;left:71%}.impact-burst i{position:absolute;width:9px;aspect-ratio:1;border-radius:50% 10%;background:var(--type-color);box-shadow:0 0 10px var(--type-color);animation:particle-burst .55s ease-out both;animation-delay:var(--particle-delay)}.effect>strong{position:absolute;top:56%;left:50%;transform:translateX(-50%);color:#ff918a;font:900 clamp(.9rem,2vw,1.5rem) var(--mono);text-shadow:0 2px 12px #000;animation:value-pop .7s both}.effect>strong.positive{color:#8ef3a9}.effect-super-effective span{border-color:#ffd267;color:#ffd267}.effect-resisted span,.effect-immune span{color:#c6d0c8}
  .effect[data-move-type],.move-visual[data-move-type]{--type-color:#e4e7df}.effect[data-move-type='fire'],.move-visual[data-move-type='fire']{--type-color:#ff704f}.effect[data-move-type='water'],.move-visual[data-move-type='water']{--type-color:#55b8ff}.effect[data-move-type='electric'],.move-visual[data-move-type='electric']{--type-color:#ffe45e}.effect[data-move-type='grass'],.move-visual[data-move-type='grass']{--type-color:#75df6d}.effect[data-move-type='ice'],.move-visual[data-move-type='ice']{--type-color:#8feaff}.effect[data-move-type='fighting'],.move-visual[data-move-type='fighting']{--type-color:#ef7558}.effect[data-move-type='poison'],.move-visual[data-move-type='poison']{--type-color:#d073e5}.effect[data-move-type='ground'],.move-visual[data-move-type='ground']{--type-color:#d6a65e}.effect[data-move-type='flying'],.move-visual[data-move-type='flying']{--type-color:#9fb9ff}.effect[data-move-type='psychic'],.move-visual[data-move-type='psychic']{--type-color:#ff70b1}.effect[data-move-type='bug'],.move-visual[data-move-type='bug']{--type-color:#a8cf55}.effect[data-move-type='rock'],.move-visual[data-move-type='rock']{--type-color:#c6b477}.effect[data-move-type='ghost'],.move-visual[data-move-type='ghost']{--type-color:#9e88df}.effect[data-move-type='dragon'],.move-visual[data-move-type='dragon']{--type-color:#7e79ff}.effect[data-move-type='dark'],.move-visual[data-move-type='dark']{--type-color:#88766e}.effect[data-move-type='steel'],.move-visual[data-move-type='steel']{--type-color:#b5c4cb}.effect[data-move-type='fairy'],.move-visual[data-move-type='fairy']{--type-color:#ff9bd1}
  .battle-renderer.reduced-motion .sprite,.battle-renderer.reduced-motion .pulse-ring,.battle-renderer.reduced-motion .move-visual,.battle-renderer.reduced-motion .impact-burst,.battle-renderer.reduced-motion .arena-shake{animation:none!important;transform:none!important}
  .battle-renderer[data-layout='standard-vertical']{grid-template-columns:1fr;grid-template-rows:auto auto minmax(520px,1fr) auto auto;width:min(100%,620px);aspect-ratio:9/16;min-height:900px;margin-inline:auto;padding:24px}.battle-renderer[data-layout='standard-vertical'] .scoreboard{grid-column:1;grid-row:1}.battle-renderer[data-layout='standard-vertical'] .player-far{grid-column:1;grid-row:2;min-height:142px}.battle-renderer[data-layout='standard-vertical'] .arena-stage{grid-column:1;grid-row:3;min-height:520px}.battle-renderer[data-layout='standard-vertical'] .player-near{grid-column:1;grid-row:4;min-height:142px}.battle-renderer[data-layout='standard-vertical'] .battle-log{grid-column:1;grid-row:5;grid-template-columns:1fr}.battle-renderer[data-layout='standard-vertical'] .battle-log p{display:none}.battle-renderer[data-layout='standard-vertical'] .battle-log p:nth-last-child(-n+2){display:flex}.battle-renderer[data-layout='standard-vertical'] .combatant{width:54%}.battle-renderer[data-layout='standard-vertical'] .combatant-far{top:4%;right:3%}.battle-renderer[data-layout='standard-vertical'] .combatant-near{bottom:4%;left:3%}.battle-renderer[data-layout='standard-vertical'] .format{display:none}.battle-renderer[data-layout='standard-vertical'] .scoreboard{grid-template-columns:1fr auto}.battle-renderer[data-layout='standard-vertical'] .turn{text-align:right}.battle-renderer[data-layout='overlay-landscape']{border-radius:0}.battle-renderer.overlay{width:100vw;height:100vh;min-height:0;aspect-ratio:auto;border-radius:0}.battle-renderer.overlay[data-layout='standard-vertical']{width:100vw;max-width:none;height:100vh;min-height:0;margin:0}.renderer-loading{display:grid;place-content:center;min-height:420px;padding:2rem;text-align:center}.renderer-loading h2{margin:.5rem 0}.renderer-loading p{color:var(--muted)}
  @keyframes idle{50%{transform:translateY(-3%) scale(1.015)}}@keyframes attack{45%{transform:translate(-12%,-7%) scale(1.08)}}@keyframes attack-near{45%{transform:translate(12%,7%) scale(1.08)}}@keyframes hit{20%,60%{transform:translateX(-7%);filter:brightness(1.8)}40%,80%{transform:translateX(7%)}}@keyframes switch-in{from{opacity:0;transform:translateY(-15%) scale(.72)}55%{opacity:1;transform:translateY(2%) scale(1.06)}}@keyframes switch-out{to{opacity:0;transform:translateY(15%) scale(.72)}}@keyframes faint{to{opacity:0;transform:translateY(25%) rotate(5deg) scale(.78);filter:grayscale(1)}}@keyframes status-flash{50%{filter:drop-shadow(0 0 22px #ffd05d) brightness(1.4)}}@keyframes pulse{50%{transform:scale(1.18);opacity:.08}}@keyframes effect-pop{from{opacity:0;transform:scale(.7)}35%{opacity:1;transform:scale(1.08)}to{opacity:0;transform:scale(1.2)}}@keyframes winner-in{from{opacity:0;clip-path:inset(50% 0)}to{opacity:1;clip-path:inset(0)}}
  @keyframes arena-shake{0%,100%{transform:translate(0)}25%{transform:translate(-.45%,.25%)}50%{transform:translate(.38%,-.2%)}75%{transform:translate(-.18%,.12%)}}@keyframes projectile-flight{0%{transform:translate(-50%,-50%) scale(.45);opacity:0}18%{opacity:1}82%{opacity:1}100%{top:var(--target-y);left:var(--target-x);transform:translate(-50%,-50%) scale(1.35);opacity:0}}@keyframes beam-fire{0%,18%{transform:rotate(var(--beam-angle)) scaleX(0);opacity:0}38%,65%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:.9}100%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:0}}@keyframes charge-ring{0%{transform:translate(-50%,-50%) scale(1.5);opacity:0}30%{opacity:.8}70%{transform:translate(-50%,-50%) scale(.35);opacity:.8}100%{opacity:0}}@keyframes status-aura{from{transform:translate(-50%,-50%) scale(.25);opacity:.8}to{transform:translate(-50%,-50%) scale(1.5);opacity:0}}@keyframes particle-burst{from{transform:translate(0) scale(1);opacity:1}to{transform:translate(var(--particle-x),var(--particle-y)) rotate(150deg) scale(.15);opacity:0}}@keyframes value-pop{from{opacity:0;transform:translate(-50%,10px) scale(.8)}25%{opacity:1;transform:translate(-50%,-4px) scale(1.1)}to{opacity:0;transform:translate(-50%,-20px)}}@keyframes weather-drift{to{background-position:72px 20px}}@keyframes weather-fall{to{background-position:18px 38px}}
  @media(max-width:900px){.battle-renderer:not([data-layout='standard-vertical']){grid-template-columns:1fr 1fr;grid-template-rows:auto minmax(420px,1fr) auto auto;aspect-ratio:auto;min-height:760px}.battle-renderer:not([data-layout='standard-vertical']) .scoreboard{grid-column:1/-1}.battle-renderer:not([data-layout='standard-vertical']) .arena-stage{grid-column:1/-1;grid-row:2}.battle-renderer:not([data-layout='standard-vertical']) .player-far{grid-column:1;grid-row:3}.battle-renderer:not([data-layout='standard-vertical']) .player-near{grid-column:2;grid-row:3}.battle-renderer:not([data-layout='standard-vertical']) .battle-log{grid-column:1/-1;grid-row:4;grid-template-columns:1fr 1fr}.battle-renderer:not([data-layout='standard-vertical']) .battle-log p:nth-of-type(-n+3){display:none}}
  @media(max-width:560px){.battle-renderer{padding:14px;border-radius:16px}.battle-renderer:not([data-layout='standard-vertical']){grid-template-columns:1fr;grid-template-rows:auto 390px auto auto auto;min-height:850px}.battle-renderer:not([data-layout='standard-vertical']) .player-far{grid-column:1;grid-row:3}.battle-renderer:not([data-layout='standard-vertical']) .player-near{grid-column:1;grid-row:4}.battle-renderer:not([data-layout='standard-vertical']) .battle-log{grid-column:1;grid-row:5}.brand-lockup strong,.format{display:none}.combatant{width:52%}.arena-stage{min-height:390px}.commentary{margin-top:.6rem}.player-card{min-height:125px}}
  @media(prefers-reduced-motion:reduce){.sprite,.pulse-ring,.effect span,.winner-banner{animation-duration:.001ms!important;animation-iteration-count:1!important}.hp-track i{transition-duration:.001ms!important}}
</style>
