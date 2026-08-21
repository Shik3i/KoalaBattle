# Architecture

## Provider boundary

`ShowdownBattleEngine` depends only on the `Agent` protocol. `ApiAgent` owns provider
timeouts, validation, retries, repair prompts, usage/cost normalization, and fallback.
Provider adapters own SDK translation only. Manual Web Chat uses the same structured
decision parser and legality check. The event/replay path remains provider-free.

Presentation consumers use `GET /api/matches/{id}/presentation` and the sanitized
WebSocket snapshot. Full audit data stays on `GET /api/matches/{id}` for the local
production-control UI.

```text
Pokemon Showdown -> poke-env -> ShowdownBattleEngine
                                  |
                                  v
Agent <- AgentRequest <- AgentContextSnapshot / PlayerKnowledgeState / BattleAction
                                  |
                                  +-> immutable BattleEvent -> SQLite
                                                           -> WebSocket clients
                                                           -> replay reducer
                                                           -> presentation reducer
                                                           -> shared renderer
```

## Boundaries

`poke-env` imports exist only in `backend/koalabattle/engines/showdown`. The adapter
converts its player-scoped battle view into versioned Pydantic contracts and converts a
validated action ID back into one Showdown order. Storage, agents, APIs, replay, and the
frontend never receive a `poke-env` object.

The adapter uses two pinned private compatibility surfaces—protocol handling and replay
log extraction—to preserve raw evidence. They are contained in the adapter and covered by
the real-server integration test. A future direct `BattleStream` adapter can implement the
same `BattleEngine` interface.

Each `_KoalaPlayer` owns one knowledge reducer and one bounded Strategy Memory value. The
reducer consumes only that player's poke-env view and survives turns, never matches. Prompt
rendering and provider adapters depend on versioned domain models, not poke-env. The separate
team-validator HTTP service uses the same pinned Showdown image and official library APIs;
team legality does not leak into the Python domain.

## Multi-match orchestration and loops

`poke-env` owns a worker event loop. Agent decisions and event persistence run on the
FastAPI loop through a thread-safe coroutine bridge. `MatchSupervisor` owns the durable queue
and concurrency permits; every `MatchSession` constructs a separate `ShowdownBattleEngine`,
agent pair, `ManualDecisionBroker`, pause gate, and task. A ManualAgent may therefore wait on
a browser response without blocking Showdown processing or another match.

`backend/koalabattle/tournaments` is above this boundary. It creates generic series graphs and
accepts generic results; `BattleService` is the adapter that turns a ready series into one or
more engine-specific matches. See [Orchestration](ORCHESTRATION.md) and
[Tournaments](TOURNAMENTS.md).

`backend/koalabattle/challenges` is another orchestration layer above normal matches. It owns
versioned Showdown-backed draft pools, consumed offers, recommended EVs, difficulty, campaign, and
stage-progression snapshots, then derives two immutable validated team snapshots and creates a
linked normal match. Difficulty is a property of the run, applied only while deriving the player's
stage export; neither the drafted roster snapshot nor the opponent's level is ever rewritten. The battle engine does not
know challenge rules. Terminal match results flow back through a narrow hook; presentation and
replay remain unchanged. See [Draft Challenge](CHALLENGES.md).

## Event sourcing

SQLite is the historical source. `battle_events(match_id, sequence)` has a uniqueness
constraint; insertion is serialized per match. Completed event rows are never updated.
`state_snapshot` events give replay a stable checkpoint, while semantic events retain
animation and inspection detail. Raw protocol logs remain archival evidence, not replay
input.

Summary queries use `config_json` and grouped cost rows without loading event/decision
relationships. Full archives explicitly eager-load those relationships. Queue position and
tournament claims use short immediate/conditional transactions; one start lock owns dispatcher
creation. See [Performance](PERFORMANCE.md).

## Presentation

Live control, historical replay, and `/overlay/:matchId` share one rendering path:

```text
BattleEvent[] -> PresentationTimeline -> BattlePresentationState -> BattleRenderer
```

The presentation reducer adds transient motion, effects, commentary history, and a
spectator-friendly feed without writing them to SQLite. `PresentationTimeline` owns the
single visual timer and deterministic event cursor. It never uses historical API wait time
as animation timing. Layout and theme are declarative renderer configuration and do not
change replay position or battle state.

OBS remains a read-only presentation client. It can fetch an archive and subscribe to the
normalized WebSocket, but cannot submit engine commands or orchestrate battles.

The tournament overlay consumes a separate sanitized tournament snapshot. Admin/control
routes remain local operator surfaces; watch and overlay payloads never reuse full audit data.

## Assets

The asset API is a separate local boundary. It canonicalizes species identifiers, resolves
only files below `KOALABATTLE_ASSET_ROOT`, and returns 404 when media is absent. The
renderer then draws a built-in CSS placeholder. No asset path is stored in battle events.

## Production projection

Production is a separate projection above the immutable archive:

```text
MatchArchive -> ProductionProfile -> ProductionTimeline
                                      | captions
                                      | speech cache/queue
                                      | SFX/music cues
                                      ` director state
```

`BattleRenderer` remains visual and contains no provider or audio logic. The browser
`ProductionAudioEngine` is the sole mixer/scheduler owner. A production rebuild reads stored
events and public commentary only; it never updates the archive and never recalls an LLM.
Multiple production IDs can therefore provide different output timing and voices for one match.

## Production styles and branding

`ProductionStyle` (schema 1.0) is the declarative description of a production's
presentation. It is stored on the production, snapshotted into every export manifest, and
consumed by one compositor:

```text
MatchArchive -> ProductionTimeline (+ ProductionStyle)
             -> ProductionFrameState -> ProductionScene -> native compositor -> frames
```

The Studio preview, the offline export and the single-frame render route all run that same
path, so a preview cannot disagree with an export about layout. The live DOM renderer
consumes the same style object through a documented mapping (see [OBS.md](OBS.md)).

Brand assets (logos, backgrounds, watermarks, fonts) are stored outside Git under
`KOALABATTLE_BRANDING_ROOT` with server-generated names; SQLite holds only metadata.
Styles reference assets by id, never by path, and a missing asset degrades to a documented
fallback rather than crashing or silently substituting another file.

## Video exports

```text
Battle (immutable events)
  -> Production (fixed logical clock and presentation decisions)
    -> VideoExportJob (preset, backend, range, progress)
      -> OBSRecorderExporter      -> realtime OBS recording
      -> OfflineRendererExporter -> RenderPlan -> ProductionScene -> Canvas -> WebCodecs -> FFprobe
```

`ProductionService` receives repository post-commit hooks. It appends only the new event's
cues and finalizes result/outro/audio without blocking battle execution. `VideoExportService`
owns the bounded persistent queue; exporters do not enter match/tournament orchestration.

Offline production reuses the indexed reducer and local sprite endpoint, then derives a pure
`ProductionScene` for the native Canvas compositor. `RenderPlan` marks animated frames, cue
boundaries, and static holds. Every output keeps exact CFR timestamps, while unchanged spans
reuse the previous raster. WebCodecs chunks stream through a bounded Playwright binding into
H.264 Annex-B or VP9 IVF. Where an actual codec-frame probe fails, unique Canvas RGBA rasters
stream through a bounded `libx264` pipe with pipe-side static expansion. FFmpeg containers/muxes
without screenshot capture. Animation and
impact authority derive only from logical cue progress, never browser wall-clock time.
