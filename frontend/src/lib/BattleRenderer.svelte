<script lang="ts">
  import { pokemonAssetUrl } from './presentation/assets';
  import {
    defaultRendererConfig,
    type AgentPresentationStatus,
    type BattlePresentationState,
    type RendererConfig,
    type SpectatorLogEntry
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
  const particleIndexes = Array.from({ length: 12 }, (_, index) => index);
  /**
   * Installed Showdown battle sprites are 96px static PNGs and ~60-96px animated GIFs.
   * Enlarging one beyond this factor turns a crisp asset into mush, so the stage caps the
   * footprint instead of stretching sprites to fill space.
   */
  const NATIVE_SPRITE_PX = 96;
  const MAX_UPSCALE = 3;
  const RETRO_GENERATIONS = new Set([1, 2]);

  interface Slot {
    place: 'far' | 'near';
    side: Side;
    data: BattleSide | null;
    perspective: 'front' | 'back';
  }

  let nearSide: Side = 'p1';
  let farSide: Side = 'p2';
  $: nearSide = config.nearSide;
  $: farSide = nearSide === 'p1' ? 'p2' : 'p1';
  $: near = presentation ? battleSide(presentation, nearSide) : null;
  $: far = presentation ? battleSide(presentation, farSide) : null;
  // The format id carries the generation, so a match that has not produced its first event yet
  // still labels itself correctly instead of falling back to Gen 9 for every format.
  $: generation =
    presentation?.battle?.generation ?? generationFromFormat(presentation?.format) ?? 9;
  // Gen 1 and 2 sprites are pixel art by intent; everything later is smoothed.
  $: retro = RETRO_GENERATIONS.has(generation);
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
  $: formatLabel = formatName(presentation?.format || '', generation);
  $: feed = groupedFeed(presentation);
  $: slots = [
    { place: 'far', side: farSide, data: far, perspective: 'front' },
    { place: 'near', side: nearSide, data: near, perspective: 'back' }
  ] as Slot[];

  function battleSide(state: BattlePresentationState, side: Side): BattleSide | null {
    const battle = state.battle;
    if (!battle) return null;
    if (battle.player.side === side) return battle.player;
    return battle.opponent.side === side ? battle.opponent : null;
  }

  /** Only the commentary that belongs to the action in flight is public-facing. */
  function currentIntent(state: BattlePresentationState | null, side: Side) {
    if (!state || config.commentaryMode === 'hidden') return null;
    const player = state.players[side];
    if (player.commentaryPhase === 'resolved' || player.commentaryPhase === 'waiting') return null;
    return player;
  }

  function generationFromFormat(id: string | undefined) {
    const match = /^gen(\d+)/.exec(id || '');
    return match ? Number(match[1]) : null;
  }

  function formatName(id: string, gen: number) {
    if (!id) return `GEN ${gen}`;
    const suffix = id.replace(/^gen\d+/, '').replace(/randombattle/, 'random battle');
    return `GEN ${gen} · ${(suffix || 'custom game').replace(/([a-z])([A-Z])/g, '$1 $2').toUpperCase()}`;
  }

  /** Spectator feed grouped by turn, newest turn last, no repeated authoritative lines. */
  function groupedFeed(state: BattlePresentationState | null) {
    const groups: Array<{ turn: number; lines: SpectatorLogEntry[] }> = [];
    if (!state) return groups;
    const recent = state.log.slice(-9);
    for (const entry of recent) {
      if (entry.kind === 'turn_started') continue;
      const last = groups[groups.length - 1];
      if (last && last.turn === entry.turn) last.lines.push(entry);
      else groups.push({ turn: entry.turn, lines: [entry] });
    }
    return groups.slice(-3).map((group) => ({ ...group, lines: group.lines.slice(-3) }));
  }

  function assetKey(side: BattleSide, perspective: 'front' | 'back') {
    return `${side.active?.species}:${perspective}:${config.animatedSprites}`;
  }

  function onAssetError(key: string) {
    failedAssets = new Set([...failedAssets, key]);
  }

  /**
   * Record the sprite's own pixel height so the stage can cap its upscale per asset.
   * Installed assets range from ~48px animated frames to 96px static sheets; a single
   * fit-to-box rule would blow the small ones up six times over.
   */
  function onAssetLoad(event: Event) {
    const image = event.currentTarget as HTMLImageElement;
    if (image.naturalHeight) image.style.setProperty('--natural-h', String(image.naturalHeight));
  }

  /**
   * Deterministic renders must not depend on wall-clock GIF playback, so the offline path
   * always asks the asset service for the static sprite.
   */
  function spriteUrl(species: string, perspective: 'front' | 'back') {
    return pokemonAssetUrl(species, perspective, config.animatedSprites && !deterministic);
  }

  function hpTone(fraction: number) {
    return fraction > 0.5 ? 'high' : fraction > 0.2 ? 'mid' : 'low';
  }

  function previousHp(side: Side, fraction: number) {
    const impact = presentation?.impacts[side];
    if (!impact) return fraction;
    return Math.max(0, Math.min(1, fraction - impact.value / 100));
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

  function spriteStyle(motion: string, isNear: boolean) {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const pulse = Math.sin(progress * Math.PI);
    if (motion === 'idle') {
      const idle = Math.sin(logicalElapsedMs / 3400 * Math.PI * 2);
      return `transform:translateY(${idle * -2}%) scale(${1 + Math.max(0, idle) * .012})`;
    }
    if (motion === 'attacking') return `transform:translate(${(isNear ? 14 : -14) * pulse}%,${(isNear ? -9 : 9) * pulse}%) scale(${1 + .07 * pulse})`;
    if (motion === 'taking-damage') return `transform:translateX(${Math.sin(progress * Math.PI * 8) * (1 - progress) * 8}%);filter:brightness(${1 + pulse * .9}) saturate(${1 - pulse * .5})`;
    if (motion === 'switching-in') return `opacity:${progress};transform:translateY(${(1 - progress) * -18}%) scale(${.7 + progress * .3})`;
    if (motion === 'switching-out') return `opacity:${1 - progress};transform:translateY(${progress * 18}%) scale(${1 - progress * .3})`;
    if (motion === 'fainting') return `opacity:${1 - progress};transform:translateY(${progress * 30}%) scale(${1 - progress * .25});filter:grayscale(${progress}) brightness(${1 - progress * .4})`;
    if (motion === 'status-flash') return `filter:brightness(${1 + pulse * .45}) drop-shadow(0 0 ${pulse * 22}px #ffd05d)`;
    return '';
  }

  function projectileStyle(direction: 'near-to-far' | 'far-to-near') {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const nearToFar = direction === 'near-to-far';
    const origin = nearToFar ? [30, 74] : [70, 40];
    const target = nearToFar ? [70, 40] : [30, 74];
    const x = origin[0] + (target[0] - origin[0]) * progress;
    const y = origin[1] + (target[1] - origin[1]) * progress;
    return `left:${x}%;top:${y}%;opacity:${Math.sin(progress * Math.PI)};transform:translate(-50%,-50%) scale(${.45 + progress * .9})`;
  }

  function arenaStyle() {
    if (!deterministic || !strongImpact || config.reducedMotion) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    const strength = (1 - progress) * Math.sin(progress * Math.PI * 8) * .5;
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
    const angle = direction === 'near-to-far' ? -38 : 142;
    return `opacity:${Math.sin(progress * Math.PI)};transform:rotate(${angle}deg) scaleX(${Math.min(1, progress * 3)})`;
  }

  function readableStatus(status: string) {
    const labels: Record<string, string> = {
      brn: 'BRN', par: 'PAR', psn: 'PSN', tox: 'TOX', slp: 'SLP', frz: 'FRZ'
    };
    return labels[status.toLowerCase()] || status.toUpperCase();
  }

  function typeColor(type: string) {
    const colors: Record<string, string> = {
      normal: '#d9d7ca', fire: '#ff633f', water: '#3cc8ff', electric: '#ffe148', grass: '#79f05d',
      ice: '#82f4f1', fighting: '#ff714f', poison: '#de64e8', ground: '#e3a44d', flying: '#8ec7ff',
      psychic: '#ff5bac', bug: '#b9e744', rock: '#cfb56f', ghost: '#a17cff', dragon: '#766dff',
      dark: '#8a7772', steel: '#b5cbd6', fairy: '#ff96d2'
    };
    return colors[type.toLowerCase()] || colors.normal;
  }

  /** Production surfaces always show the public percentage so both sides read identically. */
  function hpPercent(active: NonNullable<BattleSide['active']>) {
    return Math.round(active.hp_fraction * 100);
  }

  function exactHp(active: NonNullable<BattleSide['active']>) {
    if (active.current_hp == null || !active.max_hp) return null;
    const absolute = active.current_hp / active.max_hp;
    return Math.abs(absolute - active.hp_fraction) <= 0.01
      ? `${active.current_hp}/${active.max_hp}`
      : null;
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
    data-generation={generation}
    data-retro={retro}
    style={`--hp-duration:${hpDuration}ms;--sprite-native:${NATIVE_SPRITE_PX}px;--max-upscale:${MAX_UPSCALE}`}
    aria-label="KoalaBattle production renderer"
  >
    <!-- Broadcast bar: brand, turn, format. Deliberately slim so the arena dominates. -->
    <header class="broadcast-bar">
      <span class="brand"><img src="/koalabattle-mark.svg" alt="" /><b>KOALABATTLE</b></span>
      {#if config.showTurn}<span class="turn">TURN <b>{presentation.battle?.turn ?? 0}</b></span>{/if}
      <span class="format">{formatLabel}</span>
    </header>

    <div style={arenaStyle()} class:arena-shake={strongImpact && config.effects !== 'off' && !config.reducedMotion} class="stage">
      <!-- Original KoalaBattle arena: stadium bowl, crowd, lit floor plane. -->
      <div class="stage-sky" aria-hidden="true"></div>
      <div class="stage-bowl" aria-hidden="true"><i class="crowd"></i><i class="rail"></i></div>
      <div class="stage-lights" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <div class="stage-floor" aria-hidden="true"><i class="floor-grid"></i><i class="floor-glow"></i></div>
      {#if presentation.battle?.weather.length}
        <div class="weather-layer" data-weather={presentation.battle.weather[0]} aria-hidden="true"></div>
      {/if}
      {#if presentation.battle?.fields.length}
        <div class="terrain-layer" data-terrain={presentation.battle.fields[0]} aria-hidden="true"></div>
      {/if}

      <!-- Compact player identity, fighting-game style: name first, role as metadata. -->
      {#each slots as slot (slot.side)}
        <div class={`player-hud hud-${slot.place}`} data-side={slot.side}>
          <span class="player-name">{presentation.players[slot.side].displayName}</span>
          <span class="player-meta">
            <b>{slot.side.toUpperCase()}</b>
            <span>{presentation.players[slot.side].providerLabel}</span>
            {#if config.showAgentState}
              <em class={`agent-state ${agentStatus[slot.side] || presentation.players[slot.side].agentStatus}`}
                >{agentStatus[slot.side] || presentation.players[slot.side].agentStatus}</em>
            {/if}
          </span>
          <span class="team-strip" aria-label={`${slot.data?.team.length || 0} Pokémon remaining`}>
            {#each slot.data?.team || [] as member}
              <i class:active={member.active} class:fainted={member.fainted}></i>
            {/each}
          </span>
        </div>
      {/each}

      <!-- Combatants. Far uses the front sprite, near the back sprite, as in a real battle. -->
      {#each slots as slot (slot.side)}
        {#if slot.data?.active}
          <article
            class={`combatant combatant-${slot.place}`}
            data-side={slot.side}
            aria-label={`${slot.data.active.name}, ${hpPercent(slot.data.active)} percent health`}
          >
            <div class="sprite-slot">
              <div class="platform" aria-hidden="true"><i></i></div>
              <div class="contact-shadow" aria-hidden="true"></div>
              {#key `${presentation.eventSequence}:${slot.side}:${presentation.players[slot.side].motion}`}
                <div
                  style={spriteStyle(presentation.players[slot.side].motion, slot.place === 'near')}
                  class={`sprite ${presentation.players[slot.side].motion}`}
                >
                  {#if !failedAssets.has(assetKey(slot.data, slot.perspective))}
                    <img
                      src={spriteUrl(slot.data.active.species, slot.perspective)}
                      alt={slot.data.active.name}
                      on:load={onAssetLoad}
                      on:error={() => slot.data && onAssetError(assetKey(slot.data, slot.perspective))}
                    />
                  {:else}
                    <div class="placeholder"><span>{slot.data.active.name.slice(0, 1)}</span></div>
                  {/if}
                </div>
              {/key}
              {#if config.showDamageNumbers && presentation.impacts[slot.side]}
                {#key presentation.impacts[slot.side]?.sequence}
                  <strong
                    class="hp-delta"
                    class:positive={(presentation.impacts[slot.side]?.value ?? 0) > 0}
                    style={transientStyle()}
                  >{(presentation.impacts[slot.side]?.value ?? 0) > 0 ? '+' : ''}{presentation.impacts[slot.side]?.value}%</strong>
                {/key}
              {/if}
            </div>

            <!-- Both sides get an identical HP plate: species, level, types, bar, percent. -->
            <div class="hp-plate">
              <div class="plate-head">
                <b class="species">{slot.data.active.name}</b>
                {#if slot.data.active.level}<span class="level">Lv{slot.data.active.level}</span>{/if}
                {#if slot.data.active.status}<span class="status">{readableStatus(slot.data.active.status)}</span>{/if}
              </div>
              <div class="hp-track" data-tone={hpTone(slot.data.active.hp_fraction)}>
                <b style={`width:${previousHp(slot.side, slot.data.active.hp_fraction) * 100}%`}></b>
                <i style={`width:${slot.data.active.hp_fraction * 100}%`}></i>
              </div>
              <div class="plate-foot">
                <span class="types">
                  {#each slot.data.active.types as type}
                    <i class="type-badge" style={`--type-color:${typeColor(type)}`}>{type}</i>
                  {/each}
                </span>
                <span class="hp-value">
                  {hpPercent(slot.data.active)}%
                  {#if config.commentaryMode === 'full' && exactHp(slot.data.active)}
                    <small>{exactHp(slot.data.active)}</small>
                  {/if}
                </span>
              </div>
            </div>
          </article>
        {/if}
      {/each}

      {#if moveProfile && config.effects !== 'off'}
        <div
          class="move-visual"
          data-archetype={moveProfile.archetype}
          data-move-type={moveProfile.type}
          data-direction={attackerSide === nearSide ? 'near-to-far' : 'far-to-near'}
          data-quality={config.effects}
          aria-hidden="true"
        >
          <div style={chargeStyle()} class="charge-ring"></div>
          <div style={projectileStyle(attackerSide === nearSide ? 'near-to-far' : 'far-to-near')} class="move-projectile"></div>
          <div style={beamStyle(attackerSide === nearSide ? 'near-to-far' : 'far-to-near')} class="move-beam"></div>
        </div>
      {/if}

      {#key `${presentation.eventSequence}:${presentation.effect}`}
        {#if presentation.effect !== 'none' && presentation.effect !== 'impact'}
          <div class={`effect effect-${presentation.effect}`} data-side={presentation.effectSide || ''} data-move-type={presentation.currentMoveProfile?.type || 'normal'}>
            {#if config.effects !== 'off'}
              <div class="impact-burst" aria-hidden="true">
                {#each particleIndexes.slice(0, config.effects === 'low' ? 6 : config.effects === 'high' ? 12 : 9) as index}
                  <i style={particleStyle(index, presentation.currentMoveProfile?.seed || presentation.eventSequence)}></i>
                {/each}
              </div>
            {/if}
            <span style={transientStyle()}>{presentation.effect === 'super-effective' ? 'SUPER EFFECTIVE' : presentation.effect === 'resisted' ? 'NOT VERY EFFECTIVE' : presentation.effect === 'immune' ? 'NO EFFECT' : presentation.effect.replace('-', ' ')}</span>
          </div>
        {/if}
      {/key}

      <!-- One unambiguous headline: is this action running now, or already resolved? -->
      {#if presentation.currentMove}
        <div class="action-banner" data-phase={presentation.currentMovePhase} data-side={presentation.currentMoveSide || ''}>
          <small>{presentation.currentMovePhase === 'executing' ? 'NOW' : 'LAST ACTION'}</small>
          <b>{presentation.currentMove}</b>
          {#if moveProfile && presentation.currentMovePhase === 'executing'}
            <em>{moveProfile.type.toUpperCase()} · {moveProfile.archetype.toUpperCase()}</em>
          {/if}
        </div>
      {/if}

      <!-- Intent panels only exist while their action is pending or executing. -->
      {#each slots as slot (slot.side)}
        {@const player = currentIntent(presentation, slot.side)}
        {#if player}
          <div class={`intent intent-${slot.place}`} data-side={slot.side} aria-live="polite">
            <small>{player.commentaryPhase === 'thinking' ? 'THINKING' : 'INTENT'}</small>
            {#if player.commentaryPhase === 'thinking'}
              <p class="thinking">Thinking…</p>
            {:else}
              <p>{player.currentCommentary?.commentary || `${player.currentCommentary?.actionName || player.currentCommentary?.action || 'Action'} selected.`}</p>
            {/if}
          </div>
        {/if}
      {/each}
    </div>

    {#if config.showBattleLog}
      <aside class="battle-feed" aria-label="Spectator battle feed" aria-live="polite">
        {#each feed as group (group.turn)}
          <div class="feed-turn">
            <span class="feed-label">Turn {group.turn}</span>
            {#each group.lines as entry (entry.sequence)}
              <p data-emphasis={entry.emphasis}>{entry.text}</p>
            {/each}
          </div>
        {/each}
        {#if !feed.length}<div class="feed-turn"><span class="feed-label">Ready</span><p>Waiting for the first turn.</p></div>{/if}
      </aside>
    {/if}

    {#if presentation.finished}
      <div class="winner-banner" role="status">
        <small>BATTLE COMPLETE</small>
        <strong>{presentation.winnerName || presentation.battle?.result?.winner_name || 'DRAW'}</strong>
        <span>{presentation.winner || 'no winner'}</span>
      </div>
    {/if}
  </section>
{:else}
  <section class="renderer-loading panel"><span class="eyebrow">Renderer ready</span><h2>Waiting for normalized battle state…</h2><p>No engine connection is required to draw this frame.</p></section>
{/if}

<style>
  /* ── Shell ──────────────────────────────────────────────────────────────── */
  .battle-renderer{
    --r-ink:#f4fbf6;--r-dim:#93a89b;--r-line:rgba(140,255,186,.16);--r-accent:#78ffa9;
    --r-p1:#5fe39a;--r-p2:#c98cff;--r-panel:rgba(6,12,10,.88);
    position:relative;isolation:isolate;display:grid;grid-template-rows:auto 1fr auto;
    width:100%;aspect-ratio:16/9;min-height:480px;overflow:hidden;
    border:1px solid var(--r-line);border-radius:14px;background:#050a08;color:var(--r-ink);
    box-shadow:0 30px 90px rgba(0,0,0,.42);font-family:var(--display)
  }
  .battle-renderer.transparent{background:transparent;border-color:transparent;box-shadow:none}
  .battle-renderer.overlay{width:100vw;height:100vh;min-height:0;aspect-ratio:auto;border:0;border-radius:0;box-shadow:none}

  /* ── Broadcast bar ──────────────────────────────────────────────────────── */
  .broadcast-bar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;height:clamp(34px,4.4%,46px);padding:0 clamp(10px,1.2vw,20px);background:rgba(4,9,7,.92);border-bottom:1px solid var(--r-line)}
  .brand{display:flex;align-items:center;gap:.45rem;color:var(--r-dim);font:800 clamp(.52rem,.72vw,.68rem) var(--display);letter-spacing:.14em}
  .brand img{width:clamp(17px,1.5vw,22px);aspect-ratio:1}
  .turn{color:var(--r-dim);font:600 clamp(.5rem,.68vw,.64rem) var(--mono);letter-spacing:.14em}
  .turn b{margin-left:.3rem;color:var(--r-ink);font-size:1.5em;letter-spacing:0}
  .format{justify-self:end;color:var(--r-dim);font:500 clamp(.46rem,.62vw,.6rem) var(--mono);letter-spacing:.1em}

  /* ── Arena ──────────────────────────────────────────────────────────────── */
  .stage{position:relative;overflow:hidden;background:#060d0b;container-type:size}
  .stage-sky{position:absolute;inset:0;background:radial-gradient(120% 80% at 50% 6%,#1a4a54 0,#0d2733 42%,#060d0b 78%)}
  .stage-sky::after{content:'';position:absolute;inset:0;background:radial-gradient(70% 48% at 50% 34%,rgba(122,255,183,.13),transparent 70%)}
  /* Stadium bowl with a procedural crowd. No copyrighted artwork is used. */
  .stage-bowl{position:absolute;inset:4% 0 38%;overflow:hidden}
  .stage-bowl .crowd{position:absolute;inset:12% -8% 18%;border-radius:50% 50% 42% 42%/70% 70% 30% 30%;background:
    radial-gradient(circle at 50% 50%,rgba(255,255,255,.055) 0 1.1px,transparent 1.6px) 0 0/13px 11px,
    linear-gradient(180deg,#0a1c22,#0b262c 62%,#08161a);opacity:.95}
  .stage-bowl .rail{position:absolute;right:-8%;bottom:16%;left:-8%;height:8%;border-radius:50%;background:linear-gradient(180deg,rgba(126,255,175,.2),rgba(6,14,11,.9));box-shadow:0 0 26px rgba(94,255,175,.16)}
  .stage-lights{position:absolute;inset:0;pointer-events:none}
  .stage-lights i{position:absolute;top:-6%;width:22%;height:74%;background:linear-gradient(180deg,rgba(190,255,220,.14),transparent 72%);filter:blur(6px)}
  .stage-lights i:nth-child(1){left:6%;transform:rotate(9deg)}
  .stage-lights i:nth-child(2){left:29%;transform:rotate(3deg)}
  .stage-lights i:nth-child(3){right:29%;transform:rotate(-3deg)}
  .stage-lights i:nth-child(4){right:6%;transform:rotate(-9deg)}
  /* Ground plane: a real perspective floor so Pokémon stand on something. */
  .stage-floor{position:absolute;inset:58% 0 0;background:linear-gradient(180deg,#154238 0,#0b241f 38%,#050c0a)}
  .stage-floor::after{content:'';position:absolute;inset:0;background:radial-gradient(120% 90% at 50% 0,transparent 40%,rgba(3,8,6,.72))}
  .floor-grid{position:absolute;inset:0;background-image:
    linear-gradient(rgba(126,255,175,.13) 1px,transparent 1px),
    linear-gradient(90deg,rgba(126,255,175,.1) 1px,transparent 1px);
    background-size:100% 15%,7% 100%;transform:perspective(360px) rotateX(62deg);transform-origin:center top;
    mask-image:linear-gradient(rgba(0,0,0,.9),transparent 88%)}
  .floor-glow{position:absolute;inset:-20% 10% 30%;border-radius:50%;background:radial-gradient(ellipse,rgba(126,255,175,.16),transparent 66%)}
  .weather-layer{position:absolute;z-index:2;inset:0;overflow:hidden;opacity:.32;pointer-events:none}
  .weather-layer[data-weather*='rain']{background:repeating-linear-gradient(104deg,transparent 0 26px,rgba(156,211,255,.5) 27px 28px,transparent 29px 56px);animation:weather-drift .7s linear infinite}
  .weather-layer[data-weather*='sun']{background:radial-gradient(circle at 76% 8%,rgba(255,215,107,.44),transparent 36%)}
  .weather-layer[data-weather*='sand']{background:repeating-linear-gradient(168deg,transparent 0 34px,rgba(226,188,117,.26) 36px 39px);animation:weather-drift 1.4s linear infinite}
  .weather-layer[data-weather*='snow'],.weather-layer[data-weather*='hail']{background-image:radial-gradient(circle,#fff 0 2px,transparent 3px);background-size:36px 36px;animation:weather-fall 2s linear infinite}
  .terrain-layer{position:absolute;z-index:2;inset:60% 8% 6%;border-radius:50%;background:radial-gradient(ellipse,rgba(122,255,183,.2),transparent 66%);opacity:.8}

  /* ── Compact player HUD ─────────────────────────────────────────────────── */
  .player-hud{position:absolute;z-index:12;display:grid;gap:.12rem;max-width:30%;padding:.4rem .7rem;border-radius:6px;background:linear-gradient(90deg,rgba(4,9,7,.92),rgba(4,9,7,.55));border-left:3px solid var(--side-color)}
  .player-hud[data-side='p1']{--side-color:var(--r-p1)}
  .player-hud[data-side='p2']{--side-color:var(--r-p2)}
  .hud-far{top:2.5%;left:2.5%}
  .hud-near{right:2.5%;bottom:2.5%;justify-items:end;text-align:right;border-right:3px solid var(--side-color);border-left:0;background:linear-gradient(270deg,rgba(4,9,7,.92),rgba(4,9,7,.55))}
  .player-name{overflow:hidden;font:800 clamp(.72rem,1.15vw,1.15rem)/1 var(--display);letter-spacing:-.02em;text-overflow:ellipsis;text-transform:uppercase;white-space:nowrap}
  .player-meta{display:flex;align-items:center;gap:.4rem;color:var(--r-dim);font:600 clamp(.44rem,.6vw,.56rem) var(--mono);letter-spacing:.08em;text-transform:uppercase}
  .player-meta b{color:var(--side-color)}
  .player-meta span{overflow:hidden;max-width:11ch;text-overflow:ellipsis;white-space:nowrap}
  .agent-state{padding:.08rem .3rem;border-radius:3px;background:rgba(255,255,255,.08);font-style:normal}
  .agent-state.thinking{background:rgba(242,193,95,.2);color:#ffd679}
  .agent-state.decided,.agent-state.executing{background:rgba(120,255,169,.16);color:var(--r-accent)}
  .agent-state.error{background:rgba(255,139,135,.18);color:#ff9d98}
  .team-strip{display:flex;gap:4px;margin-top:.12rem}
  .team-strip i{width:clamp(6px,.62vw,9px);aspect-ratio:1;border:1px solid rgba(255,255,255,.55);border-radius:50%;background:var(--side-color)}
  .team-strip i.fainted{border-color:rgba(255,255,255,.2);background:transparent}
  .team-strip i.active{outline:1.5px solid #fff;outline-offset:1.5px}

  /* ── Combatants ─────────────────────────────────────────────────────────── */
  .combatant{position:absolute;z-index:8;display:flex;flex-direction:column;align-items:center;gap:.25rem;width:min(38%,420px)}
  .combatant-far{top:9%;right:8%;flex-direction:column-reverse}
  .combatant-near{bottom:13%;left:8%}
  .combatant-far{--fighter-color:var(--r-p2)}
  .combatant-near{--fighter-color:var(--r-p1)}
  .platform{position:absolute;bottom:-6%;left:50%;width:86%;aspect-ratio:3.4/1;transform:translateX(-50%);pointer-events:none}
  .platform i{position:absolute;inset:0;border-radius:50%;background:radial-gradient(ellipse at 50% 44%,rgba(150,255,200,.26),rgba(20,74,62,.44) 56%,transparent 74%);box-shadow:0 0 34px rgba(122,255,183,.14)}
  .combatant-far .platform{width:72%}
  .sprite-slot{position:relative;display:grid;align-items:end;justify-items:center;width:100%;height:min(34cqh,calc(var(--sprite-native) * var(--max-upscale) * var(--depth,1)))}
  .combatant-far .sprite-slot{--depth:.82}
  .contact-shadow{position:absolute;bottom:-1%;left:50%;z-index:1;width:46%;height:11%;transform:translateX(-50%);border-radius:50%;background:radial-gradient(ellipse,rgba(0,0,0,.6),transparent 68%);filter:blur(2.5px);pointer-events:none}
  .sprite{position:relative;z-index:2;display:grid;place-items:end center;width:100%;height:100%;transform-origin:center bottom}
  /* Never scale a 96px sprite past MAX_UPSCALE; cap the footprint instead of stretching. */
  /* Height is the smaller of the slot and this asset's own size times the upscale cap, so a
     48px animated frame is never stretched as far as a 96px sheet. */
  .sprite img{display:block;width:auto;max-width:100%;height:min(100%,calc(var(--natural-h,96) * var(--max-upscale) * 1px));object-fit:contain;image-rendering:auto;filter:drop-shadow(0 10px 12px rgba(0,0,0,.5))}
  .battle-renderer[data-retro='true'] .sprite img{image-rendering:pixelated}
  .placeholder{display:grid;place-items:center;width:70%;aspect-ratio:1;border:1px solid var(--r-line);border-radius:50%;background:rgba(10,26,20,.9)}
  .placeholder span{font-size:clamp(1.4rem,3.4vw,3rem);font-weight:800;opacity:.85}
  .hp-delta{position:absolute;top:4%;left:50%;z-index:4;transform:translateX(-50%);color:#ff9089;font:900 clamp(1rem,2.3vw,2.1rem) var(--mono);text-shadow:0 2px 10px #000,0 0 22px rgba(0,0,0,.7);animation:value-pop .6s both}
  .hp-delta.positive{color:#8ef3a9}

  /* ── HP plate: identical hierarchy on both sides ────────────────────────── */
  .hp-plate{z-index:3;display:grid;gap:.22rem;width:min(100%,340px);padding:.4rem .55rem;border:1px solid rgba(240,250,244,.24);border-radius:9px;background:rgba(5,12,10,.93);box-shadow:0 8px 22px rgba(0,0,0,.4)}
  .plate-head{display:flex;align-items:baseline;gap:.4rem}
  .species{flex:1;overflow:hidden;font:800 clamp(.66rem,1vw,1rem)/1.1 var(--display);letter-spacing:-.02em;text-overflow:ellipsis;white-space:nowrap}
  .level{color:var(--r-dim);font:600 clamp(.46rem,.62vw,.6rem) var(--mono)}
  .status{padding:.08rem .3rem;border-radius:3px;background:#f0bf3f;color:#20180a;font:900 clamp(.42rem,.58vw,.55rem) var(--mono);letter-spacing:.06em}
  .hp-track{position:relative;height:clamp(7px,.85vh,11px);overflow:hidden;border-radius:999px;background:#12201a;box-shadow:inset 0 1px 2px rgba(0,0,0,.7)}
  .hp-track b,.hp-track i{position:absolute;inset:0 auto 0 0;display:block;height:100%;border-radius:inherit}
  .hp-track b{background:#fff1a8;opacity:.7;transition:width calc(var(--hp-duration) * 1.5) ease-out}
  .hp-track i{z-index:1;background:linear-gradient(180deg,color-mix(in srgb,var(--hp-color) 78%,white),var(--hp-color));transition:width var(--hp-duration) cubic-bezier(.2,.8,.2,1),background var(--hp-duration)}
  .hp-track[data-tone='high']{--hp-color:#55d775}
  .hp-track[data-tone='mid']{--hp-color:#efbd3e}
  .hp-track[data-tone='low']{--hp-color:#eb5b55}
  .plate-foot{display:flex;align-items:center;justify-content:space-between;gap:.4rem}
  .types{display:flex;gap:.22rem}
  .type-badge{padding:.06rem .34rem;border-radius:999px;background:var(--type-color);color:#0a140d;font:900 clamp(.4rem,.55vw,.52rem) var(--mono);font-style:normal;text-transform:uppercase}
  .hp-value{display:flex;align-items:baseline;gap:.3rem;font:800 clamp(.6rem,.85vw,.82rem) var(--mono)}
  .hp-value small{color:var(--r-dim);font-size:.72em;font-weight:500}

  /* ── Headline action and intent ─────────────────────────────────────────── */
  .action-banner{position:absolute;z-index:13;top:44%;left:50%;display:grid;justify-items:center;gap:.1rem;padding:.35rem 1.4rem;transform:translate(-50%,-50%);border-radius:6px;background:rgba(4,9,7,.9);border:1px solid var(--r-line);text-align:center}
  .action-banner small{color:var(--r-accent);font:900 clamp(.42rem,.58vw,.55rem) var(--mono);letter-spacing:.18em}
  .action-banner[data-phase='resolved'] small{color:var(--r-dim)}
  .action-banner b{font:800 clamp(.76rem,1.35vw,1.35rem)/1.1 var(--display);letter-spacing:-.02em;text-transform:uppercase}
  .action-banner em{color:var(--r-dim);font:600 clamp(.4rem,.55vw,.52rem) var(--mono);font-style:normal;letter-spacing:.1em}
  .action-banner[data-phase='resolved']{opacity:.62}
  .intent{position:absolute;z-index:11;display:grid;gap:.15rem;width:min(30%,340px);padding:.42rem .6rem;border-radius:7px;background:rgba(4,9,7,.86);border-left:3px solid var(--side-color)}
  .intent[data-side='p1']{--side-color:var(--r-p1)}
  .intent[data-side='p2']{--side-color:var(--r-p2)}
  .intent-far{top:16%;left:2.5%}
  .intent-near{right:2.5%;bottom:17%;justify-items:end;text-align:right;border-right:3px solid var(--side-color);border-left:0}
  .intent small{color:var(--side-color);font:900 clamp(.4rem,.55vw,.52rem) var(--mono);letter-spacing:.16em}
  .intent p{display:-webkit-box;overflow:hidden;margin:0;color:#dfeae3;font-size:clamp(.55rem,.78vw,.78rem);line-height:1.4;line-clamp:3;-webkit-box-orient:vertical;-webkit-line-clamp:3}
  .intent .thinking{color:var(--r-dim);font-style:italic}

  /* ── Effects ────────────────────────────────────────────────────────────── */
  .effect{position:absolute;z-index:9;inset:0;display:grid;place-items:center;pointer-events:none}
  .effect span{padding:.4rem 1.1rem;border-radius:4px;background:#f7fff9;color:#05100b;font:900 clamp(.7rem,1.3vw,1.35rem) var(--mono);letter-spacing:.08em;animation:effect-pop .6s both}
  .effect-critical-hit span{background:#ffd262}
  .effect-healing span{background:#8ef3a9}
  .effect-miss span,.effect-immune span,.effect-resisted span{background:#c6d0c8}
  .impact-burst{position:absolute;top:50%;left:50%;width:1px;height:1px}
  .effect[data-side='p1'] .impact-burst{top:72%;left:28%}
  .effect[data-side='p2'] .impact-burst{top:30%;left:72%}
  .impact-burst i{position:absolute;width:11px;aspect-ratio:1;border-radius:50% 10%;background:var(--type-color,#e4e7df);box-shadow:0 0 14px var(--type-color,#e4e7df);animation:particle-burst .58s ease-out both;animation-delay:var(--particle-delay)}
  .move-visual{--type-color:#e9f2ea;position:absolute;z-index:7;inset:0;pointer-events:none}
  .move-visual[data-direction='near-to-far']{--origin-x:30%;--origin-y:74%;--target-x:70%;--target-y:40%;--beam-angle:-38deg}
  .move-visual[data-direction='far-to-near']{--origin-x:70%;--origin-y:40%;--target-x:30%;--target-y:74%;--beam-angle:142deg}
  .move-projectile{position:absolute;top:var(--origin-y);left:var(--origin-x);width:clamp(16px,2.6vw,38px);aspect-ratio:1;border:2px solid color-mix(in srgb,var(--type-color) 80%,white);border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff,var(--type-color) 28%,transparent 70%);box-shadow:0 0 18px var(--type-color);animation:projectile-flight .5s cubic-bezier(.22,.7,.2,1) both}
  .move-beam{position:absolute;top:var(--origin-y);left:var(--origin-x);width:52%;height:6px;transform-origin:left center;transform:rotate(var(--beam-angle)) scaleX(0);border-radius:999px;background:linear-gradient(90deg,#fff,var(--type-color),transparent);box-shadow:0 0 14px var(--type-color);opacity:0;animation:beam-fire .46s ease-out both}
  .charge-ring{position:absolute;top:var(--origin-y);left:var(--origin-x);width:70px;aspect-ratio:1;transform:translate(-50%,-50%);border:2px solid var(--type-color);border-radius:50%;opacity:0;animation:charge-ring .5s ease-out both}
  .move-visual[data-archetype='physical'] .move-projectile,.move-visual[data-archetype='physical'] .move-beam{display:none}
  .move-visual[data-archetype='status'] .move-projectile,.move-visual[data-archetype='status'] .move-beam{display:none}
  .move-visual[data-archetype='status'] .charge-ring{top:50%;left:50%;width:30%;animation:status-aura .5s ease-out both}
  .move-visual[data-move-type='electric'] .move-beam,.move-visual[data-move-type='psychic'] .move-beam,.move-visual[data-move-type='dragon'] .move-beam,.move-visual[data-move-type='ice'] .move-beam{opacity:1}
  .move-visual[data-quality='low'] .charge-ring{display:none}
  .effect[data-move-type],.move-visual[data-move-type]{--type-color:#e4e7df}
  .effect[data-move-type='fire'],.move-visual[data-move-type='fire']{--type-color:#ff704f}
  .effect[data-move-type='water'],.move-visual[data-move-type='water']{--type-color:#55b8ff}
  .effect[data-move-type='electric'],.move-visual[data-move-type='electric']{--type-color:#ffe45e}
  .effect[data-move-type='grass'],.move-visual[data-move-type='grass']{--type-color:#75df6d}
  .effect[data-move-type='ice'],.move-visual[data-move-type='ice']{--type-color:#8feaff}
  .effect[data-move-type='fighting'],.move-visual[data-move-type='fighting']{--type-color:#ef7558}
  .effect[data-move-type='poison'],.move-visual[data-move-type='poison']{--type-color:#d073e5}
  .effect[data-move-type='ground'],.move-visual[data-move-type='ground']{--type-color:#d6a65e}
  .effect[data-move-type='flying'],.move-visual[data-move-type='flying']{--type-color:#9fb9ff}
  .effect[data-move-type='psychic'],.move-visual[data-move-type='psychic']{--type-color:#ff70b1}
  .effect[data-move-type='bug'],.move-visual[data-move-type='bug']{--type-color:#a8cf55}
  .effect[data-move-type='rock'],.move-visual[data-move-type='rock']{--type-color:#c6b477}
  .effect[data-move-type='ghost'],.move-visual[data-move-type='ghost']{--type-color:#9e88df}
  .effect[data-move-type='dragon'],.move-visual[data-move-type='dragon']{--type-color:#7e79ff}
  .effect[data-move-type='dark'],.move-visual[data-move-type='dark']{--type-color:#88766e}
  .effect[data-move-type='steel'],.move-visual[data-move-type='steel']{--type-color:#b5c4cb}
  .effect[data-move-type='fairy'],.move-visual[data-move-type='fairy']{--type-color:#ff9bd1}

  /* ── Spectator feed ─────────────────────────────────────────────────────── */
  .battle-feed{display:flex;gap:1px;height:clamp(64px,10.5%,112px);overflow:hidden;background:var(--r-line);border-top:1px solid var(--r-line)}
  .feed-turn{flex:1;min-width:0;overflow:hidden;padding:.4rem .8rem;background:rgba(5,11,9,.95)}
  .feed-label{display:block;margin-bottom:.16rem;color:var(--r-accent);font:900 clamp(.42rem,.56vw,.54rem) var(--mono);letter-spacing:.12em;text-transform:uppercase}
  .battle-feed p{overflow:hidden;margin:.06rem 0;color:var(--r-dim);font-size:clamp(.5rem,.68vw,.68rem);line-height:1.35;text-overflow:ellipsis;white-space:nowrap}
  .battle-feed p[data-emphasis='critical']{color:#ffd262}
  .battle-feed p[data-emphasis='positive']{color:#8cf2a7}
  .battle-feed p[data-emphasis='negative']{color:#ff9d98}

  /* ── Winner ─────────────────────────────────────────────────────────────── */
  .winner-banner{position:absolute;z-index:40;inset:0;display:grid;place-content:center;background:rgba(4,10,7,.86);text-align:center;backdrop-filter:blur(8px);animation:winner-in .7s both}
  .winner-banner small{color:var(--r-accent);font:900 .62rem var(--mono);letter-spacing:.24em}
  .winner-banner strong{margin:.35rem 0;font-size:clamp(2rem,6vw,5.5rem);font-weight:900;line-height:.92;letter-spacing:-.05em;text-transform:uppercase}
  .winner-banner span{color:var(--r-dim);font:.7rem var(--mono);text-transform:uppercase}

  /* ── Motion ─────────────────────────────────────────────────────────────── */
  .sprite.attacking{animation:attack-far .5s cubic-bezier(.2,.8,.2,1)}
  .combatant-near .sprite.attacking{animation-name:attack-near}
  .sprite.taking-damage{animation:hit .44s}
  .sprite.switching-in{animation:switch-in .6s}
  .sprite.switching-out{animation:switch-out .5s}
  .sprite.fainting{animation:faint .78s both}
  .sprite.status-flash{animation:status-flash .45s}
  .sprite.idle{animation:idle 3.6s ease-in-out infinite}
  .arena-shake{animation:arena-shake .44s cubic-bezier(.2,.8,.2,1) both}
  @keyframes idle{50%{transform:translateY(-2%) scale(1.012)}}
  @keyframes attack-far{45%{transform:translate(-14%,9%) scale(1.07)}}
  @keyframes attack-near{45%{transform:translate(14%,-9%) scale(1.07)}}
  @keyframes hit{20%,60%{transform:translateX(-8%);filter:brightness(1.9) saturate(.5)}40%,80%{transform:translateX(8%)}}
  @keyframes switch-in{from{opacity:0;transform:translateY(-18%) scale(.7)}55%{opacity:1;transform:translateY(2%) scale(1.05)}}
  @keyframes switch-out{to{opacity:0;transform:translateY(18%) scale(.7)}}
  @keyframes faint{to{opacity:0;transform:translateY(30%) scale(.75);filter:grayscale(1) brightness(.6)}}
  @keyframes status-flash{50%{filter:drop-shadow(0 0 22px #ffd05d) brightness(1.4)}}
  @keyframes effect-pop{from{opacity:0;transform:scale(.72)}32%{opacity:1;transform:scale(1.06)}to{opacity:0;transform:scale(1.16)}}
  @keyframes value-pop{from{opacity:0;transform:translate(-50%,14px) scale(.8)}22%{opacity:1;transform:translate(-50%,-4px) scale(1.12)}to{opacity:.95;transform:translate(-50%,-10px) scale(1)}}
  @keyframes winner-in{from{opacity:0;clip-path:inset(50% 0)}to{opacity:1;clip-path:inset(0)}}
  @keyframes arena-shake{0%,100%{transform:translate(0)}25%{transform:translate(-.5%,.28%)}50%{transform:translate(.42%,-.22%)}75%{transform:translate(-.2%,.13%)}}
  @keyframes projectile-flight{0%{transform:translate(-50%,-50%) scale(.45);opacity:0}18%{opacity:1}82%{opacity:1}100%{top:var(--target-y);left:var(--target-x);transform:translate(-50%,-50%) scale(1.3);opacity:0}}
  @keyframes beam-fire{0%,18%{transform:rotate(var(--beam-angle)) scaleX(0);opacity:0}38%,65%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:.9}100%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:0}}
  @keyframes charge-ring{0%{transform:translate(-50%,-50%) scale(1.5);opacity:0}30%{opacity:.8}70%{transform:translate(-50%,-50%) scale(.35);opacity:.8}100%{opacity:0}}
  @keyframes status-aura{from{transform:translate(-50%,-50%) scale(.25);opacity:.8}to{transform:translate(-50%,-50%) scale(1.5);opacity:0}}
  @keyframes particle-burst{from{transform:translate(0) scale(1);opacity:1}to{transform:translate(var(--particle-x),var(--particle-y)) rotate(150deg) scale(.15);opacity:0}}
  @keyframes weather-drift{to{background-position:70px 20px}}
  @keyframes weather-fall{to{background-position:18px 36px}}
  .battle-renderer.deterministic .sprite,.battle-renderer.deterministic .effect span,.battle-renderer.deterministic .impact-burst i,.battle-renderer.deterministic .move-projectile,.battle-renderer.deterministic .move-beam,.battle-renderer.deterministic .charge-ring,.battle-renderer.deterministic .arena-shake,.battle-renderer.deterministic .weather-layer,.battle-renderer.deterministic .winner-banner,.battle-renderer.deterministic .hp-delta{animation:none!important}
  .battle-renderer.deterministic .hp-track i,.battle-renderer.deterministic .hp-track b{transition:none!important}
  .battle-renderer.reduced-motion .sprite,.battle-renderer.reduced-motion .move-visual,.battle-renderer.reduced-motion .impact-burst,.battle-renderer.reduced-motion .arena-shake{animation:none!important;transform:none!important}
  @media(prefers-reduced-motion:reduce){.sprite,.effect span,.winner-banner{animation-duration:.001ms!important;animation-iteration-count:1!important}.hp-track i{transition-duration:.001ms!important}}

  /* ── Vertical (1080×1920) ───────────────────────────────────────────────── */
  .battle-renderer[data-layout='standard-vertical']{width:min(100%,620px);aspect-ratio:9/16;margin-inline:auto}
  .battle-renderer.overlay[data-layout='standard-vertical']{width:100vw;max-width:none;height:100vh;margin:0}
  .battle-renderer[data-layout='standard-vertical'] .combatant{width:min(64%,460px)}
  .battle-renderer[data-layout='standard-vertical'] .combatant-far{top:14%;right:3%}
  .battle-renderer[data-layout='standard-vertical'] .combatant-near{bottom:16%;left:3%}
  .battle-renderer[data-layout='standard-vertical'] .player-hud{max-width:46%}
  .battle-renderer[data-layout='standard-vertical'] .intent{width:min(52%,420px)}
  .battle-renderer[data-layout='standard-vertical'] .intent-far{top:26%}
  .battle-renderer[data-layout='standard-vertical'] .intent-near{bottom:28%}
  .battle-renderer[data-layout='standard-vertical'] .action-banner{top:48%}
  .battle-renderer[data-layout='standard-vertical'] .battle-feed{flex-direction:column;height:clamp(72px,11%,132px)}
  .battle-renderer[data-layout='standard-vertical'] .feed-turn:not(:last-child){display:none}
  .battle-renderer[data-layout='overlay-landscape']{border-radius:0}

  /* ── Narrow desktop and mobile ──────────────────────────────────────────── */
  @media(max-width:900px){
    .battle-renderer:not([data-layout='standard-vertical']){aspect-ratio:auto;min-height:620px}
    .combatant{width:46%}
    .intent{width:44%}
  }
  @media(max-width:560px){
    .battle-renderer{border-radius:10px}
    .combatant{width:56%}
    .combatant-far{top:10%;right:2%}
    .combatant-near{bottom:6%;left:2%}
    .player-hud{max-width:44%}
    .intent{display:none}
    .battle-feed .feed-turn:not(:last-child){display:none}
  }

  .renderer-loading{display:grid;place-content:center;min-height:420px;padding:2rem;text-align:center}
  .renderer-loading h2{margin:.5rem 0}
  .renderer-loading p{color:var(--muted)}
</style>
