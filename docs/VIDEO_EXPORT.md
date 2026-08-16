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
H.264/yuv420p MP4 is the compatible final output. The default native engine feature-detects
WebCodecs H.264, then VP9 with a local FFmpeg H.264 conversion. Encoder selection maps only to
a bounded hardware preference; arbitrary codec arguments are never accepted.
An actual one-frame encode validates advertised WebCodecs support. If neither browser encoder
works, bounded Canvas RGBA frames feed local `libx264`; static holds are expanded in the pipe.

`render_engine=native` is the default. `render_engine=legacy` exposes the previous screenshot
pipeline for explicit debug/compatibility work only. Native failures never silently switch to
Legacy. OBS remains a separate realtime backend.

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
records visual profile version, codec path, output/unique/static/animated frame counts, asset
cache counts, encode-queue high-water mark, stage timings, and measured media/wall ratio.

## API

- `GET /api/video/presets`
- `GET /api/video/pacing-profiles`
- `GET /api/video/capabilities`
- `GET /api/productions/{id}/video-preflight?backend=offline|obs&render_engine=native|legacy`
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

Native preflight requires a finalized production, writable output, configured free disk,
FFmpeg/FFprobe, Playwright, Chromium, working WebCodecs H.264/VP9 or raw-frame `libx264`, and required cached
speech. It never makes paid TTS calls.
Use **Prepare free neural speech** explicitly when required clips are absent.

When Chromium runs in the optional external renderer container, the API reads its capability
heartbeat from the shared video volume. The renderer refreshes it every 10 seconds and the API
rejects heartbeats older than 30 seconds.
