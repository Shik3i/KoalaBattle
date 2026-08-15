# Manual Web Chat mode

Manual mode is a player-scoped transport for any external web chat. It has no provider
account integration and needs no key.

1. Choose **Manual Web Chat** independently for P1 or P2.
2. On the live page, copy that player's generated prompt.
3. Paste it into a web chat.
4. Paste the response into the same player's workspace.
5. Select **Validate**. Fix the response if the action is missing or stale.
6. Select **Submit decision**.

Expected shape:

```json
{"action":"move:2","commentary":"Short public explanation."}
```

Plain JSON and a single JSON object inside explanatory text or Markdown fences are
accepted. Unknown fields, missing `action`, malformed JSON, overlong commentary, and
actions outside the current `legal_actions` list are rejected. Only normalized
KoalaBattle IDs are executed. Raw Showdown commands are never accepted from a model.

Manual vs Manual can expose two simultaneous workspaces. Each response is keyed by its
request UUID and side; submitting one cannot answer the other.
