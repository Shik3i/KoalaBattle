# Draft Challenge mode

Draft Challenge is a persistent solo campaign above the normal match engine. The first bundled
definition is **Kanto Gym Gauntlet**: six drafted Pokémon, one shared EV budget, the exact
Pokémon Red/Blue rosters and moves for all eight Kanto Gym Leaders, the Elite Four, and Champion
Blue. Every stage creates a normal immutable KoalaBattle match and replay.

The V2 content pack uses the English Pokémon Red/Blue teams. Champion Blue uses the documented
variant for a player who chose Bulbasaur. Species order, source levels, and moves are sourced
from Bisafans and Serebii and regression-locked. Source levels remain stored in the private team
definitions; the actual Challenge fight still applies the campaign's equal level curve to both
sides. Generation I had no abilities, natures, held items, or modern EVs, so the modern Showdown
adapter adds only a legal explicit ability and the non-stat-changing EV confirmation marker.
It does not replace recorded Pokémon or moves.

## Install a pricing board

KoalaBattle does not bundle, scrape, or silently refresh a third-party draft board. Make or
obtain a board copy that you are allowed to use, then import the local `.csv`, `.tsv`, or `.xlsx`
file explicitly:

```bash
.venv/bin/python scripts/setup_draft_prices.py import ./my-board.xlsx \
  --board-name "My SV NatDex copy" \
  --sheet Pokedex \
  --price-column "SV NatDex" \
  --mechanics-assumption "No Tera, Mega Evolution, Z-Moves, or Dynamax actions"
.venv/bin/python scripts/setup_draft_prices.py verify
.venv/bin/python scripts/setup_draft_prices.py status
```

An explicit Google Sheets document URL is also supported:

```bash
.venv/bin/python scripts/setup_draft_prices.py import \
  --url "https://docs.google.com/spreadsheets/d/DOCUMENT_ID/edit" \
  --board-name "My authorized copy" \
  --price-column "SV NatDex"
```

The importer performs one requested download. Application startup never downloads pricing. Raw
input plus normalized `catalog.json` stay in ignored `data/draft-prices/`; `verify` checks both
the raw source SHA-256 and the normalized catalog hash. A missing, changed, or tampered source
blocks new runs until it is re-imported. Re-importing affects new runs only because every run
snapshots its full catalog, hash, rules, definition version, controllers, and seed.

The table must have a `Pokemon`, `Pokémon`, `Species`, or `Name` column and one exact price
column. Prices are positive integer Draft Credits. Empty cells remain explicitly missing;
`ban`, `banned`, `unavailable`, `not available`, `n/a`, `na`, and `-` remain explicitly banned.
Duplicate normalized species/form names, ambiguous columns, unrecognized tier text, and invalid
files fail closed. The setup screen reports unmatched, banned, missing, temporary, cosmetic,
Mega, and Gigantamax rows instead of silently treating them as legal picks.

## Run the campaign

1. Start `showdown`, `team-validator`, `backend`, and `frontend`.
2. Open `/challenges/new` and choose draft, player-battle, and opponent controllers independently.
3. Draft one candidate from each deterministic offer. Offers contain up to three choices and
   safely shrink only when the remaining Generation + Type pools are exhausted. Number keys
   `1`–`8` select the corresponding visible choice. A refresh or backend restart returns the same
   persisted offer. A reroll consumes one persisted reroll.
4. Allocate the shared EV budget. The backend enforces the configured global, per-Pokémon, and
   per-stat limits.
5. Complete the generated Showdown roster scaffold. Finalization requires the exact drafted
   forms and exact EV allocation and passes the result through the pinned Showdown validator.
6. Launch the current stage. A win advances; loss, draw, cancellation, interruption, or engine
   failure records a stage result and leaves that same stage retryable.

`Human Player` is a direct control surface: the battle page submits only an action ID from the
current pending legal-action set. It is distinct from `Manual Web Chat`, which retains the
copy/paste JSON workflow. API agents, random agents, and both manual modes use the existing
isolated match orchestration, audit, replay, cost, queue, and cancellation paths.

An AI draft waits for one provider decision per round. A failed decision can be retried without
changing the saved offer, or the user can take over the remaining draft. Takeover archives the
original controller and invalidates any late AI response through the run revision check.

## Rules and mechanics

Bundled defaults: six picks, 68 Draft Credits, two rerolls, three choices per round, Species
Clause, a global 1200-EV budget, 510 EVs per Pokémon, and 252 EVs per stat. Draft pools are
grouped by introduction generation plus current type and only contain exact pinned-Showdown
forms covered by the imported context. Every offered choice is checked for a feasible completion
of the remaining roster before it is shown.

The bundled definition inherits Gen 9 NatDex Draft through
`gen9koalabattlecanonicalnatdexdraft`. It repeals only the OHKO and evasion clauses that would
otherwise reject recorded Red/Blue moves or required modern compatibility abilities. Challenge
matches deliberately disable special gimmick actions. Campaign level scaling rewrites both teams
to the stage's exact level.
For an intentional zero spread, final validation adds Showdown's harmless one-HP-EV confirmation
marker only to the derived validated export. At levels below 100, a derived stage snapshot may add
the same remainder when every allocated EV is divisible by four. Neither changes a battle stat or
the run's source Training Camp allocation. Level scaling never changes draft cost, move legality,
or Species Clause. Opponent exports remain private in Challenge and linked match API payloads.

## Recovery and ownership

Challenge state lives in `challenge_runs`; each stage match stores `challenge_run_id` and
`challenge_stage_id`. Startup reconciles terminal, interrupted, or missing linked matches. Runs
use database-level optimistic revisions plus per-run locks, so stale or duplicate
pick/reroll/training/launch requests are rejected even across multiple application processes.
Cancelling a run cancels its active normal match through the existing supervisor.

Campaign content is versioned data in
`backend/koalabattle/challenges/content/kanto-gym-gauntlet.json`. Change its version whenever
rules, stages, levels, or teams change; existing runs retain their original snapshot.
Every future regional pack must declare one exact source game, generation, and battle variant;
teams from different appearances or rematches must never be merged into an invented roster.

Bundled Kanto references:

- <https://www.bisafans.de/spiele/editionen/rot-blau/arenaleiter.php>
- <https://www.serebii.net/rb/gyms.shtml>
- <https://www.serebii.net/rb/elitefour.shtml>

## Current limitations

- Pricing imports intentionally require an exact price column. Public community boards change
  layout and terminology over time, so KoalaBattle does not guess tier-to-credit conversions or
  pin a third-party board URL. Copy/adapt the relevant sheet, then pass its exact sheet and column
  names to the importer.
- Mega, Gigantamax, battle-only, cosmetic-only, unavailable, and unmatched form rows are reported
  but excluded. Challenge battles also disable Terastallization; Z-Moves, Mega Evolution, and
  Dynamax actions are not part of Challenge mode.
- The completion summary reports progress, record, battles, technical failures, duration, turns,
  roster, credit use, rerolls, EV use, and aggregate provider latency/cost. It does not yet
  calculate campaign MVPs.
- Every stage keeps its normal per-match replay and video artifacts. Challenge mode does not yet
  concatenate them into one campaign-length video or add a separate campaign reward economy.
