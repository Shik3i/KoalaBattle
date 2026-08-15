# Deterministic offline renderer

The renderer samples explicit production time. It does not play at 10x and record the screen.

```text
frame index -> index * 1000 / FPS -> renderAt(t)
ProductionTimeline + safe stored events -> ProductionFrameState
same Svelte BattleRenderer + captions -> in-memory JPEG frames
MJPEG image2pipe -> FFmpeg H.264 -> deterministic audio mux -> FFprobe -> atomic MP4
```

`renderAt(t)` reduces only persisted event sequences whose visual cue begins at or before `t`.
This is the future-information boundary. The full archive may be loaded, but later winner,
moves, commentary, team reveal, and director cues never reach the current state. Tests cover
frame zero, attack, future caption, and victory boundaries.

Animations are paused at the current logical cue offset; CSS/browser wall time is irrelevant.
Frame mapping uses an absolute formula and `ceil(duration_ms * FPS / 1000)`, avoiding cumulative
drift and final-frame off-by-one errors. Vertical rendering selects the native 9:16 layout;
it does not crop landscape output.

Voice clips and operator-installed local music come from the validated Phase-6 cache with
deterministic start offsets. The same built-in generic SFX frequencies and levels used by the
browser are synthesized by FFmpeg. Voice intervals apply the ProductionProfile ducking gain
to music before the fixed-duration AAC mux. Disabled cues and per-cue custom-audio cache-key
overrides are consumed from the production layer. Missing optional media is silent; required
speech fails preflight. Caption segments are both burned into frames and written to an SRT
sidecar without regenerating commentary. No battle LLM, Showdown connection, remote sprite,
or paid speech call occurs.

Playwright runs headless and captures each frame into memory; JPEG frames stream directly to FFmpeg,
so no full image sequence fills disk. Browser requests are restricted to configured local
frontend/API origins. Playwright documents buffer screenshots and headless operation:
<https://playwright.dev/python/docs/screenshots>. FFprobe is the final machine-readable media
inspection boundary: <https://ffmpeg.org/ffprobe.html>.

Host setup:

```bash
.venv/bin/pip install -e './backend[renderer]'
# Install a compatible Chrome/Chromium and FFmpeg through the operating system.
.venv/bin/python -m koalabattle.video.cli capabilities
```

The optional Docker profile pins the runtime shape through `Dockerfile.renderer`.
