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
a bounded hardware preference; arbitrary codec arguments are never accepted. An actual one-frame
encode validates advertised WebCodecs support. On Linux/container rendering, compressed MJPEG
keyframes feed local `libx264`; static holds are expanded in the pipe. Raw RGBA is the bounded
compatibility fallback.

`render_engine=native` is the default. `render_engine=legacy` exposes the previous screenshot
pipeline for explicit debug/compatibility work only. Native failures never silently switch to
Legacy. OBS remains a separate realtime backend.

Pacing profiles are versioned independently: Full Replay, YouTube, Fast, and Shorts. They
define deterministic minimum turn slots, the gap between turns, intro/result/outro holds, and
commentary policy; persisted provider latency remains untouched in the historical decision
records. Events within one turn share the same slot and do not receive synthetic gaps. Query
them through `GET /api/video/pacing-profiles`.

The YouTube defaults are 20,000 ms minimum per turn, 180 ms between turns, and
2,200/1,800/600 ms for intro/result/outro. A real speech artifact may extend a turn when its
duration is longer than the slot. This is the only intended timing extension.

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

## Review media

Visual review needs motion, not stills: choreography, pacing, HP interpolation and speech
timing cannot be judged from a screenshot. Two scripts produce a local review pack under the
ignored `data/review-pack/<name>/`:

```bash
# A battle whose public commentary reads like a real Manual Web Chat answer.
python3 scripts/drive_manual_match.py --format gen9randombattle --name "Review battle"

# Short MP4 clips plus their caption sidecars, exported through the normal pipeline.
python3 scripts/capture_review_clips.py --match <uuid> --output data/review-pack/<name>
```

`capture_review_clips.py` locates the interesting windows itself — the commentary that
introduces a landing move, the densest stretch of distinct action, and the result banner —
then exports each as a time range of a real production. Nothing is stitched from stills and
nothing bypasses the exporter, so a clip that looks wrong is evidence of a real production
problem. Stills pulled from those clips are the same pixels the reviewer sees in motion.

A third script renders the same recorded match through several Video Studio presentations,
including uploaded logos, an uploaded background and a watermark:

```bash
python3 scripts/capture_studio_pack.py --match <uuid> --output data/review-pack/<name>
```

For exact renderer regression checks, create one 16:9 and one 9:16 production from the same
archive. The first command accepts six deterministic local baselines; subsequent runs fail when
any intro, mid-battle or result frame changes:

```bash
python3 scripts/visual_regression.py --landscape <16:9-production-uuid> --vertical <9:16-production-uuid> --accept
python3 scripts/visual_regression.py --landscape <16:9-production-uuid> --vertical <9:16-production-uuid>
```

Captures remain in ignored `data/visual-regression/`; they can contain locally installed media
that must not enter the MIT repository.

Speech must be prepared *before* export and never rebuilt afterwards: `rebuild` regenerates
the timeline from the archive and drops synthesized voice cues. Preparation also re-times
the clock against the real audio, so **re-read the production after preparing** — a copy
held from before that call describes estimated timing, and a clip window computed from it
lands in the wrong place.

## Preflight

Preflight reports presentation readiness alongside the renderer:

```text
production        finalized
production_style  fighting v1.0
player_branding   p1 + p2 resolved
background        ready
fonts             curated local stacks
watermark         ready
sprites           local asset provider
speech            73/73 cached
renderer          native / webcodecs h264
disk              41231183872 bytes free
```

Custom media is optional presentation. A missing logo, background or font is reported as
`missing — falls back` with a warning, and the export still runs using the documented
fallback: the generated participant mark, the style's solid colour, and the built-in font
stack respectively. Nothing is silently substituted with an unrelated asset.

## Style snapshot

The export manifest records the presentation the video was rendered with — preset id and
version, stage, HUD, typography, callouts, commentary, captions, effects, intro, result,
watermark, per-player branding and the brand asset **ids** it referenced. Editing the saved
preset later therefore cannot make it impossible to determine how an older export looked.
The snapshot contains no binary media, no filesystem paths and no credentials.


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

Native preflight requires a finalized or prepared production, writable output, configured free
disk, FFmpeg/FFprobe, Playwright, Chromium, working WebCodecs H.264/VP9 or raw-frame `libx264`,
and required cached speech. Archived replay creation, preflight, and export automatically prepare
missing public Edge Neural speech with `allow_paid=false`, reusing valid cache entries and
regenerating only missing or corrupt artifacts. The default automatic path never selects a system
voice. Missing Edge cues are scheduled concurrently, bounded by
`KOALABATTLE_SPEECH_MAX_CONCURRENCY`. Internal agent progress/state and raw Showdown message
events do not become replay beats. The **Prepare speech audio** action remains available for an
explicit retry or regeneration.

When Chromium runs in the optional external renderer container, the API reads its capability
heartbeat from the shared video volume. The renderer refreshes it every 10 seconds and the API
rejects heartbeats older than 30 seconds.
