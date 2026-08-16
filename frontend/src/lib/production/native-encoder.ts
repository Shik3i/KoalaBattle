import type { MatchArchive, ProductionTimeline } from '../types.ts';
import { ProductionCompositor, type CompositorMetrics } from './compositor.ts';
import { createProductionFrameRenderer } from './frame-state.ts';
import { createRenderPlan } from './render-plan.ts';
import { createProductionScene } from './scene.ts';

export interface NativeRenderRequest {
  width: number;
  height: number;
  fps: number;
  bitrate: number;
  startMs: number;
  endMs: number;
  hardwareAcceleration: 'no-preference' | 'prefer-hardware' | 'prefer-software';
  assetApiBase: string;
  transport: 'webcodecs' | 'raw-rgba';
}

export interface NativeRenderMetrics {
  transport: 'canvas-webcodecs-stream' | 'canvas-raw-rgba-pipe';
  codec: string;
  codecPath: 'h264-annexb' | 'vp9-ivf' | 'raw-rgba';
  hardwareAcceleration: string;
  outputFrames: number;
  uniqueRenders: number;
  staticHeldFrames: number;
  animatedFrames: number;
  renderPlanSeconds: number;
  rasterSeconds: number;
  frameCreateSeconds: number;
  encoderWaitSeconds: number;
  transferSeconds: number;
  totalSeconds: number;
  speedRatio: number;
  encodedBytes: number;
  maxEncodeQueue: number;
  assetLoads: number;
  assetFailures: number;
  cachedAssets: number;
}

export async function renderNativeFrame(
  canvas: HTMLCanvasElement,
  match: MatchArchive,
  production: ProductionTimeline,
  request: { width: number; height: number; timeMs: number; assetApiBase: string }
): Promise<CompositorMetrics> {
  canvas.width = request.width;
  canvas.height = request.height;
  const compositor = new ProductionCompositor(canvas);
  const frame = createProductionFrameRenderer(match, production).renderAt(request.timeMs);
  await compositor.render(createProductionScene(frame, request.height > request.width, request.assetApiBase));
  return compositor.metrics();
}

interface EncodedPacket { codecPath: 'h264-annexb' | 'vp9-ivf'; timestamp: number; type: string; data: string; }
interface EncoderConfig { codec: string; width: number; height: number; framerate: number; bitrate: number; hardwareAcceleration: string; latencyMode: string; avc?: { format: string }; }
interface EncodedChunk { byteLength: number; timestamp: number; type: string; copyTo(destination: Uint8Array): void; }
interface VideoEncoderLike { encodeQueueSize: number; configure(config: EncoderConfig): void; encode(frame: VideoFrame, options?: { keyFrame?: boolean }): void; flush(): Promise<void>; close(): void; }
interface VideoEncoderConstructor {
  new(callbacks: { output(chunk: EncodedChunk): void; error(error: DOMException): void }): VideoEncoderLike;
  isConfigSupported(config: EncoderConfig): Promise<{ supported: boolean; config: EncoderConfig }>;
}

declare global {
  interface Window {
    __KOALABATTLE_WRITE_CHUNKS?: (packets: EncodedPacket[]) => Promise<void>;
    __KOALABATTLE_RENDER_PROGRESS?: (payload: { completed: number; total: number; speedRatio: number }) => Promise<void>;
    __KOALABATTLE_RENDER_CANCELLED?: () => Promise<boolean>;
    __KOALABATTLE_WRITE_RAW_FRAME?: (payload: { data: string; repeat: number }) => Promise<void>;
  }
}

export async function renderNativeProduction(
  canvas: HTMLCanvasElement,
  match: MatchArchive,
  production: ProductionTimeline,
  request: NativeRenderRequest
): Promise<NativeRenderMetrics> {
  if (request.transport === 'raw-rgba') {
    return renderRawProduction(canvas, match, production, request);
  }
  return renderWebCodecsProduction(canvas, match, production, request);
}

async function renderWebCodecsProduction(
  canvas: HTMLCanvasElement,
  match: MatchArchive,
  production: ProductionTimeline,
  request: NativeRenderRequest
): Promise<NativeRenderMetrics> {
  const Encoder = (globalThis as unknown as { VideoEncoder?: VideoEncoderConstructor }).VideoEncoder;
  if (!Encoder || typeof VideoFrame === 'undefined') throw new Error('WebCodecs VideoEncoder/VideoFrame is unavailable');
  if (!window.__KOALABATTLE_WRITE_CHUNKS) throw new Error('native renderer chunk transport is unavailable');
  canvas.width = request.width;
  canvas.height = request.height;
  const planStarted = performance.now();
  const plan = createRenderPlan(production, request.startMs, request.endMs, request.fps);
  const renderPlanSeconds = (performance.now() - planStarted) / 1000;
  const selected = await selectCodec(Encoder, request);
  const packets: EncodedPacket[] = [];
  let packetBytes = 0;
  let encodedBytes = 0;
  let maxEncodeQueue = 0;
  let transferSeconds = 0;
  let encoderError: Error | null = null;
  const encoder = new Encoder({
    output(chunk) {
      const bytes = new Uint8Array(chunk.byteLength);
      chunk.copyTo(bytes);
      packets.push({ codecPath: selected.path, timestamp: chunk.timestamp, type: chunk.type, data: base64(bytes) });
      packetBytes += bytes.byteLength;
      encodedBytes += bytes.byteLength;
    },
    error(error) { encoderError = new Error(String(error)); }
  });
  encoder.configure(selected.config);
  const compositor = new ProductionCompositor(canvas);
  const frameRenderer = createProductionFrameRenderer(match, production);
  const durationUs = Math.round(1_000_000 / request.fps);
  let rasterSeconds = 0;
  let frameCreateSeconds = 0;
  let encoderWaitSeconds = 0;
  let uniqueRenders = 0;
  let lastProgress = 0;
  const started = performance.now();

  const transfer = async () => {
    if (!packets.length) return;
    const batch = packets.splice(0, packets.length);
    packetBytes = 0;
    const transferStarted = performance.now();
    await window.__KOALABATTLE_WRITE_CHUNKS?.(batch);
    transferSeconds += (performance.now() - transferStarted) / 1000;
  };

  try {
    for (const instruction of plan.frames) {
      if (instruction.index % 30 === 0 && await window.__KOALABATTLE_RENDER_CANCELLED?.()) {
        throw new DOMException('Render cancelled', 'AbortError');
      }
      if (instruction.render) {
        const rasterStarted = performance.now();
        const frameState = frameRenderer.renderAt(instruction.logicalTimeMs);
        const scene = createProductionScene(frameState, request.height > request.width, request.assetApiBase);
        await compositor.render(scene);
        rasterSeconds += (performance.now() - rasterStarted) / 1000;
        uniqueRenders += 1;
      }
      const frameStarted = performance.now();
      const timestamp = Math.round(instruction.index * 1_000_000 / request.fps);
      const videoFrame = new VideoFrame(canvas, { timestamp, duration: durationUs });
      frameCreateSeconds += (performance.now() - frameStarted) / 1000;
      encoder.encode(videoFrame, { keyFrame: instruction.index % (request.fps * 2) === 0 });
      videoFrame.close();
      maxEncodeQueue = Math.max(maxEncodeQueue, encoder.encodeQueueSize);
      if (encoder.encodeQueueSize > 10 || packetBytes >= 768 * 1024) {
        const waitStarted = performance.now();
        await encoder.flush();
        encoderWaitSeconds += (performance.now() - waitStarted) / 1000;
        await transfer();
      }
      const now = performance.now();
      if (instruction.index === plan.frames.length - 1 || now - lastProgress >= 500) {
        const completed = instruction.index + 1;
        await window.__KOALABATTLE_RENDER_PROGRESS?.({
          completed,
          total: plan.outputFrames,
          speedRatio: (completed / request.fps) / Math.max(.001, (now - started) / 1000)
        });
        lastProgress = now;
      }
    }
    const waitStarted = performance.now();
    await encoder.flush();
    encoderWaitSeconds += (performance.now() - waitStarted) / 1000;
    await transfer();
    if (encoderError) throw encoderError;
  } finally {
    encoder.close();
  }
  const totalSeconds = (performance.now() - started) / 1000;
  const assets = compositor.metrics();
  return {
    transport: 'canvas-webcodecs-stream',
    codec: selected.config.codec,
    codecPath: selected.path,
    hardwareAcceleration: selected.config.hardwareAcceleration,
    outputFrames: plan.outputFrames,
    uniqueRenders,
    staticHeldFrames: plan.outputFrames - uniqueRenders,
    animatedFrames: plan.plannedAnimatedFrames,
    renderPlanSeconds,
    rasterSeconds,
    frameCreateSeconds,
    encoderWaitSeconds,
    transferSeconds,
    totalSeconds,
    speedRatio: (plan.outputFrames / request.fps) / Math.max(.000001, totalSeconds),
    encodedBytes,
    maxEncodeQueue,
    ...assets
  };
}

async function renderRawProduction(
  canvas: HTMLCanvasElement,
  match: MatchArchive,
  production: ProductionTimeline,
  request: NativeRenderRequest
): Promise<NativeRenderMetrics> {
  if (!window.__KOALABATTLE_WRITE_RAW_FRAME) throw new Error('native raw-frame transport is unavailable');
  canvas.width = request.width;
  canvas.height = request.height;
  const planStarted = performance.now();
  const plan = createRenderPlan(production, request.startMs, request.endMs, request.fps);
  const renderPlanSeconds = (performance.now() - planStarted) / 1000;
  const compositor = new ProductionCompositor(canvas);
  const frameRenderer = createProductionFrameRenderer(match, production);
  const context = canvas.getContext('2d', {alpha: false});
  if (!context) throw new Error('Canvas 2D raw-frame readback is unavailable');
  let rasterSeconds = 0;
  let frameCreateSeconds = 0;
  let transferSeconds = 0;
  let uniqueRenders = 0;
  let transferredBytes = 0;
  const started = performance.now();
  let index = 0;
  while (index < plan.frames.length) {
    const instruction = plan.frames[index];
    if (await window.__KOALABATTLE_RENDER_CANCELLED?.()) {
      throw new DOMException('Render cancelled', 'AbortError');
    }
    const rasterStarted = performance.now();
    const frameState = frameRenderer.renderAt(instruction.logicalTimeMs);
    const scene = createProductionScene(frameState, request.height > request.width, request.assetApiBase);
    await compositor.render(scene);
    rasterSeconds += (performance.now() - rasterStarted) / 1000;
    uniqueRenders += 1;
    let repeat = 1;
    while (index + repeat < plan.frames.length && !plan.frames[index + repeat].render) repeat += 1;
    const frameStarted = performance.now();
    const pixels = context.getImageData(0, 0, request.width, request.height).data;
    const data = base64(pixels);
    frameCreateSeconds += (performance.now() - frameStarted) / 1000;
    const transferStarted = performance.now();
    await window.__KOALABATTLE_WRITE_RAW_FRAME({data, repeat});
    transferSeconds += (performance.now() - transferStarted) / 1000;
    transferredBytes += pixels.byteLength;
    index += repeat;
    await window.__KOALABATTLE_RENDER_PROGRESS?.({
      completed: index,
      total: plan.outputFrames,
      speedRatio: (index / request.fps) / Math.max(.001, (performance.now() - started) / 1000)
    });
  }
  const totalSeconds = (performance.now() - started) / 1000;
  const assets = compositor.metrics();
  return {
    transport: 'canvas-raw-rgba-pipe',
    codec: 'raw-rgba',
    codecPath: 'raw-rgba',
    hardwareAcceleration: 'prefer-software',
    outputFrames: plan.outputFrames,
    uniqueRenders,
    staticHeldFrames: plan.outputFrames - uniqueRenders,
    animatedFrames: plan.plannedAnimatedFrames,
    renderPlanSeconds,
    rasterSeconds,
    frameCreateSeconds,
    encoderWaitSeconds: 0,
    transferSeconds,
    totalSeconds,
    speedRatio: (plan.outputFrames / request.fps) / Math.max(.000001, totalSeconds),
    encodedBytes: transferredBytes,
    maxEncodeQueue: 0,
    ...assets
  };
}

async function selectCodec(Encoder: VideoEncoderConstructor, request: NativeRenderRequest) {
  const common = {
    width: request.width,
    height: request.height,
    framerate: request.fps,
    bitrate: request.bitrate,
    hardwareAcceleration: request.hardwareAcceleration,
    latencyMode: 'quality'
  };
  const h264: EncoderConfig = { ...common, codec: 'avc1.64002a', avc: { format: 'annexb' } };
  const supportedH264 = await Encoder.isConfigSupported(h264);
  if (supportedH264.supported) return { config: supportedH264.config, path: 'h264-annexb' as const };
  const vp9: EncoderConfig = { ...common, codec: 'vp09.00.10.08' };
  const supportedVp9 = await Encoder.isConfigSupported(vp9);
  if (supportedVp9.supported) return { config: supportedVp9.config, path: 'vp9-ivf' as const };
  throw new Error('WebCodecs has no supported H.264 or VP9 encoder for this preset');
}

function base64(bytes: Uint8Array | Uint8ClampedArray): string {
  let result = '';
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    result += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(result);
}
