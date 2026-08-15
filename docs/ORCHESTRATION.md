# Match orchestration

`MatchSupervisor` owns durable scheduling. Each `MatchSession` owns exactly one engine,
manual-decision broker, agent pair, pause gate, and terminal callback. No mutable engine or
waiter is shared across matches.

```text
create -> queued -> starting -> running <-> waiting_for_input
                               running <-> paused
queued|starting|running|waiting_for_input|paused -> cancelled
starting|running|waiting_for_input|paused -> completed|failed|interrupted
```

Invalid transitions are rejected by `orchestration/lifecycle.py`. Queue position and status
are persisted before workers launch. `KOALABATTLE_MAX_CONCURRENT_MATCHES` limits active
sessions globally; a tournament may impose a lower limit. Provider calls remain subject to
their existing per-player and tournament cost limits.

## Pause, cancel, restart

Pause takes effect at the next safe agent-decision boundary; it does not interrupt an engine
write mid-event. Cancel requests the session task to stop and stores a terminal state. On
backend startup, previously active rows become `interrupted`; safely queued rows are eligible
for dispatch again. Historical events and decisions are never rewritten.

## Isolation and live updates

Match REST/WebSocket routes address a single match ID. Admin and tournament streams publish
separate overview snapshots. A slow/disconnected browser cannot block persistence or another
match. Manual submissions include match, side, and request UUID and cannot satisfy a waiter
owned by another session.

## Capacity semantics

`created` means persisted but not submitted. `queued` means eligible and ordered.
`starting`/`running`/`waiting_for_input`/`paused` consume capacity. Terminal states release a
slot and wake the scheduler. Queue ordering is deterministic by `queue_position`, then
creation time.
