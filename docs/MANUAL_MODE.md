# Manual Web Chat mode

Manual mode is a player-scoped transport for any external web chat. It has no provider
account integration and needs no key.

## Two-tab workflow

Manual mode is designed around two browser tabs:

| Tab | URL | Purpose |
| --- | --- | --- |
| Battle view | `/watch/:matchId` | What you watch and what OBS captures. No controls, no scroll |
| Control | `/battle/:matchId` | Copy prompts, paste responses, run the match |

The control page exposes **Open battle view**, **Copy battle view URL** and **Copy OBS URL**,
so the capture surface never has to be scrolled to reach a paste box.

1. Choose **Manual Web Chat** independently for P1 or P2.
2. On the control page, pick the agent's tab. The workspace is headed by that agent's own
   name — `GEMINI`, `CHATGPT` — with `Player 1 / Player 2` as secondary metadata, and both
   tabs show their state: *Waiting for response*, *Submitted*, *Waiting for opponent*.
3. Select **Copy prompt** and paste it into a web chat.
4. Paste the response into that same workspace. **Legal actions** below the columns lists every
   legal choice with its metadata and prefills a response when clicked.
5. Select **Validate**. Fix the response if the action is missing or stale.
6. Select **Submit**.

Expected shape:

```json
{"action":"move:2","commentary":"Short public explanation.","strategy_memory":"Replacement note or null"}
```

Plain JSON and a single JSON object inside explanatory text or Markdown fences are
accepted. Unknown fields, missing `action`, malformed JSON, overlong commentary, and
actions outside the current `legal_actions` list are rejected. Commentary longer than the
240-character public limit is trimmed rather than rejected, so a usable action never costs a
turn. Only normalized
KoalaBattle IDs are executed. Raw Showdown commands are never accepted from a model.

Manual vs Manual can expose two simultaneous workspaces. Each response is keyed by its
request UUID and side; submitting one cannot answer the other. A request can be answered only
once.

Each displayed prompt is complete enough for a fresh external chat with no history: role and
rules first, then format and generation, your active Pokémon, your full bench with its moves,
the opponent's revealed information, field state, readable recent events, your strategy note,
and self-describing legal actions. Mechanics the selected generation does not have are omitted
entirely, so a Gen 1 prompt carries no ability, item or Terastallization fields. External chat
history is optional and never authoritative. See [Prompt contract](PROMPTS.md).
