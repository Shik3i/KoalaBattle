# Provider and presentation security

- Provider credentials exist only in backend process settings.
- `.env` is ignored. `.env.example` contains empty placeholders only.
- Match configuration, SQLite player configuration, prompts, events, REST responses,
  WebSocket messages, replays, overlays, and browser storage contain no credential field.
- OpenAI-compatible base URLs must use HTTP(S) and cannot contain embedded credentials.
- Provider errors are bounded and redact bearer/key-shaped values before persistence or
  logging.
- The presentation endpoint and WebSocket snapshot remove raw provider responses,
  generated prompts, provider response metadata, raw Showdown logs, and error detail.
- The local production-control endpoint may expose the full safe audit,
  including provider output and prompt. KoalaBattle 0.4 remains local-first and does not
  add accounts or remote authorization.
- Provider text is parsed as data. Only an exact normalized legal action ID reaches the
  engine adapter.
- Tournament watch/overlay payloads omit engine configuration, provider settings, internal
  errors, and raw match audit. Admin/control endpoints are not an authorization boundary.
- Match-scoped manual request UUIDs prevent one browser submission from answering another
  match's waiter. Queue and result updates are persisted transactionally.

Do not use a `PUBLIC_` variable for a provider secret. Do not place a key in a compatible
base URL. Rotate any key that was pasted into a manual response because full audit mode
intentionally preserves operator input.
