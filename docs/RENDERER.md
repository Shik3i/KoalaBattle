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

Transient state includes Pokémon motion (`idle`, `attacking`, `taking-damage`, `switching-in`,
`switching-out`, `fainting`, `status-flash`), type/category move profiles, damage/heal values,
effectiveness, weather, terrain, side conditions, public commentary history, agent audience
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

Procedural CSS motion covers all 18 move types and physical, special, and status archetypes,
including projectile/beam/charge layers, seeded particles, arena-local impact shake, HP ghost
bars, damage/heal numbers, effectiveness, field states, switch/faint, and victory. It contains
no extracted game VFX or battle backgrounds. Playback speed controls scheduler and HP
interpolation durations.
`prefers-reduced-motion` collapses decorative motion.

Only the current presentation state and the last five spectator messages are rendered.
History pages continue to use `MatchSummary`; heavyweight events load only for battle,
replay, and overlay routes. Timers and listeners are destroyed on route teardown.

The offline route builds one indexed `ProductionFrameRenderer` per page. Timeline tracks and
presentation snapshots are indexed once; binary search selects the current state, including
backward seeks and future-information boundaries.

Phase 9 projects the same state into a pure `ProductionScene` for offline Canvas composition.
The scene covers landscape/vertical placement, HP/status panels, local sprites/placeholders,
physical/special/status choreography, projectiles, beams, pulses, impact authority, weather,
terrain, camera shake, captions, intros, and results. It does not query Showdown or providers.
Static RenderPlan spans reuse Canvas pixels; active animation remains sampled at preset FPS.

Renderer version: `2.0.0`. Renderer configuration version: `2.0`.
