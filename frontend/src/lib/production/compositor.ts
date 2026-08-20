import type { PokemonType } from '../presentation/types.ts';
import { moveEffectAssetUrl, resolveMoveEffect, type MoveEffectFamily } from '../move-effects.ts';
import type { PokemonState, ProductionStyle } from '../types.ts';
import { damageCallout, directorCard, isKnockedOut } from './scene.ts';
import type { ProductionScene, ProductionSceneSide } from './scene.ts';
import { commentaryMotion, hpReadout, hudLayout, mix, withAlpha } from './layout.ts';
import {
  assetUrl,
  cameraScale,
  ensureStyleFonts,
  fontFamily,
  idleScale,
  intensityScale
} from './style.ts';

const TYPE_COLORS: Record<PokemonType, string> = {
  normal: '#d9d7ca', fire: '#ff633f', water: '#3cc8ff', electric: '#ffe148', grass: '#79f05d',
  ice: '#82f4f1', fighting: '#ff714f', poison: '#de64e8', ground: '#e3a44d', flying: '#8ec7ff',
  psychic: '#ff5bac', bug: '#b9e744', rock: '#cfb56f', ghost: '#a17cff', dragon: '#766dff',
  dark: '#8a7772', steel: '#b5cbd6', fairy: '#ff96d2'
};

const TONE_COLORS: Record<string, string> = {
  damage: '#ff6a5c', heal: '#7bf0a2', crit: '#ffd451', effective: '#ffb44c',
  resist: '#9fb4c2', immune: '#c8cfd4', miss: '#dfe6ea'
};

export interface CompositorMetrics { assetLoads: number; assetFailures: number; cachedAssets: number }
interface Point { x: number; y: number }

/** Everything derived once per frame so draw calls stay cheap and consistent. */
interface Resolved {
  style: ProductionStyle;
  display: string;
  body: string;
  mono: string;
  scale: number;
  upper: boolean;
  outline: boolean;
  shadow: boolean;
  tracking: number;
  weight: number;
  effect: number;
  camera: number;
  idle: number;
  accent: string;
}

export class ProductionCompositor {
  private context: CanvasRenderingContext2D;
  private images = new Map<string, Promise<ImageBitmap | null>>();
  private resolvedImages = new Map<string, ImageBitmap | null>();
  private assetLoads = 0;
  private assetFailures = 0;
  private fontsReady: Promise<string[]> | null = null;
  /** Asset ids whose file is gone. Rendered as the documented fallback, never substituted. */
  private missingAssets = new Set<string>();
  /**
   * The stage does not change between frames, but redrawing its gradients, ridges and
   * perspective grid dominated per-frame cost. Painting it once per distinct look lets
   * every frame be re-rendered cheaply, which is what allows the Pokemon to keep breathing
   * instead of being frozen by the frame-hold optimisation. Custom background images are
   * decoded once and composited into the same cache rather than per frame.
   */
  private worldCache: HTMLCanvasElement | OffscreenCanvas | null = null;
  private worldKey = '';

  constructor(private canvas: HTMLCanvasElement, private assetApiBase = '') {
    const context = canvas.getContext('2d', { alpha: false, desynchronized: true });
    if (!context) throw new Error('Canvas 2D compositor is unavailable');
    this.context = context;
  }

  /** Decode every asset this scene needs. Safe to call repeatedly; results are cached. */
  async preload(scene: ProductionScene): Promise<void> {
    const style = scene.style;
    if (!this.fontsReady) this.fontsReady = ensureStyleFonts(style, this.assetApiBase);
    const missingFonts = await this.fontsReady;
    for (const id of missingFonts) this.missingAssets.add(id);
    const background = style.stage.background.kind === 'image' ? style.stage.background.asset_id : null;
    const moveRecipe = scene.effect.moveName
      ? resolveMoveEffect(
          scene.effect.moveName,
          scene.effect.type,
          scene.effect.category,
          scene.style.hud.preset === 'retro' ? 'retro' : 'broadcast'
        )
      : null;
    await Promise.all(
      [
        scene.p1.spriteUrl,
        scene.p2.spriteUrl,
        ...scene.p1.team.map((member) => this.teamSpriteUrl(member)),
        ...scene.p2.team.map((member) => this.teamSpriteUrl(member)),
        scene.p1.logoUrl,
        scene.p2.logoUrl,
        assetUrl(this.assetApiBase, background),
        style.watermark.enabled ? assetUrl(this.assetApiBase, style.watermark.asset_id) : null,
        moveRecipe?.assetId ? moveEffectAssetUrl(moveRecipe.assetId, this.assetApiBase) : null
      ].map((url) => this.load(url))
    );
    for (const [id, url] of [
      [background, assetUrl(this.assetApiBase, background)],
      [style.players.p1?.logo_asset_id, scene.p1.logoUrl],
      [style.players.p2?.logo_asset_id, scene.p2.logoUrl],
      [style.watermark.asset_id, assetUrl(this.assetApiBase, style.watermark.asset_id)]
    ] as [string | null | undefined, string | null][]) {
      if (id && url && this.resolvedImages.get(url) === null) this.missingAssets.add(id);
    }
  }

  async render(scene: ProductionScene): Promise<void> {
    await this.preload(scene);
    const resolved = resolve(scene);
    const { width, height } = this.canvas;
    const scale = Math.min(width / (scene.vertical ? 1080 : 1920), height / (scene.vertical ? 1920 : 1080));
    const camera = cameraOffset(scene, scale, resolved.camera);
    this.context.save();
    this.context.translate(camera.x, camera.y);
    this.paintWorld(scene, resolved, width, height, scale);
    this.drawCombatants(scene, resolved, width, height, scale);
    this.drawEffect(scene, resolved, width, height, scale);
    this.context.restore();
    this.drawHud(scene, resolved, width, height, scale);
    this.drawMoveCallout(scene, resolved, width, height, scale);
    this.drawDamageCallout(scene, resolved, width, height, scale);
    this.drawCommentary(scene, resolved, width, height, scale);
    this.drawCaption(scene, resolved, width, height, scale);
    this.drawDirector(scene, resolved, width, height, scale);
    this.drawWatermark(scene, resolved, width, height, scale);
    this.drawFrame(resolved, width, height, scale);
  }

  metrics(): CompositorMetrics {
    return { assetLoads: this.assetLoads, assetFailures: this.assetFailures, cachedAssets: this.images.size };
  }

  /** Assets a production references that are no longer on disk. */
  missing(): string[] { return [...this.missingAssets]; }

  private async load(url: string | null): Promise<ImageBitmap | null> {
    if (!url) return null;
    let pending = this.images.get(url);
    if (!pending) {
      this.assetLoads += 1;
      pending = fetch(url, { credentials: 'omit', cache: 'force-cache' })
        .then((response) => { if (!response.ok) throw new Error(`asset ${response.status}`); return response.blob(); })
        .then((blob) => createImageBitmap(blob))
        .catch(() => { this.assetFailures += 1; return null; })
        .then((image) => { this.resolvedImages.set(url, image); return image; });
      this.images.set(url, pending);
    }
    return pending;
  }

  private bitmap(url: string | null): ImageBitmap | null {
    return url ? this.resolvedImages.get(url) || null : null;
  }

  // ------------------------------------------------------------------ stage

  private paintWorld(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const stage = scene.style.stage;
    // Weather is time-varying, so it stays outside the cache and is drawn per frame.
    const key = [
      width, height, scene.vertical, scene.effect.seed, scene.fields.join(),
      stage.background.kind, stage.background.color, stage.background.secondary_color,
      stage.background.asset_id, stage.background.fit, stage.background.position,
      stage.background.brightness, stage.background.contrast, stage.background.blur,
      stage.background.overlay_opacity, stage.background.vignette, stage.arena,
      stage.floor_visible, stage.stage_lighting, stage.ambient_intensity, stage.accent
    ].join('|');
    if (!this.worldCache || this.worldKey !== key) {
      const surface =
        typeof OffscreenCanvas === 'function'
          ? new OffscreenCanvas(width, height)
          : Object.assign(document.createElement('canvas'), { width, height });
      const surfaceContext = surface.getContext('2d') as CanvasRenderingContext2D | null;
      if (!surfaceContext) {
        this.drawWorld(this.context, scene, resolved, width, height, scale);
        return;
      }
      this.drawWorld(surfaceContext, scene, resolved, width, height, scale);
      this.worldCache = surface;
      this.worldKey = key;
    }
    this.context.drawImage(this.worldCache as CanvasImageSource, 0, 0);
    if (scene.style.stage.background_motion) this.drawAtmosphere(scene, width, height, scale);
  }

  private drawWorld(
    context: CanvasRenderingContext2D,
    scene: ProductionScene,
    resolved: Resolved,
    width: number,
    height: number,
    scale: number
  ) {
    const stage = scene.style.stage;
    const background = stage.background;
    context.fillStyle = background.color;
    context.fillRect(0, 0, width, height);
    if (background.kind === 'image') {
      this.drawBackgroundImage(context, scene, width, height);
    } else if (background.kind === 'gradient' || background.kind === 'arena') {
      const sky = context.createLinearGradient(0, 0, width, height);
      sky.addColorStop(0, background.color);
      sky.addColorStop(.62, mix(background.color, background.secondary_color, .55));
      sky.addColorStop(1, background.secondary_color);
      context.fillStyle = sky;
      context.fillRect(-40, -40, width + 80, height + 80);
    }
    if (background.kind === 'arena') this.drawArenaSky(context, scene, resolved, width, height, scale);
    if (stage.stage_lighting > 0) {
      const sunX = scene.vertical ? width * .72 : width * .58;
      const glow = context.createRadialGradient(sunX, height * .22, 0, sunX, height * .22, width * .42);
      glow.addColorStop(0, withAlpha(stage.accent, .3 * stage.stage_lighting));
      glow.addColorStop(.4, withAlpha(stage.accent, .1 * stage.stage_lighting));
      glow.addColorStop(1, 'rgba(0,0,0,0)');
      context.fillStyle = glow;
      context.fillRect(0, 0, width, height);
    }
    if (background.overlay_opacity > 0) {
      context.fillStyle = withAlpha(background.secondary_color, background.overlay_opacity);
      context.fillRect(0, 0, width, height);
    }
    this.drawArena(context, scene, resolved, width, height, scale);
    if (background.vignette > 0) {
      const vignette = context.createRadialGradient(
        width / 2, height / 2, Math.min(width, height) * .3,
        width / 2, height / 2, Math.max(width, height) * .78
      );
      vignette.addColorStop(0, 'rgba(0,0,0,0)');
      vignette.addColorStop(1, `rgba(0,0,0,${background.vignette})`);
      context.fillStyle = vignette;
      context.fillRect(0, 0, width, height);
    }
  }

  private drawBackgroundImage(
    context: CanvasRenderingContext2D,
    scene: ProductionScene,
    width: number,
    height: number
  ) {
    const background = scene.style.stage.background;
    const bitmap = this.bitmap(assetUrl(this.assetApiBase, background.asset_id));
    // A missing background degrades to the style's solid colour, which is already painted.
    if (!bitmap) return;
    const ratio = bitmap.width / bitmap.height;
    const cover = background.fit === 'cover';
    let drawWidth = width;
    let drawHeight = width / ratio;
    if (cover ? drawHeight < height : drawHeight > height) {
      drawHeight = height;
      drawWidth = height * ratio;
    }
    const offsetX = background.position === 'left' ? 0 : background.position === 'right' ? width - drawWidth : (width - drawWidth) / 2;
    const offsetY = background.position === 'top' ? 0 : background.position === 'bottom' ? height - drawHeight : (height - drawHeight) / 2;
    context.save();
    const filters: string[] = [];
    if (background.brightness !== 1) filters.push(`brightness(${background.brightness})`);
    if (background.contrast !== 1) filters.push(`contrast(${background.contrast})`);
    if (background.blur > 0) filters.push(`blur(${background.blur}px)`);
    if (filters.length) context.filter = filters.join(' ');
    context.drawImage(bitmap, offsetX, offsetY, drawWidth, drawHeight);
    context.restore();
  }

  private drawArenaSky(
    context: CanvasRenderingContext2D,
    scene: ProductionScene,
    resolved: Resolved,
    width: number,
    height: number,
    scale: number
  ) {
    const accent = scene.style.stage.accent;
    context.fillStyle = withAlpha(scene.style.stage.background.secondary_color, .85);
    context.beginPath(); context.moveTo(0, height * .18); context.lineTo(width * .12, height * .32); context.lineTo(width * .21, height * .24); context.lineTo(width * .32, height * .43); context.lineTo(width * .39, height * .35); context.lineTo(width * .48, height * .51); context.lineTo(0, height * .57); context.closePath(); context.fill();
    context.beginPath(); context.moveTo(width, height * .12); context.lineTo(width * .87, height * .27); context.lineTo(width * .8, height * .21); context.lineTo(width * .7, height * .42); context.lineTo(width * .61, height * .35); context.lineTo(width * .55, height * .53); context.lineTo(width, height * .58); context.closePath(); context.fill();
    context.strokeStyle = withAlpha(accent, .2 * resolved.style.stage.ambient_intensity);
    context.lineWidth = Math.max(1, 2 * scale);
    for (let index = 0; index < 12; index += 1) {
      const x = hash(scene.effect.seed + index * 47) * width;
      const y = hash(scene.effect.seed + index * 83) * height * .48;
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + 18 * scale, y - 55 * scale); context.stroke();
    }
  }

  private drawArena(
    context: CanvasRenderingContext2D,
    scene: ProductionScene,
    resolved: Resolved,
    width: number,
    height: number,
    scale: number
  ) {
    const stage = scene.style.stage;
    if (stage.arena === 'none' || !stage.floor_visible) return;
    const accent = stage.accent;
    const horizon = height * (scene.vertical ? .48 : .52);
    const floor = context.createLinearGradient(0, horizon, 0, height);
    // An opaque floor hid the lower half of an uploaded background entirely, and a flat
    // tint left a hard seam at the horizon. Over a custom image the floor fades in from
    // nothing, so the picture stays visible and the Pokemon still read as grounded.
    const custom = stage.background.kind === 'image';
    if (custom) {
      floor.addColorStop(0, withAlpha(stage.background.color, 0));
      floor.addColorStop(.35, withAlpha(stage.background.color, .3));
      floor.addColorStop(1, withAlpha(stage.background.secondary_color, .62));
    } else {
      floor.addColorStop(0, mix(stage.background.color, '#ffffff', .06));
      floor.addColorStop(1, stage.background.secondary_color);
    }
    context.save();
    context.fillStyle = floor;
    context.beginPath(); context.moveTo(0, horizon); context.lineTo(width, horizon); context.lineTo(width, height); context.lineTo(0, height); context.closePath(); context.fill();
    context.restore();
    const ambient = stage.ambient_intensity;
    if (stage.arena === 'grid') {
      context.strokeStyle = withAlpha(accent, .16 * ambient); context.lineWidth = Math.max(1, 2 * scale);
      for (let index = -10; index <= 10; index += 1) { context.beginPath(); context.moveTo(width / 2, horizon); context.lineTo(width / 2 + index * width * .12, height); context.stroke(); }
      for (let row = 1; row < 10; row += 1) { const y = horizon + (height - horizon) * Math.pow(row / 9, 1.65); context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke(); }
    } else if (stage.arena === 'stadium') {
      // Tiered seating above the horizon plus a lit oval floor: reads as a venue rather
      // than an abstract plane, without copying any real stadium or game artwork.
      for (let tier = 0; tier < 5; tier += 1) {
        const y = horizon - (tier + 1) * height * .045;
        context.fillStyle = withAlpha(mix(stage.background.secondary_color, accent, .1 + tier * .04), .9);
        context.fillRect(0, y, width, height * .04);
        context.fillStyle = withAlpha(accent, .09 * ambient);
        for (let seat = 0; seat < 46; seat += 1) {
          const x = (seat + (tier % 2) * .5) * (width / 46);
          context.fillRect(x, y + height * .008, width / 90, height * .022);
        }
      }
      context.fillStyle = withAlpha(accent, .1 * ambient);
      context.beginPath(); context.ellipse(width / 2, height * .78, width * .46, height * .2, 0, 0, Math.PI * 2); context.fill();
      context.strokeStyle = withAlpha(accent, .4 * ambient); context.lineWidth = Math.max(2, 5 * scale);
      context.beginPath(); context.ellipse(width / 2, height * .78, width * .46, height * .2, 0, 0, Math.PI * 2); context.stroke();
      context.beginPath(); context.ellipse(width / 2, height * .78, width * .3, height * .13, 0, 0, Math.PI * 2); context.stroke();
    } else if (stage.arena === 'platform') {
      context.fillStyle = withAlpha(accent, .12 * ambient);
      for (const position of Object.values(combatantPositions(scene, width, height))) {
        context.beginPath(); context.ellipse(position.x, position.y, width * .17, height * .045, 0, 0, Math.PI * 2); context.fill();
      }
      context.strokeStyle = withAlpha(accent, .3 * ambient); context.lineWidth = Math.max(1, 3 * scale);
      for (const position of Object.values(combatantPositions(scene, width, height))) {
        context.beginPath(); context.ellipse(position.x, position.y, width * .17, height * .045, 0, 0, Math.PI * 2); context.stroke();
      }
    } else if (stage.arena === 'minimal-floor') {
      context.strokeStyle = withAlpha(accent, .22 * ambient); context.lineWidth = Math.max(1, 2 * scale);
      context.beginPath(); context.moveTo(0, horizon); context.lineTo(width, horizon); context.stroke();
    }
    if (stage.arena !== 'minimal-floor') {
      context.fillStyle = withAlpha(accent, .035 * ambient);
      context.beginPath(); context.ellipse(width / 2, height * .73, width * .44, height * .19, 0, 0, Math.PI * 2); context.fill();
    }
    void resolved;
  }

  private drawAtmosphere(scene: ProductionScene, width: number, height: number, scale: number) {
    if (scene.weather.some((value) => value.toLowerCase().includes('rain'))) {
      this.context.strokeStyle = 'rgba(155,220,255,.28)'; this.context.lineWidth = Math.max(1, 2 * scale);
      for (let index = 0; index < 64; index += 1) { const x = ((hash(index * 61) * width + scene.timeMs * .24) % (width + 100)) - 50; const y = ((hash(index * 97) * height + scene.timeMs * .58) % height); this.context.beginPath(); this.context.moveTo(x, y); this.context.lineTo(x - 13 * scale, y + 31 * scale); this.context.stroke(); }
    }
    if (scene.weather.length || scene.fields.length) { this.context.fillStyle = scene.fields.length ? 'rgba(105,255,177,.065)' : 'rgba(112,190,255,.06)'; this.context.fillRect(0, 0, width, height); }
  }

  // ------------------------------------------------------------- combatants

  private drawCombatants(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const positions = combatantPositions(scene, width, height);
    const p1Size = (scene.vertical ? 455 : 475) * scale;
    const p2Size = (scene.vertical ? 425 : 445) * scale;
    if (scene.p2.active && scene.style.stage.ground_shadow) {
      this.drawPlatform(positions.p2.x, positions.p2.y, p2Size * .55, p2Size * .09, scene.p2.accent);
    }
    if (scene.p2.active) this.drawPokemon(scene, resolved, scene.p2, positions.p2.x, positions.p2.y, p2Size);
    if (scene.p1.active && scene.style.stage.ground_shadow) {
      this.drawPlatform(positions.p1.x, positions.p1.y, p1Size * .58, p1Size * .095, scene.p1.accent);
    }
    if (scene.p1.active) this.drawPokemon(scene, resolved, scene.p1, positions.p1.x, positions.p1.y, p1Size);
  }

  private drawPlatform(x: number, y: number, rx: number, ry: number, color: string) {
    const gradient = this.context.createRadialGradient(x, y, 0, x, y, rx);
    gradient.addColorStop(0, withAlpha(color, .34)); gradient.addColorStop(.48, withAlpha(color, .11)); gradient.addColorStop(1, 'rgba(0,0,0,0)');
    this.context.fillStyle = gradient; this.context.beginPath(); this.context.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); this.context.fill();
    this.context.strokeStyle = withAlpha(color, .34); this.context.lineWidth = Math.max(1, ry * .05); this.context.beginPath(); this.context.ellipse(x, y, rx * .73, ry * .47, 0, 0, Math.PI * 2); this.context.stroke();
  }

  private drawPokemon(scene: ProductionScene, resolved: Resolved, side: ProductionSceneSide, x: number, y: number, size: number) {
    const context = this.context;
    const attacking = scene.effect.actor === side.side ? anticipationLunge(scene.effect.progress) : 0;
    const impact = scene.effect.target === side.side ? impactEnvelope(scene.effect.impactProgress) : 0;
    const direction = side.near ? 1 : -1;
    const lunge = attacking * size * .24 * direction;
    const recoil = impact * size * .1 * direction * resolved.effect;
    const shake = impact * Math.sin(scene.effect.impactProgress * 72) * size * .025 * resolved.effect;
    const idle = Math.sin(scene.timeMs / 640 + (side.near ? 0 : 2.1)) * resolved.idle;
    // A fainted Pokemon stays down until it is replaced. Driving this only from the faint
    // cue made it spring back to a healthy standing pose the moment that cue ended.
    const fainting =
      scene.effect.kind === 'pokemon_fainted' && scene.effect.target === side.side
        ? easeInOut(scene.effect.progress)
        : 0;
    const down = isKnockedOut(side);
    const faint = down ? Math.max(fainting, 1) : fainting;
    const appear = scene.effect.kind === 'pokemon_switched' && scene.effect.actor === side.side ? easeOut(scene.effect.progress) : 1;
    const quake = isGroundMove(scene.effect.moveId) && scene.effect.attack
      ? Math.sin(scene.effect.progress * Math.PI * 7 + (side.near ? 0 : .8))
        * Math.sin(scene.effect.progress * Math.PI) * size * .045
      : 0;
    const bitmap = this.bitmap(side.spriteUrl);
    const breath = idle * size * .014;
    context.save(); context.translate(x + lunge + recoil + shake, y - size * .012 - breath + quake);
    // Squash on the inhale and stretch on the exhale so even a static PNG has weight.
    const squash = idle * .008;
    context.globalAlpha = (1 - faint) * appear; context.rotate((recoil / size) * .16 + faint * direction * .12); context.scale(.78 + appear * .22 + attacking * .06 + squash, .78 + appear * .22 - attacking * .025 - squash);
    context.shadowColor = impact ? '#fff4bd' : 'rgba(0,0,0,.75)'; context.shadowBlur = impact ? size * .15 : size * .055;
    if (resolved.effect > 0 && attacking > .18 && bitmap) { context.save(); context.globalAlpha = attacking * .16; context.translate(-direction * size * .11, 0); context.drawImage(bitmap, -size / 2, -size, size, size); context.restore(); }
    if (bitmap) context.drawImage(bitmap, -size / 2, -size, size, size); else this.drawMissingSprite(side, size);
    context.restore();
  }

  private drawMissingSprite(side: ProductionSceneSide, size: number) {
    // A missing asset is a compact Pokéball marker, never a giant egg silhouette. This also
    // keeps the battle readable when a user has not installed a local sprite pack yet.
    const radius = size * .1;
    const y = -size * .14;
    const context = this.context;
    context.save();
    context.globalAlpha = .82;
    context.fillStyle = withAlpha(side.accent, .16);
    context.beginPath(); context.ellipse(0, 0, size * .18, size * .045, 0, 0, Math.PI * 2); context.fill();
    context.fillStyle = '#e85d5d'; context.beginPath(); context.arc(0, y, radius, Math.PI, 0); context.fill();
    context.fillStyle = '#f1f4ed'; context.beginPath(); context.arc(0, y, radius, 0, Math.PI); context.fill();
    context.strokeStyle = '#1b2522'; context.lineWidth = Math.max(1, size * .012); context.beginPath(); context.arc(0, y, radius, 0, Math.PI * 2); context.stroke();
    context.fillStyle = '#f5faf5'; context.beginPath(); context.arc(0, y, radius * .24, 0, Math.PI * 2); context.fill();
    context.restore();
  }

  // -------------------------------------------------------------------- HUD

  private drawHud(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const hud = scene.style.hud;
    const boxes = hudLayout(hud.preset, scene.vertical, width, height, scale);
    if (hud.show_turn) this.drawHeader(scene, resolved, width, height, scale);
    this.drawHealth(scene, resolved, scene.p1, boxes.p1, false, scale);
    this.drawHealth(scene, resolved, scene.p2, boxes.p2, true, scale);
  }

  private drawHeader(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const context = this.context;
    const hud = scene.style.hud;
    const y = (scene.vertical ? 38 : 30) * scale;
    const parts: string[] = [];
    if (scene.turn) parts.push(`TURN ${scene.turn}`);
    if (scene.style.show_format) parts.push(scene.formatLabel.toUpperCase());
    if (hud.show_weather && scene.weather.length) parts.push(scene.weather[0].toUpperCase());
    if (!parts.length) return;
    const label = parts.join('   ·   ');
    context.save();
    context.textAlign = 'center';
    context.font = this.font(resolved, 'display', 23 * scale, resolved.weight);
    const boxWidth = Math.max(380 * scale, context.measureText(label).width + 90 * scale);
    const headerY = scene.style.hud.preset === 'fighting' || scene.style.hud.preset === 'esports' ? height - 78 * scale : y;
    context.fillStyle = 'rgba(4,7,11,.9)';
    this.shape(context, scene, width / 2 - boxWidth / 2, headerY, boxWidth, (scene.style.show_koala_branding ? 62 : 42) * scale, 18 * scale);
    context.fill();
    context.strokeStyle = withAlpha(resolved.accent, .58); context.lineWidth = 2 * scale; context.stroke();
    let textY = headerY + 28 * scale;
    if (scene.style.show_koala_branding) {
      context.fillStyle = resolved.accent;
      context.font = this.font(resolved, 'mono', 18 * scale, 900);
      context.fillText('KOALABATTLE', width / 2, headerY + 25 * scale);
      textY = headerY + 50 * scale;
    }
    context.fillStyle = '#f5f7f5';
    context.font = this.font(resolved, 'display', 23 * scale, resolved.weight);
    context.fillText(this.text(resolved, label), width / 2, textY);
    context.restore();
  }

  private drawHealth(
    scene: ProductionScene,
    resolved: Resolved,
    side: ProductionSceneSide,
    box: { x: number; y: number; width: number; height: number },
    alignRight: boolean,
    scale: number
  ) {
    const context = this.context;
    const hud = scene.style.hud;
    const { x, y, width, height } = box;
    const sideColor = side.accent;
    const typeColor = pokemonTypeColor(side.active?.types);
    const pad = 28 * scale;
    const compact = hud.preset === 'minimal';
    context.save();
    this.shape(context, scene, x, y, width, height, 30 * scale, alignRight);
    context.fillStyle = compact ? 'rgba(5,8,13,.72)' : 'rgba(5,8,13,.96)';
    context.fill();
    context.strokeStyle = compact ? withAlpha(sideColor, .5) : 'rgba(238,245,241,.72)';
    context.lineWidth = (compact ? 2 : 3) * scale;
    context.stroke();
    if (!compact) {
      context.fillStyle = typeColor;
      context.fillRect(alignRight ? x + width - 9 * scale : x, y + 8 * scale, 9 * scale, height - 16 * scale);
    }
    context.textAlign = alignRight ? 'right' : 'left';
    const anchor = alignRight ? x + width - pad : x + pad;
    let cursor = y + 24 * scale;
    if (hud.show_player_name) {
      const bits: string[] = [];
      if (hud.show_player_slot) bits.push(side.slot);
      bits.push(side.displayName.toUpperCase());
      if (hud.show_provider) bits.push(side.providerLabel.toUpperCase());
      context.fillStyle = withAlpha(sideColor, .95);
      context.font = this.font(resolved, 'mono', 13 * scale, 900);
      context.fillText(this.text(resolved, bits.join('  ·  ')), anchor, cursor, width - pad * 2 - (hud.show_logo ? 60 * scale : 0));
    }
    if (hud.show_logo) {
      this.drawLogo(side, alignRight ? x + pad : x + width - pad - 44 * scale, y + 8 * scale, 44 * scale, resolved);
    }
    cursor = y + (compact ? 56 : 66) * scale;
    const nameSize = (compact ? 28 : 39) * scale;
    context.fillStyle = '#fff';
    context.font = this.font(resolved, 'display', nameSize, resolved.weight);
    const name = side.active?.name || 'AWAITING POKÉMON';
    const level = hud.show_level && side.active?.level ? `  Lv${side.active.level}` : '';
    this.paintText(context, resolved, this.text(resolved, name) + level, anchor, cursor, width * .66);
    if (hud.show_types) {
      const types = side.active?.types.slice(0, 2) || [];
      types.forEach((type, index) =>
        this.drawTypeChip(resolved, type, alignRight ? x + pad + index * 88 * scale : x + width - pad - index * 88 * scale, y + 43 * scale, alignRight, scale)
      );
    }
    const hp = clamp(side.active?.hp_fraction ?? 0);
    const previous = clamp(side.previousHpFraction ?? hp);
    const barHeight = hud.hp_thickness * scale;
    const barY = y + (compact ? 68 : 91) * scale;
    const readout = hpReadout(side, hud);
    context.font = this.font(resolved, 'mono', 18 * scale, 950);
    const readoutWidth = readout ? context.measureText(readout).width + 22 * scale : 0;
    const labelWidth = compact ? 0 : 46 * scale;
    const barX = x + pad + labelWidth;
    const barWidth = width - pad * 2 - labelWidth - readoutWidth;
    if (!compact) {
      context.fillStyle = '#edf3ef'; context.textAlign = 'left';
      context.fillText('HP', x + pad, barY + barHeight * .72);
    }
    this.drawHpBar(scene, barX, barY, barWidth, barHeight, hp, previous, alignRight, scale);
    if (readout) {
      context.fillStyle = '#f8fbf9'; context.textAlign = 'right';
      context.font = this.font(resolved, 'mono', 18 * scale, 950);
      context.fillText(readout, x + width - pad, barY + barHeight * .72);
    }
    const status = hud.show_status ? side.active?.status?.toUpperCase() : null;
    if (status) {
      context.fillStyle = statusColor(status);
      roundedRect(context, x + pad, y + height - 50 * scale, 62 * scale, 25 * scale, 5 * scale);
      context.fill();
      context.fillStyle = '#111'; context.textAlign = 'center';
      context.font = this.font(resolved, 'mono', 13 * scale, 950);
      context.fillText(readableStatus(status), x + pad + 31 * scale, y + height - 32 * scale);
    }
    this.drawTeamDots(scene, side, x, y, width, height, alignRight, typeColor, scale);
    context.restore();
  }

  private drawHpBar(
    scene: ProductionScene,
    x: number,
    y: number,
    width: number,
    height: number,
    hp: number,
    previous: number,
    alignRight: boolean,
    scale: number
  ) {
    const context = this.context;
    const hud = scene.style.hud;
    const radius = hud.hp_shape === 'pill' ? height / 2 : hud.hp_shape === 'rounded' ? height * .28 : 0;
    const track = () => {
      if (hud.hp_shape === 'slash') slashRect(context, x, y, width, height, height * .5, alignRight);
      else roundedRect(context, x, y, width, height, radius);
    };
    track(); context.fillStyle = '#161b20'; context.fill();
    context.strokeStyle = 'rgba(255,255,255,.72)'; context.lineWidth = 2 * scale; context.stroke();
    context.save(); track(); context.clip();
    const fill = (fraction: number, fillStyle: string | CanvasGradient) => {
      const fillWidth = width * fraction;
      context.fillStyle = fillStyle;
      context.fillRect(alignRight ? x + width - fillWidth : x, y, fillWidth, height);
    };
    // The ghost bar is what makes a hit legible at a glance: it holds the pre-hit value
    // for a moment so the viewer sees how much was taken, not just where HP landed.
    if (hud.damage_ghost && previous > hp) fill(previous, '#f5c64e');
    if (hp > 0) {
      const gradient = context.createLinearGradient(x, 0, x + width, 0);
      const tone = hp > .5 ? '#55dc75' : hp > .2 ? '#f5c64e' : '#f04e57';
      gradient.addColorStop(0, tone);
      gradient.addColorStop(1, hp > .5 ? '#b8f28d' : hp > .2 ? '#ffe683' : '#ff8b79');
      fill(hp, gradient);
    }
    context.restore();
  }

  private drawTeamDots(
    scene: ProductionScene,
    side: ProductionSceneSide,
    x: number,
    y: number,
    width: number,
    height: number,
    alignRight: boolean,
    typeColor: string,
    scale: number
  ) {
    const mode = scene.style.hud.team_indicators;
    if (mode === 'hidden') return;
    const context = this.context;
    // Showdown keeps six fixed positions. Unknown opponents occupy a Pokéball slot instead of
    // disappearing, so the HUD never jumps between two and six indicators.
    const members = Array.from({ length: 6 }, (_, index) => {
      const member = side.team[index] || null;
      if (!member) return null;
      if (mode === 'fainted-only') return member.fainted || member.active ? member : null;
      if (mode === 'revealed') return member.active || member.fainted || member.hp_fraction < 1 ? member : null;
      return member;
    });
    const pad = 28 * scale;
    const size = 25 * scale;
    const gap = 31 * scale;
    members.forEach((member, index) => {
      const centerX = alignRight ? x + width - pad - index * gap : x + pad + index * gap;
      const centerY = y + height - 18 * scale;
      const left = centerX - size / 2;
      const top = centerY - size / 2;
      roundedRect(context, left, top, size, size, size * .22);
      context.fillStyle = member?.fainted ? 'rgba(255,255,255,.08)' : member ? withAlpha(index % 2 ? typeColor : side.accent, .16) : 'rgba(9,14,13,.72)';
      context.fill();
      context.strokeStyle = member?.active ? '#fff' : 'rgba(255,255,255,.38)';
      context.lineWidth = member?.active ? 2.5 * scale : 1.2 * scale;
      context.stroke();
      const bitmap = member ? this.bitmap(this.teamSpriteUrl(member)) : null;
      if (bitmap) {
        const ratio = bitmap.width / bitmap.height;
        const drawWidth = ratio >= 1 ? size * 1.2 : size * 1.2 * ratio;
        const drawHeight = ratio >= 1 ? size * 1.2 / ratio : size * 1.2;
        context.drawImage(bitmap, centerX - drawWidth / 2, centerY - drawHeight / 2, drawWidth, drawHeight);
      } else {
        this.drawTeamPokeball(centerX, centerY, size * .28, member?.fainted ? 'rgba(255,255,255,.36)' : '#e85d5d');
      }
      if (member?.fainted) {
        context.strokeStyle = 'rgba(255,255,255,.68)'; context.lineWidth = Math.max(1, scale * 1.5);
        context.beginPath(); context.moveTo(left + size * .2, top + size * .2); context.lineTo(left + size * .8, top + size * .8); context.stroke();
      }
    });
  }

  private teamSpriteUrl(member: PokemonState): string {
    return `${this.assetApiBase}/api/assets/pokemon/${encodeURIComponent(member.species)}?perspective=front&animated=false`;
  }

  private drawTeamPokeball(x: number, y: number, radius: number, topColor: string) {
    const context = this.context;
    context.fillStyle = topColor; context.beginPath(); context.arc(x, y, radius, Math.PI, 0); context.fill();
    context.fillStyle = '#f1f4ed'; context.beginPath(); context.arc(x, y, radius, 0, Math.PI); context.fill();
    context.strokeStyle = 'rgba(12,20,18,.9)'; context.lineWidth = Math.max(1, radius * .13); context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.stroke();
    context.fillStyle = '#f5faf5'; context.beginPath(); context.arc(x, y, radius * .26, 0, Math.PI * 2); context.fill();
  }

  private drawTypeChip(resolved: Resolved, type: string, x: number, y: number, alignRight: boolean, scale: number) {
    const context = this.context; const width = 78 * scale; const left = alignRight ? x : x - width;
    roundedRect(context, left, y, width, 25 * scale, 12 * scale);
    context.fillStyle = pokemonTypeColor([type]); context.fill();
    context.fillStyle = '#07100b'; context.textAlign = 'center';
    context.font = this.font(resolved, 'mono', 11 * scale, 950);
    context.fillText(type.toUpperCase(), left + width / 2, y + 17 * scale);
  }

  /**
   * A participant logo, or the generated wordmark when none is set or the file is gone.
   * Aspect ratio is always preserved — a squashed logo looks broken and misrepresents a
   * brand the user does not own.
   */
  private drawLogo(side: ProductionSceneSide, x: number, y: number, size: number, resolved: Resolved) {
    const context = this.context;
    const bitmap = this.bitmap(side.logoUrl);
    context.save();
    if (bitmap) {
      const ratio = bitmap.width / bitmap.height;
      const drawWidth = ratio >= 1 ? size : size * ratio;
      const drawHeight = ratio >= 1 ? size / ratio : size;
      context.drawImage(bitmap, x + (size - drawWidth) / 2, y + (size - drawHeight) / 2, drawWidth, drawHeight);
    } else {
      roundedRect(context, x, y, size, size, size * .24);
      context.fillStyle = withAlpha(side.accent, .18); context.fill();
      context.strokeStyle = withAlpha(side.accent, .7); context.lineWidth = Math.max(1, size * .05); context.stroke();
      context.fillStyle = side.accent; context.textAlign = 'center';
      const label = side.markLabel.slice(0, 8);
      context.font = this.font(resolved, 'mono', size * (label.length > 5 ? .21 : .28), 950);
      context.fillText(label, x + size / 2, y + size * .58);
    }
    context.restore();
  }

  // -------------------------------------------------------------- overlays

  private drawMoveCallout(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const move = scene.style.move;
    if (move.layout === 'off') return;
    if (!scene.effect.moveName || scene.effect.progress <= 0 || scene.effect.progress >= 1) return;
    const context = this.context;
    const color = TYPE_COLORS[scene.effect.type];
    const alpha = Math.min(1, scene.effect.progress * 6 * move.duration_scale, (1 - scene.effect.progress) * 5 * move.duration_scale);
    const boxes = hudLayout(scene.style.hud.preset, scene.vertical, width, height, scale);
    const hudBottom = Math.max(boxes.p1.y + boxes.p1.height, boxes.p2.y + boxes.p2.height);
    const y = move.layout === 'lower-third'
      ? height * .8
      : scene.vertical
        ? height * .48
        : Math.max(height * .34, hudBottom + 50 * scale);
    context.save();
    context.globalAlpha = alpha;
    context.textAlign = 'center';
    if (move.layout === 'minimal') {
      context.fillStyle = color;
      context.font = this.font(resolved, 'display', 34 * scale, resolved.weight);
      this.paintText(context, resolved, this.text(resolved, scene.effect.moveName), width / 2, y, width * .7);
      context.restore();
      return;
    }
    const impact = move.layout === 'impact';
    const boxWidth = Math.min((impact ? 700 : 620) * scale, width * .52);
    const boxHeight = (impact ? 112 : 98) * scale;
    if (impact) {
      context.translate(width / 2, y);
      context.scale(1 + (1 - alpha) * .18, 1 + (1 - alpha) * .18);
      context.translate(-width / 2, -y);
    }
    context.shadowColor = 'rgba(0,0,0,.35)';
    context.shadowBlur = 18 * scale;
    context.fillStyle = 'rgba(4,6,10,.94)';
    this.shape(context, scene, width / 2 - boxWidth / 2, y - boxHeight / 2, boxWidth, boxHeight, 24 * scale);
    context.fill();
    context.shadowBlur = 0;
    context.strokeStyle = withAlpha(color, .92); context.lineWidth = (impact ? 5 : 3) * scale; context.stroke();

    const category = scene.effect.category || categoryLabel(scene.effect.archetype);
    const tags = [
      move.show_type ? scene.effect.type.toUpperCase() : null,
      move.show_archetype ? category : null
    ].filter((value): value is string => Boolean(value));
    const tagGap = 8 * scale;
    const tagWidths = tags.map((tag) => {
      context.font = this.font(resolved, 'mono', 12 * scale, 900);
      return context.measureText(tag).width + 26 * scale;
    });
    const tagsWidth = tagWidths.reduce((sum, value) => sum + value, 0) + Math.max(0, tags.length - 1) * tagGap;
    let tagX = width / 2 - tagsWidth / 2;
    tags.forEach((tag, index) => {
      const tagWidth = tagWidths[index];
      roundedRect(context, tagX, y - boxHeight / 2 + 13 * scale, tagWidth, 23 * scale, 11 * scale);
      context.fillStyle = withAlpha(color, .18);
      context.fill();
      context.strokeStyle = withAlpha(color, .65);
      context.lineWidth = Math.max(1, scale);
      context.stroke();
      context.fillStyle = color;
      context.font = this.font(resolved, 'mono', 12 * scale, 900);
      context.fillText(tag, tagX + tagWidth / 2, y - boxHeight / 2 + 29 * scale);
      tagX += tagWidth + tagGap;
    });
    if (tags.length) {
      context.strokeStyle = withAlpha(color, .22);
      context.lineWidth = Math.max(1, scale);
      context.beginPath();
      context.moveTo(width / 2 - boxWidth / 2 + 28 * scale, y - boxHeight / 2 + 43 * scale);
      context.lineTo(width / 2 + boxWidth / 2 - 28 * scale, y - boxHeight / 2 + 43 * scale);
      context.stroke();
    }
    context.fillStyle = '#fff';
    const title = this.text(resolved, scene.effect.moveName);
    let titleSize = (impact ? 43 : 38) * scale;
    const titleMaxWidth = boxWidth - 58 * scale;
    context.font = this.font(resolved, 'display', titleSize, resolved.weight);
    while (context.measureText(title).width > titleMaxWidth && titleSize > 22 * scale) {
      titleSize -= 1 * scale;
      context.font = this.font(resolved, 'display', titleSize, resolved.weight);
    }
    const titleY = y + (tags.length ? boxHeight * .31 : boxHeight * .12);
    this.paintText(context, resolved, title, width / 2, titleY, titleMaxWidth);
    context.restore();
  }

  private drawDamageCallout(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const callout = damageCallout(scene);
    if (!callout || scene.style.damage.intensity === 'off') return;
    const strength = intensityScale(scene.style.damage.intensity);
    const positions = combatantPositions(scene, width, height);
    const target = positions[scene.effect.target || 'p2'];
    const rise = easeOut(callout.progress) * 90 * scale * (0.6 + strength * .5);
    const context = this.context;
    context.save();
    context.globalAlpha = Math.min(1, (1 - callout.progress) * 2.4);
    context.textAlign = 'center';
    const size = (callout.tone === 'damage' || callout.tone === 'heal' ? 64 : 42) * scale * (0.85 + strength * .2);
    context.font = this.font(resolved, 'display', size, 950);
    context.lineWidth = Math.max(2, 6 * scale);
    context.strokeStyle = 'rgba(2,4,7,.9)';
    context.strokeText(callout.text, target.x, target.y - 230 * scale - rise);
    context.fillStyle = TONE_COLORS[callout.tone];
    context.fillText(callout.text, target.x, target.y - 230 * scale - rise);
    context.restore();
  }

  private drawCommentary(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const layout = scene.style.commentary.layout;
    if (layout === 'off' || layout === 'caption' || !scene.commentary) return;
    const context = this.context;
    const side = scene.commentarySide === 'p2' ? scene.p2 : scene.p1;
    const color = side.accent;
    const lower = layout === 'lower-third';
    const boxWidth = lower
      ? Math.min(width * .82, 1280 * scale)
      : Math.min(width * (scene.vertical ? .88 : .42), (scene.vertical ? 900 : 760) * scale);
    const x = lower
      ? (width - boxWidth) / 2
      : scene.vertical
        ? (width - boxWidth) / 2
        : scene.commentarySide === 'p2'
          ? width - boxWidth - 52 * scale
          : 52 * scale;
    // In vertical framing the near player's HUD occupies the bottom fifth, so a lower third
    // placed at .78 landed on top of it and made both unreadable. Sit above that panel.
    const baseY = lower
      ? scene.vertical
        ? height * .60
        : height * .78
      : scene.vertical
        ? height * .60
        : height * .655;
    const motion = commentaryMotion(scene, scale);
    const boxHeight = (lower ? 128 : 118) * scale;
    context.save();
    context.globalAlpha = motion.alpha;
    context.translate(motion.dx, motion.dy);
    const bubble = layout === 'bubble';
    if (bubble) roundedRect(context, x, baseY, boxWidth, boxHeight, 26 * scale);
    else this.shape(context, scene, x, baseY, boxWidth, boxHeight, 22 * scale, scene.commentarySide === 'p2' && !lower);
    context.fillStyle = 'rgba(4,7,11,.91)'; context.fill();
    context.strokeStyle = withAlpha(color, .62); context.lineWidth = 3 * scale; context.stroke();
    let textLeft = x + 28 * scale;
    if (scene.style.commentary.show_logo) {
      this.drawLogo(side, x + 20 * scale, baseY + 20 * scale, boxHeight - 40 * scale, resolved);
      textLeft = x + boxHeight - 4 * scale;
    }
    let textTop = baseY + 58 * scale;
    if (scene.style.commentary.show_agent_name || scene.style.commentary.show_label) {
      const heading = [
        scene.style.commentary.show_agent_name ? side.displayName.toUpperCase() : null,
        scene.style.commentary.show_label ? 'FIGHTER INTENT' : null
      ].filter(Boolean).join(' // ');
      context.fillStyle = color; context.textAlign = 'left';
      context.font = this.font(resolved, 'mono', 14 * scale, 900);
      context.fillText(heading, textLeft, baseY + 27 * scale);
    } else {
      textTop = baseY + 44 * scale;
    }
    // The caption already carries the spoken words; repeating them here is noise.
    const spoken = scene.caption && scene.commentary.startsWith(scene.caption.slice(0, 18));
    context.fillStyle = spoken ? withAlpha('#f5f7f5', .55) : '#f5f7f5';
    context.textAlign = 'left';
    const bodyFont = this.font(resolved, 'body', 22 * scale, 750);
    context.font = bodyFont;
    const lines = wrap(context, scene.commentary, boxWidth - (textLeft - x) - 28 * scale, bodyFont).slice(0, spoken ? 1 : 3);
    lines.forEach((line, index) => context.fillText(line, textLeft, textTop + index * 25 * scale));
    context.restore();
  }

  private drawCaption(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const caption = scene.style.caption;
    if (caption.preset === 'off' || !scene.caption) return;
    const context = this.context;
    const maxWidth = Math.min(width * .84, (scene.vertical ? 920 : 1180) * scale);
    const fontSize = (scene.vertical || caption.preset === 'vertical' ? 34 : 30) * caption.size_scale * scale;
    const y = caption.position === 'top' ? height * .12 : caption.position === 'center' ? height * .5 : scene.vertical ? height * .947 : height * .875;
    const font = this.font(resolved, 'body', fontSize, 850);
    const lines = wrap(context, scene.caption, maxWidth - 86 * scale, font).slice(0, 2);
    const boxHeight = (lines.length * fontSize * 1.26 + 28 * scale);
    context.save();
    if (caption.background_opacity > 0) {
      roundedRect(context, (width - maxWidth) / 2, y - boxHeight / 2, maxWidth, boxHeight, 12 * scale);
      context.fillStyle = caption.preset === 'high-contrast'
        ? `rgba(0,0,0,${Math.max(caption.background_opacity, .92)})`
        : `rgba(0,0,0,${caption.background_opacity})`;
      context.fill();
    }
    context.textAlign = 'center';
    context.font = font;
    let top = y - (lines.length - 1) * fontSize * .63 + fontSize * .34;
    if (caption.show_speaker && scene.captionSide) {
      const speaker = scene.captionSide === 'p2' ? scene.p2 : scene.p1;
      context.fillStyle = speaker.accent;
      context.font = this.font(resolved, 'mono', 15 * scale, 900);
      context.fillText(speaker.displayName.toUpperCase(), width / 2, y - boxHeight / 2 - 10 * scale);
      context.font = font;
    }
    lines.forEach((line, index) => {
      const lineY = top + index * fontSize * 1.26;
      if (caption.outline) {
        context.lineWidth = Math.max(2, 5 * scale);
        context.strokeStyle = 'rgba(0,0,0,.95)';
        context.strokeText(line, width / 2, lineY);
      }
      context.fillStyle = '#fff';
      context.fillText(line, width / 2, lineY);
    });
    void top;
    context.restore();
  }

  private drawDirector(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const card = directorCard(scene);
    if (!card) return;
    const context = this.context;
    const result = card.kind === 'result';
    const p1 = scene.p1.accent;
    const p2 = scene.p2.accent;
    context.save();
    context.globalAlpha = card.opacity;
    // Opaque, not 94%: the HUD underneath was ghosting through the intro card, so a match
    // that has not started yet showed "AWAITING POKÉMON" and empty 0% bars behind the
    // matchup. The card's own fade is carried by globalAlpha, so the transition is intact.
    context.fillStyle = '#020408'; context.fillRect(0, 0, width, height);
    context.fillStyle = withAlpha(result ? '#ffd96a' : p1, .2);
    context.beginPath(); context.moveTo(0, 0); context.lineTo(width * .62, 0); context.lineTo(width * .38, height); context.lineTo(0, height); context.closePath(); context.fill();
    context.fillStyle = withAlpha(result ? '#ff984c' : p2, .18);
    context.beginPath(); context.moveTo(width * .62, 0); context.lineTo(width, 0); context.lineTo(width, height); context.lineTo(width * .38, height); context.closePath(); context.fill();
    for (let index = -2; index <= 2; index += 1) {
      context.strokeStyle = 'rgba(255,255,255,.08)'; context.lineWidth = 12 * scale;
      context.beginPath(); context.moveTo(width * .5 + index * 52 * scale, 0); context.lineTo(width * .32 + index * 52 * scale, height); context.stroke();
    }
    context.textAlign = 'center';
    if (card.showLogos) {
      const logoSize = (scene.vertical ? 190 : 220) * scale;
      this.drawLogo(scene.p1, width * (scene.vertical ? .27 : .22) - logoSize / 2, height * .17, logoSize, resolved);
      this.drawLogo(scene.p2, width * (scene.vertical ? .73 : .78) - logoSize / 2, height * .17, logoSize, resolved);
    }
    if (card.eyebrow) {
      context.fillStyle = result ? '#ffd96a' : resolved.accent;
      context.font = this.font(resolved, 'mono', 22 * scale, 950);
      context.fillText(card.eyebrow, width / 2, height * .34);
    }
    context.fillStyle = '#fff';
    context.font = this.font(resolved, 'display', (scene.vertical ? 62 : 86) * scale, resolved.weight);
    this.paintText(context, resolved, this.text(resolved, card.headline), width / 2, height * .49, width * .9);
    if (card.subtitle) {
      context.fillStyle = 'rgba(240,246,242,.86)';
      context.font = this.font(resolved, 'mono', 26 * scale, 800);
      context.fillText(card.subtitle.toUpperCase(), width / 2, height * .57, width * .86);
    }
    if (card.badge) {
      context.fillStyle = result ? '#ffd96a' : '#fff';
      context.font = this.font(resolved, 'display', (scene.vertical ? 110 : 140) * scale, resolved.weight);
      context.fillText(card.badge, width / 2, height * .72);
    }
    if (scene.title) {
      context.fillStyle = 'rgba(255,255,255,.7)';
      context.font = this.font(resolved, 'mono', 22 * scale, 800);
      context.fillText(scene.title.toUpperCase(), width / 2, height * .88, width * .8);
    }
    context.restore();
  }

  private drawWatermark(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const watermark = scene.style.watermark;
    if (!watermark.enabled) return;
    const size = 110 * watermark.size * scale;
    const margin = 34 * scale;
    const x = watermark.position.endsWith('right') ? width - margin - size : margin;
    const y = watermark.position.startsWith('top') ? margin : height - margin - size;
    const bitmap = this.bitmap(assetUrl(this.assetApiBase, watermark.asset_id));
    const context = this.context;
    context.save();
    context.globalAlpha = watermark.opacity;
    if (bitmap) {
      const ratio = bitmap.width / bitmap.height;
      const drawWidth = ratio >= 1 ? size : size * ratio;
      const drawHeight = ratio >= 1 ? size / ratio : size;
      context.drawImage(bitmap, x + (size - drawWidth) / 2, y + (size - drawHeight) / 2, drawWidth, drawHeight);
    } else if (watermark.text) {
      context.textAlign = watermark.position.endsWith('right') ? 'right' : 'left';
      context.fillStyle = '#fff';
      context.font = this.font(resolved, 'display', 30 * watermark.size * scale, 900);
      context.fillText(this.text(resolved, watermark.text), watermark.position.endsWith('right') ? width - margin : margin, y + size * .6);
    }
    context.restore();
  }

  private drawFrame(resolved: Resolved, width: number, height: number, scale: number) {
    if (!resolved.style.show_koala_branding) return;
    this.context.save();
    this.context.strokeStyle = withAlpha(resolved.accent, .58); this.context.lineWidth = 3 * scale;
    this.context.strokeRect(14 * scale, 14 * scale, width - 28 * scale, height - 28 * scale);
    this.context.fillStyle = resolved.accent;
    this.context.fillRect(14 * scale, 14 * scale, 150 * scale, 6 * scale);
    this.context.fillRect(width - 164 * scale, height - 20 * scale, 150 * scale, 6 * scale);
    this.context.restore();
  }

  // ------------------------------------------------------------------ text

  private font(resolved: Resolved, role: 'display' | 'body' | 'mono', size: number, weight: number): string {
    return `${weight} ${Math.round(size * resolved.scale)}px ${resolved[role]}`;
  }

  private text(resolved: Resolved, value: string): string {
    return resolved.upper ? value.toUpperCase() : value;
  }

  private paintText(
    context: CanvasRenderingContext2D,
    resolved: Resolved,
    value: string,
    x: number,
    y: number,
    maxWidth?: number
  ) {
    const spacing = resolved.tracking;
    if (spacing) context.letterSpacing = `${spacing}px`;
    if (resolved.shadow) { context.shadowColor = 'rgba(0,0,0,.6)'; context.shadowBlur = 8; }
    if (resolved.outline) {
      context.lineWidth = 4;
      context.strokeStyle = 'rgba(4,6,10,.92)';
      context.strokeText(value, x, y, maxWidth);
    }
    context.fillText(value, x, y, maxWidth);
    context.shadowBlur = 0;
    if (spacing) context.letterSpacing = '0px';
  }

  /** Panel silhouette. `slash` is the house shape; other HUD presets use rectangles. */
  private shape(
    context: CanvasRenderingContext2D,
    scene: ProductionScene,
    x: number,
    y: number,
    width: number,
    height: number,
    cut: number,
    reverse = false
  ) {
    const preset = scene.style.hud.preset;
    if (preset === 'retro') { roundedRect(context, x, y, width, height, 4); return; }
    if (preset === 'minimal' || preset === 'esports') { roundedRect(context, x, y, width, height, cut * .35); return; }
    if (preset === 'fighting') { roundedRect(context, x, y, width, height, cut * .2); return; }
    slashRect(context, x, y, width, height, cut, reverse);
  }

  // --------------------------------------------------------------- effects

  private drawEffect(scene: ProductionScene, resolved: Resolved, width: number, height: number, scale: number) {
    const effect = scene.effect;
    if (resolved.effect <= 0 || effect.progress <= 0 || effect.progress >= 1) return;
    const positions = combatantPositions(scene, width, height);
    const targetSide = effect.target || (effect.actor === 'p1' ? 'p2' : 'p1');
    const end = positions[targetSide];
    const color = TYPE_COLORS[effect.type];
    const impactCue = new Set(['damage', 'critical_hit', 'super_effective', 'resisted', 'immune']);
    const context = this.context;
    const recipe = resolveMoveEffect(
      effect.moveName || effect.moveId || '',
      effect.type,
      effect.category,
      scene.style.hud.preset === 'retro' ? 'retro' : 'broadcast'
    );
    context.save(); context.globalCompositeOperation = 'lighter';
    if (effect.archetype === 'heal') this.drawHeal(end, effect, color, scale);
    else if (effect.archetype === 'status') this.drawStatusEffect(end, effect, color, scale);
    else if (['pulse', 'field', 'buff', 'debuff'].includes(effect.archetype)) this.drawPulse(effect.archetype === 'field' ? { x: width / 2, y: height * .7 } : end, effect, effect.archetype === 'debuff' ? '#ff5f72' : color, scale);
    else if (effect.archetype === 'barrier') this.drawBarrier(end, effect, color, scale);
    else if (effect.archetype === 'hazard') this.drawHazard(end, effect, color, scale);
    else if (effect.attack && recipe.family === 'quake') this.drawEarthquake(scene, effect, width, height, scale);
    else if (effect.attack && effect.actor) {
      const archetype = recipe.family === 'beam' || recipe.family === 'lightning'
        ? 'beam'
        : recipe.family === 'contact' ? 'contact' : effect.archetype;
      this.drawAttack(positions[effect.actor], end, { ...effect, archetype }, recipe.color, width, scale, resolved);
      this.drawRecipeMotif(recipe.family, positions[effect.actor], end, effect, recipe.color, recipe.assetId, scale);
    }
    if (scene.style.effect.impact_flash && impactCue.has(effect.kind) && effect.impactProgress > 0 && effect.impactProgress < 1) {
      const burst = impactEnvelope(effect.impactProgress) * resolved.effect;
      const rays = Math.max(6, Math.round(18 * resolved.effect));
      const impactColor = effect.kind === 'critical_hit' ? TONE_COLORS.crit : color;
      context.globalAlpha = Math.min(1, burst); context.strokeStyle = impactColor; context.lineWidth = 10 * scale; context.lineCap = 'round';
      for (let index = 0; index < rays; index += 1) { const angle = index / rays * Math.PI * 2 + hash(effect.seed + index) * .22; const inner = 30 * scale; const outer = (90 + hash(index * 7) * 175) * scale * burst; context.beginPath(); context.moveTo(end.x + Math.cos(angle) * inner, end.y - 120 * scale + Math.sin(angle) * inner); context.lineTo(end.x + Math.cos(angle) * outer, end.y - 120 * scale + Math.sin(angle) * outer); context.stroke(); }
      context.fillStyle = withAlpha(impactColor, .28); context.globalAlpha = Math.min(1, burst * .7); context.beginPath(); context.arc(end.x, end.y - 120 * scale, 75 * scale * burst, 0, Math.PI * 2); context.fill();
    }
    context.restore();
  }

  /** Move-specific accent shared with the live recipe registry; always has a procedural fallback. */
  private drawRecipeMotif(family: MoveEffectFamily, start: Point, end: Point, effect: ProductionScene['effect'], color: string, assetId: string | null, scale: number) {
    const context = this.context;
    const travel = easeInOut(clamp((effect.progress - .12) / .68));
    const origin = { x: start.x, y: start.y - 150 * scale };
    const target = { x: end.x, y: end.y - 125 * scale };
    const x = origin.x + (target.x - origin.x) * travel;
    const y = origin.y + (target.y - origin.y) * travel - Math.sin(travel * Math.PI) * (family === 'water' ? 35 : 85) * scale;
    const pulse = Math.sin(effect.progress * Math.PI);
    const bitmap = assetId ? this.bitmap(moveEffectAssetUrl(assetId, this.assetApiBase)) : null;
    if (bitmap && !['beam', 'lightning', 'quake', 'rock', 'ice', 'wind'].includes(family)) {
      const size = (80 + pulse * 55) * scale;
      context.globalAlpha = pulse;
      context.drawImage(bitmap, x - size / 2, y - size / 2, size, size);
    }
    context.strokeStyle = color;
    context.fillStyle = color;
    context.lineCap = 'round';
    if (family === 'lightning') {
      context.lineWidth = 12 * scale;
      context.globalAlpha = pulse;
      context.beginPath(); context.moveTo(origin.x, origin.y);
      for (let i = 1; i < 7; i += 1) {
        const t = Math.min(travel, i / 6);
        context.lineTo(origin.x + (target.x - origin.x) * t + (hash(effect.seed + i) - .5) * 70 * scale, origin.y + (target.y - origin.y) * t);
      }
      context.stroke();
    } else if (family === 'water' || family === 'wind') {
      context.globalAlpha = pulse * .8;
      context.lineWidth = 8 * scale;
      for (let i = 0; i < 3; i += 1) {
        context.beginPath(); context.ellipse(x, y, (45 + i * 22) * scale, (13 + i * 7) * scale, -.35, 0, Math.PI * 2); context.stroke();
      }
    } else if (family === 'ice' || family === 'rock') {
      context.globalAlpha = pulse;
      for (let i = 0; i < 7; i += 1) {
        const angle = i / 7 * Math.PI * 2 + hash(effect.seed + i);
        const radius = (28 + hash(effect.seed + i * 11) * 55) * scale;
        const px = target.x + Math.cos(angle) * radius;
        const py = target.y + Math.sin(angle) * radius;
        const size = (8 + hash(effect.seed + i * 17) * 18) * scale;
        context.beginPath(); context.moveTo(px, py - size); context.lineTo(px + size, py + size); context.lineTo(px - size, py + size * .65); context.closePath(); context.fill();
      }
    } else if (family === 'explosion') {
      context.globalAlpha = pulse * .8;
      const glow = context.createRadialGradient(target.x, target.y, 0, target.x, target.y, 190 * scale * pulse);
      glow.addColorStop(0, '#fff'); glow.addColorStop(.3, color); glow.addColorStop(1, 'rgba(0,0,0,0)');
      context.fillStyle = glow; context.beginPath(); context.arc(target.x, target.y, 190 * scale * pulse, 0, Math.PI * 2); context.fill();
    }
  }

  /** Original canvas treatment for Ground moves: arena-wide shockwaves, cracks and debris. */
  private drawEarthquake(scene: ProductionScene, effect: ProductionScene['effect'], width: number, height: number, scale: number) {
    const context = this.context;
    const progress = effect.progress;
    const pulse = Math.sin(progress * Math.PI);
    const floor = height * (scene.vertical ? .66 : .72);
    context.lineCap = 'round';
    for (let ring = 0; ring < 3; ring += 1) {
      const phase = clamp(progress * 1.5 - ring * .16);
      if (phase <= 0) continue;
      const fade = (1 - phase) * pulse;
      context.globalAlpha = fade * .72;
      context.strokeStyle = '#e3a44d';
      context.lineWidth = (7 - ring * 1.5) * scale;
      context.beginPath();
      context.ellipse(width / 2, floor, (50 + phase * width * .48) * scale, (12 + phase * height * .09) * scale, 0, 0, Math.PI * 2);
      context.stroke();
    }
    const positions = combatantPositions(scene, width, height);
    const crackOrigins = [positions.p1.x, positions.p2.x, width * .5];
    for (let index = 0; index < crackOrigins.length; index += 1) {
      const origin = crackOrigins[index];
      const crackProgress = clamp((progress - .08 - index * .035) / .55);
      context.globalAlpha = crackProgress * (1 - progress * .35) * .82;
      context.strokeStyle = index === 2 ? '#f0c56b' : '#b8793f';
      context.lineWidth = (4 + (index === 2 ? 2 : 0)) * scale;
      context.beginPath();
      context.moveTo(origin - 48 * scale, floor + 3 * scale);
      context.lineTo(origin - 18 * scale, floor - 12 * scale);
      context.lineTo(origin - 5 * scale, floor + 2 * scale);
      context.lineTo(origin + 26 * scale, floor - 28 * crackProgress * scale);
      context.lineTo(origin + 48 * scale, floor - 18 * crackProgress * scale);
      context.stroke();
    }
    for (let index = 0; index < 10; index += 1) {
      const launch = clamp((progress - .16 - hash(effect.seed + index) * .12) / .56);
      if (launch <= 0) continue;
      const source = positions[index % 2 === 0 ? 'p1' : 'p2'];
      const x = source.x + (hash(effect.seed + index * 13) - .5) * 180 * scale;
      const y = floor - easeOut(launch) * (46 + hash(effect.seed + index * 19) * 130) * scale;
      const size = (5 + hash(effect.seed + index * 29) * 10) * scale;
      context.globalAlpha = (1 - launch) * pulse * .9;
      context.fillStyle = index % 3 === 0 ? '#f0c56b' : '#ad713f';
      context.beginPath();
      context.moveTo(x - size, y + size);
      context.lineTo(x + size * .65, y + size * .3);
      context.lineTo(x + size * .3, y - size);
      context.lineTo(x - size * .8, y - size * .45);
      context.closePath();
      context.fill();
    }
  }

  /** Earth Power keeps the Ground identity but adds a directed, molten projectile. */
  private drawEarthPower(start: Point, end: Point, scene: ProductionScene, effect: ProductionScene['effect'], width: number, height: number, scale: number) {
    this.drawEarthquake(scene, effect, width, height, scale * .72);
    const context = this.context;
    const travel = easeInOut(clamp((effect.progress - .12) / .58));
    const origin = { x: start.x, y: start.y - 125 * scale };
    const target = { x: end.x, y: end.y - 125 * scale };
    const x = origin.x + (target.x - origin.x) * travel;
    const y = origin.y + (target.y - origin.y) * travel - Math.sin(travel * Math.PI) * 95 * scale;
    const pulse = Math.sin(effect.progress * Math.PI);
    for (let index = 0; index < 6; index += 1) {
      const offset = (hash(effect.seed + index * 23) - .5) * 34 * scale;
      const drift = Math.sin(effect.progress * Math.PI * 2 + index) * 18 * scale;
      context.globalAlpha = pulse * (.45 + hash(effect.seed + index * 31) * .45);
      context.fillStyle = index % 2 ? '#ff8b3d' : '#e3a44d';
      context.beginPath();
      context.arc(x + offset + drift, y + offset * .35, (10 + hash(effect.seed + index * 37) * 16) * scale, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = pulse;
    const glow = context.createRadialGradient(x, y, 0, x, y, 70 * scale);
    glow.addColorStop(0, '#ffd36b'); glow.addColorStop(.3, '#ff8b3d'); glow.addColorStop(1, 'rgba(255,139,61,0)');
    context.fillStyle = glow;
    context.beginPath(); context.arc(x, y, 70 * scale, 0, Math.PI * 2); context.fill();
  }

  private drawAttack(start: Point, end: Point, effect: ProductionScene['effect'], color: string, width: number, scale: number, resolved: Resolved) {
    const context = this.context; const travel = clamp((effect.progress - .18) / .56); const miss = effect.kind === 'move_missed' ? (effect.actor === 'p1' ? 1 : -1) * 200 * scale : 0;
    const target = { x: end.x + miss, y: end.y - 130 * scale }; const origin = { x: start.x, y: start.y - 165 * scale }; const x = origin.x + (target.x - origin.x) * easeInOut(travel); const y = origin.y + (target.y - origin.y) * easeInOut(travel) - Math.sin(travel * Math.PI) * 105 * scale;
    if (effect.archetype === 'contact') {
      const slashProgress = clamp((effect.progress - .34) / .42);
      const impactX = target.x;
      const impactY = target.y;
      context.lineCap = 'round';
      for (let index = -1; index <= 1; index += 1) {
        const offset = index * 42 * scale;
        const length = (105 + Math.abs(index) * 22) * scale * easeOut(slashProgress);
        const angle = -.72 + index * .22;
        const alpha = (.88 - Math.abs(index) * .18) * slashProgress * resolved.effect;
        context.globalAlpha = alpha;
        context.strokeStyle = mix(color, '#061016', .28); context.lineWidth = (22 - Math.abs(index) * 3) * scale;
        context.beginPath();
        context.moveTo(impactX - Math.cos(angle) * length - offset, impactY - 120 * scale - Math.sin(angle) * length);
        context.lineTo(impactX + Math.cos(angle) * length * .35 - offset, impactY - 120 * scale + Math.sin(angle) * length * .35);
        context.stroke();
        context.strokeStyle = color; context.lineWidth = (10 - Math.abs(index) * 1.5) * scale; context.stroke();
        context.globalAlpha = alpha * .42;
        context.strokeStyle = mix(color, '#ffffff', .35); context.lineWidth = 3 * scale;
        context.beginPath();
        context.moveTo(impactX - Math.cos(angle) * length * .82 - offset, impactY - 120 * scale - Math.sin(angle) * length * .82);
        context.lineTo(impactX - Math.cos(angle) * length * .25 - offset, impactY - 120 * scale - Math.sin(angle) * length * .25);
        context.stroke();
      }
      context.globalAlpha = slashProgress * .75 * resolved.effect;
      context.strokeStyle = color; context.lineWidth = 7 * scale;
      context.beginPath(); context.arc(impactX, impactY - 120 * scale, (42 + slashProgress * 70) * scale, 0, Math.PI * 2); context.stroke();
    } else if (effect.archetype === 'beam') {
      const beam = clamp((effect.progress - .18) / .45); const angle = Math.atan2(target.y - origin.y, target.x - origin.x); const length = Math.hypot(target.x - origin.x, target.y - origin.y) * easeOut(beam);
      const pulse = Math.sin(beam * Math.PI);
      context.strokeStyle = withAlpha(color, .26); context.lineWidth = 72 * scale * pulse; context.lineCap = 'round'; context.beginPath(); context.moveTo(origin.x, origin.y); context.lineTo(origin.x + Math.cos(angle) * length, origin.y + Math.sin(angle) * length); context.stroke();
      context.strokeStyle = color; context.lineWidth = 28 * scale * pulse; context.beginPath(); context.moveTo(origin.x, origin.y); context.lineTo(origin.x + Math.cos(angle) * length, origin.y + Math.sin(angle) * length); context.stroke();
      context.strokeStyle = mix(color, '#ffffff', .3); context.lineWidth = 8 * scale * pulse; context.beginPath(); context.moveTo(origin.x, origin.y); context.lineTo(origin.x + Math.cos(angle) * length, origin.y + Math.sin(angle) * length); context.stroke();
      for (let particle = 0; particle < 5; particle += 1) {
        const distance = length * clamp(beam + (hash(effect.seed + particle * 31) - .5) * .22);
        const px = origin.x + Math.cos(angle) * distance;
        const py = origin.y + Math.sin(angle) * distance;
        const radius = (7 + hash(effect.seed + particle * 17) * 9) * scale * pulse;
        context.fillStyle = withAlpha(mix(color, '#ffffff', .2), .8);
        context.globalAlpha = .35 + pulse * .65;
        context.beginPath(); context.arc(px, py, radius, 0, Math.PI * 2); context.fill();
      }
    } else {
      const trails = resolved.style.effect.trails ? 4 : 0;
      for (let trail = trails; trail >= 0; trail -= 1) { const tx = x - (x - origin.x) * trail * .05; const ty = y - (y - origin.y) * trail * .05; const radius = (34 + (4 - trail) * 8) * scale; const glow = context.createRadialGradient(tx, ty, 0, tx, ty, radius * 2.4); glow.addColorStop(0, mix(color, '#ffffff', .22)); glow.addColorStop(.28, withAlpha(color, .8)); glow.addColorStop(1, 'rgba(0,0,0,0)'); context.globalAlpha = 1 - trail * .16; context.fillStyle = glow; context.beginPath(); context.arc(tx, ty, radius * 2.4, 0, Math.PI * 2); context.fill(); }
      context.strokeStyle = color; context.lineWidth = 7 * scale; context.globalAlpha = .72; context.beginPath(); context.moveTo(origin.x, origin.y); context.quadraticCurveTo(width / 2, Math.min(origin.y, target.y) - 150 * scale, x, y); context.stroke();
    }
  }

  private drawStatusEffect(end: Point, effect: ProductionScene['effect'], color: string, scale: number) {
    const context = this.context;
    const center = { x: end.x, y: end.y - 120 * scale };
    const condition = effect.condition || '';
    const pulse = Math.sin(effect.progress * Math.PI);
    const statusColor = condition.includes('par') ? '#ffe148'
      : condition.includes('brn') ? '#ff7043'
        : condition.includes('psn') || condition.includes('tox') ? '#d16bff'
          : condition.includes('slp') ? '#a9a4ff'
            : condition.includes('frz') ? '#82f4f1'
              : color;
    context.globalAlpha = pulse * .7;
    context.strokeStyle = statusColor;
    context.lineWidth = 7 * scale;
    context.beginPath(); context.arc(center.x, center.y, (64 + pulse * 34) * scale, 0, Math.PI * 2); context.stroke();
    for (let index = 0; index < 8; index += 1) {
      const angle = index / 8 * Math.PI * 2 + effect.progress * Math.PI;
      const distance = (70 + pulse * 28 + hash(effect.seed + index) * 24) * scale;
      const x = center.x + Math.cos(angle) * distance;
      const y = center.y + Math.sin(angle) * distance;
      const size = (6 + hash(effect.seed + index * 7) * 8) * scale;
      context.fillStyle = statusColor;
      context.beginPath();
      if (condition.includes('par')) {
        context.moveTo(x, y - size); context.lineTo(x + size * .55, y); context.lineTo(x - size * .1, y); context.lineTo(x + size * .25, y + size); context.lineTo(x - size * .55, y + size * .05); context.lineTo(x, y + size * .05); context.closePath();
      } else {
        context.arc(x, y, size, 0, Math.PI * 2);
      }
      context.fill();
    }
  }

  private drawHeal(end: Point, effect: ProductionScene['effect'], color: string, scale: number) {
    for (let index = 0; index < 18; index += 1) { const lift = easeOut(effect.progress); const x = end.x + (hash(effect.seed + index) - .5) * 250 * scale; const y = end.y - (40 + hash(index * 17) * 240) * scale * lift; this.context.fillStyle = withAlpha(color === TYPE_COLORS.normal ? '#7bf0a2' : color, Math.sin(effect.progress * Math.PI)); this.context.fillRect(x - 4 * scale, y - 20 * scale, 8 * scale, 40 * scale); this.context.fillRect(x - 20 * scale, y - 4 * scale, 40 * scale, 8 * scale); }
  }

  private drawPulse(center: Point, effect: ProductionScene['effect'], color: string, scale: number) {
    this.context.strokeStyle = color; this.context.lineWidth = 9 * scale;
    for (let ring = 0; ring < 5; ring += 1) { const phase = clamp(effect.progress * 1.5 - ring * .1); this.context.globalAlpha = (1 - phase) * .75; this.context.beginPath(); this.context.ellipse(center.x, center.y, (50 + phase * 280) * scale, (28 + phase * 130) * scale, 0, 0, Math.PI * 2); this.context.stroke(); }
  }

  private drawBarrier(end: Point, effect: ProductionScene['effect'], color: string, scale: number) {
    this.context.globalAlpha = Math.sin(effect.progress * Math.PI); this.context.strokeStyle = color; this.context.lineWidth = 11 * scale; this.context.beginPath(); this.context.ellipse(end.x, end.y - 155 * scale, 165 * scale, 245 * scale, 0, Math.PI, Math.PI * 2); this.context.stroke();
    for (let ring = 1; ring < 4; ring += 1) { this.context.globalAlpha *= .72; this.context.beginPath(); this.context.arc(end.x, end.y - 155 * scale, ring * 48 * scale, 0, Math.PI * 2); this.context.stroke(); }
  }

  private drawHazard(end: Point, effect: ProductionScene['effect'], color: string, scale: number) {
    this.context.fillStyle = color; this.context.globalAlpha = Math.sin(effect.progress * Math.PI);
    for (let index = -3; index <= 3; index += 1) { const x = end.x + index * 53 * scale; this.context.beginPath(); this.context.moveTo(x, end.y); this.context.lineTo(x + 18 * scale, end.y - (65 + Math.abs(index) * 10) * scale); this.context.lineTo(x + 38 * scale, end.y); this.context.fill(); }
  }
}

function resolve(scene: ProductionScene): Resolved {
  const style = scene.style;
  return {
    style,
    display: fontFamily(style, 'display'),
    body: fontFamily(style, 'body'),
    mono: fontFamily(style, 'mono'),
    scale: style.typography.scale,
    upper: style.typography.uppercase,
    outline: style.typography.outline,
    shadow: style.typography.shadow,
    tracking: style.typography.letter_spacing,
    weight: style.typography.display_weight,
    effect: intensityScale(style.effect.intensity),
    camera: cameraScale(style.effect.camera),
    idle: idleScale(style.effect.idle_motion),
    accent: style.stage.accent
  };
}

function combatantPositions(scene: ProductionScene, width: number, height: number): Record<'p1' | 'p2', Point> {
  return scene.vertical ? { p1: { x: width * .36, y: height * .69 }, p2: { x: width * .67, y: height * .43 } } : { p1: { x: width * .29, y: height * .76 }, p2: { x: width * .71, y: height * .63 } };
}

function cameraOffset(scene: ProductionScene, scale: number, strength: number) {
  const impact = impactEnvelope(scene.effect.impactProgress) * strength;
  const quake = isGroundMove(scene.effect.moveId) && scene.effect.attack
    ? Math.sin(scene.effect.progress * Math.PI * 7) * Math.sin(scene.effect.progress * Math.PI) * strength
    : 0;
  if (impact <= 0 && quake === 0) return { x: 0, y: 0 };
  return {
    x: Math.sin(scene.effect.seed + scene.effect.impactProgress * 97) * 20 * scale * impact
      + Math.sin(scene.effect.seed * .0001 + scene.effect.progress * 37) * 9 * scale * quake,
    y: Math.cos(scene.effect.seed + scene.effect.impactProgress * 79) * 13 * scale * impact
      + Math.cos(scene.effect.seed * .00013 + scene.effect.progress * 43) * 6 * scale * quake
  };
}
function anticipationLunge(progress: number): number {
  if (progress < .16) return -easeInOut(progress / .16) * .16;
  if (progress < .58) return -0.16 + easeOut((progress - .16) / .42) * 1.16;
  return Math.max(0, 1 - (progress - .58) / .42);
}
function impactEnvelope(progress: number): number {
  if (progress <= 0 || progress >= 1) return 0;
  if (progress < .16) return easeOut(progress / .16);
  if (progress < .34) return 1;
  return 1 - easeInOut((progress - .34) / .66);
}
function slashRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, cut: number, reverse = false) {
  context.beginPath();
  if (reverse) { context.moveTo(x, y); context.lineTo(x + width - cut, y); context.lineTo(x + width, y + height); context.lineTo(x + cut, y + height); }
  else { context.moveTo(x + cut, y); context.lineTo(x + width, y); context.lineTo(x + width - cut, y + height); context.lineTo(x, y + height); }
  context.closePath();
}
function roundedRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  const r = Math.min(radius, width / 2, height / 2); context.beginPath(); context.moveTo(x + r, y); context.arcTo(x + width, y, x + width, y + height, r); context.arcTo(x + width, y + height, x, y + height, r); context.arcTo(x, y + height, x, y, r); context.arcTo(x, y, x + width, y, r); context.closePath();
}
function wrap(context: CanvasRenderingContext2D, text: string, maxWidth: number, font: string): string[] {
  context.font = font; const lines: string[] = []; let line = '';
  for (const word of text.split(/\s+/)) { const candidate = `${line} ${word}`.trim(); if (line && context.measureText(candidate).width > maxWidth) { lines.push(line); line = word; } else line = candidate; }
  if (line) lines.push(line); return lines;
}
function readableStatus(value: string): string { return ({ BRN: 'BURN', PAR: 'PAR', PSN: 'PSN', TOX: 'TOXIC', SLP: 'SLEEP', FRZ: 'FRZ' } as Record<string, string>)[value.toUpperCase()] || value.toUpperCase(); }
function pokemonTypeColor(types: string[] | undefined): string { return TYPE_COLORS[(types?.[0]?.toLowerCase() || 'normal') as PokemonType] || TYPE_COLORS.normal; }
function statusColor(status: string): string { return ({ BRN: '#ff8055', PAR: '#f6d34c', PSN: '#c979e8', TOX: '#9d59c8', SLP: '#9ba8b6', FRZ: '#7ee8f0' } as Record<string, string>)[status] || '#d9d7ca'; }

function categoryLabel(archetype: ProductionScene['effect']['archetype']): string {
  if (archetype === 'contact') return 'PHYSICAL';
  if (archetype === 'beam' || archetype === 'projectile') return 'SPECIAL';
  if (archetype === 'status' || archetype === 'buff' || archetype === 'debuff') return 'STATUS';
  if (archetype === 'heal') return 'RECOVERY';
  return archetype.toUpperCase();
}

function isGroundMove(moveId: string | null): boolean {
  return moveId === 'earthquake' || moveId === 'earthpower' || moveId === 'magnitude' || moveId === 'bulldoze';
}

function clamp(value: number): number { return Math.max(0, Math.min(1, value)); }
function easeOut(value: number): number { return 1 - Math.pow(1 - value, 3); }
function easeInOut(value: number): number { return value * value * (3 - 2 * value); }
function hash(value: number): number { const x = Math.sin(value * 12.9898) * 43758.5453; return x - Math.floor(x); }
