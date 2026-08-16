# Deterministic native offline renderer

Normal offline production uses a native Canvas compositor, not one browser screenshot per
output frame:

```text
ProductionTimeline -> RenderPlan -> ProductionFrameState(t) -> ProductionScene
  -> Canvas2D -> VideoFrame(timestamp, duration) -> WebCodecs
  -> H.264 Annex-B (or VP9 IVF fallback) -> FFmpeg MP4/AAC -> FFprobe -> atomic output
```

`RenderPlan` retains the preset's exact constant frame rate and absolute clock. It marks cue
boundaries and animated spans for a fresh scene/raster. Static spans reuse the existing Canvas
pixels while still sending timestamped CFR `VideoFrame`s to the encoder. Frame count remains
`ceil(duration_ms * fps / 1000)`; frame time is always `index * 1000 / fps`.

`ProductionFrameState(t)` reduces only persisted event sequences whose visual cue has begun.
The compositor delays authoritative HP, status, and faint state until the deterministic impact
point, so projectile travel cannot reveal target damage early. Winner, future moves,
commentary, hidden teams, and later series data remain outside the current frame.

All attack motion, particles, field layers, camera movement, shake, captions, intros, and result
cards are pure functions of logical production time and stable cue/event seeds. `performance.now()`
is used only for profiling. Offline sprites request `animated=false`; installed local PNGs are
decoded on demand and cached. A procedural placeholder is deterministic when media is absent.
No copyrighted sprite, VFX, background, music, or sound-pack file is bundled.

## Codec and transport

The renderer calls `VideoEncoder.isConfigSupported()` for H.264 Annex-B first and VP9 second.
Capability probing also encodes a real synthetic frame: advertising a codec is not sufficient.
H.264 streams directly into FFmpeg's MP4 container path. If H.264 is unavailable but VP9 is
supported, chunks receive an IVF frame envelope and FFmpeg converts them with the selected
local H.264 encoder.

If Chromium exposes no working WebCodecs encoder, the same compositor uses bounded Canvas RGBA
readback into a direct `libx264` FFmpeg pipe. Static RenderPlan holds cross the binding once and
are expanded at the pipe, while animated states transfer once per unique raster. This is slower
than working WebCodecs but remains deterministic and never invokes `page.screenshot()`. No
automatic fallback to screenshots occurs.

Encoded chunks cross one bounded Playwright binding in batches. The browser monitors
`encodeQueueSize`, flushes at a fixed high-water mark, and waits for each transfer. The backend
validates payload shape/size, preserves VP9 frame boundaries, and never buffers a full video in
memory. Cancellation is checked every 30 frames; incomplete streams and containers are removed.

The old `LegacyScreenshotRendererExporter` remains available only through
`render_engine=legacy` in the advanced UI/API/CLI. It is never the default and is never selected
automatically after a native failure.

## Output and audio

Voice clips and operator-installed music come from the validated production cache with fixed cue
offsets. Generic SFX remain locally synthesized. Voice intervals apply the production profile's
ducking gain before AAC mux. Captions are burned into Canvas frames and retained as an SRT
sidecar. FFprobe verifies resolution, duration, stream presence, and final H.264 MP4 output
before atomic publication.

Capabilities expose native compositor readiness, WebCodecs, H.264, VP9, raw-frame fallback,
legacy availability,
FFmpeg, FFprobe, Chromium, and Playwright independently. HTTP renderer origins inside Compose
are explicitly treated as secure for that configured local origin only.

With the optional Compose renderer profile, the renderer worker publishes a capability heartbeat
to the shared video volume every 10 seconds. The API accepts it for at most 30 seconds, so a
stopped or stale renderer cannot leave native preflight falsely available.

Host setup and benchmark:

```bash
.venv/bin/pip install -e './backend[renderer]'
# Install a compatible Chrome/Chromium and FFmpeg through the operating system.
.venv/bin/python -m koalabattle.video.cli capabilities
PYTHONPATH=backend .venv/bin/python scripts/benchmark_renderer.py PRODUCTION_ID \
  --preset youtube-1080p60 --encoder auto --render-engine native
```

The optional Docker `renderer` profile pins the runtime shape through `Dockerfile.renderer`.
See `docs/PERFORMANCE.md` for the measured screenshot comparison and native stage profile.
