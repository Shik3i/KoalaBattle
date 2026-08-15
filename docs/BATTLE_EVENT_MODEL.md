# Battle event model

Schema version `1.0` uses monotonically increasing `sequence` values scoped to one match.
`turn` is the Showdown turn known when an event is recorded; `logical_offset_ms` is for
presentation timing and does not affect ordering.

Required fields:

```json
{
  "match_id": "uuid",
  "sequence": 17,
  "turn": 3,
  "event_type": "damage",
  "logical_offset_ms": 842,
  "payload": {},
  "schema_version": "1.0"
}
```

Known semantic types include `battle_started`, `turn_started`, `pokemon_switched`,
`move_used`, `move_missed`, `damage`, `healing`, `critical_hit`, `status_applied`,
`status_removed`, `weather_changed`, `pokemon_fainted`, `agent_decision`,
`state_snapshot`, `battle_finished`, and `battle_failed`. Unknown Showdown protocol lines
are preserved as `showdown_message`, so the format is intentionally open-ended.

`payload.raw` may contain untrusted source text. Clients display it as text only. Events
are append-only; future schema upgrades should add reducer migrations rather than rewrite
completed history.
