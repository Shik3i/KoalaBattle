# KoalaBattle

KoalaBattle is an open-source, self-hosted AI-vs-AI battle production suite. It runs
independent matches concurrently, records immutable replay/audit data, and provides match,
tournament, watch, control, and OBS interfaces. The first engine is Pokémon Showdown Gen 9
Random Battle; the tournament core consumes generic participants and results.

Supported agents: Random, Manual Web Chat, OpenAI, Gemini, Anthropic, DeepSeek, and generic
OpenAI-compatible providers. Manual Web Chat needs no API key.

KoalaBattle is not affiliated with Nintendo, Game Freak, The Pokémon Company, Smogon, or
Pokémon Showdown. No Pokémon artwork, sprites, audio, or other third-party media is bundled.

## Docker quick start

Requirements: Docker with Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:3000>; API docs: <http://localhost:8001/docs>. If port 3000 is in
use, set `KOALABATTLE_FRONTEND_PORT=3001` in `.env`.

The stack contains the SvelteKit UI, FastAPI backend, SQLite, and a local Pokémon Showdown
server. Showdown is pinned to `b22742debfdce6e640193384f5731b9030f9cb6e`; the backend pins
`poke-env==0.15.0`. Pins keep the private protocol bridge reproducible and are upgraded only
with the real-server integration gate.

## First run

1. Open `/new` for a standalone match or `/tournaments/new` for the ten-step tournament
   wizard.
2. Use `/admin` to inspect capacity, queued/running/waiting matches, Showdown health, costs,
   and active tournaments.
3. Use `/watch/:matchId` for a spectator-safe view and `/matches/:matchId/control` for local
   production control.

Global concurrency defaults to two active matches. Additional work remains durably queued.
Tournament templates, presets, participants, series, results, costs, and bracket dependencies
are stored in SQLite.

## Manual Web Chat

Select **Manual Web Chat** for either player. Copy the player-scoped prompt to any external
web chat, then paste one response into that same match workspace:

```json
{"action":"move:2","commentary":"This legal move best advances the position."}
```

Only an ID from the supplied `legal_actions` is accepted. Raw Showdown commands and arbitrary
model text are never executed. See [Manual mode](docs/MANUAL_MODE.md).

## Optional sprites

A fresh checkout tracks no sprite files. KoalaBattle renders built-in placeholders unless the
operator explicitly installs third-party Pokémon Showdown assets into the ignored runtime
directories:

```bash
python3 scripts/setup_assets.py status
python3 scripts/setup_assets.py install                # static front/back
python3 scripts/setup_assets.py install --profile full # plus animated front/back
python3 scripts/setup_assets.py verify
```

Downloaded files live only under ignored `data/assets/` and `data/vendor/`. They are not
covered by KoalaBattle's MIT license. Read [Assets and rights](docs/ASSETS.md) before use.

## OBS

Match source: `/overlay/:matchId`. Tournament source: `/overlay/tournament/:tournamentId`.
Both are read-only and support transparent browser-source layouts. Presets and query options:
[OBS guide](docs/OBS.md).

## Persistent data and backups

`data/koalabattle.db` contains match/tournament history, events, decisions, templates, and
presets. `data/assets/` contains optional media; `data/vendor/` contains its installer
manifest. Stop writers or use SQLite's backup API before copying the database; back up all
three paths if local media must be reproducible. Replays are derived from stored events and
have no separate required file store.

## Development and checks

Requirements: Python 3.12+, Node.js 22+, npm, Docker Compose v2.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e './backend[dev]'
cd backend && ../.venv/bin/alembic upgrade head
cd ../frontend && npm ci
```

```bash
cd backend && ../.venv/bin/ruff check . && ../.venv/bin/mypy koalabattle && ../.venv/bin/pytest
cd frontend && npm test && npm run check && npm run build
python3 scripts/check_docs.py
```

Details: [Development](docs/DEVELOPMENT.md). Documentation index: [docs/README.md](docs/README.md).

## Project map

- `backend/koalabattle/orchestration`: queue, isolated sessions, lifecycle, real-time hub
- `backend/koalabattle/tournaments`: engine-independent brackets, standings, persistence
- `backend/koalabattle/engines/showdown`: the only `poke-env` boundary
- `backend/koalabattle/storage`: SQLite match archive and ordering guarantees
- `backend/koalabattle/replay`: pure recorded-event reducer
- `frontend`: SvelteKit admin, control, watch, replay, tournament, and OBS UI
- `scripts/setup_assets.py`: explicit third-party asset installer/status tool
- `showdown`: reproducibly pinned local engine image

Licensed under the [MIT License](LICENSE).
