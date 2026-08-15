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
