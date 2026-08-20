# Optional move-effect textures

KoalaBattle's MIT-licensed code includes procedural, move-specific recipes for every move.
Optional textures are local-only polish: they are ignored by Git, never bundled, and a missing
texture falls back to the same deterministic CSS/Canvas recipe.

## Pokémon Showdown CC0 subset

The installer downloads a fixed allowlist of generic FX files directly from a pinned Pokémon
Showdown source commit and records source URL, commit, declared license, path, and SHA-256.

```bash
python3 scripts/setup_move_effects.py status
python3 scripts/setup_move_effects.py install-showdown
python3 scripts/setup_move_effects.py verify
python3 scripts/setup_move_effects.py remove --pack showdown-cc0
```

Source: <https://github.com/smogon/pokemon-showdown-client> at commit
`daa28cfeb19775dea9f19f90a8c8f1418bac316a`. The upstream source header declares most generic
FX images CC0. The allowlist deliberately excludes `icicle*`, `lightning`, `bone`, all `rock*`,
Poké Ball and transformation-symbol art because their headers identify different/unclear
licensing or Pokémon-specific imagery. KoalaBattle draws those motifs procedurally.

## Kenney Particle Pack or your own CC0 pack

Download the pack yourself from <https://kenney.nl/assets/particle-pack>, keep its license file,
extract it outside this repository, then map chosen raster files:

```bash
python3 scripts/setup_move_effects.py install-local \
  --source /absolute/path/to/ParticlePack \
  --mapping docs/move-effects-mapping.example.json \
  --pack kenney-particles \
  --source-url https://kenney.nl/assets/particle-pack \
  --license CC0-1.0 \
  --license-url https://creativecommons.org/publicdomain/zero/1.0/
python3 scripts/setup_move_effects.py verify
```

Only PNG, WebP, and JPEG files are accepted. Mapping paths cannot leave the source directory.
Managed files live in `data/assets/effects/<pack>/`; provenance lives in
`data/vendor/move-effects-manifest.json`. Both locations are ignored. Removal deletes only
manifest-owned files.

The renderer setting `moveEffectSkin` selects `broadcast`, `retro`, or `procedural`. Broadcast
and retro try installed textures first; procedural guarantees a texture-free output.
