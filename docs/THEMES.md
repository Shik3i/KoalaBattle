# Production styles

A `ProductionStyle` is the complete, versioned description of how a replay looks. It is
declarative on purpose: bounded enumerations, numbers and colours only, never CSS, markup
or filesystem paths. That is what lets the browser preview, the OBS surface and the offline
compositor all agree, and what keeps a downloaded preset from being an execution vector.

```text
ProductionStyle (schema 1.0)
├── StageStyle        background, arena treatment, lighting, accent
├── HudStyle          preset, HP presentation, information toggles
├── TypographyStyle   families, scale, weight, tracking, case, outline
├── MoveCalloutStyle  layout and metadata for move names
├── DamageStyle       which callouts appear, and how loud
├── CommentaryStyle   layout, identity, entrance motion
├── CaptionStyle      preset, position, size, background, outline
├── EffectStyle       intensity, camera, idle motion, pacing
├── IntroStyle        on/off, length, which metadata appears
├── ResultStyle       on/off, winner, logos, series, duration
├── WatermarkStyle    off by default
├── ParticipantBranding (per side)
└── SeriesDisplay     tournament, round, game number, best-of, score
```

## Built-in presets

Presets are compositions, not one-setting variants. Each changes stage, HUD, typography,
callouts, commentary and effects together.

| Preset | Stage | HUD | Type | Callout | Commentary | Effects |
| --- | --- | --- | --- | --- | --- | --- |
| **Koala Broadcast** | grid arena | broadcast, slash bars | system | banner | fighter card | standard, subtle camera |
| **Fighting** | stadium, lit | fighting, thick pills, no exact HP | geometric, outlined, tracked | impact | lower third, punch-in | dramatic, dynamic camera |
| **Minimal** | flat floor, no motion | minimal, thin bars, fainted-only team | grotesk, lowercase, no shadow | minimal | off | minimal, static camera |
| **Retro** | platform, dark | retro, square bars, level shown | pixel stack, tight | lower third | captions only | minimal, subtle idle, no trails |
| **Vertical** | platform, purple | esports, compact | geometric, large | centered | lower third | standard, dynamic, fast pacing |

Built-ins are read-only. **Save as preset** duplicates the current style under a new name;
built-in ids can never be overwritten or deleted, so there is always something to return to.

### Style suggestion

Creating a production pre-selects a style: Gen 1–2 → Retro, vertical output → Vertical,
everything else → Koala Broadcast. It is a suggestion in the picker and nothing more.

## Retro and originality

The Retro preset is an original interpretation: a dark platform stage, a blocky monospace
display stack, restrained effects and square HP plates. It is **not** a reproduction of any
Game Boy or Pokémon game interface, and no HUD in KoalaBattle copies a copyrighted game UI.
For a true pixel typeface, upload a font you have the rights to (see [ASSETS.md](ASSETS.md)).

## Typography

Fonts are local stacks. Nothing is fetched from Google Fonts or any other host at render
time — an export must not depend on the network, and KoalaBattle does not redistribute
typefaces.

| Family | Stack |
| --- | --- |
| `system` | `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` |
| `geometric` | `"Avenir Next", "Century Gothic", Futura, "Trebuchet MS", …` |
| `grotesk` | `"Helvetica Neue", Helvetica, Arial, …` |
| `serif` | `"Iowan Old Style", Georgia, "Times New Roman", serif` |
| `mono` | `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` |
| `pixel` | `Monaco, "Andale Mono", "Courier New", ui-monospace, monospace` |

Uploading a font asset registers it as `kb-font-<asset-id>` and puts it in front of the
chosen stack. Fonts are loaded and awaited **before** the first frame is composited, so a
face can never arrive halfway through a render. Export preflight reports the font state; a
font file that has gone missing falls back to its stack and is listed as missing rather
than silently substituted.

Because the stacks resolve against locally installed families, a preview in a browser
without (say) Avenir Next will fall back differently from one that has it. The exported
video is rendered by the local Chromium the exporter drives, and the Studio preview uses
the *same compositor code*, so layout is identical; only glyph substitution can differ
between two machines.

## Format naming

Formats are always shown by name — `Gen 1 · OU`, `Gen 9 · Random Battle`. The Showdown ids
(`gen1ou`, `gen9randombattle`) stay internal and never appear in a production surface.
Format and generation display can each be switched off entirely.

## Information limits

Two rules are enforced by the model, not by convention:

- **No hidden information.** Team indicators can be `full`, `revealed`, `fainted-only` or
  `hidden`. Every mode reads the public presentation archive, so a setting can narrow what
  a spectator sees but never widen it.
- **No private reasoning.** Only public commentary is available to any production surface.
  Strategy memory, raw model responses and prompts are not reachable from a style.

## Portability

A style is plain JSON containing settings and asset **ids**. It carries no API keys, no
absolute paths and no binary media. Copying a style to another machine therefore copies the
look, and any custom images or fonts must be uploaded there separately.

## See also

- [VIDEO_STUDIO.md](VIDEO_STUDIO.md) — the editing workflow
- [ASSETS.md](ASSETS.md) — uploads, storage and licensing
- [RENDERER.md](RENDERER.md) — how a style reaches pixels
