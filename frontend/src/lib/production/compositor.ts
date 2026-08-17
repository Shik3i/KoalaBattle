import type { PokemonType } from '../presentation/types.ts';
import { isKnockedOut } from './scene.ts';
import type { ProductionScene, ProductionSceneSide } from './scene.ts';

const TYPE_COLORS: Record<PokemonType, string> = {
  normal: '#d9d7ca', fire: '#ff633f', water: '#3cc8ff', electric: '#ffe148', grass: '#79f05d',
  ice: '#82f4f1', fighting: '#ff714f', poison: '#de64e8', ground: '#e3a44d', flying: '#8ec7ff',
  psychic: '#ff5bac', bug: '#b9e744', rock: '#cfb56f', ghost: '#a17cff', dragon: '#766dff',
  dark: '#8a7772', steel: '#b5cbd6', fairy: '#ff96d2'
};
const P1 = '#6fffa8';
const P2 = '#e36fff';

export interface CompositorMetrics { assetLoads: number; assetFailures: number; cachedAssets: number }
interface Point { x: number; y: number }

export class ProductionCompositor {
  private context: CanvasRenderingContext2D;
  private images = new Map<string, Promise<ImageBitmap | null>>();
  private resolvedImages = new Map<string, ImageBitmap | null>();
  private assetLoads = 0;
  private assetFailures = 0;
  /**
   * The arena itself does not change between frames, but redrawing its gradients, ridges and
   * perspective grid dominated per-frame cost. Painting it once per distinct look lets every
   * frame be re-rendered cheaply, which is what allows the Pokemon to keep breathing instead
   * of being frozen by the frame-hold optimisation.
   */
  private worldCache: HTMLCanvasElement | OffscreenCanvas | null = null;
  private worldKey = '';

  constructor(private canvas: HTMLCanvasElement) {
    const context = canvas.getContext('2d', { alpha: false, desynchronized: true });
    if (!context) throw new Error('Canvas 2D compositor is unavailable');
    this.context = context;
  }

  async render(scene: ProductionScene): Promise<void> {
    await Promise.all([this.load(scene.p1.spriteUrl), this.load(scene.p2.spriteUrl)]);
    const { width, height } = this.canvas;
    const scale = Math.min(width / (scene.vertical ? 1080 : 1920), height / (scene.vertical ? 1920 : 1080));
    const camera = cameraOffset(scene, scale);
    this.context.save();
    this.context.translate(camera.x, camera.y);
    this.paintWorld(scene, width, height, scale);
    this.drawCombatants(scene, width, height, scale);
    this.drawEffect(scene, width, height, scale);
    this.context.restore();
    this.drawHud(scene, width, height, scale);
    this.drawCommentary(scene, width, height, scale);
    this.drawCaption(scene, width, height, scale);
    this.drawDirector(scene, width, height, scale);
    this.drawFrame(width, height, scale);
  }

  metrics(): CompositorMetrics {
    return { assetLoads: this.assetLoads, assetFailures: this.assetFailures, cachedAssets: this.images.size };
  }

  private async load(url: string | null): Promise<ImageBitmap | null> {
    if (!url) return null;
    let pending = this.images.get(url);
    if (!pending) {
      this.assetLoads += 1;
      pending = fetch(url, { credentials: 'omit', cache: 'force-cache' })
        .then((response) => { if (!response.ok) throw new Error(`sprite ${response.status}`); return response.blob(); })
        .then((blob) => createImageBitmap(blob))
        .catch(() => { this.assetFailures += 1; return null; })
        .then((image) => { this.resolvedImages.set(url, image); return image; });
      this.images.set(url, pending);
    }
    return pending;
  }

  /** Blit the cached arena, rebuilding it only when its appearance actually changes. */
  private paintWorld(scene: ProductionScene, width: number, height: number, scale: number) {
    // Weather is time-varying, so it stays outside the cache and is drawn per frame.
    const key = [width, height, scene.vertical, scene.effect.seed, scene.fields.join()].join('|');
    if (!this.worldCache || this.worldKey !== key) {
      const surface =
        typeof OffscreenCanvas === 'function'
          ? new OffscreenCanvas(width, height)
          : Object.assign(document.createElement('canvas'), { width, height });
      const surfaceContext = surface.getContext('2d') as CanvasRenderingContext2D | null;
      if (!surfaceContext) {
        this.drawWorld(this.context, scene, width, height, scale);
        return;
      }
      this.drawWorld(surfaceContext, scene, width, height, scale);
      this.worldCache = surface;
      this.worldKey = key;
    }
    this.context.drawImage(this.worldCache as CanvasImageSource, 0, 0);
    this.drawAtmosphere(scene, width, height, scale);
  }

  private drawWorld(
    context: CanvasRenderingContext2D,
    scene: ProductionScene,
    width: number,
    height: number,
    scale: number
  ) {
    const sky = context.createLinearGradient(0, 0, width, height);
    sky.addColorStop(0, '#07191c'); sky.addColorStop(.43, '#0c2730'); sky.addColorStop(.7, '#17202e'); sky.addColorStop(1, '#080a10');
    context.fillStyle = sky; context.fillRect(-40, -40, width + 80, height + 80);
    const sunX = scene.vertical ? width * .72 : width * .58;
    const glow = context.createRadialGradient(sunX, height * .22, 0, sunX, height * .22, width * .38);
    glow.addColorStop(0, 'rgba(129,255,183,.24)'); glow.addColorStop(.35, 'rgba(43,193,186,.11)'); glow.addColorStop(1, 'rgba(0,0,0,0)');
    context.fillStyle = glow; context.fillRect(0, 0, width, height);

    context.fillStyle = '#071113';
    context.beginPath(); context.moveTo(0, height * .18); context.lineTo(width * .12, height * .32); context.lineTo(width * .21, height * .24); context.lineTo(width * .32, height * .43); context.lineTo(width * .39, height * .35); context.lineTo(width * .48, height * .51); context.lineTo(0, height * .57); context.closePath(); context.fill();
    context.beginPath(); context.moveTo(width, height * .12); context.lineTo(width * .87, height * .27); context.lineTo(width * .8, height * .21); context.lineTo(width * .7, height * .42); context.lineTo(width * .61, height * .35); context.lineTo(width * .55, height * .53); context.lineTo(width, height * .58); context.closePath(); context.fill();
    context.strokeStyle = 'rgba(117,255,178,.2)'; context.lineWidth = Math.max(1, 2 * scale);
    for (let index = 0; index < 12; index += 1) {
      const x = hash(scene.effect.seed + index * 47) * width; const y = hash(scene.effect.seed + index * 83) * height * .48;
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + 18 * scale, y - 55 * scale); context.stroke();
    }
    const horizon = height * (scene.vertical ? .48 : .52);
    const floor = context.createLinearGradient(0, horizon, 0, height);
    floor.addColorStop(0, '#12282a'); floor.addColorStop(1, '#06080c'); context.fillStyle = floor;
    context.beginPath(); context.moveTo(0, horizon); context.lineTo(width, horizon); context.lineTo(width, height); context.lineTo(0, height); context.closePath(); context.fill();
    context.strokeStyle = 'rgba(112,255,174,.13)'; context.lineWidth = Math.max(1, 2 * scale);
    for (let index = -10; index <= 10; index += 1) { context.beginPath(); context.moveTo(width / 2, horizon); context.lineTo(width / 2 + index * width * .12, height); context.stroke(); }
    for (let row = 1; row < 10; row += 1) { const y = horizon + (height - horizon) * Math.pow(row / 9, 1.65); context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke(); }
    context.fillStyle = 'rgba(105,255,177,.035)'; context.beginPath(); context.ellipse(width / 2, height * .73, width * .44, height * .19, 0, 0, Math.PI * 2); context.fill();
  }

  private drawCombatants(scene: ProductionScene, width: number, height: number, scale: number) {
    const positions = combatantPositions(scene, width, height);
    const p1Size = (scene.vertical ? 455 : 475) * scale;
    const p2Size = (scene.vertical ? 425 : 445) * scale;
    this.drawPlatform(positions.p2.x, positions.p2.y, p2Size * .55, p2Size * .09, P2);
    this.drawPokemon(scene, scene.p2, positions.p2.x, positions.p2.y, p2Size);
    this.drawPlatform(positions.p1.x, positions.p1.y, p1Size * .58, p1Size * .095, P1);
    this.drawPokemon(scene, scene.p1, positions.p1.x, positions.p1.y, p1Size);
  }

  private drawPlatform(x: number, y: number, rx: number, ry: number, color: string) {
    const gradient = this.context.createRadialGradient(x, y, 0, x, y, rx);
    gradient.addColorStop(0, withAlpha(color, .34)); gradient.addColorStop(.48, withAlpha(color, .11)); gradient.addColorStop(1, 'rgba(0,0,0,0)');
    this.context.fillStyle = gradient; this.context.beginPath(); this.context.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); this.context.fill();
    this.context.strokeStyle = withAlpha(color, .34); this.context.lineWidth = Math.max(1, ry * .05); this.context.beginPath(); this.context.ellipse(x, y, rx * .73, ry * .47, 0, 0, Math.PI * 2); this.context.stroke();
  }

  private drawPokemon(scene: ProductionScene, side: ProductionSceneSide, x: number, y: number, size: number) {
    const context = this.context;
    const attacking = scene.effect.actor === side.side ? anticipationLunge(scene.effect.progress) : 0;
    const impact = scene.effect.target === side.side ? impactEnvelope(scene.effect.impactProgress) : 0;
    const direction = side.near ? 1 : -1;
    const lunge = attacking * size * .24 * direction;
    const recoil = impact * size * .1 * direction;
    const shake = impact * Math.sin(scene.effect.impactProgress * 72) * size * .025;
    const idle = Math.sin(scene.timeMs / 640 + (side.near ? 0 : 2.1));
    // A fainted Pokemon stays down until it is replaced. Driving this only from the faint
    // cue made it spring back to a healthy standing pose the moment that cue ended.
    const fainting =
      scene.effect.kind === 'pokemon_fainted' && scene.effect.target === side.side
        ? easeInOut(scene.effect.progress)
        : 0;
    const down = isKnockedOut(side);
    const faint = down ? Math.max(fainting, 1) : fainting;
    const appear = scene.effect.kind === 'pokemon_switched' && scene.effect.actor === side.side ? easeOut(scene.effect.progress) : 1;
    const bitmap = side.spriteUrl ? this.resolvedImages.get(side.spriteUrl) : null;
    const breath = idle * size * .014;
    context.save(); context.translate(x + lunge + recoil + shake, y - size * .012 - breath);
    // Squash on the inhale and stretch on the exhale so even a static PNG has weight.
    const squash = idle * .008;
    context.globalAlpha = (1 - faint) * appear; context.rotate((recoil / size) * .16 + faint * direction * .12); context.scale(.78 + appear * .22 + attacking * .06 + squash, .78 + appear * .22 - attacking * .025 - squash);
    context.shadowColor = impact ? '#fff4bd' : 'rgba(0,0,0,.75)'; context.shadowBlur = impact ? size * .15 : size * .055;
    if (attacking > .18 && bitmap) { context.save(); context.globalAlpha = attacking * .16; context.translate(-direction * size * .11, 0); context.drawImage(bitmap, -size / 2, -size, size, size); context.restore(); }
    if (bitmap) context.drawImage(bitmap, -size / 2, -size, size, size); else this.drawPlaceholder(side, size);
    context.restore();
  }

  private drawPlaceholder(side: ProductionSceneSide, size: number) {
    const color = side.near ? P1 : P2; const gradient = this.context.createLinearGradient(0, -size, 0, 0);
    gradient.addColorStop(0, withAlpha(color, .95)); gradient.addColorStop(1, withAlpha(color, .25)); this.context.fillStyle = gradient;
    this.context.beginPath(); this.context.ellipse(0, -size * .43, size * .31, size * .43, side.near ? -.18 : .18, 0, Math.PI * 2); this.context.fill();
    this.context.fillStyle = '#fff'; this.context.beginPath(); this.context.arc(side.near ? size * .08 : -size * .08, -size * .57, size * .035, 0, Math.PI * 2); this.context.fill();
  }

  private drawHud(scene: ProductionScene, width: number, height: number, scale: number) {
    if (scene.vertical) {
      this.drawHeader(scene, width, 38 * scale, scale);
      this.drawHealth(scene.p2, 46 * scale, 144 * scale, width - 92 * scale, 190 * scale, true, scale);
      this.drawHealth(scene.p1, 46 * scale, height - 370 * scale, width - 92 * scale, 190 * scale, false, scale);
    } else {
      this.drawHeader(scene, width, 30 * scale, scale);
      this.drawHealth(scene.p1, 55 * scale, 102 * scale, 750 * scale, 190 * scale, false, scale);
      this.drawHealth(scene.p2, width - 805 * scale, 102 * scale, 750 * scale, 190 * scale, true, scale);
    }
    this.drawMoveCallout(scene, width, height, scale);
  }

  private drawHeader(scene: ProductionScene, width: number, y: number, scale: number) {
    const context = this.context; context.save(); context.textAlign = 'center'; context.fillStyle = 'rgba(4,7,11,.9)';
    slashRect(context, width / 2 - 205 * scale, y, 410 * scale, 62 * scale, 18 * scale); context.fill(); context.strokeStyle = 'rgba(126,255,174,.58)'; context.lineWidth = 2 * scale; context.stroke();
    context.fillStyle = '#82ffae'; context.font = `900 ${18 * scale}px ui-monospace, monospace`; context.fillText('KOALABATTLE // VERDANT CIRCUIT', width / 2, y + 25 * scale);
    context.fillStyle = '#f5f7f5'; context.font = `900 ${23 * scale}px system-ui`; context.fillText(`TURN ${scene.turn || '—'}   ·   ${formatLabel(scene.format)}`, width / 2, y + 50 * scale); context.restore();
  }

  private drawHealth(side: ProductionSceneSide, x: number, y: number, width: number, height: number, alignRight: boolean, scale: number) {
    const context = this.context; const sideColor = side.near ? P1 : P2; const typeColor = pokemonTypeColor(side.active?.types); const pad = 28 * scale;
    context.save(); slashRect(context, x, y, width, height, 30 * scale, alignRight); context.fillStyle = 'rgba(5,8,13,.96)'; context.fill(); context.strokeStyle = 'rgba(238,245,241,.72)'; context.lineWidth = 3 * scale; context.stroke();
    context.fillStyle = typeColor; context.fillRect(alignRight ? x + width - 9 * scale : x, y + 8 * scale, 9 * scale, height - 16 * scale);
    context.textAlign = alignRight ? 'right' : 'left'; const anchor = alignRight ? x + width - pad : x + pad;
    context.fillStyle = withAlpha(sideColor, .92); context.font = `900 ${13 * scale}px ui-monospace, monospace`; context.fillText(`TRAINER ${side.displayName.toUpperCase()}  ·  ${side.providerLabel.toUpperCase()}`, anchor, y + 24 * scale, width - pad * 2);
    context.fillStyle = '#fff'; context.font = `950 ${39 * scale}px system-ui`; context.fillText((side.active?.name || 'AWAITING POKÉMON').toUpperCase(), anchor, y + 66 * scale, width * .66);
    const types = side.active?.types.slice(0, 2) || [];
    types.forEach((type, index) => this.drawTypeChip(type, alignRight ? x + pad + index * 88 * scale : x + width - pad - index * 88 * scale, y + 43 * scale, alignRight, scale));
    const hp = clamp(side.active?.hp_fraction ?? 0); const previous = clamp(side.previousHpFraction ?? hp); const barX = x + 74 * scale; const barY = y + 91 * scale; const readoutWidth = 132 * scale; const barWidth = width - 150 * scale - readoutWidth; const barHeight = 31 * scale;
    context.fillStyle = '#edf3ef'; context.font = `950 ${18 * scale}px ui-monospace, monospace`; context.textAlign = 'left'; context.fillText('HP', x + 28 * scale, barY + 23 * scale);
    context.fillStyle = '#161b20'; context.fillRect(barX, barY, barWidth, barHeight); context.strokeStyle = 'rgba(255,255,255,.72)'; context.lineWidth = 2 * scale; context.strokeRect(barX, barY, barWidth, barHeight);
    const fill = (fraction: number, fillStyle: string | CanvasGradient) => { const fillWidth = barWidth * fraction; context.fillStyle = fillStyle; context.fillRect(alignRight ? barX + barWidth - fillWidth : barX, barY, fillWidth, barHeight); };
    if (previous > hp) fill(previous, '#f5c64e');
    if (hp > 0) { const hpGradient = context.createLinearGradient(barX, 0, barX + barWidth, 0); const tone = hp > .5 ? '#55dc75' : hp > .2 ? '#f5c64e' : '#f04e57'; hpGradient.addColorStop(0, tone); hpGradient.addColorStop(1, hp > .5 ? '#b8f28d' : hp > .2 ? '#ffe683' : '#ff8b79'); fill(hp, hpGradient); }
    context.fillStyle = '#f8fbf9'; context.font = `950 ${18 * scale}px ui-monospace, monospace`; context.textAlign = 'right'; context.fillText(hpReadout(side), x + width - 27 * scale, barY + 23 * scale);
    const status = side.active?.status?.toUpperCase(); if (status) { context.fillStyle = statusColor(status); roundedRect(context, x + 28 * scale, y + 140 * scale, 58 * scale, 25 * scale, 5 * scale); context.fill(); context.fillStyle = '#111'; context.font = `950 ${13 * scale}px ui-monospace, monospace`; context.textAlign = 'center'; context.fillText(status, x + 57 * scale, y + 157 * scale); }
    const tags = side.sideConditions.slice(0, 2).map(readableCondition).join(' · '); context.fillStyle = '#dce6e0'; context.font = `800 ${12 * scale}px ui-monospace, monospace`; context.textAlign = alignRight ? 'left' : 'right'; context.fillText(tags, alignRight ? x + 102 * scale : x + width - 102 * scale, y + 157 * scale, width * .44);
    const members = side.team.length || 1; for (let index = 0; index < Math.min(6, members); index += 1) { const member = side.team[index]; const px = alignRight ? x + width - pad - index * 27 * scale : x + pad + index * 27 * scale; const py = y + 178 * scale; context.fillStyle = member?.fainted ? 'rgba(255,255,255,.12)' : index % 2 ? typeColor : sideColor; context.beginPath(); context.arc(px, py, 8 * scale, 0, Math.PI * 2); context.fill(); context.strokeStyle = member?.active ? '#fff' : 'rgba(255,255,255,.45)'; context.lineWidth = member?.active ? 3 * scale : 1.5 * scale; context.stroke(); }
    context.restore();
  }

  private drawTypeChip(type: string, x: number, y: number, alignRight: boolean, scale: number) {
    const context = this.context; const width = 78 * scale; const left = alignRight ? x : x - width; roundedRect(context, left, y, width, 25 * scale, 12 * scale); context.fillStyle = pokemonTypeColor([type]); context.fill(); context.fillStyle = '#07100b'; context.font = `950 ${11 * scale}px ui-monospace, monospace`; context.textAlign = 'center'; context.fillText(type.toUpperCase(), left + width / 2, y + 17 * scale);
  }

  private drawMoveCallout(scene: ProductionScene, width: number, height: number, scale: number) {
    if (!scene.effect.moveName || scene.effect.progress <= 0 || scene.effect.progress >= 1) return;
    const context = this.context; const color = TYPE_COLORS[scene.effect.type]; const alpha = Math.min(1, scene.effect.progress * 6, (1 - scene.effect.progress) * 5); const y = scene.vertical ? height * .48 : height * .275;
    context.save(); context.globalAlpha = alpha; context.textAlign = 'center'; context.fillStyle = 'rgba(4,6,10,.88)'; slashRect(context, width / 2 - 290 * scale, y - 42 * scale, 580 * scale, 86 * scale, 24 * scale); context.fill(); context.strokeStyle = color; context.lineWidth = 4 * scale; context.stroke();
    context.fillStyle = color; context.font = `900 ${16 * scale}px ui-monospace, monospace`; context.fillText(`${scene.effect.type.toUpperCase()} // ${scene.effect.archetype.toUpperCase()}`, width / 2, y - 10 * scale);
    context.fillStyle = '#fff'; context.font = `950 ${38 * scale}px system-ui`; context.fillText(scene.effect.moveName.toUpperCase(), width / 2, y + 29 * scale, 520 * scale); context.restore();
  }

  private drawAtmosphere(scene: ProductionScene, width: number, height: number, scale: number) {
    if (scene.weather.some((value) => value.toLowerCase().includes('rain'))) {
      this.context.strokeStyle = 'rgba(155,220,255,.28)'; this.context.lineWidth = Math.max(1, 2 * scale);
      for (let index = 0; index < 64; index += 1) { const x = ((hash(index * 61) * width + scene.timeMs * .24) % (width + 100)) - 50; const y = ((hash(index * 97) * height + scene.timeMs * .58) % height); this.context.beginPath(); this.context.moveTo(x, y); this.context.lineTo(x - 13 * scale, y + 31 * scale); this.context.stroke(); }
    }
    if (scene.weather.length || scene.fields.length) { this.context.fillStyle = scene.fields.length ? 'rgba(105,255,177,.065)' : 'rgba(112,190,255,.06)'; this.context.fillRect(0, 0, width, height); }
  }

  private drawEffect(scene: ProductionScene, width: number, height: number, scale: number) {
    const effect = scene.effect; if (effect.progress <= 0 || effect.progress >= 1) return;
    const positions = combatantPositions(scene, width, height); const targetSide = effect.target || (effect.actor === 'p1' ? 'p2' : 'p1'); const end = positions[targetSide]; const color = TYPE_COLORS[effect.type]; const context = this.context;
    context.save(); context.globalCompositeOperation = 'lighter';
    if (effect.archetype === 'heal') this.drawHeal(end, effect, color, scale);
    else if (['status', 'pulse', 'field', 'buff', 'debuff'].includes(effect.archetype)) this.drawPulse(effect.archetype === 'field' ? { x: width / 2, y: height * .7 } : end, effect, effect.archetype === 'debuff' ? '#ff5f72' : color, scale);
    else if (effect.archetype === 'barrier') this.drawBarrier(end, effect, color, scale);
    else if (effect.archetype === 'hazard') this.drawHazard(end, effect, color, scale);
    else if (effect.actor) this.drawAttack(positions[effect.actor], end, effect, color, width, scale);
    if (effect.impactProgress > 0 && effect.kind !== 'move_missed' && effect.archetype !== 'heal') {
      const burst = impactEnvelope(effect.impactProgress); context.globalAlpha = burst; context.strokeStyle = '#fff9d6'; context.lineWidth = 10 * scale; context.lineCap = 'round';
      for (let index = 0; index < 18; index += 1) { const angle = index / 18 * Math.PI * 2 + hash(effect.seed + index) * .22; const inner = 30 * scale; const outer = (90 + hash(index * 7) * 175) * scale * burst; context.beginPath(); context.moveTo(end.x + Math.cos(angle) * inner, end.y - 120 * scale + Math.sin(angle) * inner); context.lineTo(end.x + Math.cos(angle) * outer, end.y - 120 * scale + Math.sin(angle) * outer); context.stroke(); }
      context.fillStyle = '#fff'; context.globalAlpha = burst * .7; context.beginPath(); context.arc(end.x, end.y - 120 * scale, 75 * scale * burst, 0, Math.PI * 2); context.fill();
    }
    context.restore();
  }

  private drawAttack(start: Point, end: Point, effect: ProductionScene['effect'], color: string, width: number, scale: number) {
    const context = this.context; const travel = clamp((effect.progress - .18) / .56); const miss = effect.kind === 'move_missed' ? (effect.actor === 'p1' ? 1 : -1) * 200 * scale : 0;
    const target = { x: end.x + miss, y: end.y - 130 * scale }; const origin = { x: start.x, y: start.y - 165 * scale }; const x = origin.x + (target.x - origin.x) * easeInOut(travel); const y = origin.y + (target.y - origin.y) * easeInOut(travel) - Math.sin(travel * Math.PI) * 105 * scale;
    if (effect.archetype === 'contact') {
      context.strokeStyle = color; context.lineWidth = 16 * scale; context.lineCap = 'round';
      for (let index = -2; index <= 2; index += 1) { const spread = index * 34 * scale; context.globalAlpha = .18 + (2 - Math.abs(index)) * .2; context.beginPath(); context.moveTo(origin.x - 40 * scale, origin.y + spread); context.lineTo(target.x + 40 * scale, target.y + spread * .3); context.stroke(); }
    } else if (effect.archetype === 'beam') {
      const beam = clamp((effect.progress - .18) / .45); const angle = Math.atan2(target.y - origin.y, target.x - origin.x); const length = Math.hypot(target.x - origin.x, target.y - origin.y) * easeOut(beam);
      context.strokeStyle = withAlpha(color, .3); context.lineWidth = 62 * scale * Math.sin(beam * Math.PI); context.lineCap = 'round'; context.beginPath(); context.moveTo(origin.x, origin.y); context.lineTo(origin.x + Math.cos(angle) * length, origin.y + Math.sin(angle) * length); context.stroke();
      context.strokeStyle = '#fff'; context.lineWidth = 12 * scale * Math.sin(beam * Math.PI); context.beginPath(); context.moveTo(origin.x, origin.y); context.lineTo(origin.x + Math.cos(angle) * length, origin.y + Math.sin(angle) * length); context.stroke();
    } else {
      for (let trail = 4; trail >= 0; trail -= 1) { const tx = x - (x - origin.x) * trail * .05; const ty = y - (y - origin.y) * trail * .05; const radius = (34 + (4 - trail) * 8) * scale; const glow = context.createRadialGradient(tx, ty, 0, tx, ty, radius * 2.4); glow.addColorStop(0, trail === 0 ? '#fff' : withAlpha(color, .75)); glow.addColorStop(.28, withAlpha(color, .8)); glow.addColorStop(1, 'rgba(0,0,0,0)'); context.globalAlpha = 1 - trail * .16; context.fillStyle = glow; context.beginPath(); context.arc(tx, ty, radius * 2.4, 0, Math.PI * 2); context.fill(); }
      context.strokeStyle = color; context.lineWidth = 4 * scale; context.globalAlpha = .65; context.beginPath(); context.moveTo(origin.x, origin.y); context.quadraticCurveTo(width / 2, Math.min(origin.y, target.y) - 150 * scale, x, y); context.stroke();
    }
  }

  private drawHeal(end: Point, effect: ProductionScene['effect'], color: string, scale: number) {
    for (let index = 0; index < 18; index += 1) { const lift = easeOut(effect.progress); const x = end.x + (hash(effect.seed + index) - .5) * 250 * scale; const y = end.y - (40 + hash(index * 17) * 240) * scale * lift; this.context.fillStyle = withAlpha(color === TYPE_COLORS.normal ? P1 : color, Math.sin(effect.progress * Math.PI)); this.context.fillRect(x - 4 * scale, y - 20 * scale, 8 * scale, 40 * scale); this.context.fillRect(x - 20 * scale, y - 4 * scale, 40 * scale, 8 * scale); }
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

  private drawCommentary(scene: ProductionScene, width: number, height: number, scale: number) {
    if (!scene.commentary) return;
    const context = this.context; const color = scene.commentarySide === 'p2' ? P2 : P1; const boxWidth = Math.min(width * (scene.vertical ? .88 : .42), (scene.vertical ? 900 : 760) * scale);
    const x = scene.vertical ? (width - boxWidth) / 2 : scene.commentarySide === 'p2' ? width - boxWidth - 52 * scale : 52 * scale; const y = scene.vertical ? height * .705 : height * .655;
    context.save(); slashRect(context, x, y, boxWidth, 118 * scale, 22 * scale, scene.commentarySide === 'p2'); context.fillStyle = 'rgba(4,7,11,.91)'; context.fill(); context.strokeStyle = withAlpha(color, .62); context.lineWidth = 3 * scale; context.stroke();
    context.fillStyle = color; context.font = `900 ${14 * scale}px ui-monospace, monospace`; context.textAlign = 'left'; const side = scene.commentarySide === 'p2' ? scene.p2 : scene.p1; context.fillText(`${side.displayName.toUpperCase()} // FIGHTER INTENT`, x + 28 * scale, y + 27 * scale);
    // The caption already carries the spoken words; repeating them here is noise.
    const spoken = scene.caption && scene.commentary.startsWith(scene.caption.slice(0, 18));
    context.fillStyle = spoken ? withAlpha('#f5f7f5', .55) : '#f5f7f5';
    context.font = `750 ${22 * scale}px system-ui`;
    const lines = wrap(context, scene.commentary, boxWidth - 56 * scale, 22 * scale).slice(0, spoken ? 1 : 3);
    lines.forEach((line, index) => context.fillText(line, x + 28 * scale, y + (58 + index * 25) * scale));
    context.restore();
  }

  private drawCaption(scene: ProductionScene, width: number, height: number, scale: number) {
    if (!scene.caption) return;
    const context = this.context; const maxWidth = Math.min(width * .82, (scene.vertical ? 920 : 1180) * scale); const y = scene.vertical ? height * .947 : height * .875; const fontSize = scene.vertical ? 34 : 30;
    const lines = wrap(context, scene.caption, maxWidth - 86 * scale, fontSize * scale).slice(0, 2); const boxHeight = (lines.length * 38 + 28) * scale;
    context.save(); roundedRect(context, (width - maxWidth) / 2, y - boxHeight / 2, maxWidth, boxHeight, 12 * scale); context.fillStyle = 'rgba(0,0,0,.88)'; context.fill(); context.fillStyle = '#fff'; context.textAlign = 'center'; context.font = `850 ${fontSize * scale}px system-ui`; lines.forEach((line, index) => context.fillText(line, width / 2, y - (lines.length - 1) * 19 * scale + index * 38 * scale + 10 * scale)); context.restore();
  }

  private drawDirector(scene: ProductionScene, width: number, height: number, scale: number) {
    if (!scene.director || !['match-intro', 'team-reveal', 'result', 'outro', 'champion'].includes(scene.director.kind)) return;
    const elapsed = scene.timeMs - scene.director.start_ms; const progress = clamp(elapsed / Math.max(1, scene.director.duration_ms)); const opacity = Math.min(1, progress * 7, (1 - progress) * 7); const context = this.context; const result = ['result', 'outro', 'champion'].includes(scene.director.kind);
    context.save(); context.globalAlpha = opacity; context.fillStyle = 'rgba(2,4,8,.94)'; context.fillRect(0, 0, width, height);
    context.fillStyle = withAlpha(result ? '#ffd96a' : P1, .2); context.beginPath(); context.moveTo(0, 0); context.lineTo(width * .62, 0); context.lineTo(width * .38, height); context.lineTo(0, height); context.closePath(); context.fill();
    context.fillStyle = withAlpha(result ? '#ff984c' : P2, .18); context.beginPath(); context.moveTo(width * .62, 0); context.lineTo(width, 0); context.lineTo(width, height); context.lineTo(width * .38, height); context.closePath(); context.fill();
    for (let index = -2; index <= 2; index += 1) { context.strokeStyle = 'rgba(255,255,255,.08)'; context.lineWidth = 12 * scale; context.beginPath(); context.moveTo(width * .5 + index * 52 * scale, 0); context.lineTo(width * .32 + index * 52 * scale, height); context.stroke(); }
    context.textAlign = 'center'; context.fillStyle = result ? '#ffd96a' : '#82ffae'; context.font = `950 ${22 * scale}px ui-monospace, monospace`; context.fillText(result ? 'VERDANT CIRCUIT // FINAL' : 'KOALABATTLE // MAIN EVENT', width / 2, height * .34);
    context.fillStyle = '#fff'; context.font = `950 ${(scene.vertical ? 62 : 86) * scale}px system-ui`; const players = scene.director.payload.players; const title = !result && Array.isArray(players) ? players.join('  VS  ') : scene.winnerName ? `${scene.winnerName} WINS` : 'DRAW'; context.fillText(title.toUpperCase(), width / 2, height * .49, width * .9);
    context.fillStyle = result ? '#ffd96a' : '#fff'; context.font = `950 ${(scene.vertical ? 118 : 150) * scale}px system-ui`; context.fillText(result ? 'K.O.' : 'VS', width / 2, height * .66); context.restore();
  }

  private drawFrame(width: number, height: number, scale: number) {
    this.context.save(); this.context.strokeStyle = 'rgba(126,255,174,.58)'; this.context.lineWidth = 3 * scale; this.context.strokeRect(14 * scale, 14 * scale, width - 28 * scale, height - 28 * scale);
    this.context.fillStyle = '#7dffae'; this.context.fillRect(14 * scale, 14 * scale, 150 * scale, 6 * scale); this.context.fillRect(width - 164 * scale, height - 20 * scale, 150 * scale, 6 * scale); this.context.restore();
  }
}

function combatantPositions(scene: ProductionScene, width: number, height: number): Record<'p1' | 'p2', Point> {
  return scene.vertical ? { p1: { x: width * .36, y: height * .69 }, p2: { x: width * .67, y: height * .43 } } : { p1: { x: width * .29, y: height * .76 }, p2: { x: width * .71, y: height * .63 } };
}

function cameraOffset(scene: ProductionScene, scale: number) {
  const impact = impactEnvelope(scene.effect.impactProgress); if (impact <= 0) return { x: 0, y: 0 };
  return { x: Math.sin(scene.effect.seed + scene.effect.impactProgress * 97) * 20 * scale * impact, y: Math.cos(scene.effect.seed + scene.effect.impactProgress * 79) * 13 * scale * impact };
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
function wrap(context: CanvasRenderingContext2D, text: string, maxWidth: number, fontSize: number): string[] {
  context.font = `750 ${fontSize}px system-ui`; const lines: string[] = []; let line = '';
  for (const word of text.split(/\s+/)) { const candidate = `${line} ${word}`.trim(); if (line && context.measureText(candidate).width > maxWidth) { lines.push(line); line = word; } else line = candidate; }
  if (line) lines.push(line); return lines;
}
function formatLabel(value: string): string {
  const normalized = value.toLowerCase().replaceAll('_', '').replaceAll('-', '');
  const generation = normalized.match(/^gen(\d+)(.+)$/);
  if (!generation) return value.replaceAll('_', ' ').replaceAll('-', ' ').toUpperCase();
  const formats: Record<string, string> = {
    randombattle: 'RANDOM BATTLE', ou: 'OU', uu: 'UU', ru: 'RU', nu: 'NU', pu: 'PU',
    ubers: 'UBERS', doublesou: 'DOUBLES OU'
  };
  return `GEN ${generation[1]} · ${formats[generation[2]] || generation[2].toUpperCase()}`;
}
function readableCondition(value: string): string { return value.replaceAll('_', ' ').replace(/^move: /i, '').toUpperCase(); }
function readableStatus(value: string): string { return ({ brn: 'BURN', par: 'PARALYSIS', psn: 'POISON', tox: 'TOXIC', slp: 'SLEEP', frz: 'FREEZE' } as Record<string, string>)[value.toLowerCase()] || value.toUpperCase(); }
function pokemonTypeColor(types: string[] | undefined): string { return TYPE_COLORS[(types?.[0]?.toLowerCase() || 'normal') as PokemonType] || TYPE_COLORS.normal; }
function statusColor(status: string): string { return ({ BRN: '#ff8055', PAR: '#f6d34c', PSN: '#c979e8', TOX: '#9d59c8', SLP: '#9ba8b6', FRZ: '#7ee8f0' } as Record<string, string>)[status] || '#d9d7ca'; }
function hpReadout(side: ProductionSceneSide): string {
  const active = side.active;
  const hpFraction = active?.hp_fraction || 0;
  const currentHp = active?.current_hp;
  const maxHp = active?.max_hp;
  if (currentHp != null && maxHp && Math.abs(currentHp / maxHp - hpFraction) <= 0.01) return `${currentHp}/${maxHp}`;
  return `${Math.round(hpFraction * 100)}%`;
}
function withAlpha(hex: string, alpha: number): string {
  const value = hex.replace('#', ''); const full = value.length === 3 ? value.split('').map((item) => item + item).join('') : value;
  return `rgba(${Number.parseInt(full.slice(0, 2), 16)},${Number.parseInt(full.slice(2, 4), 16)},${Number.parseInt(full.slice(4, 6), 16)},${alpha})`;
}
function clamp(value: number): number { return Math.max(0, Math.min(1, value)); }
function easeOut(value: number): number { return 1 - Math.pow(1 - value, 3); }
function easeInOut(value: number): number { return value * value * (3 - 2 * value); }
function hash(value: number): number { const x = Math.sin(value * 12.9898) * 43758.5453; return x - Math.floor(x); }
