# Release readiness

KoalaBattle 0.11.0 is a self-hosted, pre-1.0 release candidate for local dogfooding. The
supported path is Docker Compose with a Chromium-based browser. The normal application UI may
work in other current browsers, but deterministic offline composition specifically requires a
compatible Chromium/WebCodecs path or the documented FFmpeg fallback.

## Supported workflows

- Every two-player singles format in the pinned Showdown registry, Generations 1-9
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

## Security expectations

KoalaBattle has no application authentication. Admin, team, prompt, provider, match-control,
tournament-control, production, and renderer APIs are trusted-operator surfaces. Do not expose
them directly to the public Internet; use an authenticating reverse proxy and request-size limits.
Public presentation DTOs remove prompts, raw provider responses, context, and fixed-team exports,
but generic match APIs are part of the local control plane. Local/loopback compatible-provider
URLs are intentional for self-hosted models.

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
