<script lang="ts">
  import { pokemonAssetUrl } from './presentation/assets';
  import { apiBase } from './api';
  import { moveEffectAssetUrl, resolveMoveEffect } from './move-effects';
  import { readableInk } from './challenge';
  import {
    defaultRendererConfig,
    type BattlePresentationState,
    type RendererConfig
  } from './presentation/types';
  import type { BattleSide, CampaignBadge, PokemonState, Side } from './types';
  import type { VoiceChannel } from './production/audio-engine';
  import RendererBroadcast from './battle-renderer/RendererBroadcast.svelte';
  import RendererCommentary from './battle-renderer/RendererCommentary.svelte';
  import RendererCards from './battle-renderer/RendererCards.svelte';

  export let presentation: BattlePresentationState | null = null;
  export let config: RendererConfig = defaultRendererConfig();
  export let overlay = false;
  export let deterministic = false;
  export let logicalElapsedMs = 0;
  export let visualProgress = 0;
  export let speaking: readonly VoiceChannel[] = [];
  /** Public Draft stage identity, when this match is one. Presentation only. */
  export let campaign: CampaignBadge | null = null;

  let failedAssets = new Set<string>();
  let failedEffectAssets = new Set<string>();
  const particleIndexes = Array.from({ length: 12 }, (_, index) => index);
  /**
   * Installed Showdown battle sprites are 96px static PNGs and ~60-96px animated GIFs.
   * Enlarging one beyond this factor turns a crisp asset into mush, so the stage caps the
   * footprint instead of stretching sprites to fill space.
   */
  const NATIVE_SPRITE_PX = 96;
  const MAX_UPSCALE = 2;
  const TEAM_SIZE = 6;
  const RETRO_GENERATIONS = new Set([1, 2]);

  interface Slot {
    place: 'far' | 'near';
    side: Side;
    active: PokemonState;
    fieldSlot: number;
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
  $: moveRecipe = moveProfile && presentation?.currentMove
    ? resolveMoveEffect(presentation.currentMove, moveProfile.type, moveProfile.archetype, config.moveEffectSkin)
    : null;
  $: strongImpact = Boolean(
    presentation && ['impact', 'critical-hit', 'super-effective'].includes(presentation.effect)
  );
  $: hpDuration =
    config.playbackSpeed === 'instant' || config.preset === 'instant'
      ? 0
      : Math.round(650 / Number(config.playbackSpeed));
  $: formatLabel = formatName(presentation?.format || '', generation);
  $: finalPokemon = isFinalPokemon(near) && isFinalPokemon(far);
  $: doublesLayout = activeSlots(near).length > 1 || activeSlots(far).length > 1;
  $: slots = [
    ...activeSlots(far).map((active, fieldSlot) => ({
      place: 'far' as const,
      side: farSide,
      active,
      fieldSlot,
      perspective: 'front' as const
    })),
    ...activeSlots(near).map((active, fieldSlot) => ({
      place: 'near' as const,
      side: nearSide,
      active,
      fieldSlot,
      perspective: 'back' as const
    }))
  ] as Slot[];

  function battleSide(state: BattlePresentationState, side: Side): BattleSide | null {
    const battle = state.battle;
    if (!battle) return null;
    if (battle.player.side === side) return battle.player;
    return battle.opponent.side === side ? battle.opponent : null;
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

  function activeSlots(side: BattleSide | null): PokemonState[] {
    if (!side) return [];
    if (side.active_slots?.length) return side.active_slots;
    const teamActives = side.team.filter((pokemon) => pokemon.active);
    if (teamActives.length) return teamActives;
    return side.active ? [side.active] : [];
  }

  function assetKey(active: PokemonState, perspective: 'front' | 'back') {
    return `${active.species}:${perspective}:${config.animatedSprites}`;
  }

  function renderablePokemon(active: PokemonState | null | undefined): active is PokemonState {
    const species = active?.species?.toLocaleLowerCase().replace(/[^a-z0-9]/g, '') || '';
    return Boolean(active && species && species !== 'unknown' && species !== 'egg');
  }

  function onAssetError(key: string) {
    failedAssets = new Set([...failedAssets, key]);
  }

  function onEffectAssetError(key: string) {
    failedEffectAssets = new Set([...failedEffectAssets, key]);
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

  function isFinalPokemon(side: BattleSide | null) {
    const team = side?.team || [];
    return team.length === TEAM_SIZE && team.filter((member) => !member.fainted).length === 1;
  }

  function pokemonGender(active: PokemonState | null | undefined): 'male' | 'female' | null {
    if (!active) return null;
    const text = `${active.id} ${active.name}`;
    if (text.includes('♂') || text.endsWith(', M') || text.includes(' M ')) return 'male';
    if (text.includes('♀') || text.endsWith(', F') || text.includes(' F ')) return 'female';
    return null;
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

  function switchTransitionStyle(phase: 'outgoing' | 'incoming', isNear: boolean) {
    if (!deterministic) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    if (phase === 'outgoing') {
      const local = Math.min(1, progress / .38);
      return `opacity:${1 - local};transform:translate(${(isNear ? -1 : 1) * local * 14}%,${local * 10}%) scale(${1 - local * .2})`;
    }
    const local = Math.max(0, Math.min(1, (progress - .34) / .66));
    return `opacity:${local};transform:translate(${(isNear ? 1 : -1) * (1 - local) * 12}%,${(1 - local) * -10}%) scale(${.78 + local * .22})`;
  }

  function switchPlateStyle(side: Side) {
    if (!deterministic || !presentation?.switchTransitions[side]) return '';
    const progress = Math.max(0, Math.min(1, visualProgress));
    return `opacity:${progress < .34 ? 0 : Math.min(1, (progress - .34) / .2)}`;
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

  /** Screen-reader wording that never claims HP points the app does not have. */
  function hpLabel(active: NonNullable<BattleSide['active']>) {
    return active.hp_is_exact === false
      ? `${hpPercent(active)}%`
      : `${formatExactHp(active)} HP (${hpPercent(active)}%)`;
  }

  function formatExactHp(active: NonNullable<BattleSide['active']>) {
    // Showdown only reveals real HP points for the side it is talking to; the other
    // side arrives as a percentage. Rendering that as "2 / 100" claimed a 100 HP bar,
    // so a percentage-only reading is shown as the percentage it actually is.
    if (active.hp_is_exact === false) return `${hpPercent(active)}%`;
    if (active.current_hp != null && active.max_hp) {
      // Older normalized snapshots can carry a stale absolute value next to the authoritative
      // fraction. Never render a mathematically impossible pair such as 303 / 303 (19%).
      const recordedFraction = active.current_hp / active.max_hp;
      const current = Math.abs(recordedFraction - active.hp_fraction) <= 0.015
        ? active.current_hp
        : Math.round(active.hp_fraction * active.max_hp);
      return `${current} / ${active.max_hp}`;
    }
    const max = active.max_hp || (active.level ? Math.round(active.level * 3.1 + 25) : 250);
    const curr = Math.round(active.hp_fraction * max);
    return `${curr} / ${max}`;
  }
</script>

{#if presentation}
  {@const p1Side = battleSide(presentation, 'p1')}
  {@const p2Side = battleSide(presentation, 'p2')}
  <section
    class:overlay
    class:transparent={config.transparentBackground}
    class:deterministic
    class:doubles-layout={doublesLayout}
    class:reduced-motion={config.reducedMotion}
    class:voice-active={speaking.length > 0}
    class="battle-renderer"
    data-layout={config.layout}
    data-renderer-theme={config.theme}
    data-generation={generation}
    data-retro={retro}
    style={`--hp-duration:${hpDuration}ms;--sprite-native:${NATIVE_SPRITE_PX}px;--max-upscale:${MAX_UPSCALE};--hud-scale:${config.hudScale}`}
    aria-label="KoalaBattle production renderer"
  >
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

      <!-- Authentic Pokémon Gen 5 HUD: Symmetrical HP Plates in the classic corners -->
      {#each slots as slot (`${slot.side}-${slot.fieldSlot}`)}
        {#if renderablePokemon(slot.active)}
          {@const gender = pokemonGender(slot.active)}
          <div
            class={`hp-plate plate-${slot.place} field-slot-${slot.fieldSlot}`}
            class:switching={Boolean(presentation.switchTransitions[slot.side])}
            data-side={slot.side}
            data-field-slot={slot.fieldSlot}
            style={switchPlateStyle(slot.side)}
            role="region"
            aria-label={`${slot.active.name}, ${hpLabel(slot.active)} health`}
          >
            <div class={`gen5-box gen5-${slot.place}-box`}>
              <!-- Top Row: Name | Level | Gender | Types | Status -->
              <div class="gen5-top-row">
                <div class="gen5-name-wrap">
                  <b class="gen5-name">{slot.active.name}</b>
                </div>
                <div class="gen5-lv-badge" aria-label={`Level ${slot.active.level ?? 50}`}>
                  <span class="lv-text">Lv.</span>
                  <b class="lv-val">{slot.active.level ?? 50}</b>
                </div>
                {#if gender}
                  <div class={`gen5-gender-badge ${gender}`} aria-label={gender}>
                    <span>{gender === 'male' ? '♂' : '♀'}</span>
                  </div>
                {/if}
                <div class="gen5-types-row">
                  {#each slot.active.types as type}
                    <span class="gen5-type-badge" style={`--type-bg:${typeColor(type)};--type-ink:${readableInk(typeColor(type))}`}>{type}</span>
                  {/each}
                </div>
                {#if slot.active.status}
                  <span class={`gen5-status-badge status-${slot.active.status.toLowerCase()}`}>{readableStatus(slot.active.status)}</span>
                {/if}
              </div>

              <!-- Bar Row: High-visibility HP Bar -->
              <div class="gen5-bar-row">
                <div
                  class="gen5-hp-track"
                  data-tone={hpTone(slot.active.hp_fraction)}
                  role="progressbar"
                  aria-valuenow={hpPercent(slot.active)}
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-label={`${slot.active.name} health`}
                >
                  <b style={`width:${previousHp(slot.side, slot.active.hp_fraction) * 100}%`}></b>
                  <i style={`width:${slot.active.hp_fraction * 100}%`}></i>
                </div>
              </div>

              <!-- Bottom Row: HP Readout (Exact numbers + % on BOTH plates) -->
              <div class="gen5-bottom-row">
                <div class="gen5-hp-label">HP</div>
                <div class="gen5-exact-hp-wrap">
                  <b class="gen5-exact-hp">{formatExactHp(slot.active)}</b>
                  <!-- Suppressed when the bar is already a percentage: "2% (2%)". -->
                  {#if slot.active.hp_is_exact !== false}
                    <span class="gen5-hp-pct">({hpPercent(slot.active)}%)</span>
                  {/if}
                </div>
              </div>
            </div>
          </div>
        {/if}
      {/each}

      <!-- Combatants: Grounded sprites positioned in classic perspective -->
      {#each slots as slot (`${slot.side}-${slot.fieldSlot}`)}
        {@const transition = slot.fieldSlot === 0 ? presentation.switchTransitions[slot.side] : null}
        {#if renderablePokemon(slot.active) && (transition || !slot.active.fainted || presentation.players[slot.side].motion === 'fainting')}
          <article
            class={`combatant combatant-${slot.place} field-slot-${slot.fieldSlot}`}
            class:speaking={speaking.includes(slot.side) || speaking.includes('narrator')}
            data-side={slot.side}
            data-field-slot={slot.fieldSlot}
            data-fainted={slot.active.fainted}
            data-switching={Boolean(transition)}
            aria-label={`${slot.active.name}: ${hpLabel(slot.active)}`}
          >
            <div class="sprite-slot">
              <div class="platform" aria-hidden="true"><i class="pedestal-surface"></i><i class="pedestal-rim"></i></div>
              <div class="contact-shadow" aria-hidden="true"></div>
              {#if transition}
                {#key transition.sequence}
                  {#if transition.outgoing}
                    {@const outgoingKey = `${transition.outgoing.species}:${slot.perspective}:${config.animatedSprites}`}
                    <div style={switchTransitionStyle('outgoing', slot.place === 'near')} class="sprite switch-sprite switch-outgoing">
                      {#if !failedAssets.has(outgoingKey)}
                        <img src={spriteUrl(transition.outgoing.species, slot.perspective)} alt={transition.outgoing.name} on:load={onAssetLoad} on:error={() => onAssetError(outgoingKey)} />
                      {:else}<div class="sprite-missing"><span class="pokeball" aria-hidden="true"><i></i></span><small>SPRITE</small></div>{/if}
                    </div>
                  {/if}
                  {@const incomingKey = `${transition.incoming.species}:${slot.perspective}:${config.animatedSprites}`}
                  <div style={switchTransitionStyle('incoming', slot.place === 'near')} class="sprite switch-sprite switch-incoming">
                    {#if !failedAssets.has(incomingKey)}
                      <img src={spriteUrl(transition.incoming.species, slot.perspective)} alt={transition.incoming.name} on:load={onAssetLoad} on:error={() => onAssetError(incomingKey)} />
                    {:else}<div class="sprite-missing"><span class="pokeball" aria-hidden="true"><i></i></span><small>SPRITE</small></div>{/if}
                  </div>
                {/key}
              {:else}
                {#key `${slot.active.species}:${presentation.players[slot.side].motion}`}
                  <div
                    style={spriteStyle(presentation.players[slot.side].motion, slot.place === 'near')}
                    class={`sprite ${presentation.players[slot.side].motion}`}
                  >
                    {#if !failedAssets.has(assetKey(slot.active, slot.perspective))}
                      <img
                        src={spriteUrl(slot.active.species, slot.perspective)}
                        alt={slot.active.name}
                        on:load={onAssetLoad}
                        on:error={() => onAssetError(assetKey(slot.active, slot.perspective))}
                      />
                    {:else}
                      <div class="sprite-missing"><span class="pokeball" aria-hidden="true"><i></i></span><small>SPRITE</small></div>
                    {/if}
                  </div>
                {/key}
              {/if}
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
          </article>
        {/if}
      {/each}

      <!-- Move visual animations: projectiles, beams, bursts -->
      {#if presentation.currentMoveProfile && presentation.currentMovePhase === 'executing' && moveRecipe && config.effects !== 'off'}
        {@const profile = presentation.currentMoveProfile}
        <div
          class="move-visual"
          data-archetype={profile.archetype}
          data-move-type={profile.type}
          data-direction={presentation.currentMoveSide === (config.nearSide || 'p1') ? 'near-to-far' : 'far-to-near'}
          data-quality={config.effects}
          data-recipe={moveRecipe.family}
          data-skin={config.moveEffectSkin}
          style={`--type-color:${moveRecipe.color};--type-highlight:${moveRecipe.secondary};--move-duration:${moveRecipe.durationMs}ms`}
          aria-hidden="true"
        >
          <div style={chargeStyle()} class="charge-ring"></div>
          <div class="physical-swipe" aria-hidden="true"><i></i><i></i><i></i></div>
          <div style={projectileStyle(presentation.currentMoveSide === (config.nearSide || 'p1') ? 'near-to-far' : 'far-to-near')} class="move-projectile"></div>
          <div style={beamStyle(presentation.currentMoveSide === (config.nearSide || 'p1') ? 'near-to-far' : 'far-to-near')} class="move-beam"></div>
          <div class="recipe-layer recipe-layer-a"></div>
          <div class="recipe-layer recipe-layer-b"></div>
          <div class="recipe-layer recipe-layer-c"></div>
          {#if moveRecipe.assetId && !failedEffectAssets.has(moveRecipe.assetId)}
            <img class="move-texture" src={moveEffectAssetUrl(moveRecipe.assetId, apiBase())} alt="" on:error={() => moveRecipe?.assetId && onEffectAssetError(moveRecipe.assetId)} />
          {/if}
        </div>
      {/if}

      {#if finalPokemon && !presentation.finished}
        <div class="final-signal" role="status" aria-live="polite">
          <small>CLUTCH MOMENT</small>
          <strong>FINAL POKÉMON!</strong>
          <span>One remaining fighter on each side</span>
        </div>
      {/if}

      <!-- Effect callout & particles -->
      {#key `${presentation.effect}:${presentation.eventSequence}`}
        {#if presentation.effect !== 'none'}
          <div
            class={`effect effect-${presentation.effect}`}
            data-side={presentation.effectSide || ''}
            data-move-type={presentation.currentMoveProfile?.type || 'normal'}
            aria-hidden="true"
          >
            {#if config.effects !== 'off'}
              <div class="impact-burst">
                {#each particleIndexes.slice(0, config.effects === 'low' ? 6 : config.effects === 'high' ? 12 : 9) as index}
                  <i style={particleStyle(index, presentation.currentMoveProfile?.seed || presentation.eventSequence)}></i>
                {/each}
              </div>
            {/if}
            <span style={transientStyle()}>{presentation.effect === 'super-effective' ? 'SUPER EFFECTIVE' : presentation.effect === 'resisted' ? 'NOT VERY EFFECTIVE' : presentation.effect === 'immune' ? 'NO EFFECT' : presentation.effect.replace('-', ' ')}</span>
          </div>
        {/if}
      {/key}

      <RendererCommentary {presentation} {config} />
    </div>

    <RendererBroadcast {config} {p1Side} {p2Side} {deterministic} />

    <RendererCards {presentation} {config} {formatLabel} {campaign} {deterministic} />
  </section>
{:else}
  <section class="renderer-loading panel"><span class="eyebrow">Renderer ready</span><h2>Waiting for normalized battle state…</h2><p>No engine connection is required to draw this frame.</p></section>
{/if}

<style>
  /* ── Shell ──────────────────────────────────────────────────────────────── */
  .battle-renderer{
    --r-ink:#f4fbf6;--r-dim:#93a89b;--r-line:rgba(140,255,186,.16);--r-accent:#78ffa9;
    --r-p1:#5fe39a;--r-p2:#c98cff;--r-panel:rgba(6,12,10,.88);
    --r-hp-high:#55d775;--r-hp-mid:#efbd3e;--r-hp-low:#eb5b55;
    position:relative;isolation:isolate;display:grid;grid-template-rows:1fr auto;
    container-type:size;width:100%;aspect-ratio:16/9;min-height:480px;overflow:hidden;
    border:1px solid var(--r-line);border-radius:14px;background:#050a08;color:var(--r-ink);
    box-shadow:0 30px 90px rgba(0,0,0,.42);font-family:var(--display)
  }
  .battle-renderer.transparent{background:transparent;border-color:transparent;box-shadow:none}
  .battle-renderer.overlay{width:100vw;height:100vh;min-height:0;aspect-ratio:auto;border:0;border-radius:0;box-shadow:none}

  /* ── Arena ──────────────────────────────────────────────────────────────── */
  .stage{position:relative;overflow:hidden;background:#060d0b;container-type:size}
  .stage-sky{position:absolute;inset:0;background:radial-gradient(120% 80% at 50% 6%,#1a4a54 0,#0d2733 42%,#060d0b 78%)}
  .stage-sky::after{content:'';position:absolute;inset:0;background:radial-gradient(70% 48% at 50% 34%,rgba(122,255,183,.13),transparent 70%)}
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
  .stage-floor{position:absolute;inset:52% 0 0;background:linear-gradient(180deg,#154238 0,#0b241f 38%,#050c0a)}
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

  /* ── Pokemon Route Theme (Matches Reference Screenshot Pixel-for-Pixel) ─── */
  [data-renderer-theme='pokemon-route'] .stage-sky{background:linear-gradient(180deg,#7a99a8 0%,#9eb9c5 45%,#bfd5dd 80%,#d2e4ea 100%)}
  [data-renderer-theme='pokemon-route'] .stage-sky::after{background:radial-gradient(75% 35% at 75% 20%,rgba(255,255,255,.7),transparent 65%)}
  [data-renderer-theme='pokemon-route'] .stage-bowl{inset:10% 0 38%}
  [data-renderer-theme='pokemon-route'] .stage-bowl .crowd{border-radius:0;background:repeating-linear-gradient(90deg,transparent 0 45px,rgba(50,42,35,.7) 45px 52px,transparent 52px 90px),linear-gradient(180deg,transparent 0%,rgba(40,75,50,.5) 25%,#2a5538 55%,#1c3d26 85%,#142e1c 100%);opacity:.98;mask-image:linear-gradient(180deg,transparent 0%,black 20%)}
  [data-renderer-theme='pokemon-route'] .stage-bowl .rail{display:none}
  [data-renderer-theme='pokemon-route'] .stage-lights{display:none}
  [data-renderer-theme='pokemon-route'] .stage-floor{inset:42% 0 0;background:radial-gradient(ellipse 45% 38% at 78% 28%,#e2d9b6 0%,#d0c49b 70%,transparent 72%),linear-gradient(132deg,#91b572 0%,#84a866 22%,#e2d9b6 26%,#d4c89e 48%,#cfc296 56%,#d8cc9e 70%,#84a866 74%,#91b572 100%)}
  [data-renderer-theme='pokemon-route'] .floor-grid{background-image:radial-gradient(circle,rgba(0,0,0,.035) 1px,transparent 1px);background-size:16px 16px;transform:none;mask-image:none}
  [data-renderer-theme='pokemon-route'] .floor-glow{display:none}

  /* ── Pokemon Stadium Theme ──────────────────────────────────────────────── */
  [data-renderer-theme='pokemon-stadium'] .stage-sky{background:linear-gradient(180deg,#1c3342 0%,#112530 50%,#09151c 100%)}
  [data-renderer-theme='pokemon-stadium'] .stage-floor{inset:48% 0 0;background:linear-gradient(180deg,#1d4036 0%,#112b24 50%,#091713 100%)}
  [data-renderer-theme='pokemon-stadium'] .stage-bowl .rail{background:linear-gradient(180deg,rgba(90,200,255,.4),rgba(5,15,20,.9));box-shadow:0 0 30px rgba(70,180,255,.25)}

  /* ── Authentic Gen 5 Pokemon HP Plates (Exact Match to Reference Screenshot) */
  .hp-plate{position:absolute;z-index:25;pointer-events:none;font-family:var(--display);filter:drop-shadow(0 6px 14px rgba(0,0,0,.65))}
  .plate-far{top:5%;left:3%;width:clamp(260px,33cqw,390px)}
  .plate-near{bottom:8%;right:3%;width:clamp(270px,35cqw,410px)}

  /* Far Box (Opponent): Charcoal polygon angled to the right */
  .gen5-far-box{position:relative;background:#242827;border:2px solid #363e3d;border-radius:3px;padding:clamp(6px,.85cqw,9px) clamp(10px,1.3cqw,16px);clip-path:polygon(0 0,calc(100% - 22px) 0,100% 100%,0 100%);box-shadow:inset 0 1px 1px rgba(255,255,255,.15)}

  /* Near Box (Player): Charcoal polygon angled to the left */
  .gen5-near-box{position:relative;background:#242827;border:2px solid #363e3d;border-radius:3px;padding:clamp(6px,.85cqw,9px) clamp(10px,1.3cqw,16px);clip-path:polygon(22px 0,100% 0,100% 100%,0 100%);box-shadow:inset 0 1px 1px rgba(255,255,255,.15)}

  .gen5-top-row{display:flex;align-items:center;gap:clamp(6px,.8cqw,12px);margin-bottom:3px}
  .plate-near .gen5-top-row{justify-content:flex-end}
  .gen5-name-wrap{flex:1;overflow:hidden}
  .gen5-name{font-size:calc(var(--hud-scale,1) * clamp(1.05rem,1.5cqw,1.55rem));font-weight:900;letter-spacing:-.01em;text-transform:capitalize;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.9);white-space:nowrap}

  /* Level Badge: Lv. stacked above number in white */
  .gen5-lv-badge{display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1;font-family:var(--display);color:#fff}
  .gen5-lv-badge .lv-text{font-size:calc(var(--hud-scale,1) * clamp(.55rem,.72cqw,.72rem));font-weight:700;color:#cde0e0;letter-spacing:-.02em}
  .gen5-lv-badge .lv-val{font-size:calc(var(--hud-scale,1) * clamp(.88rem,1.15cqw,1.15rem));font-weight:900}

  /* Gender Rhombus: Sky blue parallelogram */
  .gen5-gender-badge{display:flex;align-items:center;justify-content:center;padding:2px 9px;background:#5ba5f5;transform:skewX(-20deg);border-radius:2px;box-shadow:0 1px 3px rgba(0,0,0,.4)}
  .gen5-gender-badge.female{background:#f57ab5}
  .gen5-gender-badge span{transform:skewX(20deg);font-size:.95em;font-weight:900;color:#0b1928}
  .gen5-status-badge{padding:1px 5px;border-radius:2px;background:#e69d24;color:#1a0f00;font-size:.65rem;font-weight:900;letter-spacing:.05em;text-transform:uppercase}

  /* Full-width HP bar groove with lime-green bar */
  .gen5-bar-row{position:relative;width:100%;margin-top:2px}
  .gen5-hp-track{position:relative;width:100%;height:calc(var(--hud-scale,1) * clamp(9px,1.2cqh,14px));border-radius:999px;background:#080e10;border:1px solid rgba(255,255,255,.18);overflow:hidden;box-shadow:inset 0 2px 4px rgba(0,0,0,.85)}
  .gen5-hp-track b,.gen5-hp-track i{position:absolute;inset:0 auto 0 0;height:100%;border-radius:inherit}
  .gen5-hp-track b{background:#fff3a8;opacity:.6;transition:width calc(var(--hp-duration) * 1.4) ease-out}
  .gen5-hp-track i{z-index:1;background:linear-gradient(180deg,#9be842 0%,#74e028 55%,#429b10 100%);transition:width var(--hp-duration) cubic-bezier(.2,.8,.2,1)}
  .gen5-hp-track[data-tone='mid'] i{background:linear-gradient(180deg,#ffd756 0%,#e6a817 60%,#a87405 100%)}
  .gen5-hp-track[data-tone='low'] i{background:linear-gradient(180deg,#ff7268 0%,#e62c20 60%,#9e140b 100%)}

  /* Near Box: Exact Numbers Row with Percentage */
  .gen5-num-row,.gen5-bottom-row{display:flex;justify-content:space-between;align-items:center;gap:.35rem;margin-top:4px}
  .gen5-exact-hp-wrap{display:flex;align-items:baseline;gap:.25rem}
  .gen5-exact-hp{font-family:var(--display);font-size:calc(var(--hud-scale,1) * clamp(.92rem,1.25cqw,1.25rem));font-weight:800;color:#fff;letter-spacing:.04em;font-variant-numeric:tabular-nums;font-feature-settings:'tnum' 1;text-shadow:0 1px 3px rgba(0,0,0,.85)}
  .gen5-near-pct{font-family:var(--mono);font-size:calc(var(--hud-scale,1) * clamp(.72rem,.95cqw,.95rem));font-weight:700;color:#9fe6b8;font-variant-numeric:tabular-nums;font-feature-settings:'tnum' 1;text-shadow:0 1px 2px rgba(0,0,0,.9)}
  /* ── Authentic Gen 5 Pokemon HP Plates (Symmetrical & High Readability) ─── */
  .hp-plate{position:absolute;z-index:25;pointer-events:none;font-family:var(--display);filter:drop-shadow(0 8px 18px rgba(0,0,0,.75))}
  .hp-plate.switching{animation:hp-plate-switch .3s .14s ease-out both}
  .plate-far{top:5%;left:3.5%;width:clamp(320px,39cqw,500px)}
  .plate-near{bottom:6%;right:3.5%;width:clamp(320px,39cqw,500px)}
  .doubles-layout .hp-plate{width:clamp(230px,29cqw,370px)}
  .doubles-layout .plate-far.field-slot-0{left:2%}
  .doubles-layout .plate-far.field-slot-1{left:31.5%}
  /* Near-side sprites grow left-to-right; their HUD cards must follow that same slot order. */
  .doubles-layout .plate-near.field-slot-0{right:31.5%}
  .doubles-layout .plate-near.field-slot-1{right:2%}

  .gen5-box{position:relative;background:#202524;border:2px solid #36403e;border-radius:4px;padding:clamp(6px,.85cqw,9px) clamp(12px,1.4cqw,18px);box-shadow:inset 0 1px 1px rgba(255,255,255,.18),0 8px 20px rgba(0,0,0,.7)}
  .gen5-far-box{clip-path:polygon(0 0,calc(100% - 24px) 0,100% 100%,0 100%)}
  .gen5-near-box{clip-path:polygon(24px 0,100% 0,100% 100%,0 100%)}

  .gen5-top-row{display:flex;align-items:center;gap:clamp(6px,.8cqw,10px);margin-bottom:3px}
  .gen5-name-wrap{flex:1;overflow:hidden}
  .gen5-name{font-size:calc(var(--hud-scale,1) * clamp(1.1rem,1.55cqw,1.6rem));font-weight:900;letter-spacing:-.01em;text-transform:capitalize;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.9);white-space:nowrap}

  /* Level Badge: Lv. stacked above number in white */
  .gen5-lv-badge{display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1;font-family:var(--display);color:#fff}
  .gen5-lv-badge .lv-text{font-size:calc(var(--hud-scale,1) * clamp(.55rem,.72cqw,.72rem));font-weight:700;color:#cde0e0;letter-spacing:-.02em}
  .gen5-lv-badge .lv-val{font-size:calc(var(--hud-scale,1) * clamp(.92rem,1.2cqw,1.25rem));font-weight:900}

  /* Gender Rhombus */
  .gen5-gender-badge{display:flex;align-items:center;justify-content:center;padding:2px 8px;background:#5ba5f5;transform:skewX(-20deg);border-radius:2px;box-shadow:0 1px 3px rgba(0,0,0,.4)}
  .gen5-gender-badge.female{background:#f57ab5}
  .gen5-gender-badge span{transform:skewX(20deg);font-size:.95em;font-weight:900;color:#0b1928}

  /* Prominent Type Badges */
  .gen5-types-row{display:flex;gap:5px;align-items:center}
  .gen5-type-badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:4px;background:var(--type-bg,#788a80);color:var(--type-ink,#fff);font-family:var(--mono);font-size:calc(var(--hud-scale,1) * clamp(.62rem,.8cqw,.82rem));font-weight:900;text-transform:uppercase;letter-spacing:.06em;box-shadow:0 1px 3px rgba(0,0,0,.5)}

  /* Distinct Status Badges */
  .gen5-status-badge{padding:2px 7px;border-radius:3px;font-family:var(--mono);font-size:.68rem;font-weight:900;letter-spacing:.06em;text-transform:uppercase;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.85)}
  .status-brn{background:#ff5733}
  .status-par{background:#f4bf23;color:#1c1400;text-shadow:none}
  .status-slp{background:#8e909a}
  .status-frz{background:#3ec7f3;color:#021a24;text-shadow:none}
  .status-psn,.status-tox{background:#b538e6}

  /* Full-width HP bar groove with lime-green bar */
  .gen5-bar-row{position:relative;width:100%;margin-top:3px}
  .gen5-hp-track{position:relative;width:100%;height:calc(var(--hud-scale,1) * clamp(10px,1.3cqh,15px));border-radius:999px;background:#080e10;border:1.5px solid rgba(255,255,255,.2);overflow:hidden;box-shadow:inset 0 2px 5px rgba(0,0,0,.9)}
  .gen5-hp-track b,.gen5-hp-track i{position:absolute;inset:0 auto 0 0;height:100%;border-radius:inherit}
  .gen5-hp-track b{background:#fff3a8;opacity:.6;transition:width calc(var(--hp-duration) * 1.4) ease-out}
  .gen5-hp-track i{z-index:1;background:linear-gradient(180deg,#9be842 0%,#74e028 55%,#429b10 100%);transition:width var(--hp-duration) cubic-bezier(.2,.8,.2,1)}
  .gen5-hp-track[data-tone='mid'] i{background:linear-gradient(180deg,#ffd756 0%,#e6a817 60%,#a87405 100%)}
  .gen5-hp-track[data-tone='low'] i{background:linear-gradient(180deg,#ff7268 0%,#e62c20 60%,#9e140b 100%)}

  /* Bottom Row: Exact HP Numbers & Readout on Both Plates */
  .gen5-bottom-row{display:flex;justify-content:space-between;align-items:baseline;margin-top:4px}
  .gen5-hp-label{font-family:var(--mono);font-size:calc(var(--hud-scale,1) * clamp(.66rem,.86cqw,.88rem));font-weight:900;color:#ffd679;letter-spacing:.08em}
  .gen5-exact-hp-wrap{display:flex;align-items:baseline;gap:.35rem}
  .gen5-exact-hp{font-family:var(--display);font-size:calc(var(--hud-scale,1) * clamp(.98rem,1.3cqw,1.35rem));font-weight:900;color:#fff;letter-spacing:.02em;font-variant-numeric:tabular-nums;font-feature-settings:'tnum' 1;text-shadow:0 1px 3px rgba(0,0,0,.9)}
  .gen5-hp-pct{font-family:var(--mono);font-size:calc(var(--hud-scale,1) * clamp(.76rem,1cqw,1.02rem));font-weight:800;color:#8ef3a9;font-variant-numeric:tabular-nums;font-feature-settings:'tnum' 1;text-shadow:0 1px 2px rgba(0,0,0,.9)}

  /* ── Combatants & Sprites (Classic Perspective) ─────────────────────────── */
  .combatant{position:absolute;z-index:10;display:flex;align-items:center;justify-content:center;pointer-events:none}
  .combatant-far{top:15%;right:27%;width:min(30%,340px)}
  .combatant-near{bottom:4%;left:8%;width:min(38%,440px)}
  .doubles-layout .combatant{width:min(27%,310px)}
  .doubles-layout .combatant-far.field-slot-0{right:54%}
  .doubles-layout .combatant-far.field-slot-1{right:32%}
  .doubles-layout .combatant-near.field-slot-0{left:7%}
  .doubles-layout .combatant-near.field-slot-1{left:30%}
  .platform{position:absolute;bottom:0;left:50%;width:88%;aspect-ratio:3.4/1;transform:translate(-50%,36%);pointer-events:none}
  .platform .pedestal-surface{position:absolute;inset:0;border-radius:50%;background:radial-gradient(ellipse at 50% 46%,rgba(140,255,190,.32),rgba(20,74,62,.44) 56%,transparent 74%);box-shadow:0 0 32px rgba(122,255,183,.16)}
  [data-renderer-theme='pokemon-route'] .combatant-far .platform .pedestal-surface{background:radial-gradient(ellipse at 50% 50%,#e2d9b6 0%,#d2c59a 65%,#b8ab7f 90%,transparent 100%);border:none;box-shadow:0 10px 24px rgba(40,45,30,.35)}
  [data-renderer-theme='pokemon-route'] .combatant-near .platform .pedestal-surface{background:radial-gradient(ellipse at 50% 50%,rgba(200,190,150,.45) 0%,rgba(160,150,110,.2) 60%,transparent 80%);border:none;box-shadow:0 8px 20px rgba(40,45,30,.25)}
  .contact-shadow{position:absolute;bottom:0;left:50%;z-index:1;width:50%;height:15%;transform:translate(-50%,30%);border-radius:50%;background:radial-gradient(ellipse,rgba(0,0,0,.7),transparent 70%);filter:blur(3px)}
  .sprite-slot{position:relative;display:flex;align-items:flex-end;justify-content:center;width:100%;height:min(32cqh,calc(var(--sprite-native) * var(--max-upscale) * var(--depth,1)))}
  .combatant-far .sprite-slot{--depth:.78}
  .combatant-near .sprite-slot{--depth:1.15}
  .sprite{position:relative;z-index:2;display:flex;align-items:flex-end;justify-content:center;width:100%;height:100%;transform-origin:center bottom}
  .switch-sprite{position:absolute;inset:0}
  .switch-outgoing{animation:switch-sequence-out .18s ease-in both}
  .switch-incoming{opacity:0;animation:switch-sequence-in .3s .16s cubic-bezier(.2,.8,.2,1) both}
  .sprite img{display:block;width:auto;max-width:100%;height:min(100%,calc(var(--natural-h,96) * var(--max-upscale) * var(--depth,1) * 1px));object-fit:contain;image-rendering:pixelated;filter:drop-shadow(0 8px 14px rgba(0,0,0,.45))}
  .sprite-missing{display:grid;place-items:center;gap:.25rem;color:var(--r-dim);font:800 .55rem var(--mono);letter-spacing:.12em}
  .sprite-missing .pokeball{width:clamp(28px,4cqw,52px)}
  .sprite-missing small{font:inherit}
  .hp-delta{position:absolute;top:4%;left:50%;z-index:4;transform:translateX(-50%);color:#ff9089;font:900 calc(var(--hud-scale,1) * clamp(1rem,2.3cqw,2.1rem)) var(--mono);text-shadow:0 2px 10px #000,0 0 22px rgba(0,0,0,.7);animation:value-pop .6s both}
  .hp-delta.positive{color:#8ef3a9}

  /* ── Effects ────────────────────────────────────────────────────────────── */
  .effect{position:absolute;z-index:9;inset:0;display:grid;place-items:center;pointer-events:none}
  .effect span{padding:.4rem 1.1rem;border-radius:4px;background:#f7fff9;color:#05100b;font:900 calc(var(--hud-scale,1) * clamp(.7rem,1.3cqw,1.35rem)) var(--mono);letter-spacing:.08em;animation:effect-pop .6s both}
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
  .move-projectile{position:absolute;top:var(--origin-y);left:var(--origin-x);width:clamp(16px,2.6cqw,38px);aspect-ratio:1;border:2px solid color-mix(in srgb,var(--type-color) 80%,white);border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff,var(--type-color) 28%,transparent 70%);box-shadow:0 0 18px var(--type-color);animation:projectile-flight .5s cubic-bezier(.22,.7,.2,1) both}
  .move-beam{position:absolute;top:var(--origin-y);left:var(--origin-x);width:52%;height:6px;transform-origin:left center;transform:rotate(var(--beam-angle)) scaleX(0);border-radius:999px;background:linear-gradient(90deg,#fff,var(--type-color),transparent);box-shadow:0 0 14px var(--type-color);opacity:0;animation:beam-fire .46s ease-out both}
  .charge-ring{position:absolute;top:var(--origin-y);left:var(--origin-x);width:70px;aspect-ratio:1;transform:translate(-50%,-50%);border:2px solid var(--type-color);border-radius:50%;opacity:0;animation:charge-ring .5s ease-out both}
  .move-visual[data-archetype='physical'] .move-projectile,.move-visual[data-archetype='physical'] .move-beam{display:none}
  .physical-swipe{position:absolute;top:50%;left:50%;width:22%;height:18%;transform:translate(-50%,-50%) rotate(-18deg);opacity:0;filter:drop-shadow(0 0 10px var(--type-color));animation:physical-swipe .48s cubic-bezier(.2,.8,.2,1) both}
  .physical-swipe i{position:absolute;left:0;width:100%;height:9%;border-radius:999px;background:linear-gradient(90deg,transparent,#fff,var(--type-color),transparent);transform:rotate(calc((var(--slash-index) - 1) * 24deg));}
  .physical-swipe i:nth-child(1){--slash-index:0;top:12%}.physical-swipe i:nth-child(2){--slash-index:1;top:43%}.physical-swipe i:nth-child(3){--slash-index:2;top:74%}
  .move-visual[data-archetype='special'] .physical-swipe,.move-visual[data-archetype='status'] .physical-swipe{display:none}
  .move-visual[data-archetype='status'] .move-projectile,.move-visual[data-archetype='status'] .move-beam{display:none}
  .move-visual[data-archetype='status'] .charge-ring{top:50%;left:50%;width:30%;animation:status-aura .5s ease-out both}
  .move-visual[data-move-type='electric'] .move-beam,.move-visual[data-move-type='psychic'] .move-beam,.move-visual[data-move-type='dragon'] .move-beam,.move-visual[data-move-type='ice'] .move-beam{opacity:1}
  .move-visual[data-quality='low'] .charge-ring{display:none}
  .recipe-layer,.move-texture{position:absolute;z-index:2;top:var(--origin-y);left:var(--origin-x);width:clamp(20px,3.4cqw,52px);aspect-ratio:1;transform:translate(-50%,-50%);pointer-events:none}
  .move-texture{z-index:3;object-fit:contain;filter:drop-shadow(0 0 12px var(--type-color));animation:recipe-projectile var(--move-duration) cubic-bezier(.2,.7,.2,1) both}
  .recipe-layer{border:2px solid var(--type-highlight);border-radius:50%;background:radial-gradient(circle at 36% 30%,#fff,var(--type-color) 30%,transparent 72%);box-shadow:0 0 22px var(--type-color);animation:recipe-projectile var(--move-duration) cubic-bezier(.2,.7,.2,1) both}
  .recipe-layer-b{animation-delay:-80ms;opacity:.55}.recipe-layer-c{animation-delay:-145ms;opacity:.3}
  .move-visual[data-recipe='contact'] .recipe-layer,.move-visual[data-recipe='barrier'] .recipe-layer,.move-visual[data-recipe='dance'] .recipe-layer,.move-visual[data-recipe='heal'] .recipe-layer,.move-visual[data-recipe='status'] .recipe-layer{top:var(--target-y);left:var(--target-x);background:transparent;animation:recipe-ring var(--move-duration) ease-out both}
  .move-visual[data-recipe='contact'] .move-projectile,.move-visual[data-recipe='contact'] .move-beam{display:none}
  .move-visual[data-recipe='beam'] .recipe-layer,.move-visual[data-recipe='lightning'] .recipe-layer{width:48%;height:clamp(5px,.7cqw,12px);aspect-ratio:auto;border:0;border-radius:999px;transform-origin:left center;background:linear-gradient(90deg,#fff,var(--type-color),transparent);animation:recipe-beam var(--move-duration) ease-out both}
  .move-visual[data-recipe='lightning'] .recipe-layer{height:clamp(8px,1cqw,16px);clip-path:polygon(0 35%,35% 0,30% 40%,62% 8%,55% 52%,100% 30%,64% 100%,70% 55%,35% 88%,40% 50%);border-radius:0}
  .move-visual[data-recipe='quake'] .recipe-layer,.move-visual[data-recipe='rock'] .recipe-layer{top:74%;left:50%;width:18%;height:7%;aspect-ratio:auto;background:transparent;border:clamp(2px,.35cqw,6px) solid var(--type-color);animation:recipe-quake var(--move-duration) ease-out both}
  .move-visual[data-recipe='ice'] .recipe-layer{border-radius:5% 55% 5% 55%;clip-path:polygon(50% 0,100% 42%,62% 100%,0 65%);background:linear-gradient(135deg,#fff,var(--type-color) 48%,transparent);animation:recipe-projectile var(--move-duration) ease-in both}
  .move-visual[data-recipe='water'] .recipe-layer,.move-visual[data-recipe='wind'] .recipe-layer{width:18%;height:7%;aspect-ratio:auto;background:transparent;border-width:clamp(3px,.55cqw,9px);border-left-color:transparent;border-right-color:transparent;animation:recipe-wave var(--move-duration) ease-out both}
  .move-visual[data-recipe='explosion'] .recipe-layer{top:var(--target-y);left:var(--target-x);clip-path:polygon(50% 0,61% 35%,90% 18%,72% 45%,100% 54%,66% 61%,82% 94%,56% 70%,38% 100%,39% 67%,4% 82%,30% 56%,0 39%,36% 40%);border:0;border-radius:0;animation:recipe-explosion var(--move-duration) ease-out both}
  .move-visual[data-recipe='poison'] .recipe-layer{border-radius:58% 42% 64% 36%;filter:saturate(1.35)}
  .move-visual[data-recipe='leaf'] .recipe-layer{border-radius:100% 0 100% 0;transform:rotate(35deg)}
  .move-visual[data-skin='retro'] .recipe-layer,.move-visual[data-skin='retro'] .move-texture{image-rendering:pixelated;filter:none;box-shadow:0 0 0 3px #111,0 0 0 5px var(--type-highlight)}
  .move-visual[data-quality='low'] .recipe-layer-b,.move-visual[data-quality='low'] .recipe-layer-c,.move-visual[data-quality='low'] .move-texture{display:none}
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

  .final-signal{position:absolute;z-index:21;top:8%;left:50%;display:grid;gap:.2rem;min-width:min(70%,520px);padding:.7rem 1.2rem;transform:translateX(-50%);border:1px solid color-mix(in srgb,#ffd262 72%,transparent);border-radius:8px;background:linear-gradient(90deg,rgba(65,28,8,.92),rgba(18,13,8,.96),rgba(65,28,8,.92));box-shadow:0 8px 30px rgba(0,0,0,.6),0 0 30px rgba(255,210,98,.18);text-align:center;animation:final-signal-in .55s both}
  .final-signal small{color:#ffd262;font:900 calc(var(--hud-scale,1) * clamp(.55rem,.76cqw,.78rem)) var(--mono);letter-spacing:.24em}
  .final-signal strong{color:#fff4c9;font:900 calc(var(--hud-scale,1) * clamp(1.15rem,2.5cqw,2.4rem)) var(--display);letter-spacing:.06em;text-shadow:0 0 16px rgba(255,210,98,.4)}
  .final-signal span{color:#e4c990;font:600 calc(var(--hud-scale,1) * clamp(.56rem,.72cqw,.72rem)) var(--mono)}

  /* ── Motion ─────────────────────────────────────────────────────────────── */
  .sprite.attacking{animation:attack-far .38s cubic-bezier(.2,.8,.2,1)}
  .combatant-near .sprite.attacking{animation-name:attack-near}
  .sprite.taking-damage{animation:hit .3s}
  .sprite.switching-in{animation:switch-in .46s}
  .sprite.switching-out{animation:switch-out .18s}
  .sprite.fainting{animation:faint .58s both}
  .sprite.status-flash{animation:status-flash .45s}
  .sprite.idle{animation:idle 3.6s ease-in-out infinite}
  .combatant.speaking .sprite.idle{animation:voice-idle 1.8s ease-in-out infinite}
  .combatant.speaking .contact-shadow{animation:voice-shadow 1.8s ease-in-out infinite}
  .arena-shake{animation:arena-shake .44s cubic-bezier(.2,.8,.2,1) both}
  @keyframes idle{50%{transform:translateY(-2%) scale(1.012)}}
  @keyframes voice-idle{25%{transform:translateY(-2.8%) rotate(-.6deg) scale(1.018)}75%{transform:translateY(-1.2%) rotate(.6deg) scale(1.008)}}
  @keyframes voice-shadow{50%{opacity:.72;transform:translate(-50%,30%) scaleX(.93)}}
  @keyframes attack-far{45%{transform:translate(-14%,9%) scale(1.07)}}
  @keyframes attack-near{45%{transform:translate(14%,-9%) scale(1.07)}}
  @keyframes hit{20%,60%{transform:translateX(-8%);filter:brightness(1.9) saturate(.5)}40%,80%{transform:translateX(8%)}}
  @keyframes switch-in{from{opacity:0;transform:translateY(-18%) scale(.7)}55%{opacity:1;transform:translateY(2%) scale(1.05)}}
  @keyframes switch-out{to{opacity:0;transform:translateY(18%) scale(.7)}}
  @keyframes switch-sequence-out{to{opacity:0;transform:translateY(10%) scale(.8);filter:brightness(.7)}}
  @keyframes switch-sequence-in{from{opacity:0;transform:translateY(-10%) scale(.78)}65%{opacity:1;transform:translateY(2%) scale(1.04)}to{opacity:1;transform:none}}
  @keyframes hp-plate-switch{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
  @keyframes faint{to{opacity:0;transform:translateY(30%) scale(.75);filter:grayscale(1) brightness(.6)}}
  @keyframes status-flash{50%{filter:drop-shadow(0 0 22px #ffd05d) brightness(1.4)}}
  @keyframes effect-pop{from{opacity:0;transform:scale(.72)}32%{opacity:1;transform:scale(1.06)}to{opacity:0;transform:scale(1.16)}}
  @keyframes value-pop{from{opacity:0;transform:translate(-50%,14px) scale(.8)}22%{opacity:1;transform:translate(-50%,-4px) scale(1.12)}to{opacity:.95;transform:translate(-50%,-10px) scale(1)}}
  @keyframes arena-shake{0%,100%{transform:translate(0)}25%{transform:translate(-.5%,.28%)}50%{transform:translate(.42%,-.22%)}75%{transform:translate(-.2%,.13%)}}
  @keyframes projectile-flight{0%{transform:translate(-50%,-50%) scale(.45);opacity:0}18%{opacity:1}82%{opacity:1}100%{top:var(--target-y);left:var(--target-x);transform:translate(-50%,-50%) scale(1.3);opacity:0}}
  @keyframes beam-fire{0%,18%{transform:rotate(var(--beam-angle)) scaleX(0);opacity:0}38%,65%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:.9}100%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:0}}
  @keyframes charge-ring{0%{transform:translate(-50%,-50%) scale(1.5);opacity:0}30%{opacity:.8}70%{transform:translate(-50%,-50%) scale(.35);opacity:.8}100%{opacity:0}}
  @keyframes status-aura{from{transform:translate(-50%,-50%) scale(.25);opacity:.8}to{transform:translate(-50%,-50%) scale(1.5);opacity:0}}
  @keyframes particle-burst{from{transform:translate(0) scale(1);opacity:1}to{transform:translate(var(--particle-x),var(--particle-y)) rotate(150deg) scale(.15);opacity:0}}
  @keyframes physical-swipe{0%{opacity:0;transform:translate(-50%,-50%) scale(.35) rotate(-18deg)}28%{opacity:1}70%{opacity:.95;transform:translate(-50%,-50%) scale(1.3) rotate(8deg)}100%{opacity:0;transform:translate(-50%,-50%) scale(1.65) rotate(18deg)}}
  @keyframes recipe-projectile{0%{transform:translate(-50%,-50%) scale(.25);opacity:0}18%{opacity:1}82%{opacity:1}100%{top:var(--target-y);left:var(--target-x);transform:translate(-50%,-50%) scale(1.45) rotate(220deg);opacity:0}}
  @keyframes recipe-ring{0%{transform:translate(-50%,-50%) scale(.15);opacity:0}25%{opacity:.9}100%{transform:translate(-50%,-50%) scale(3.5);opacity:0}}
  @keyframes recipe-beam{0%,18%{transform:rotate(var(--beam-angle)) scaleX(0);opacity:0}36%,72%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:1}100%{transform:rotate(var(--beam-angle)) scaleX(1);opacity:0}}
  @keyframes recipe-quake{0%{transform:translate(-50%,-50%) scale(.1);opacity:0}22%{opacity:.9}100%{transform:translate(-50%,-50%) scale(6,2.8);opacity:0}}
  @keyframes recipe-wave{0%{transform:translate(-50%,-50%) scale(.2);opacity:0}25%{opacity:1}100%{top:var(--target-y);left:var(--target-x);transform:translate(-50%,-50%) scale(2.2,1.2) rotate(var(--beam-angle));opacity:0}}
  @keyframes recipe-explosion{0%{transform:translate(-50%,-50%) scale(.1);opacity:0}35%{opacity:1}75%{transform:translate(-50%,-50%) scale(4);opacity:.85}100%{transform:translate(-50%,-50%) scale(5.5);opacity:0}}
  @keyframes final-signal-in{from{opacity:0;transform:translateX(-50%) translateY(-14px) scale(.96)}to{opacity:1;transform:translateX(-50%) translateY(0) scale(1)}}
  @keyframes weather-drift{to{background-position:70px 20px}}
  @keyframes weather-fall{to{background-position:18px 36px}}
  .battle-renderer.deterministic .sprite,.battle-renderer.deterministic .effect span,.battle-renderer.deterministic .impact-burst i,.battle-renderer.deterministic .move-projectile,.battle-renderer.deterministic .move-beam,.battle-renderer.deterministic .charge-ring,.battle-renderer.deterministic .arena-shake,.battle-renderer.deterministic .weather-layer,.battle-renderer.deterministic .hp-delta{animation:none!important}
  .battle-renderer.deterministic .hp-track i,.battle-renderer.deterministic .hp-track b{transition:none!important}
  .battle-renderer.reduced-motion .sprite,.battle-renderer.reduced-motion .move-visual,.battle-renderer.reduced-motion .impact-burst,.battle-renderer.reduced-motion .arena-shake{animation:none!important;transform:none!important}
  .battle-renderer.reduced-motion .switch-outgoing{display:none}.battle-renderer.reduced-motion .switch-incoming{opacity:1!important}
  .battle-renderer.reduced-motion .hp-plate.switching{animation:none;opacity:1!important}
  @media(prefers-reduced-motion:reduce){.sprite,.effect span,.hp-plate.switching{animation-duration:.001ms!important;animation-delay:0ms!important;animation-iteration-count:1!important}.switch-outgoing{display:none}.switch-incoming{opacity:1!important}.hp-track i{transition-duration:.001ms!important}}

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
  }

  .renderer-loading{display:grid;place-content:center;min-height:420px;padding:2rem;text-align:center}
  .renderer-loading h2{margin:.5rem 0}
  .renderer-loading p{color:var(--muted)}
</style>
