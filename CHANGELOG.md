# Changelog

## Unreleased

- added persistent Draft runs with deterministic consumed offers, three Pokémon rerolls plus one
  Type and one Generation reroll,
  automatic Pokémon-specific EV/team preparation, pinned-Showdown validation, and a strict Kanto
  Gym Gauntlet campaign built on normal immutable matches and replays;
- added explicit local CSV/TSV/XLSX draft-board import, provenance hashes, strict form coverage,
  restart recovery, optimistic revisions, and operator documentation; and
- added Tactical Auto as the free local default plus Quick Sim, Fast Watch, Human/LLM alternatives,
  continuous controller-aware campaign progression, compact battle results, safe Pause/Continue,
  browser-native replay controls, retry, battle history, keyboard drafting, and completion UI; and
- hardened pricing integrity verification, AI draft failure boundaries, opponent-team redaction,
  multi-process revision checks, paginated restart recovery, real Showdown content CI, and the
  patched `pip 26.2` runtime build tool; and
- updated DeepSeek for the current `deepseek-v4-flash` and `deepseek-v4-pro` API models after
  retirement of the legacy aliases, with explicit web selectors, documented JSON mode, and V4
  thinking-effort mapping;
- replaced the Kanto Gym Gauntlet content pack (V9) with KoalaBattle-authored competitive teams
  per trainer theme — every opponent set now has a legal ability, nature, held item, EV and IV
  spread, real coverage, and an escalating roster size, all regression-locked and validated by the
  pinned Showdown validator;
- added Normal/Hard/Expert/Nightmare Draft difficulty as a player-only level disadvantage
  (0/-5/-10/-15) persisted in the run's rules snapshot and derived per stage without mutating the
  immutable drafted roster;
- improved automatic team preparation: recommended sets now carry a matching nature and held item,
  and recommended moves are chosen for attacking-category fit and distinct coverage types rather
  than four same-type moves; and
- fixed Draft run states that had no UI: `preparing` no longer offers a launch the backend
  rejects, a persisted run error (including a failed or unreachable automatic team preparation)
  is shown with the editor underneath, and `failed`/`abandoned` runs get an explicit ending with
  a retry and a way out;
- hardened the Draft page against its own polling: out-of-order poll responses can no longer
  overwrite a newer mutation, the client auto-advance fallback fires at most once per deadline,
  and opening a run with a live match no longer bounces the user out of the Draft map;
- added deleting a saved Draft run (cancels its active match, keeps immutable stage replays),
  difficulty on the run history, an explanation for every disabled reroll, and screen-reader-safe
  reels that announce only the settled Generation and Type;
- rebuilt the Draft and battle-control screens around the battle — the renderer is visible without
  scrolling on a laptop viewport, battle-view/OBS actions moved into a compact Tools menu,
  presentation controls collapsed, campaign progress reduced to a compact rail, and the
  Generation/Type roll redesigned as a real inline slot reel with masked edges, staggered
  deceleration, and a lock flash.

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
