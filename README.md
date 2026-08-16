# KoalaBattle

KoalaBattle is an open-source, self-hosted AI-vs-AI battle production suite. It runs
independent matches concurrently, records immutable replay/audit data, and provides match,
tournament, watch, control, and OBS interfaces. Pokémon Showdown supports Gen 9 Random
Battle and validated fixed-team Gen 9 OU; the tournament core consumes generic participants
and results.

The deterministic Canvas/WebCodecs compositor creates H.264/AAC landscape and vertical video
without rerunning Showdown or battle LLMs. Live watch and OBS views reconnect automatically;
stored events, optional local assets, and cached audio remain the source of truth.

Supported agents: Random, Manual Web Chat, OpenAI, Gemini, Anthropic, DeepSeek, and generic
OpenAI-compatible providers. Manual Web Chat needs no API key.

Free Edge neural voices are the production-audio default; they need Internet access but no API
key and receive only public commentary. Basic offline system speech and completely silent
production remain available.

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

The stack contains the SvelteKit UI, FastAPI backend, SQLite, free Edge neural speech with an
`espeak-ng` offline fallback, a
local Pokémon Showdown server,
and an isolated Showdown team-validator service. Showdown is pinned to
`b22742debfdce6e640193384f5731b9030f9cb6e`; the backend pins
`poke-env==0.15.0`. Pins keep the private protocol bridge reproducible and are upgraded only
with the real-server integration gate.

Optional reproducible offline renderer (Chromium, Playwright, FFmpeg):

```bash
docker compose --profile renderer up --build
```

## First run

1. Open `/new` for a standalone match or `/tournaments/new` for the ten-step tournament
   wizard.
2. Open `/teams` to import or explicitly generate a legal Gen 9 OU team snapshot. Random
   Battle requires no team setup.
3. Use `/admin` to inspect capacity, queued/running/waiting matches, Showdown health, costs,
   and active tournaments.
4. Use `/watch/:matchId` for a spectator-safe view and `/battle/:matchId` for local production
   control. The default 200-turn safety limit can be changed explicitly per match.

Every Manual/API turn receives a fresh, versioned player-scoped knowledge/context snapshot.
Prompts do not depend on provider chat history. Strategy Memory is a bounded replacement note,
not hidden reasoning. Local controls expose decision context inspection; watch/OBS payloads do
not expose prompts, raw responses, context snapshots, or fixed opponent teams. See
[Agent context](docs/AGENT_CONTEXT.md) and [Team building](docs/TEAM_BUILDING.md).

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

Audio follows browser autoplay policy: open the source once and choose **Enable audio**. A
production timeline must exist for that match. Cached speech stays available without the
original provider; captions remain available when speech or media is missing. See
[Production](docs/PRODUCTION.md), [Audio](docs/AUDIO.md), [TTS](docs/TTS.md), and
[Captions](docs/CAPTIONS.md).

## Video export

- Live streaming: OBS Browser Source.
- Realtime recording: automated OBS WebSocket v5 recorder; a ten-minute production takes
  about ten minutes to record.
- Fast/batch production: deterministic Offline Renderer; no OBS or visible desktop required.

Open a replay, choose/create a finalized Production, then use **Render & recording jobs**.
Generated MP4/SRT/JSON files stay in ignored `data/videos/`. Install host renderer support
with `.venv/bin/pip install -e './backend[renderer]'`; an existing compatible Chrome/Chromium
and FFmpeg/FFprobe must be available. CLI example:

```bash
.venv/bin/python -m koalabattle.video.cli render match MATCH_ID --preset youtube-1080p60 --wait
```

Details: [Video export](docs/VIDEO_EXPORT.md),
[Offline renderer](docs/OFFLINE_RENDERER.md), and
[OBS recording](docs/OBS_RECORDING.md).

On the measured macOS development host, the native compositor rendered 27.617 s of 1080p60
media in 17.673 s (`1.562x` realtime including job overhead); the corresponding compositor,
encode, and mux span reached `2.021x`. See [Performance](docs/PERFORMANCE.md) for methodology,
vertical and long-video results, and platform limits.

## Persistent data and backups

`data/koalabattle.db` contains match/tournament history, events, decisions, templates, and
presets. `data/assets/` contains optional media; `data/audio/` contains generated speech;
`data/vendor/` contains its installer manifest; `data/videos/` contains generated video,
captions, and manifests. Stop writers or use SQLite's backup API before copying the database;
back up these paths if local media must be reproducible. Replays are derived from stored events and
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
- `backend/koalabattle/production`: profiles, timelines, speech cache/queue, and director
- `backend/koalabattle/video`: export jobs, queue, OBS/offline exporters, validation, storage
- `frontend`: SvelteKit admin, control, watch, replay, tournament, and OBS UI
- `scripts/setup_assets.py`: explicit third-party asset installer/status tool
- `showdown`: reproducibly pinned local engine image

KoalaBattle source is licensed under the [MIT License](LICENSE). Pokémon Showdown, `poke-env`,
optional Pokémon media, generated media, and operator-provided content retain their own terms;
none of the optional sprite pack is covered by this repository's MIT license. Release status
and intentional limits: [Release readiness](docs/RELEASE_READINESS.md). Changes:
[Changelog](CHANGELOG.md).
