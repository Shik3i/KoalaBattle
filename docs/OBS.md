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
- `preset=live|video|fast|instant`;
- `effects=off|low|standard|high`;
- `damageNumbers=1|0`;
- `reducedMotion=1|0`;
- `roster=1|0` — the six-slot squad row under each player;
- `hudScale=0.8…1.6` — multiplies every HUD text and bar size.

**Copy OBS URL**, in the control page's **Tools** menu, writes the settings you tuned in the
collapsed **Presentation settings** panel into
these parameters, so the captured source matches what you saw rather than falling back to the
capture browser's own stored defaults.

No API keys or secrets belong in overlay URLs. Match and tournament overlays use sanitized,
read-only APIs and cannot pause/cancel work or submit manual decisions. Transparent mode
removes renderer and page backgrounds; regular KoalaBattle use does not require OBS.

## Production audio and captions

Match overlays load the newest stored production for that match, if one exists. Captions run
without audio. OBS Chromium still enforces autoplay rules: interact with the source once and
choose **Enable audio**, then configure OBS to control audio through the browser source. Do not
open two audible clients for one production; the operator-selected authoritative client owns
playback, while all other sources remain muted visual clients.

Each overlay creates and destroys its own mixer. Cache keys and timelines are match-scoped, so
simultaneous browser sources cannot share an active audio element or scheduler. Tournament
bracket overlay state remains separate from match audio; use the active match overlay as a
nested OBS source for commentary and captions. Recommended QA sizes remain 1920×1080 and
1080×1920.

## Production styles on live surfaces

There is one style system, not one per surface. `/watch/<id>` and `/overlay/<id>` accept a
`style=<preset-id>` query parameter that applies a built-in or saved `ProductionStyle`:

```text
http://localhost:3000/overlay/<match-id>?layout=overlay-landscape&transparent=1&style=minimal
```

The live surfaces are a DOM renderer with a smaller vocabulary than the offline compositor,
so the style is *mapped* onto it rather than reimplemented: effect intensity becomes effect
quality, `idle_motion: off` or `camera: static` becomes reduced motion, damage callouts and
the turn header follow their toggles, and `commentary: off` hides the commentary panel.
Settings the DOM renderer cannot express — stage backgrounds, HUD presets, typography — are
left alone rather than approximated with a second theme system.

Complex styles are persisted server-side and referenced by id. Do not attempt to encode a
whole style into the Browser Source URL.
