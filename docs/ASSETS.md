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

The resolver checks canonical IDs plus legacy installer names and refuses paths that resolve
outside `KOALABATTLE_ASSET_ROOT`. APIs: `GET /api/assets/status`,
`POST /api/assets/rescan`, `GET /api/assets/resolve/pokemon/:species`, and the content route
`GET /api/assets/pokemon/:species`. Missing media returns 404.

## Rights

The setup tool and KoalaBattle source are MIT-licensed. The sprites are not. The upstream
repository states that Pokémon sprites are property of Nintendo, Game Freak, and The Pokémon
Company, with some community-created work having separate/undetermined terms. Downloading
does not grant rights. Operators are responsible for applicable copyright, trademark, usage,
distribution, platform, and jurisdiction requirements. Never commit or redistribute the
downloaded pack as part of KoalaBattle.
