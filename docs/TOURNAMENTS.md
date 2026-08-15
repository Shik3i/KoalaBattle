# Tournaments

The tournament domain is engine-independent. It stores generic participant IDs and consumes
`GenericMatchResult(winner_id, loser_id, status, metadata)`. Pokémon/Showdown configuration is
attached only when the battle service schedules a concrete match.

## Formats

- Single Elimination: deterministic seeding, non-power-of-two byes, best-of-N series,
  dependency-linked rounds, one champion.
- Round Robin: deterministic pair schedule and standings ordered by match points, wins, then
  participant seed. A win is 3 points and a draw 1 point per participant.

Participants, series games, wins, dependencies, statuses, standings inputs, costs, and audit
timestamps persist in SQLite. Only dependency-ready series may run. Tournament and global
concurrency limits both apply.

## Lifecycle

`draft -> ready -> running -> completed`; operators may also pause, resume, cancel, or mark a
tournament failed. The ten-step wizard creates a draft and can save reusable match templates
or tournament presets. Starting validates participant count, engine settings, and budget
before scheduling.

Control UI: `/tournaments/:id/control`. Public overlay:
`/overlay/tournament/:id`. Public payloads omit provider configuration, prompts, raw responses,
raw Showdown logs, and internal errors.

## Recovery and consistency

Bracket progression and result recording use SQLite `BEGIN IMMEDIATE` transactions and
idempotent match-ID lists. Concurrent completions cannot advance one series twice. On restart,
active match rows are interrupted and historical results remain authoritative; ready series
can be started again explicitly.

## Current limits

No double elimination, Swiss pairing, account authorization, remote multi-tenant mode, or
automatic reconciliation of an interrupted in-progress Showdown room. Round Robin exposes
standings rather than a single persisted champion.
