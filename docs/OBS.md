# OBS Browser Source

Use the chrome-free route:

```text
/overlay/:matchId?layout=overlay-landscape&theme=koala-dark&transparent=1
```

Tournament status/bracket source:

```text
/overlay/tournament/:tournamentId
```

The overlay fetches the recorded archive, restores the last normalized presentation state,
subscribes to `/api/matches/:id/stream`, deduplicates event sequences, and reconnects after
connection loss. It cannot submit agent decisions or Showdown commands.

## Presets

| Preset | Browser source | FPS |
| --- | --- | --- |
| YouTube 1080p | 1920×1080 | 60 |
| Twitch 1080p | 1920×1080 | 60 |
| Vertical | 1080×1920 | 60 |

The Settings page generates and copies the URL for an existing match. Supported query
parameters:

- `layout=overlay-landscape|standard-landscape|standard-vertical`;
- `theme=koala-dark|koala-light`;
- `transparent=1|0`;
- `commentary=latest|last-3|full|hidden`;
- `log=1|0`;
- `near=p1|p2`;
- `preset=live|video|fast|instant`.

No API keys or secrets belong in overlay URLs. Match and tournament overlays use sanitized,
read-only APIs and cannot pause/cancel work or submit manual decisions. Transparent mode
removes renderer and page backgrounds; regular KoalaBattle use does not require OBS.
