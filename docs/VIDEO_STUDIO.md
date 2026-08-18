# Video Studio

The Video Studio turns a recorded match into a reusable source for video. One battle can be
rendered any number of times, in any presentation, without replaying it on Pokémon Showdown
and without calling a single battle LLM again.

```text
Recorded Match  →  Replay  →  Create Video  →  Customize  →  Preview  →  Render  →  MP4
```

## The four layers

| Layer | Owns | Mutable? |
| --- | --- | --- |
| **Match** | what happened — events, decisions, teams, winner | Never rewritten |
| **Replay** | reconstructing what happened, deterministically | Derived |
| **Production** | how this replay should look and sound | Edited freely |
| **Export** | one rendered video file plus its manifest | Immutable once written |

A match may carry many productions. Editing one never touches the match and never touches
another production. Deleting a production leaves the match alone.

```text
GPT vs Gemini #42
├── YouTube Default      1920×1080  koala-broadcast
├── Vertical Social      1080×1920  vertical
└── Retro Test           1920×1080  retro
```

## Opening the Studio

From `/replay/<match-id>`, the **Video Studio** panel lists existing productions and creates
new ones. Choose an output shape (landscape, vertical, silent, live) and a style, then press
**Create Video**. KoalaBattle pre-selects a style — Gen 1–2 suggests *Retro*, a vertical
output suggests *Vertical* — but the choice is only a suggestion and never forced.

Creating a production automatically:

1. loads the historical match archive,
2. builds the deterministic ProductionTimeline,
3. fills in player branding from each agent (display name, neutral mark, accent),
4. applies the chosen style preset,
5. prepares missing public Edge Neural speech through the configured free provider,
6. opens `/studio/<production-id>` after the production media is ready.

Preparation reuses valid cache entries and regenerates only missing or corrupt artifacts. It
never selects a system voice implicitly, never uses a paid provider, and may take a while for a
long replay because every public commentary cue must be prepared before the Studio opens.

## The workspace

```text
┌──────────────────────────────────────────────────────┐
│ GPT vs Gemini · Gen 9 · Random Battle                │
├───────────────────────────────┬──────────────────────┤
│                               │ Style                │
│        LIVE PREVIEW           │ Intro                │
│      (native compositor)      │ Player branding      │
│                               │ Arena                │
│                               │ HUD                  │
│                               │ Commentary           │
│                               │ Captions             │
│                               │ Effects              │
│                               │ Result & watermark   │
│                               │ Advanced             │
├───────────────────────────────┴──────────────────────┤
│ Play · Seek · Prev/Next turn · Jump to Intro/Attack…  │
└──────────────────────────────────────────────────────┘
```

The preview is the **same compositor that renders the exported video**, running on a canvas
at full output resolution and scaled down for display. There is no separate preview
renderer to drift out of sync with the export.

### Preview shortcuts

Buttons jump straight to Intro, Neutral, Commentary, Attack, Damage, Switch and Victory.
A shortcut only appears when the production actually contains that cue — a match with no
switch never grows a fake one.

### Framing and guides

- **9:16 framing** re-lays the preview for vertical output without rendering a video.
- **Safe areas** draws caption and title guides. Editor-only; never present in an export.
- **Fullscreen preview** hides the settings panel to judge the real composition.

## Saving

Edits live in the page until you press **Save**. **Discard** restores the last saved state,
and navigating away with unsaved changes asks first. Seeking and playback are not edits and
never trigger the warning.

- **Save as preset** stores the current style under a new name, reusable on any match.
- Built-in presets cannot be overwritten or deleted; duplicate one and edit the copy.
- **Duplicate** copies a production's presentation onto a new id sharing the same match.

Exports render the **saved** production. Save before exporting.

## What customization cannot do

Production settings are presentation only. Nothing in the Studio can change battle events,
agent decisions, commentary text, teams, the winner, historical timing or provider data.
Pacing presets change visual transition timing, not the recorded order of events.

Hidden information stays hidden: the team-indicator setting can *narrow* what a spectator
sees but never widen it, because the Studio only ever reads the public presentation archive.
Private strategy memory and raw model output are not available to any production surface.

## See also

- [PRODUCTION.md](PRODUCTION.md) — timeline, cues and the director model
- [THEMES.md](THEMES.md) — every style setting and the built-in presets
- [ASSETS.md](ASSETS.md) — logos, backgrounds, fonts, storage and licensing
- [VIDEO_EXPORT.md](VIDEO_EXPORT.md) — preflight, rendering and the export manifest
- [OBS.md](OBS.md) — driving live surfaces from the same style
