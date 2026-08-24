# Release readiness

KoalaBattle 0.11.0 is a self-hosted, pre-1.0 release candidate for local dogfooding. The
supported path is Docker Compose with a Chromium-based browser. The normal application UI may
work in other current browsers, but deterministic offline composition specifically requires a
compatible Chromium/WebCodecs path or the documented FFmpeg fallback.

## Supported workflows

- Every two-player singles format in the pinned Showdown registry, Generations 1-9
- Persistent six-Pokémon Draft and regional Gauntlet runs with real Showdown-backed species,
  legal recommended sets, fixed-HP overrides, deterministic offers, and normal stored battles
- Random, Manual Web Chat, OpenAI, Gemini, Anthropic, DeepSeek, and OpenAI-compatible agents
- Single Elimination and Round Robin tournaments with durable concurrent scheduling
- spectator-safe watch/replay and match/tournament OBS browser sources
- free Edge neural speech, basic offline system fallback, captions, optional operator audio, and
  silent production
- deterministic 1920x1080 and 1080x1920 H.264/AAC export

Paid LLM or speech providers are never called by startup or by Random/Manual workflows. Provider
credentials are optional backend-only configuration. The deterministic Fake provider is disabled
by default and appears only as a Development / Testing choice when explicitly enabled.
DeepSeek uses the current `deepseek-v4-flash` and `deepseek-v4-pro` model IDs; the retired
`deepseek-chat` and `deepseek-reasoner` aliases are not offered. Contract tests cover both V4
models, JSON mode, thinking effort mapping, environment status, and credential redaction without
making a paid provider call.

## External dependencies and assets

Docker Compose starts pinned Pokémon Showdown and its isolated validator. Host rendering requires
the documented Chromium and FFmpeg/FFprobe capabilities. KoalaBattle contains no Pokémon sprites,
artwork, music, or sound effects. `scripts/setup_assets.py` is an explicit opt-in downloader;
downloaded media is ignored, not MIT-licensed by KoalaBattle, and remains the operator's
responsibility. Edge neural speech requires Internet access and sends public commentary to
Microsoft; disable it for strict offline operation. The offline fallback is intentionally basic.

## Validated environment

The release-candidate gate was run on macOS 26.5.2 ARM64 with Google Chrome 151.0.7922.138,
FFmpeg 8.1.2, Docker Engine 29.4.0, and Docker Compose 5.1.2. A 30-second 1920x1080/60 sample
rendered on the native host path in 11.391 seconds (`2.634x` realtime wall speed; `3.256x`
measured compositor/encode/mux speed) with no asset failures. The Docker renderer's compatible
raw-RGBA fallback remains valid but may render below realtime on ARM64.

The focused 2026-08-22 Draft mechanics and presentation gate passed Ruff, Mypy, 276 backend tests
with 21 opt-in/environment tests skipped, 6 explicit real-Showdown integration tests, 105 frontend
tests, Svelte diagnostics with zero errors or warnings, and the production frontend build. Browser
QA covered active, completed legacy, and invalid Draft routes plus a completed battle at 390x844:
no console errors or horizontal overflow, and visible interactive controls use at least a 44 px
touch dimension. The release-polish browser pass additionally covered 1440x900, 1024x768, and
390x844. With histories closed, the completed battle shrank from 5,885 px to 1,004 px at desktop
and rendered zero decision records until its audit drawer opened; the active Draft shrank from
1,387 px to 1,034 px. Mobile uses an internal scroll-snap Draft row and retained a 390 px document
width. The current pinned catalog measured 1,216 validated draftable entries out of 1,417 forms.

The completed 2026-08-22 evolution, rarity, Mega Evolution, and release-polish pass passed Ruff,
Mypy, 297 backend unit tests, all 18 real-Showdown integration tests, 105 frontend tests, 3 real
Chromium Playwright flows, Svelte diagnostics with zero errors or warnings, and the production
frontend build. The Kanto campaign's level curve changed to 10/30/35/40/45/50/55/60/68/76/84/92/100;
difficulty now only raises the opponent above that curve (`+0/+5/+10/+15`, capped at 100) instead
of lowering the player, and every drafted species' recommended set is now built and validated at
level 10 — a full sweep of all 1,216 draftable entries found zero illegal at their assigned level
(previously up to 62 were illegal depending on difficulty). The primary navigation was reduced to
Home/Battle/Draft with a utility menu for Dashboard/Tournaments/Teams/Settings. Draft candidates
now use a locally pinned Smogon Draft Points snapshot and five deterministic weighted rarity
tiers. Evolution choices and the final Mega choice are persisted in the run, and the real
Showdown integration proves that a selected Mega action produces a `|-mega|` event.

The Battle control page now consumes the public presentation DTO by default and loads the private
decision archive only when the audit drawer is opened. On a measured local match, this reduced the
initial response from 2,090,395 bytes to 520,639 bytes (75.1%). Earlier Lighthouse measurements
predate this payload fix and must not be treated as current post-fix scores; rerun Lighthouse in
the target deployment environment before making a performance-score claim.

## Security expectations

Admin, team, prompt, provider, match-control, tournament-control, production, and renderer APIs
are trusted-operator surfaces. Setting `KOALABATTLE_API_TOKEN` requires
`Authorization: Bearer <token>` on every mutating and audit-exposing endpoint, and `?token=` on
the websocket streams; the operator enters the same value once per browser under
**Settings → Operator access**. It is deliberately not a `PUBLIC_` build variable, because the
frontend bundle is served to anyone who can reach its port. Unset (the default) leaves the API
open and logs a warning at startup, which is fine while every published port stays on
`127.0.0.1` — the compose default. Set the token before widening `KOALABATTLE_BIND_HOST`, and
still prefer a reverse proxy for TLS and request-size limits.

Public presentation DTOs remove prompts, raw provider responses, context, and fixed-team exports,
but generic match APIs are part of the local control plane. Provider base URLs reject non-HTTP(S)
schemes and the link-local metadata range; loopback and LAN URLs stay allowed because
self-hosted models are the intended use.

## Known limitations

- Real OBS integration is environment-dependent; use the browser-source protocol tests and
  Chromium overlay QA when OBS is unavailable.
- Edge neural TTS is an unofficial online service integration without an availability SLA; the
  fully offline system fallback has visibly lower voice quality.
- Only two-player singles formats are supported. Doubles, triples, multi and free-for-all are
  listed in the format selector with an explicit unsupported reason.
- The isolated pinned Showdown tree has documented upstream dependency findings; compatibility
  upgrades require the real-engine integration gate rather than a blind major audit fix.
- Native WebCodecs capability differs by host/container. The renderer probes actual encoding and
  falls back to bounded raw RGBA plus FFmpeg where necessary.
- There is no publishing, upload, account, rating, or public multi-tenant subsystem.

## Release checklist

Before distributing a commit: run all backend/frontend/docs gates, explicit real Showdown tests,
fresh and current-copy migrations plus SQLite integrity, Docker health, asset status/verification,
dependency audits, renderer cancellation/output validation, desktop/mobile browser QA, full
landscape/vertical video review, `git diff --check`, staged secret/media inspection, and normal
fast-forward Git synchronization. Generated assets, audio, videos, databases, caches, builds,
renderer temporary files, `.env`, tags, releases, and deployments are not release artifacts.
