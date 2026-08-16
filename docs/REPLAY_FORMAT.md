# Replay format

Replay consumes stored, sequence-ordered `BattleEvent[]`. It never starts Showdown,
loads `poke-env`, chooses an action, or contacts an agent.

The battle reducer applies `state_snapshot.payload.state` as a normalized authoritative
checkpoint. The presentation reducer interprets semantic events as transient motion,
effects, commentary, and spectator text. It never renders `payload.raw`.

## Cursor and timeline

`PresentationTimeline` rebuilds presentation state from event zero when seeking backwards.
Controls are cursor operations:

- restart;
- previous/next event;
- previous/next turn;
- range scrub;
- play/pause;
- 0.5×, 1×, 2×, 4×, and Instant.

One centralized timer is cleared on pause, seek, reset, event replacement, and component
destruction. Live follow mode uses the same scheduler and deduplicates event sequences.

## Historical timing versus presentation timing

`logical_offset_ms` and decision `latency_ms` remain historical evidence. Playback uses a
deterministic duration table plus the selected renderer preset and speed. A slow Manual
response does not force replay to reproduce the original wall-clock wait.

Given the same ordered events, renderer version, renderer configuration, and local asset
pack, event ordering and cursor state are deterministic. Browser performance cannot reorder
events.

## Compatibility

Unknown semantic events are ignored by the presentation reducer. Legacy snapshots and
actor strings remain supported. Raw logs, dependency revisions, and seeds remain archival
evidence; exact Showdown re-simulation is not required to render an old match.
