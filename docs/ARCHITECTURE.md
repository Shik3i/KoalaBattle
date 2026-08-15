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

## Video exports

```text
Battle (immutable events)
  -> Production (fixed logical clock and presentation decisions)
    -> VideoExportJob (preset, backend, range, progress)
      -> OBSRecorderExporter      -> realtime OBS recording
      -> OfflineRendererExporter -> renderAt(t) -> PNG pipe -> FFmpeg -> FFprobe
```

`ProductionService` receives repository post-commit hooks. It appends only the new event's
cues and finalizes result/outro/audio without blocking battle execution. `VideoExportService`
owns the bounded persistent queue; exporters do not enter match/tournament orchestration.

Offline frames use the same `BattleRenderer`, reducer, themes, layouts, local sprite endpoint,
and caption overlay as live/replay/OBS. At logical time `t`, only event sequences whose visual
cue has started are reduced. Winner, future moves, future commentary, hidden teams, and later
series data therefore cannot enter an early frame. CSS animation state is paused at the
logical cue offset; browser wall-clock time does not control frame sampling.
