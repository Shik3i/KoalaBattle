import type { PokemonType } from '../presentation/types.ts';
import type { ProductionScene, ProductionSceneSide } from './scene.ts';

const TYPE_COLORS: Record<PokemonType, string> = {
  normal: '#b8b6aa', fire: '#ff6a46', water: '#58a9ff', electric: '#ffd84d', grass: '#6fd27a',
  ice: '#78d9e4', fighting: '#e75c53', poison: '#bd72d9', ground: '#d6a85f', flying: '#91a7ef',
  psychic: '#ff6fa2', bug: '#a6c93e', rock: '#bca466', ghost: '#806fc4', dragon: '#7464ef',
  dark: '#74645f', steel: '#9daec4', fairy: '#ee9bd2'
};

export interface CompositorMetrics {
  assetLoads: number;
  assetFailures: number;
  cachedAssets: number;
}

export class ProductionCompositor {
  private context: CanvasRenderingContext2D;
  private images = new Map<string, Promise<ImageBitmap | null>>();
  private resolvedImages = new Map<string, ImageBitmap | null>();
  private assetLoads = 0;
  private assetFailures = 0;

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
    this.drawBackground(scene, width, height);
    this.drawArena(scene, width, height);
    if (scene.vertical) this.drawVertical(scene, width, height, scale);
    else this.drawLandscape(scene, width, height, scale);
    this.drawAtmosphere(scene, width, height, scale);
    this.drawEffect(scene, width, height, scale);
    this.context.restore();
    this.drawCaption(scene, width, height, scale);
    this.drawDirector(scene, width, height, scale);
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
        .then((response) => {
          if (!response.ok) throw new Error(`sprite ${response.status}`);
          return response.blob();
        })
        .then((blob) => createImageBitmap(blob))
        .catch(() => { this.assetFailures += 1; return null; })
        .then((image) => { this.resolvedImages.set(url, image); return image; });
      this.images.set(url, pending);
    }
    return pending;
  }

  private drawBackground(scene: ProductionScene, width: number, height: number) {
    const context = this.context;
    const gradient = context.createLinearGradient(0, 0, width, height);
    gradient.addColorStop(0, '#071d24');
    gradient.addColorStop(.5, '#102239');
    gradient.addColorStop(1, '#180d2c');
    context.fillStyle = gradient;
    context.fillRect(-20, -20, width + 40, height + 40);
    for (let index = 0; index < 42; index += 1) {
      const x = hash(scene.effect.seed + index * 31) * width;
      const y = hash(scene.effect.seed + index * 71) * height * .72;
      const pulse = .45 + .55 * Math.sin(scene.timeMs / 900 + index);
      context.fillStyle = `rgba(160,220,255,${.05 + pulse * .08})`;
      context.beginPath();
      context.arc(x, y, 1 + hash(index * 101) * 3, 0, Math.PI * 2);
      context.fill();
    }
    context.strokeStyle = 'rgba(115,225,211,.11)';
    context.lineWidth = 2;
    const horizon = height * .62;
    for (let index = -8; index <= 8; index += 1) {
      context.beginPath();
      context.moveTo(width / 2, horizon);
      context.lineTo(width / 2 + index * width * .13, height);
      context.stroke();
    }
    for (let row = 0; row < 9; row += 1) {
      const y = horizon + (height - horizon) * Math.pow(row / 8, 1.8);
      context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
    }
  }

  private drawArena(scene: ProductionScene, width: number, height: number) {
    const context = this.context;
    const ground = context.createRadialGradient(width / 2, height * .66, 10, width / 2, height * .66, width * .55);
    ground.addColorStop(0, 'rgba(37,94,100,.5)');
    ground.addColorStop(.55, 'rgba(25,46,69,.35)');
    ground.addColorStop(1, 'rgba(5,10,22,0)');
    context.fillStyle = ground;
    context.fillRect(0, height * .25, width, height * .75);
    if (scene.fields.length) {
      context.fillStyle = 'rgba(113,239,207,.06)';
      context.fillRect(0, height * .53, width, height * .47);
    }
  }

  private drawLandscape(scene: ProductionScene, width: number, height: number, scale: number) {
    this.drawPlatform(width * .28, height * .76, width * .22, height * .075);
    this.drawPlatform(width * .73, height * .49, width * .18, height * .06);
    this.drawPokemon(scene, scene.p1, width * .28, height * .63, 330 * scale);
    this.drawPokemon(scene, scene.p2, width * .73, height * .46, 260 * scale);
    this.drawPlayerCard(scene.p1, 70 * scale, height - 235 * scale, 610 * scale, 155 * scale, false);
    this.drawPlayerCard(scene.p2, width - 680 * scale, 55 * scale, 610 * scale, 155 * scale, true);
    this.drawHeader(scene, width, 35 * scale, scale);
  }

  private drawVertical(scene: ProductionScene, width: number, height: number, scale: number) {
    this.drawHeader(scene, width, 45 * scale, scale);
    this.drawPlayerCard(scene.p2, 55 * scale, 220 * scale, width - 110 * scale, 170 * scale, true);
    this.drawPlatform(width * .5, height * .41, width * .34, height * .035);
    this.drawPokemon(scene, scene.p2, width * .5, height * .39, 330 * scale);
    this.drawPlatform(width * .5, height * .69, width * .39, height * .04);
    this.drawPokemon(scene, scene.p1, width * .5, height * .61, 380 * scale);
    this.drawPlayerCard(scene.p1, 55 * scale, height - 355 * scale, width - 110 * scale, 175 * scale, false);
  }

  private drawPlatform(x: number, y: number, rx: number, ry: number) {
    const gradient = this.context.createRadialGradient(x, y, 0, x, y, rx);
    gradient.addColorStop(0, 'rgba(119,245,215,.34)');
    gradient.addColorStop(.6, 'rgba(49,114,128,.22)');
    gradient.addColorStop(1, 'rgba(12,24,42,0)');
    this.context.fillStyle = gradient;
    this.context.beginPath(); this.context.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); this.context.fill();
  }

  private drawPokemon(scene: ProductionScene, side: ProductionSceneSide, x: number, y: number, size: number) {
    const context = this.context;
    const attack = scene.effect.actor === side.side ? easeOut(clamp(scene.effect.progress / .38)) : 0;
    const hit = scene.effect.target === side.side ? Math.sin(scene.effect.impactProgress * Math.PI) : 0;
    const direction = side.near ? 1 : -1;
    const lunge = attack * size * .12 * direction;
    const shake = hit * Math.sin(scene.effect.impactProgress * 54) * size * .035;
    const bob = Math.sin(scene.timeMs / 850 + (side.near ? 0 : 1.8)) * size * .012;
    const faint = scene.effect.kind === 'pokemon_fainted' && scene.effect.target === side.side
      ? easeInOut(scene.effect.progress)
      : 0;
    const appear = scene.effect.kind === 'pokemon_switched' && scene.effect.actor === side.side
      ? easeOut(scene.effect.progress)
      : 1;
    context.save();
    context.translate(x + lunge + shake, y + bob);
    context.globalAlpha = (1 - faint) * appear;
    context.scale(.72 + appear * .28, .72 + appear * .28);
    context.shadowColor = hit ? 'rgba(255,220,120,.9)' : 'rgba(0,0,0,.55)';
    context.shadowBlur = hit ? size * .12 : size * .045;
    const bitmap = side.spriteUrl ? this.resolvedImages.get(side.spriteUrl) : null;
    if (bitmap) context.drawImage(bitmap, -size / 2, -size, size, size);
    else this.drawPlaceholder(side, size);
    context.restore();
  }

  private drawPlaceholder(side: ProductionSceneSide, size: number) {
    const context = this.context;
    const gradient = context.createLinearGradient(0, -size, 0, 0);
    gradient.addColorStop(0, side.near ? '#80f0cc' : '#d095ff');
    gradient.addColorStop(1, side.near ? '#226b75' : '#583979');
    context.fillStyle = gradient;
    context.beginPath();
    context.ellipse(0, -size * .42, size * .31, size * .42, side.near ? -.2 : .2, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = 'rgba(255,255,255,.86)';
    context.beginPath(); context.arc(side.near ? size * .08 : -size * .08, -size * .56, size * .035, 0, Math.PI * 2); context.fill();
  }

  private drawPlayerCard(side: ProductionSceneSide, x: number, y: number, width: number, height: number, alignRight: boolean) {
    const context = this.context;
    roundedRect(context, x, y, width, height, height * .14);
    context.fillStyle = 'rgba(6,14,28,.88)'; context.fill();
    context.strokeStyle = side.near ? 'rgba(94,232,197,.58)' : 'rgba(192,123,255,.58)';
    context.lineWidth = Math.max(2, height * .018); context.stroke();
    const padding = height * .18;
    context.textAlign = alignRight ? 'right' : 'left';
    context.fillStyle = '#f6f8ff'; context.font = `800 ${height * .25}px system-ui`;
    context.fillText(side.displayName, alignRight ? x + width - padding : x + padding, y + height * .34);
    context.fillStyle = 'rgba(209,220,238,.68)'; context.font = `600 ${height * .115}px ui-monospace, monospace`;
    context.fillText(side.providerLabel, alignRight ? x + width - padding : x + padding, y + height * .54);
    const hp = clamp(side.active?.hp_fraction ?? 0);
    const barX = x + padding; const barY = y + height * .68; const barWidth = width - padding * 2; const barHeight = height * .13;
    roundedRect(context, barX, barY, barWidth, barHeight, barHeight / 2); context.fillStyle = 'rgba(0,0,0,.45)'; context.fill();
    if (hp > 0) {
      roundedRect(context, barX, barY, barWidth * hp, barHeight, barHeight / 2);
      context.fillStyle = hp > .5 ? '#63e3a7' : hp > .2 ? '#f6cf55' : '#ff6f79'; context.fill();
    }
    context.fillStyle = '#fff'; context.font = `800 ${height * .105}px ui-monospace, monospace`;
    context.textAlign = 'center'; context.fillText(`${Math.round(hp * 100)}%`, barX + barWidth / 2, barY + barHeight * .83);
    const tags = [
      side.active?.status ? readableStatus(side.active.status) : null,
      ...Object.entries(side.active?.boosts || {})
        .filter(([, value]) => value !== 0)
        .slice(0, 2)
        .map(([stat, value]) => `${stat.toUpperCase()} ${value > 0 ? '↑'.repeat(Math.min(3, value)) : '↓'.repeat(Math.min(3, -value))}`),
      ...side.sideConditions.slice(0, 2).map(readableCondition)
    ].filter((value): value is string => Boolean(value));
    context.textAlign = alignRight ? 'right' : 'left';
    context.font = `700 ${height * .085}px ui-monospace, monospace`;
    context.fillStyle = '#f6cf78';
    context.fillText(tags.join('  ·  '), alignRight ? x + width - padding : x + padding, y + height * .94, barWidth);
    context.textAlign = 'left';
  }

  private drawHeader(scene: ProductionScene, width: number, y: number, scale: number) {
    const context = this.context;
    context.textAlign = 'center';
    context.fillStyle = 'rgba(6,14,26,.74)';
    roundedRect(context, width / 2 - 210 * scale, y, 420 * scale, 82 * scale, 25 * scale); context.fill();
    context.fillStyle = '#83ead1'; context.font = `800 ${22 * scale}px ui-monospace, monospace`;
    context.fillText(`TURN ${scene.turn || '—'}  ·  ${scene.format.toUpperCase()}`, width / 2, y + 33 * scale);
    context.fillStyle = '#f3f6ff'; context.font = `800 ${28 * scale}px system-ui`;
    context.fillText(scene.effect.moveName || label(scene.effect.kind), width / 2, y + 66 * scale);
    context.textAlign = 'left';
  }

  private drawAtmosphere(scene: ProductionScene, width: number, height: number, scale: number) {
    const context = this.context;
    if (scene.weather.some((value) => value.toLowerCase().includes('rain'))) {
      context.strokeStyle = 'rgba(155,210,255,.22)'; context.lineWidth = Math.max(1, 2 * scale);
      for (let index = 0; index < 55; index += 1) {
        const x = ((hash(index * 61) * width + scene.timeMs * .22) % (width + 100)) - 50;
        const y = ((hash(index * 97) * height + scene.timeMs * .55) % height);
        context.beginPath(); context.moveTo(x, y); context.lineTo(x - 12 * scale, y + 28 * scale); context.stroke();
      }
    }
    if (scene.weather.length || scene.fields.length) {
      const color = scene.fields.length ? 'rgba(104,243,186,.08)' : 'rgba(118,184,255,.07)';
      context.fillStyle = color; context.fillRect(0, 0, width, height);
    }
  }

  private drawEffect(scene: ProductionScene, width: number, height: number, scale: number) {
    const effect = scene.effect;
    if (effect.progress <= 0 || effect.progress >= 1) return;
    const positions = scene.vertical
      ? { p1: { x: width * .5, y: height * .61 }, p2: { x: width * .5, y: height * .39 } }
      : { p1: { x: width * .28, y: height * .57 }, p2: { x: width * .73, y: height * .29 } };
    const fallbackTarget = effect.actor === 'p1' ? 'p2' : 'p1';
    const target = effect.target || fallbackTarget;
    const end = positions[target];
    const color = TYPE_COLORS[effect.type];
    const travel = clamp((effect.progress - .28) / .44);
    const context = this.context;
    context.save();
    context.globalCompositeOperation = 'lighter';
    if (effect.archetype === 'heal') {
      const lift = easeOut(effect.progress);
      for (let index = 0; index < 12; index += 1) {
        const x = end.x + (hash(effect.seed + index) - .5) * 170 * scale;
        const y = end.y - (35 + hash(index * 17) * 180) * scale * lift;
        context.fillStyle = `rgba(116,255,171,${Math.sin(effect.progress * Math.PI)})`;
        context.fillRect(x - 4 * scale, y - 18 * scale, 8 * scale, 36 * scale);
        context.fillRect(x - 18 * scale, y - 4 * scale, 36 * scale, 8 * scale);
      }
    } else if (effect.archetype === 'status' || effect.archetype === 'pulse' || effect.archetype === 'field') {
      context.strokeStyle = color; context.lineWidth = 8 * scale;
      const center = effect.archetype === 'field' ? { x: width / 2, y: height * .6 } : end;
      for (let ring = 0; ring < 3; ring += 1) {
        context.globalAlpha = (.9 - ring * .22) * Math.sin(effect.progress * Math.PI);
        context.beginPath();
        context.ellipse(center.x, center.y, (45 + ring * 55 + effect.progress * 110) * scale, (24 + ring * 28 + effect.progress * 55) * scale, 0, 0, Math.PI * 2);
        context.stroke();
      }
    } else if (effect.archetype === 'barrier') {
      context.strokeStyle = color; context.lineWidth = 10 * scale;
      context.globalAlpha = Math.sin(effect.progress * Math.PI);
      context.beginPath(); context.ellipse(end.x, end.y - 95 * scale, 125 * scale, 190 * scale, 0, 0, Math.PI * 2); context.stroke();
    } else if (effect.archetype === 'hazard') {
      context.fillStyle = color;
      context.globalAlpha = Math.sin(effect.progress * Math.PI);
      for (let index = -2; index <= 2; index += 1) {
        const x = end.x + index * 46 * scale;
        context.beginPath(); context.moveTo(x, end.y); context.lineTo(x + 18 * scale, end.y - (45 + Math.abs(index) * 8) * scale); context.lineTo(x + 34 * scale, end.y); context.fill();
      }
    } else if (!effect.actor) {
      const burst = Math.sin(effect.impactProgress * Math.PI);
      context.strokeStyle = color; context.lineWidth = 8 * scale; context.globalAlpha = burst;
      context.beginPath(); context.arc(end.x, end.y, 110 * scale * burst, 0, Math.PI * 2); context.stroke();
    } else {
      const start = positions[effect.actor];
      const missOffset = effect.kind === 'move_missed' ? (effect.actor === 'p1' ? 1 : -1) * 180 * scale : 0;
      const endpoint = { x: end.x + missOffset, y: end.y - (effect.kind === 'move_missed' ? 100 * scale : 0) };
      const x = start.x + (endpoint.x - start.x) * easeInOut(travel);
      const y = start.y + (endpoint.y - start.y) * easeInOut(travel) - Math.sin(travel * Math.PI) * 115 * scale;
      if (effect.archetype === 'contact') {
        context.strokeStyle = color; context.lineWidth = 14 * scale; context.lineCap = 'round';
        for (let index = -1; index <= 1; index += 1) {
          const offset = index * 28 * scale;
          context.beginPath(); context.moveTo(x - 80 * scale, y - 50 * scale + offset); context.lineTo(x + 80 * scale, y + 50 * scale + offset); context.stroke();
        }
      } else if (effect.archetype === 'beam') {
        const charge = clamp(effect.progress / .28);
        const beam = clamp((effect.progress - .22) / .5);
        const angle = Math.atan2(endpoint.y - start.y, endpoint.x - start.x);
        const length = Math.hypot(endpoint.x - start.x, endpoint.y - start.y) * easeOut(beam);
        context.fillStyle = color; context.globalAlpha = charge;
        context.beginPath(); context.arc(start.x, start.y, (15 + charge * 38) * scale, 0, Math.PI * 2); context.fill();
        context.strokeStyle = color; context.lineWidth = (7 + 17 * Math.sin(beam * Math.PI)) * scale; context.lineCap = 'round';
        context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(start.x + Math.cos(angle) * length, start.y + Math.sin(angle) * length); context.stroke();
      } else {
        const radius = (28 + 38 * Math.sin(travel * Math.PI)) * scale;
        const glow = context.createRadialGradient(x, y, 0, x, y, radius * 2.6);
        glow.addColorStop(0, '#fff'); glow.addColorStop(.18, color); glow.addColorStop(1, 'rgba(0,0,0,0)');
        context.fillStyle = glow; context.beginPath(); context.arc(x, y, radius * 2.6, 0, Math.PI * 2); context.fill();
        context.strokeStyle = color; context.lineWidth = 4 * scale;
        context.beginPath(); context.moveTo(start.x, start.y); context.quadraticCurveTo(width / 2, Math.min(start.y, end.y) - 170 * scale, x, y); context.stroke();
      }
    }
    if (effect.impactProgress > 0 && effect.kind !== 'move_missed' && effect.archetype !== 'heal') {
      const burst = Math.sin(effect.impactProgress * Math.PI);
      context.globalAlpha = burst;
      context.strokeStyle = '#fff'; context.lineWidth = 9 * scale;
      for (let index = 0; index < 12; index += 1) {
        const angle = index / 12 * Math.PI * 2 + hash(effect.seed + index) * .25;
        const inner = 30 * scale; const outer = (75 + hash(index) * 120) * scale * burst;
        context.beginPath(); context.moveTo(end.x + Math.cos(angle) * inner, end.y + Math.sin(angle) * inner); context.lineTo(end.x + Math.cos(angle) * outer, end.y + Math.sin(angle) * outer); context.stroke();
      }
    }
    context.restore();
  }

  private drawCaption(scene: ProductionScene, width: number, height: number, scale: number) {
    if (!scene.caption) return;
    const context = this.context;
    const maxWidth = Math.min(width * .84, 1320 * scale);
    const y = scene.vertical ? height * .76 : height * .72;
    const lines = wrap(context, scene.caption, maxWidth - 100 * scale, 44 * scale);
    const boxHeight = (lines.length * 54 + 55) * scale;
    roundedRect(context, (width - maxWidth) / 2, y - boxHeight / 2, maxWidth, boxHeight, 28 * scale);
    context.fillStyle = 'rgba(3,9,20,.92)'; context.fill();
    context.strokeStyle = scene.captionSide === 'p1' ? '#64e6ba' : '#c387ff'; context.lineWidth = 4 * scale; context.stroke();
    context.fillStyle = '#fff'; context.textAlign = 'center'; context.font = `700 ${44 * scale}px system-ui`;
    lines.forEach((line, index) => context.fillText(line, width / 2, y - (lines.length - 1) * 27 * scale + index * 54 * scale + 14 * scale));
    context.textAlign = 'left';
  }

  private drawDirector(scene: ProductionScene, width: number, height: number, scale: number) {
    if (!scene.director || !['match-intro', 'result', 'outro'].includes(scene.director.kind)) return;
    const elapsed = scene.timeMs - scene.director.start_ms;
    const progress = clamp(elapsed / Math.max(1, scene.director.duration_ms));
    const opacity = Math.min(1, progress * 6, (1 - progress) * 6);
    const context = this.context;
    context.save(); context.globalAlpha = opacity;
    context.fillStyle = 'rgba(2,7,16,.72)'; context.fillRect(0, 0, width, height);
    context.textAlign = 'center';
    context.fillStyle = '#7ce8ca'; context.font = `900 ${28 * scale}px ui-monospace, monospace`;
    context.fillText(scene.director.kind === 'match-intro' ? 'KOALABATTLE' : 'BATTLE COMPLETE', width / 2, height * .43);
    context.fillStyle = '#fff'; context.font = `900 ${78 * scale}px system-ui`;
    const players = scene.director.payload.players;
    const title = scene.director.kind === 'match-intro' && Array.isArray(players)
      ? players.join('  VS  ')
      : scene.winnerName ? `${scene.winnerName} wins` : 'Draw';
    context.fillText(title, width / 2, height * .53, width * .88);
    context.restore(); context.textAlign = 'left';
  }
}

function cameraOffset(scene: ProductionScene, scale: number) {
  const impact = Math.sin(scene.effect.impactProgress * Math.PI);
  if (impact <= 0) return { x: 0, y: 0 };
  return {
    x: Math.sin(scene.effect.seed + scene.effect.impactProgress * 91) * 16 * scale * impact,
    y: Math.cos(scene.effect.seed + scene.effect.impactProgress * 73) * 10 * scale * impact
  };
}

function roundedRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  const r = Math.min(radius, width / 2, height / 2);
  context.beginPath(); context.moveTo(x + r, y); context.arcTo(x + width, y, x + width, y + height, r); context.arcTo(x + width, y + height, x, y + height, r); context.arcTo(x, y + height, x, y, r); context.arcTo(x, y, x + width, y, r); context.closePath();
}

function wrap(context: CanvasRenderingContext2D, text: string, maxWidth: number, fontSize: number): string[] {
  context.font = `700 ${fontSize}px system-ui`;
  const lines: string[] = []; let line = '';
  for (const word of text.split(/\s+/)) {
    const candidate = `${line} ${word}`.trim();
    if (line && context.measureText(candidate).width > maxWidth) { lines.push(line); line = word; }
    else line = candidate;
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}

function label(value: string): string { return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function readableCondition(value: string): string { return value.replaceAll('_', ' ').replace(/^move: /i, ''); }
function readableStatus(value: string): string {
  return ({ brn: 'BURN', par: 'PARALYSIS', psn: 'POISON', tox: 'TOXIC', slp: 'SLEEP', frz: 'FREEZE' } as Record<string, string>)[value.toLowerCase()] || value.toUpperCase();
}
function clamp(value: number): number { return Math.max(0, Math.min(1, value)); }
function easeOut(value: number): number { return 1 - Math.pow(1 - value, 3); }
function easeInOut(value: number): number { return value * value * (3 - 2 * value); }
function hash(value: number): number { const x = Math.sin(value * 12.9898) * 43758.5453; return x - Math.floor(x); }
