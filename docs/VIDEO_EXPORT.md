# Video export jobs

Battle, Production, and Export are separate records. A battle stores what happened; a
Production stores presentation cues/timing; a `VideoExportJob` stores one concrete renderer,
preset, output, metrics, diagnostics, and registered files. One match may retain many
productions and each production many exports.

## Jobs and presets

Lifecycle: `queued -> preparing -> rendering -> encoding -> finalizing -> completed`, or
`cancelled`/`failed`. Global concurrency is `KOALABATTLE_VIDEO_MAX_CONCURRENCY` (default 1).
Queue priority is bounded. An optional idempotency key prevents duplicate creation caused by
one retried request; deliberate rerenders receive new IDs.

Presets: YouTube 1080p60 and 1080p30, 1440p60, optional 4K60, Vertical 1080x1920 at
60 or 30 FPS, and Fast Preview 1280x720p30. Existing 60 FPS presets retain their meaning.
H.264/yuv420p is the compatible default. Auto prefers detected hardware H.264 on the host
(VideoToolbox, NVENC, QSV, then VAAPI) before software `libx264`; software remains explicitly
selectable for comparable benchmarks. Arbitrary encoder arguments are never accepted.

Pacing profiles are versioned independently: Full Replay, YouTube, Fast, and Shorts. They
define synthetic thinking time, transition gaps, result hold time, and commentary policy;
persisted provider latency remains untouched in the historical decision records. Query them
through `GET /api/video/pacing-profiles`.

Filesystem:

```text
data/videos/
  exports/  validated final MP4
  jobs/     bounded manifest, SRT, diagnostics
  temp/     incomplete per-job work
```

SQLite stores metadata, not video blobs. A completed job records codec, dimensions, FPS,
duration, render time, bytes, SHA-256, versions, and only relative registered paths. Encoder
success is not sufficient: FFprobe validation precedes atomic publication. The manifest also
records visual profile version, transport, page-worker count, stage timings, and measured
media/wall ratio.

## API

- `GET /api/video/presets`
- `GET /api/video/pacing-profiles`
- `GET /api/video/capabilities`
- `GET /api/productions/{id}/video-preflight?backend=offline|obs`
- `POST /api/video/jobs`
- `POST /api/video/jobs/batch` (1–100 structured requests)
- `GET /api/video/jobs?match_id=...`
- `GET /api/video/jobs/{id}`
- `POST /api/video/jobs/{id}/cancel`
- `POST /api/video/jobs/{id}/retry`
- `GET /api/video/jobs/{id}/download|captions|manifest`

Cancellation stops owned Chromium/FFmpeg or OBS recording and removes temp files. On restart,
active in-memory work becomes failed/interrupted and can be retried. Export failure never
updates match events, decisions, winner, or tournament results.

Offline preflight requires a finalized production, writable output, configured free disk,
FFmpeg/FFprobe, Playwright, Chromium, and required cached speech. It never makes paid TTS calls.
Use **Prepare free speech** explicitly when required clips are absent.
