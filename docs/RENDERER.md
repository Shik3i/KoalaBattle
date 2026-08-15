# Renderer

Phase 2 adds a versioned production presentation layer without changing battle simulation
or persisted match state:

```text
BattleEvent[]
  -> pure presentation reducer
  -> centralized PresentationTimeline
  -> BattlePresentationState
  -> shared BattleRenderer
```

`BattleRenderer` is used by live control, replay, and OBS. It receives no `poke-env`
objects, raw Showdown state, engine WebSocket, or agent connection.

## Presentation state

Transient state includes Pokémon motion (`attacking`, `taking-damage`, `switching-in`,
`fainting`, `status-flash`), generic effects, public commentary history, agent audience
state, current move, winner, and a normalized spectator feed. None is written back to
`BattleState` or SQLite.

State snapshots remain authoritative for HP, status, active Pokémon, turn, and result.
Animations only interpolate between already-recorded states.

## Layouts

- `standard-landscape`: title-safe 16:9 production composition.
- `standard-vertical`: independent 9:16 composition; not a compressed desktop grid.
- `overlay-landscape`: edge-to-edge OBS landscape variant.

`nearSide` controls orientation. Near/far placement and front/back asset perspective do not
assume that `p1` is permanently fixed to one visual side.

## Effects and performance

Generic CSS motion covers idle, attack, hit, switch, faint, status, miss, healing, critical
hit, and victory. Playback speed controls scheduler and HP interpolation durations.
`prefers-reduced-motion` collapses decorative motion.

Only the current presentation state and the last five spectator messages are rendered.
History pages continue to use `MatchSummary`; heavyweight events load only for battle,
replay, and overlay routes. Timers and listeners are destroyed on route teardown.

Renderer version: `2.0.0`. Renderer configuration version: `1.0`.
