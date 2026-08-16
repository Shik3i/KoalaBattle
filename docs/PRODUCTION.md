# Production timeline and live direction

`ProductionTimeline` is a versioned, deterministic projection of a stored `MatchArchive`.
Historical `logical_offset_ms` remains audit data; production timing is rebuilt from versioned
event durations and a `ProductionProfile`. Tracks are `visual`, `commentary`, `voice`,
`captions`, `sfx`, `music`, and `director`.

Presets: Live Stream, YouTube, Shorts (9:16), Fast Tournament, and Silent. Captions may remain
enabled when speech is disabled. A rebuild increments the revision and never mutates battle
events or recalls an LLM. A rebuild creates a new production ID and leaves the previous
timeline untouched. Multiple production records may reference the same match.

## Incremental lifecycle

New matches receive a live production on the first persisted `battle_started` event. The
post-commit event hook creates only cues owned by that new sequence. Cue IDs include the
event sequence, so retry/reconnect delivery does not duplicate work. Each append persists an
updated revision and duration; it does not rebuild earlier cues.

Lifecycle: `draft -> live -> finalizing -> finalized`, with `failed` for a finalization error.
Legacy `preparing`, `ready`, and `partial` values remain readable for database compatibility.
After match completion the result/outro cues are persisted immediately. Free Edge neural speech
is prepared outside match execution, ordering is revalidated, duration is fixed, and a SHA-256
seal is stored. Exports require this fixed presentation clock. New settings create a new
production; battle data and prior productions stay unchanged.

## Workflow

1. Open a completed replay and create a production profile.
2. Select stable VoicePresets for `p1` and `p2`.
3. **Prepare free neural speech** generates or reuses local cache media. Edge neural voices use
   Microsoft's online service without an API key; offline system presets remain available. Paid
   providers require a separate explicit API action with `allow_paid=true`.
4. Inspect each cue in the Production Timeline inspector.
5. Enable browser audio, then play or control the director.

Director states: pre-show, match intro, team reveal, battle, between games, result, champion,
paused, and ended. Production pause is persisted separately from battle pause. Manual commands
may claim an `authoritative_client_id`; OBS and other passive clients remain playback-isolated.

Tournament bracket scheduling remains owned by the tournament runtime. Video jobs export individual
tournament matches; a nonlinear full-tournament editor and automatic highlights remain out of
scope.
