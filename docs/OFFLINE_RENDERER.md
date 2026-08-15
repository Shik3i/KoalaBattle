# Deterministic offline renderer

The renderer samples explicit production time. It does not play at 10x and record the screen.

```text
frame index -> index * 1000 / FPS -> renderAt(t)
ProductionTimeline + safe stored events -> ProductionFrameState
same Svelte BattleRenderer + captions -> bounded parallel in-memory JPEG frames
MJPEG image2pipe -> FFmpeg H.264 -> deterministic audio mux -> FFprobe -> atomic MP4
```

`renderAt(t)` reduces only persisted event sequences whose visual cue begins at or before `t`.
This is the future-information boundary. The full archive may be loaded, but later winner,
moves, commentary, team reveal, and director cues never reach the current state. Tests cover
frame zero, attack, future caption, and victory boundaries.

Offline animation transforms, opacity, particles, projectiles, beams, shake, and transient
labels are calculated from the current logical cue progress. CSS/browser wall time is
irrelevant, and Playwright disables CSS animations during capture.
Frame mapping uses an absolute formula and `ceil(duration_ms * FPS / 1000)`, avoiding cumulative
drift and final-frame off-by-one errors. Legacy timelines with a zero stored duration derive
their effective end from the latest cue instead of freezing at frame zero. Vertical rendering selects the native 9:16 layout;
it does not crop landscape output.

Voice clips and operator-installed local music come from the validated Phase-6 cache with
deterministic start offsets. The same built-in generic SFX frequencies and levels used by the
browser are synthesized by FFmpeg. Voice intervals apply the ProductionProfile ducking gain
to music before the fixed-duration AAC mux. Disabled cues and per-cue custom-audio cache-key
overrides are consumed from the production layer. Missing optional media is silent; required
speech fails preflight. Caption segments are both burned into frames and written to an SRT
sidecar without regenerating commentary. No battle LLM, Showdown connection, remote sprite,
or paid speech call occurs.

Playwright runs headless with a bounded pool of preloaded pages in one browser context. A
small ordered batch is sampled concurrently; JPEG buffers then stream directly to FFmpeg
with awaited pipe backpressure, so no full image sequence fills disk. The default pool is
`KOALABATTLE_VIDEO_FRAME_WORKERS=4` and is bounded to 1–8. Browser requests are restricted
to configured local frontend/API origins. Cancellation stops the owned encoder/browser and
removes incomplete job files. Playwright documents buffer screenshots and headless operation:
<https://playwright.dev/python/docs/screenshots>. FFprobe is the final machine-readable media
inspection boundary: <https://ffmpeg.org/ffprobe.html>.

Host setup:

```bash
.venv/bin/pip install -e './backend[renderer]'
# Install a compatible Chrome/Chromium and FFmpeg through the operating system.
.venv/bin/python -m koalabattle.video.cli capabilities
PYTHONPATH=backend .venv/bin/python scripts/benchmark_renderer.py PRODUCTION_ID \
  --preset fast-preview --encoder software --workers 4
```

The optional Docker profile pins the runtime shape through `Dockerfile.renderer`.
