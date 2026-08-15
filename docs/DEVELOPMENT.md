# Development

## Requirements

- Python 3.12 or newer (`poke-env` supports 3.10+, KoalaBattle standardizes on 3.12)
- Node.js 22 or newer (required by current Pokémon Showdown)
- Docker Compose v2 for the reproducible local engine

Follow the commands in the README. Run Alembic before FastAPI; application startup reconciles
runtime lifecycle rows but does not silently create or mutate schemas.

## Dependency policy

Python and npm packages are exactly pinned for the current baseline. Pokémon Showdown is
pinned to `b22742debfdce6e640193384f5731b9030f9cb6e`. Upgrade it and `poke-env` together,
then run unit, archive, frontend, and real-server integration checks. Private `poke-env`
surfaces must not escape `engines/showdown`.

## Test layers

- unit: contracts, lifecycle, scheduling races, generic tournaments, validation, agents, assets
- storage: SQLite migrations, ordering, audit, tournament persistence, reopen/recovery
- integration: two concurrent real Gen 9 Random Battles in independent Showdown rooms
- presentation: Node tests for reducer restoration and deterministic scheduler operations
- frontend: `npm test`, Svelte diagnostics, production build, and rendered browser QA

Enable the real battle test only with `KOALABATTLE_RUN_SHOWDOWN_TEST=1`; this prevents an
accidental connection during ordinary unit checks.

Run documentation/setup checks from the repository root:

```bash
python3 scripts/check_docs.py
python3 scripts/setup_assets.py status
docker compose config --quiet
```

Validate migrations against both an empty temporary database and a copy of any existing
database. Do not use the working `data/koalabattle.db` as a migration test fixture.

## Adding an engine

Implement `BattleEngine.run(BattleEngineContext) -> EngineOutcome`. Emit normalized events,
request decisions through `Agent`, and return a normalized result. Do not add engine types
to storage, agents, replay, or frontend contracts.
