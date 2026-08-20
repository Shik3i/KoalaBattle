# Optional local assets

Repository audit result: Git tracks **0 files** below `data/assets/` and `data/vendor/`. A fresh
checkout therefore starts with no Pokémon front/back/animated sprite, icon, trainer,
background, effect, or audio category. An API or resolver does not imply an installed pack.

The opt-in validation installation performed on 2026-08-15 contained 6,535 resolver-compatible
files: 1,665 static front, 1,661 static back, 1,628 animated front, and 1,581 animated back.
Those local files and their manifest remain ignored and are not part of the repository.

KoalaBattle ships no Pokémon sprites, artwork, trainer images, backgrounds, music, or sound
effects. Normal startup performs no network request and never downloads media.

## Explicit setup

The setup tool reads the official Pokémon Showdown deployment directories. Static is the
default; full additionally installs animated sprites.

```bash
python3 scripts/setup_assets.py status
python3 scripts/setup_assets.py install
python3 scripts/setup_assets.py install --profile full
python3 scripts/setup_assets.py verify
python3 scripts/setup_assets.py install --refresh
python3 scripts/setup_assets.py remove
```

`install` first verifies that each remote directory still has a plausible current listing and
known `pikachu` entry. Downloads are atomic and checksummed. Repeated installs retain valid
files. `remove` deletes only files named in `data/vendor/pokemon-showdown-assets.json`; unrelated
operator media is preserved.

Upstream aliases occasionally normalize to the same alphanumeric Showdown ID. The installer
resolves those collisions deterministically, preferring a source stem that is already the
canonical alphanumeric ID. It never silently overwrites one downloaded file with another.

Source deployment: <https://play.pokemonshowdown.com/sprites/>. Upstream build/source:
<https://github.com/smogon/sprites>. The verified directories are `gen5/`, `gen5-back/`,
`ani/`, and `ani-back/`. Deployed filenames are normalized to the resolver's alphanumeric
Showdown IDs.

## Storage and resolver

```text
data/
  assets/
    pokemon/front/
    pokemon/back/
    pokemon/animated/front/
    pokemon/animated/back/
    pokemon/icons/              # supported locally; installer does not create sheet slices
    trainers/ backgrounds/ effects/ audio/
  vendor/
    pokemon-showdown-assets.json
```

Both `data/assets/` and `data/vendor/` are excluded by `.gitignore` and `.dockerignore`.
Docker mounts `data/assets/` read-only into the backend. Supported local image extensions:
`.webp`, `.png`, `.gif`, `.svg`, `.jpg`, `.jpeg`.

Optional sample SFX use the same ignored local-media boundary. Follow [SFX.md](SFX.md) for
source/licence guidance and `scripts/setup_sfx.py` for explicit mapping, checksum verification,
and safe removal. Curated files go below `data/assets/audio/`; the backend serves only exact
semantic ids through `GET /api/assets/audio/{effect_id}` and never accepts arbitrary paths.

Optional move textures follow the same boundary. [MOVE_EFFECTS.md](MOVE_EFFECTS.md) documents
the pinned CC0 allowlist, conservative exclusions, local-pack mapping, checksums, and removal.
They are served by exact id through `GET /api/assets/effects/{effect_id}`; procedural recipes
remain the default fallback when no texture is installed.

The resolver checks canonical IDs plus legacy installer names and refuses paths that resolve
outside `KOALABATTLE_ASSET_ROOT`. APIs: `GET /api/assets/status`,
`POST /api/assets/rescan`, `GET /api/assets/resolve/pokemon/:species`, and the content route
`GET /api/assets/pokemon/:species`. Missing media returns 404.

## Branding media (logos, backgrounds, watermarks, fonts)

The Video Studio can use images and fonts you supply. They live under
`KOALABATTLE_BRANDING_ROOT` (`data/branding` by default), which is ignored by Git:

```text
data/branding/logo/<generated-id>.png
data/branding/background/<generated-id>.webp
data/branding/watermark/<generated-id>.png
data/branding/font/<generated-id>.woff2
```

Four categories of media exist in a KoalaBattle install, and they are backed up differently:

| Category | Location | In Git? | Recoverable? |
| --- | --- | --- | --- |
| Bundled safe assets | repository (`frontend/static`) | Yes | From the repo |
| Generated/runtime | `data/audio`, `data/videos` | No | Regenerated on demand |
| User-uploaded branding | `data/branding` | No | **Only from your own backup** |
| Third-party optional | `data/assets`, `data/vendor` | No | Re-run `setup_assets.py` |

Uploaded branding is the one category nothing can rebuild. Back up `data/branding` together
with `data/koalabattle.db`, which holds the metadata that points at those files.

### Upload rules

- **Images**: PNG, WebP, JPEG. Max 8 MB, max 8192px per edge.
- **Fonts**: WOFF2, TrueType, OpenType. Max 4 MB.
- **SVG is not supported.** A safe SVG subset needs a real sanitizer (scripts,
  `foreignObject`, external references, entity expansion); a half-sanitized SVG rendered
  inside the app is worse than none.
- Content is identified from file headers, not the filename or the declared type. Nothing
  is decoded to check it, and dimensions are read from the header so an oversized image is
  refused before any decoder sees it.
- The stored path is generated from a server-side id. The uploaded filename is used only as
  a display label, with path-shaped characters stripped.

### Provider logos and trademarks

**KoalaBattle bundles no third-party logos.** The OpenAI, Google, Anthropic and DeepSeek
names, word marks and logos are trademarks of their respective owners and are governed by
their own brand guidelines; this project cannot grant redistribution rights it does not
have, so it ships none of those files.

Instead each provider family gets an original generated badge drawn by the compositor —
`GPT`, `GEMINI`, `CLAUDE`, `DEEPSEEK`, `LOCAL`, `MANUAL`, `RANDOM`, `KOALA` — in
KoalaBattle's own shapes and colours. The branding system is fully functional with no logo
file present. If you have the rights to a specific logo, upload it locally; it stays on your
machine and is never committed.

### Fonts

You are responsible for the licence of any font you add. KoalaBattle never redistributes
fonts and its built-in choices are local system stacks, not bundled files. See
[THEMES.md](THEMES.md) for the stacks and the fallback behaviour.

### Missing media

If a production references an asset that is no longer on disk, it does not crash and it
never silently substitutes a different file. Export preflight reports the asset as
`missing — falls back`, the logo degrades to the generated mark, the background degrades to
the style's solid colour, and the font degrades to its stack. Replace the asset in the Video
Studio to restore the intended look.

Deleting an asset that a production still references is refused with a 409 listing the
affected productions; deleting anyway requires an explicit `force=true`.

## Rights

The setup tool and KoalaBattle source are MIT-licensed. The sprites are not. The upstream
repository states that Pokémon sprites are property of Nintendo, Game Freak, and The Pokémon
Company, with some community-created work having separate/undetermined terms. Downloading
does not grant rights. Operators are responsible for applicable copyright, trademark, usage,
distribution, platform, and jurisdiction requirements. Never commit or redistribute the
downloaded pack as part of KoalaBattle.
