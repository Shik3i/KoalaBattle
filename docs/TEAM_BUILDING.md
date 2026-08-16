# Team building and validation

KoalaBattle supports custom teams for `gen9ou`. Random Battle remains Showdown-generated and needs
no setup. Gen 9 OU currently requires one immutable validated snapshot per player and the
`fixed` team policy.

## Import flow

Use `/teams` or `POST /api/teams/validate`. Input is limited to 50,000 UTF-8 bytes and rejects
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
carry the format and team policy. Gen 9 OU accepts fixed teams; per-series rotation or
dynamic counter-teaming is intentionally not implemented.

The authoritative real-server gate validates, packs, submits, completes, persists, and replays
a Gen 9 OU fixed-team match:

```bash
KOALABATTLE_RUN_SHOWDOWN_TEST=1 \
KOALABATTLE_SHOWDOWN_WEBSOCKET_URL=ws://127.0.0.1:8000/showdown/websocket \
KOALABATTLE_TEAM_VALIDATOR_URL=http://127.0.0.1:8002 \
.venv/bin/pytest backend/tests/integration -q
```
