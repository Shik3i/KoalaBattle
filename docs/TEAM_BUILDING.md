# Team building and validation

KoalaBattle supports custom teams for every custom-team format in the pinned Showdown
registry, for example `gen9ou`, `gen1ou` or `gen4ou`. Random Battle formats remain
Showdown-generated and need no setup. A custom-team format requires one immutable validated
snapshot per player, validated against that exact format, and the
`fixed` team policy.

## Copy-and-paste flow

`/new` carries the whole custom-team workflow, so a match never has to be abandoned to go set
up a team first. Each player block offers **Copy team prompt**, a paste box, and
**Validate and use**.

`POST /api/teams/prompt` renders that prompt. Format facts — display name with generation,
generation number, game type, and which optional mechanics the format actually has — come from
the pinned Showdown catalog rather than the caller, so a copied prompt cannot describe a format
the battle will not run. The caller adds only situational context: opponent name, turn limit,
and, for a tournament, its name, structure, round count, games per series, and whether one team
is reused across series.

The prompt also carries an `export_format` block — the exact Showdown import/export syntax, a
worked example set, and the per-generation rules — because a model asked only for "a team"
returns a species-and-moves sketch that Showdown rejects. Gen 1 and Gen 2 get no ability, item or
nature line and are told to give every stat 252 EVs; later generations get those lines and the
508/252 EV cap. Every generation is told the EV line is mandatory, since an unevved set fails
validation with "did you forget to EV it?".

The two flows describe the same team but ask for the answer differently, because they consume it
differently. The automated builder parses a structured `team` field, so its prompt carries a JSON
`response_schema`. The copy-and-paste prompt asks for the export text and nothing else, since the
reply goes straight into a paste box: a JSON wrapper pasted there reaches Showdown as one escaped
line and fails with `The Pokemon "" does not exist.`, which explains nothing.

Models wrap output anyway, so the import is forgiving as well: a `{"team": "..."}` object or a
fenced block is unwrapped before validation, and only the team inside is judged.

## Import flow

Use `/new`, `/teams`, or `POST /api/teams/validate`. Input is limited to 50,000 UTF-8 bytes and rejects
control characters and unsupported formats before network work. The isolated local validator
passes export text to the pinned Pokémon Showdown `Teams.import`, `TeamValidator`, `Teams.export`,
and `Teams.pack` APIs. KoalaBattle does not recreate legality rules.

Only a valid result can become a `TeamSnapshot`. The row stores original input, normalized
export, packed representation, structured parse, source, format, validation version, and time.
Matches copy the immutable normalized/packed snapshot into their private configuration so
historical execution is attributable to the exact team.

## Explicit AI generation

Generation starts only when the operator selects **Generate team explicitly**. The provider
returns one JSON object containing normal Pokémon Showdown export text. Showdown validates it;
exact validation errors are added to a complete repair prompt. Repairs are bounded to 0–3 and
the default is two. Failed provider calls, raw outputs, validation errors, repair count, usage,
latency, provider/model, and success are retained in a build audit. No snapshot is created for
an invalid final output. `FakeProvider` is the zero-cost deterministic QA path.

Team exports are private local control data. `/watch`, `/overlay`, public WebSocket snapshots,
and public decision DTOs omit snapshot IDs, export text, and packed teams. Protect admin/control
routes before exposing the service outside a trusted local network.

## Tournament policy

Tournament participant snapshots can reference immutable team snapshot IDs. Match templates
carry the format and team policy. Custom-team formats accept fixed teams; per-series rotation or
dynamic counter-teaming is intentionally not implemented.

The `/tournaments/new` match-template step selects any runnable Showdown format, not just Random
Battle. Choosing a custom-team format switches the template to `fixed-per-tournament` and gives
each participant the same prompt/paste/validate controls as `/new`. Because one team carries the
whole run, the copied prompt states the tournament's structure, its round count, the games per
series, and that the team cannot be rebuilt between opponents.

The authoritative real-server gate validates, packs, submits, completes, persists, and replays
a fixed-team match:

```bash
KOALABATTLE_RUN_SHOWDOWN_TEST=1 \
KOALABATTLE_SHOWDOWN_WEBSOCKET_URL=ws://127.0.0.1:8000/showdown/websocket \
KOALABATTLE_TEAM_VALIDATOR_URL=http://127.0.0.1:8002 \
.venv/bin/pytest backend/tests/integration -q
```
