# Performance and load baseline

Measured locally on 2026-08-15 on macOS with Python 3.12.13. Results are a development
baseline, not cross-machine guarantees. Run `PYTHONPATH=backend .venv/bin/python
scripts/benchmark_phase5.py` to repeat it.

| Scenario | Scale | Elapsed | Result |
| --- | ---: | ---: | --- |
| Replay reconstruction | 1,000 / 5,000 / 10,000 events | 0.78 / 3.86 / 7.65 ms | all events |
| Historical list + grouped count | 100 / 1,000 matches | 4.40 / 5.38 ms | bounded 100-row page |
| Tournament graph | 16 / 32 participants | 0.32 / 1.16 ms | 120 / 496 round-robin series |
| Concurrent Fake backend matches | 1 / 10 / 25 | 0.12 / 0.87 / 1.90 s | 1 / 10 / 25 completed |

The Fake load uses four turns, two API agents, fresh knowledge/context rendering, 8 decisions
and 28 stored events per match, SQLite WAL, the real scheduler, and the real-time hub. At 25:
200 decisions and 700 events completed with 0 failures, 0 ordering errors, 0 retained sessions,
0 completion tasks, 0 subscriber groups, and 0 event locks. Process peak RSS was 202.89 MiB;
the value is cumulative high-water RSS and includes Python/provider SDK imports. Throughput was
about 369 stored events/s.

Evidence-based fixes from the load run:

- match summary queries no longer eager-load event/decision JSON;
- initial supervisor startup is serialized, preventing parallel first requests from creating
  multiple dispatchers;
- queue position assignment uses a short SQLite `BEGIN IMMEDIATE` transaction;
- finished-session cleanup tasks are tracked/drained and per-match event locks are released;
- ready tournament series use one conditional transactional claim.

The real pinned Showdown gates pass two concurrent Random Battles and one custom Gen 9 OU
match. A separate attempt to open 25 real matches at once overloaded the local poke-env/
Showdown login path with `|nametaken|` and login assertions, so it is not reported as supported
capacity. Default global concurrency remains two. Raise it incrementally and measure the
operator's Showdown host; SQLite itself did not produce errors in the valid 25-match backend
load.

Frontend production pages remain server-rendered and archive endpoints are paginated. The
control decision inspector intentionally loads one full selected match archive; public lists
do not. Browser QA covers desktop and narrow layouts, but this baseline does not claim a
synthetic browser FPS number.

## Phase 6 audio limits

Speech work is bounded independently of match concurrency by
`KOALABATTLE_SPEECH_MAX_CONCURRENCY` (default 2). Identical cache misses share one in-flight
task, and cache hits perform no provider call. The browser uses one 40 ms production scheduler
per visible production client; seeking stops old media before re-indexing cues. WAV payloads
are capped at 16 MiB and are streamed from disk rather than SQLite.

The zero-cost system smoke test validates an actual local `espeak-ng` WAV. FakeSpeechProvider
is used for repeatable concurrency/cache tests; no paid network synthesis is part of the gate.

## Phase 7 video limits

Export concurrency defaults to one. Browser/FFmpeg work runs in a worker task and its expensive
encoder/browser work lives in subprocesses; the optional Compose `renderer` service isolates it
from battle/API processes. SQLite progress persists at most four times per second rather than
once per frame. Restart reconciliation marks active jobs failed/interrupted and retains their
finalized source production for retry.

Frame count is `ceil(duration_ms * fps / 1000)`. Frame time is always `index * 1000 / fps`,
never an accumulated delta.

Actual offline renders on the same macOS development host, using Chrome 151, FFmpeg 8.1.2,
software `libx264`, in-memory JPEG frames, and cached zero-cost system speech:

| Production | Output | Frames | Media duration | Render wall time | Media / wall ratio |
| --- | --- | ---: | ---: | ---: | ---: |
| YouTube full | 1920x1080, 60 FPS | 1,657 | 27.617 s | 72.671 s | 0.38x |
| Shorts full | 1080x1920, 60 FPS | 1,304 | 21.733 s | 55.871 s | 0.39x |

The renderer is deterministic in frame count, logical sampling, duration, and cue behavior,
but the H.264/AAC container is not promised bit-identical: two identical five-second renders
both produced exactly 300 frames and 5.000 s while their final SHA-256 hashes differed. OBS
would require approximately the media duration because it records in realtime; on this host,
the current screenshot pipeline is slower than OBS realtime. The offline advantage is
unattended queue/batch operation and explicit-time reproducibility, not speed on this machine.

## Phase 8 renderer profile and result

Phase 8 repeated the landscape production above on the same host with the same
1920x1080/60 FPS, JPEG quality 92, and software `libx264` settings. The exact Phase-7
pipeline profile took 70.420 s for 27.605 s of media (`0.392x`). Screenshot capture and
transfer consumed 64.885 s, or 92.1% of wall time; layout was 0.034 s, style recalculation
0.969 s, script 0.329 s, and FFmpeg pipe backpressure only 0.248 s. The dominant cost was
therefore browser screenshot transport, not replay reduction, layout, or encoding.

Candidate measurements used the same rendered page. For 180 1080p frames, Playwright JPEG
92 captured at 29.72 FPS, JPEG 75 at 30.52 FPS, CDP JPEG 92 at 27.75 FPS, and CDP WebP 75 at
7.40 FPS. `HeadlessExperimental.beginFrame` was unavailable in the installed Chrome, and CDP
screencast did not provide an explicit-time frame for each request. Separate browser processes
also regressed throughput. Four preloaded pages in one browser reached 46.19 capture FPS in
the 360-frame prototype, versus 25.22 FPS for one page.

The production implementation uses a bounded four-page pool in one isolated browser context.
Each page receives an explicit absolute logical time; one small batch is captured concurrently,
then written to FFmpeg in frame-index order with `drain()` after every frame. Memory is bounded
to one batch, cancellation is checked between batches, and no frame files are written.
Animations in offline frames are functions of logical cue progress rather than browser time.

Actual full exports after the change:

| Production | Output | Frames | Media duration | Wall time | Media / wall | Change |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| YouTube full | 1920x1080, 60 FPS | 1,657 | 27.605 s | 51.756 s | 0.533x | 26.5% less wall time |
| Shorts full | 1080x1920, 60 FPS | 1,304 | 21.725 s | 45.550 s | 0.477x | 18.5% less wall time |
| Fast Preview | 1280x720, 30 FPS | 829 | 27.605 s | 14.633 s | 1.887x | exceeds realtime |
| Historical 31-turn replay | 1280x720, 30 FPS | 8,546 | 284.840 s | 170.939 s | 1.666x | full long-match gate |

The 1080p60 target did not reach realtime on this machine. The best measured result is
`0.533x`; reporting it as faster than realtime would be incorrect. The remaining bottleneck
is still JPEG screenshot capture/transfer. The practical 720p30 preview exceeds realtime,
while the added 1080p30 presets trade temporal resolution for roughly half the required
captures without silently changing the existing 60 FPS presets.

The landscape manifest measured 47.689 s in the frame loop, 11.037 worker-seconds in state
updates, 169.698 worker-seconds in parallel capture, 0.538 s of pipe backpressure, and 0.104 s
of encoder finalization. Worker-seconds overlap and must not be added to wall time. Run a
stored production again with:

```bash
PYTHONPATH=backend .venv/bin/python scripts/benchmark_renderer.py PRODUCTION_ID \
  --preset youtube-1080p60 --encoder software --workers 4
```

Three real render/cancel cycles left no owned Chromium/FFmpeg process or temporary file.
During the long render, a Random-vs-Random match completed with 106 events; match creation,
Admin API/UI, and WebSocket response remained 56 ms, 157/113 ms, and 75 ms respectively.
