# Draft mode

Draft is a persistent solo campaign above the normal match engine. The first bundled
definition is **Kanto Gym Gauntlet**: six drafted Pokémon with automatic recommended EVs, the exact
Pokémon Red/Blue rosters and moves for all eight Kanto Gym Leaders, the Elite Four, and Champion
Blue. Every stage creates a normal immutable KoalaBattle match and replay.

The V8 content pack uses the English Pokémon Red/Blue teams. Champion Blue uses the documented
variant for a player who chose Bulbasaur. Species order, source levels, and moves are sourced
from Bisafans and Serebii and regression-locked. Source levels remain stored in the private team
definitions; the actual Draft fight applies the campaign's equal level curve to both sides.
Generation I had no abilities, natures, held items, or modern EVs. The modern battle adapter adds
only format-required compatibility data; it never replaces a recorded Pokémon or move.
The Draft-only format also removes Showdown's `Obtainable Misc` event-origin minimum-level
check so any otherwise legal drafted Pokémon can be normalized to the same campaign stage level.
Learnsets, abilities, forms, Species Clause, EVs, and the finalized roster remain validated.

## Run the campaign

1. Start `showdown`, `team-validator`, `backend`, and `frontend`.
2. Open `/challenges/new` and choose who drafts, who battles, and whether to Quick Sim, Fast Watch,
   or use normal presentation. Tactical Auto is the default and requires no provider.
3. Draft one candidate from each deterministic Generation + Type offer. Every species shown in
   the offer is consumed for the remainder of the run, whether selected or rejected.
4. Use each optional reroll once: Pokémon keeps Generation + Type, Type keeps Generation, and
   Generation keeps Type. Every replaced card is still consumed permanently.
5. The sixth pick automatically applies Pokémon-specific recommended EVs and abilities, generates
   up to four practical legal moves, validates the team, and prepares the first stage. Advanced
   team setup remains optional before Brock.
6. Fully automatic controllers launch the first stage immediately and continue after each short
   result countdown. Pause Auto-Run stops before the next match; Continue Run resumes exactly once.
   Human or Manual Web Chat controllers always retain their explicit launch and turn controls.
7. A win advances; loss, draw, cancellation, interruption, or engine failure records a stage
   result and leaves that same stage retryable. Every result links to an interactive browser replay.

Number keys `1`–`8` select visible draft choices. A refresh or backend restart restores the exact
offer, consumed identities, selections, controller decisions, and draft history. A failed AI
decision can be retried without changing the offer, or the user can take over the remaining
draft. The optimistic revision check rejects late AI responses after takeover.

## Draft Rules V2

Bundled defaults: six picks, three Pokémon rerolls, one Type reroll, one Generation reroll,
three choices per round, Species Clause, 510 EVs per
Pokémon, and 252 EVs per stat. There is no shared team EV pool. No Draft Credits, Pokémon prices,
pricing board, tier conversion, or pricing prerequisite exists.

The pool is an immutable snapshot of the pinned Showdown Dex for the Draft format. Every
candidate stores the exact Showdown form ID, authoritative base-species identity, introduction
generation, current types, base stats, and legal format abilities. Temporary, cosmetic,
unavailable, Mega, and Gigantamax forms are excluded. Species Clause consumes the authoritative
base-species identity, preventing alternate forms of the same species from returning later.

Offer generation is deterministic from the definition/version, rules version, seed, round,
nonce, exact pool hash, pinned Showdown version, and sorted consumed identities. A new offer is
persisted atomically with all displayed identities marked consumed. The generator only chooses
Generation + Type buckets that leave enough unseen identities to complete the roster. It reduces
the offer count only when the remaining legal pool cannot supply the configured count without
creating a dead end. If no safe offer exists, the request fails closed without mutating the run.

The lightweight draft history stores each complete offer, its pick or reroll outcome, selected
entry when applicable, controller, and timestamp. It is intentionally part of the run snapshot
rather than reconstructed from the final roster.

## Abilities and team validation

The team-validator service supplies legal abilities from `Dex.forFormat(format)`. Formats in
Generations I and II expose no ability mechanics. One-ability forms are selected automatically;
multiple regular/secondary/hidden abilities are shown explicitly and the selected Showdown ID is
persisted in the run.

Automatic finalization requires an ability selection for every drafted entry when abilities are
supported.
The backend applies those exact selections to the submitted team before validation, rejects an
ability not legal for that exact form and format, and checks the structured validator response
against the persisted selections. It also requires the exact drafted forms and recommended EV
allocation. The pinned Showdown validator is authoritative.

The bundled definition inherits Gen 9 NatDex Draft through
`gen9koalabattlecanonicalnatdexdraft`. It repeals only the clauses required for recorded
Red/Blue moves or compatibility data. Challenge matches disable special gimmick actions.
Campaign level scaling rewrites both teams to the stage's exact level.

For an intentional zero spread, final validation adds Showdown's harmless one-HP-EV confirmation
marker only to the derived validated export. At levels below 100, a derived stage snapshot may add
the same remainder when every allocated EV is divisible by four. Neither changes a battle stat or
the run's source recommended EV allocation.

## Recovery, versioning, and ownership

Challenge state lives in `challenge_runs`; each stage match stores `challenge_run_id` and
`challenge_stage_id`. Startup resumes interrupted automatic team preparation and reconciles
terminal, interrupted, or missing linked matches. Auto-Run deadlines and paused state are persisted;
the backend performs the idempotent next-stage launch, while browser countdowns are presentation only. Runs
use database-level optimistic revisions plus per-run locks, so stale or duplicate
pick/reroll/training/ability/finalize/launch requests are rejected across application processes.
Cancelling a run cancels its active normal match through the existing supervisor.

Draft Rules V2 runs use Challenge schema `2.0` and `draft-rules-v2`. Active Draft Rules V1 runs
are not silently reinterpreted: the repository migrates them into an explicit read-only
`abandoned` state with `draft-rules-v1-incompatible` and a compatibility notice. Their saved
roster and metadata remain inspectable, but continuing requires a new run.

Campaign content is versioned data in
`backend/koalabattle/challenges/content/kanto-gym-gauntlet.json`. Change its version whenever
rules, stages, levels, or teams change; existing V2 runs retain their complete definition and
pool snapshots. Every regional pack must declare one exact source game, generation, and battle
variant; teams from different appearances or rematches must never be merged.

The V8 stage metadata maps each opponent to its exact Red/Blue trainer sprite identifier.
`scripts/setup_assets.py install --profile full` installs those 13 portraits below ignored
`data/assets/trainers/`. The UI animates installed sprites and retains a deterministic fallback
when optional local media is absent.

Bundled Kanto references:

- <https://www.bisafans.de/spiele/editionen/rot-blau/arenaleiter.php>
- <https://www.serebii.net/rb/gyms.shtml>
- <https://www.serebii.net/rb/elitefour.shtml>

## Current limitations

- Mega, Gigantamax, battle-only, cosmetic-only, and unavailable forms are excluded. Challenge
  battles also disable Terastallization; Z-Moves, Mega Evolution, and Dynamax actions are not part
  of Challenge mode.
- The completion summary reports progress, record, battles, technical failures, duration, turns,
  roster, consumed species, rerolls, EV use, and aggregate provider latency/cost. It does not yet
  calculate campaign MVPs.
- Every stage keeps its normal per-match replay and video artifacts. Challenge mode does not yet
  concatenate them into one campaign-length video or add a separate campaign reward economy.
