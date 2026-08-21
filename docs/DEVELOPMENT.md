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

- unit: contracts, lifecycle, scheduling races, generic tournaments, draft challenges,
  validation, agents, assets
- storage: SQLite migrations, ordering, audit, tournament persistence, reopen/recovery
- integration: two concurrent real Gen 9 Random Battles, real Gen 1 and Gen 9 Random Battles,
  a validated imported-team Gen 1 OU battle, a live-vs-snapshot format catalog check, plus one
  validated fixed-team Gen 9 OU
  battle with parse/pack/completion/persistence/replay, and every Kanto Gym Gauntlet stage team
  at its authored level
- presentation: Node tests for reducer restoration and deterministic scheduler operations
- frontend: `npm test`, Svelte diagnostics, production build, and rendered browser QA

Enable the real battle test only with `KOALABATTLE_RUN_SHOWDOWN_TEST=1`; this prevents an
accidental connection during ordinary unit checks.

To look at a page rather than assert about it, screenshot it from inside the renderer
container, which already holds Chromium and Playwright:

```bash
docker compose cp scripts/shoot.py renderer:/tmp/shot.py
docker compose exec renderer python /tmp/shot.py MATCH_ID          # every page
docker compose exec renderer python /tmp/shot.py MATCH_ID watch    # one page
```

Images land in ignored `data/videos/shots/`. The script also prints console errors, page
errors and failed requests per page. It reaches the app over Docker-internal origins, which is
not a secure context, so it catches browser APIs that silently only work on localhost. No
browser is started on the host.

Run documentation/setup checks from the repository root:

```bash
python3 scripts/check_docs.py
python3 scripts/setup_assets.py status
docker compose config --quiet
PYTHONPATH=backend .venv/bin/python scripts/benchmark_orchestration.py
PYTHONPATH=backend .venv/bin/python scripts/benchmark_renderer.py PRODUCTION_ID \
  --preset youtube-1080p60 --encoder software --workers 4
```

Validate migrations against both an empty temporary database and a copy of any existing
database. Do not use the working `data/koalabattle.db` as a migration test fixture.

The repository-root `data/` directory is canonical. `backend/data/` is a legacy ignored
working-directory artifact, not a second database location. Generated assets, speech, music,
sound packs, videos, renderer temp files, and vendor downloads remain ignored and untracked.

Frontend production and development audits are separate. `cookie@0.7.2` is an explicit safe
override for the SvelteKit dependency tree. The pinned upstream Showdown image has known audit
findings; do not force major upgrades without the real-server gates. Details and measured limits:
[Security](SECURITY.md) and [Performance](PERFORMANCE.md).

## Adding an engine

Implement `BattleEngine.run(BattleEngineContext) -> EngineOutcome`. Emit normalized events,
request decisions through `Agent`, and return a normalized result. Do not add engine types
to storage, agents, replay, or frontend contracts.
