# Themes and layouts

Theme controls visual tokens. Layout controls composition. They are independent.

Initial themes:

- `koala-dark`: deep neutral arena, luminous green production accent;
- `koala-light`: bright editorial arena with accessible dark typography.

Themes are component-scoped CSS variables. They contain no executable JavaScript and do
not control the event reducer, replay cursor, layout order, or battle data.

Renderer configuration is stored locally under `koalabattle-renderer-config-v1`; the value
is migrated/sanitized through schema version 2:

```json
{
  "version": "2.0",
  "layout": "standard-landscape",
  "theme": "koala-dark",
  "preset": "live",
  "playbackSpeed": 1,
  "commentaryMode": "latest",
  "showBattleLog": true,
  "showTurn": true,
  "showAgentState": true,
  "transparentBackground": false,
  "animatedSprites": true,
  "nearSide": "p1",
  "effects": "standard",
  "reducedMotion": false,
  "showDamageNumbers": true
}
```

Effects are `off`, `low`, `standard`, or `high`. Reduced motion preserves authoritative HP,
status, captions, and result information while removing decorative movement.

Changing theme or layout reflows only the current rendered presentation. Timeline index,
event ordering, authoritative HP, and match history remain unchanged.
