# Changelog

## Unreleased

- added persistent Draft Challenge runs with deterministic budget-safe offers, Training Camp EV
  allocation, pinned-Showdown team validation, direct Human Player control, and a versioned Kanto
  Gym Gauntlet campaign built on normal immutable matches and replays;
- added explicit local CSV/TSV/XLSX draft-board import, provenance hashes, strict form coverage,
  restart recovery, optimistic revisions, and operator documentation; and
- added a first-class Challenge setup, campaign map, draft, roster, training, team-review, stage,
  retry, complete battle history, keyboard drafting, and completion UI; and
- hardened pricing integrity verification, AI draft failure boundaries, opponent-team redaction,
  multi-process revision checks, paginated restart recovery, real Showdown content CI, and the
  patched `pip 26.2` runtime build tool.

## 0.11.0 - 2026-08-20

- replaced placeholder product branding with a dedicated KoalaBattle mark and Phosphor UI icons;
- added a reduced-motion-aware interaction system, stronger navigation, focus, loading, and
  responsive feedback;
- aligned battle HP/status cards with familiar competitive-battle readability while preserving
  the original asset-free Verdant Circuit presentation;
- added live intro/result cards, final-Pokémon escalation, readable team strips, persistent
  sprite motion, corrected switch/move animation sequencing, and move-specific effect recipes;
- added highlight-aware pacing, synchronized live speech/captions, post-match interviews,
  sample-based SFX support, and distinct configurable Qwen voice personas;
- added manual move/switch controls plus runtime OpenAI, Gemini, Anthropic, DeepSeek, and generic
  OpenAI-compatible provider configuration and model discovery;
- corrected speech-provider labels, renderer configuration broadcasting, export-preflight status
  semantics, and static type/lint findings; and
- reorganized newcomer documentation and added opt-in, gitignored asset/SFX/effect installers
  with explicit provenance and licensing boundaries.

## 0.10.0 - 2026-08-16

Release-candidate baseline for local dogfooding:

- isolated Random, Manual Web Chat, and API-agent battles with player-scoped context;
- fixed Gen 9 OU teams, durable concurrent scheduling, tournaments, and deterministic replay;
- reconnecting live control, spectator, admin, and tournament streams with backlog-aware pacing;
- optional local sprites, free Edge neural speech with offline fallback, captions, production
  audio, and OBS browser sources;
- deterministic native landscape and vertical H.264/AAC video export; and
- release documentation, consistent versioning, safer first-match defaults, and test-provider
  separation.

No Pokémon artwork, audio, generated media, API credentials, or runtime database is distributed.
