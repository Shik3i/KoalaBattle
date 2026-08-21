# KoalaBattle

KoalaBattle is an open-source, self-hosted AI-vs-AI battle production suite. It runs
independent matches concurrently, records immutable replay/audit data, and provides match,
tournament, battle-view, control, and OBS interfaces. Battle formats come from the pinned
local Pokémon Showdown build, not from a KoalaBattle allowlist: every two-player singles
format Showdown ships is runnable, across Generations 1-9. The tournament core consumes
generic participants and results.

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

## What you can do

- Run isolated Random, Manual Web Chat, API, or mixed-agent battles.
- Build durable Single Elimination and Round Robin tournaments with bounded concurrency.
- Draft a budgeted team, train it once, and take it through a persistent Kanto Gym Gauntlet.
- Inspect player-scoped decisions and immutable event history without exposing private context
  to spectator or OBS clients.
- Direct live productions with commentary, free Edge neural speech, captions, music/SFX slots,
  and read-only browser sources.
- Export deterministic landscape or vertical H.264/AAC video from recorded events.
- Re-render any recorded match in a different presentation as often as you like.
- Import or explicitly generate validated custom teams, for any custom-team Showdown format,
  as immutable local snapshots.

## Replay any recorded match, then render it again

A recorded battle is a reusable source, not a one-shot video. Open a replay, press **Create
Video**, and the Video Studio gives you a live preview of the real compositor plus the
settings that shape it:

```text
Recorded match → Video Studio → choose a style → customize → preview → render → MP4
```

One match can carry several independent productions — a YouTube cut, a vertical cut, a
retro cut — and editing one never changes the battle or the others. Customization covers
optional match intros, player logos and accents, custom backgrounds, HUD and commentary
presentation, captions, effects and landscape or vertical output. Good defaults mean
**Create Video → Render** already produces a decent result without touching anything.

KoalaBattle bundles no third-party provider logos; each provider gets an original generated
mark, and any logo you have the rights to can be uploaded locally. Nothing is uploaded or
published anywhere — the MP4 is yours.

Details: [docs/VIDEO_STUDIO.md](docs/VIDEO_STUDIO.md), [docs/THEMES.md](docs/THEMES.md),
[docs/ASSETS.md](docs/ASSETS.md).

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
2. Open `/teams` to import or explicitly generate a legal team snapshot for a custom-team
   format such as Gen 9 OU or Gen 1 OU. Random Battle formats require no team setup.
3. Use `/admin` to inspect capacity, queued/running/waiting matches, Showdown health, costs,
   and active tournaments.
4. Work in two tabs: `/battle/:matchId` is the control view, `/watch/:matchId` is the
   battle-only view. The default 200-turn safety limit can be changed explicitly per match.

Every Manual/API turn receives a fresh, versioned player-scoped knowledge/context snapshot.
Prompts do not depend on provider chat history. Strategy Memory is a bounded replacement note,
not hidden reasoning. Local controls expose decision context inspection; watch/OBS payloads do
not expose prompts, raw responses, context snapshots, or fixed opponent teams. See
[Agent context](docs/AGENT_CONTEXT.md) and [Team building](docs/TEAM_BUILDING.md).

Global concurrency defaults to two active matches. Additional work remains durably queued.
Tournament templates, presets, participants, series, results, costs, and bracket dependencies
are stored in SQLite.

## Draft Challenge

Open `/challenges/new` to draft a persistent six-Pokémon roster and carry it through eight Kanto
Gym Leaders, the Elite Four, and the Champion. Drafting, Training Camp, team validation, stage
history, retries, normal-match control, and replays survive reloads and backend restarts.

The operator must first import an authorized local draft pricing board; none is bundled or
downloaded at startup:

```bash
.venv/bin/python scripts/setup_draft_prices.py import ./my-board.xlsx \
  --board-name "My SV NatDex copy" --sheet Pokedex --price-column "SV NatDex"
.venv/bin/python scripts/setup_draft_prices.py verify
```

Setup, rules, accepted table shapes, form exclusions, controller modes, mechanics assumptions,
and recovery behavior: [Draft Challenge](docs/CHALLENGES.md).

## Battle formats

Formats are discovered from the pinned Pokémon Showdown build at start-up and cached in a
generated snapshot so the app still starts when the container is down:

```bash
docker compose up -d showdown team-validator
python3 scripts/refresh_format_catalog.py   # regenerate the bundled snapshot
curl localhost:8001/api/formats | jq '.format_count, .source'
```

The `/new` format selector is searchable and grouped by generation; `gen 1`, `rby`, `dpp ou`,
`random` and `ou` all work. Each entry states its generation, team source and game type. See
[Battle formats](docs/FORMATS.md).

- **Runnable today**: two-player singles, Generations 1-9 — Random Battles, OU, Ubers, UU, RU,
  NU, PU, LC, Monotype, 1v1 and the rest of Showdown's singles registry.
- **Listed but not runnable**: doubles, triples, multi and free-for-all. KoalaBattle's
  normalized battle state models one active Pokémon per side, so these appear in the selector
  with the reason "Not yet supported by KoalaBattle battle renderer" rather than being hidden
  or silently run through singles-only assumptions.
- **Team source**: Random Battle formats have Showdown generate both teams. Custom-team
  formats require one validated snapshot per player, validated against that exact format.

Prompts and legal actions are generation-aware. A Gen 1 prompt contains no ability, item or
Terastallization fields and no Tera actions, because those mechanics do not exist there.

## Manual Web Chat

Select **Manual Web Chat** for either player. The control view puts the agent's own name at
the top of its workspace, with persistent tabs for both players and their current state, so
you never have to work out which model you are answering for. Copy the player-scoped prompt to
any external web chat, then paste one response back:

```json
{"action":"move:2","commentary":"This legal move best advances the position."}
```

The prompt is a compact, readable text block rather than a raw JSON dump: rules first, then
your active Pokémon and full bench with their moves, the opponent's revealed information,
field state, recent events and self-describing legal actions. It is self-contained, so a
fresh chat with no history can act on it.

Only an ID from the supplied `legal_actions` is accepted. Raw Showdown commands and arbitrary
model text are never executed. See [Manual mode](docs/MANUAL_MODE.md).

## Battle view and control view

The two views are deliberately separate:

| View | URL | Contains |
| --- | --- | --- |
| Control | `/battle/:matchId` | Manual prompts, paste/submit, match lifecycle, audit trail |
| Battle view | `/watch/:matchId` | The battle only: no navigation, no controls, no page scroll |
| OBS overlay | `/overlay/:matchId` | Battle view with transparent-source query options |

The control page exposes **Open battle view**, **Copy battle view URL** and **Copy OBS URL**
so the capture surface never has to be scrolled to paste a response. The battle view fills the
viewport at 1920×1080 and 1080×1920, updates live and reconnects on its own.

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

## Repository map

- `backend/koalabattle/orchestration`: queue, isolated sessions, lifecycle, real-time hub
- `backend/koalabattle/tournaments`: engine-independent brackets, standings, persistence
- `backend/koalabattle/challenges`: pricing snapshots, draft/training domain, campaign ownership
- `backend/koalabattle/engines/showdown`: the only `poke-env` boundary
- `backend/koalabattle/storage`: SQLite match archive and ordering guarantees
- `backend/koalabattle/replay`: pure recorded-event reducer
- `backend/koalabattle/production`: profiles, timelines, speech cache/queue, and director
- `backend/koalabattle/video`: export jobs, queue, OBS/offline exporters, validation, storage
- `backend/koalabattle/formats`: Showdown format catalog, capability rules, generated snapshot
- `frontend`: SvelteKit admin, control, battle view, replay, tournament, and OBS UI
- `scripts/setup_assets.py`: explicit third-party asset installer/status tool
- `scripts/benchmark_orchestration.py`: local replay, archive, tournament, and scheduler baseline
- `showdown`: reproducibly pinned local engine image

KoalaBattle source is licensed under the [MIT License](LICENSE). Pokémon Showdown, `poke-env`,
optional Pokémon media, generated media, and operator-provided content retain their own terms;
none of the optional sprite pack is covered by this repository's MIT license. Release status
and intentional limits: [Release readiness](docs/RELEASE_READINESS.md). Changes:
[Changelog](CHANGELOG.md).
