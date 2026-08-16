# Battle formats

KoalaBattle does not maintain a format allowlist. The pinned local Pokémon Showdown build is
the authoritative source; KoalaBattle only decides which of those formats its own battle
pipeline can run correctly.

## Where the catalog comes from

The Showdown tools container exposes `GET /formats`, built from `Dex.formats.all()`. Each
entry is normalized to:

```
id, name, display_name, generation, mod, section, game_type, player_count,
team_source, random_team, custom_team_required,
challenge_visible, tournament_visible, search_visible, rated, best_of_default,
mechanics { items, abilities, physical_special_split, mega_evolution, z_moves,
            dynamax, terastallization, hidden_power_types, natures,
            held_item_switching }
```

Mechanics are derived from the generation *and* the format's own rule table, so a format that
bans a mechanic (Dynamax Clause, Terastal Clause) reports it as absent.

The backend fetches this at start-up. When Showdown is unreachable it falls back to generated
snapshots shipped with the backend:

```
backend/koalabattle/formats/showdown-format-catalog.json   # the format registry
backend/koalabattle/formats/showdown-dex-names.json        # ability and item display names
```

Showdown reports abilities and items as IDs on a battle request (`ironfist`,
`heavydutyboots`) and only its Dex knows they read as "Iron Fist" and "Heavy-Duty Boots";
poke-env ships no equivalent table, so those names come from `GET /dex-names`.

Both files are machine-generated and must never be hand-edited. Regenerate them whenever the
pinned Showdown commit changes:

```bash
docker compose up -d showdown team-validator
python3 scripts/refresh_format_catalog.py
```

`tests/integration/test_showdown_generations.py` asserts the snapshot still matches the live
registry, so drift fails a test rather than silently shipping.

## Capability rules

KoalaBattle's normalized battle state models exactly one active Pokémon per side. A format is
runnable when all of these hold:

- `game_type == "singles"`
- `player_count == 2`
- the local server accepts direct challenges in it

Anything else stays in the catalog with an explicit `unsupported_reason`, for example
`Not yet supported by KoalaBattle battle renderer (doubles)`. The format selector shows those
entries greyed out with their reason rather than hiding them, so it is clear that Showdown
contains far more than KoalaBattle currently renders. A doubles format is never silently run
through singles-only assumptions.

## Teams

| Team source | Behaviour |
| --- | --- |
| `random` (and Showdown's factory variants) | Showdown generates both teams; no setup |
| `custom` | One validated snapshot per player, validated against that exact format |

Team validation goes through the same pinned Showdown build, for any custom-team format. Gen 1
exports need explicit EVs to satisfy Showdown's "did you forget to EV it?" check.

## API

```
GET  /api/formats?supported_only=true
GET  /api/formats/groups?supported_only=false
GET  /api/formats/search?q=gen+1
GET  /api/formats/{id}
POST /api/formats/refresh
```

## Selector

`/new` uses a searchable selector grouped by generation, newest first, with the formats people
reach for most (Random Battle, OU, Ubers, UU, RU, NU, PU, LC, Monotype, 1v1) ranked first
inside each group. Search understands generation shorthand: `gen 1`, `rby`, `gsc`, `adv`,
`dpp`, `bw`, `xy`, `sm`, `swsh`, `sv`, plus `random`, `rands` and `randbats`. Matching is
prefix-based per token, so `ou` does not match `doubles`.

Each entry shows `GEN n · RANDOM TEAMS|CUSTOM TEAM · SINGLES`.

## Generation-specific behaviour

Prompts, legal actions and the renderer are all generation-aware. See
[Prompt contract](PROMPTS.md) for which fields are omitted per generation. The renderer
switches Gen 1 and Gen 2 sprites to an intentional pixel-art presentation and leaves later
generations smoothed.
