# Provider and presentation security

- Provider credentials exist only in backend process settings.
- `.env` is ignored. `.env.example` contains empty placeholders only.
- Match configuration, SQLite player configuration, prompts, events, REST responses,
  WebSocket messages, replays, overlays, and browser storage contain no credential field.
- OpenAI-compatible base URLs must use HTTP(S) and cannot contain embedded credentials.
- Provider errors are bounded and redact bearer/key-shaped values before persistence or
  logging.
- The presentation endpoint and WebSocket snapshot remove raw provider responses,
  generated prompts, normalized agent context/knowledge, provider response metadata, raw
  Showdown logs, fixed team snapshot IDs/exports/packed teams, and error detail.
- The local production-control endpoint may expose the full safe audit,
  including provider output, prompt, context, and private team snapshots. KoalaBattle 0.10.0
  remains local-first and does not
  add accounts or remote authorization.
- Provider text is parsed as data. Only an exact normalized legal action ID reaches the
  engine adapter.
- Tournament watch/overlay payloads omit engine configuration, provider settings, internal
  errors, and raw match audit. Admin/control endpoints are not an authorization boundary.
- Match-scoped manual request UUIDs prevent one browser submission from answering another
  match's waiter. One request is accepted once. Queue, tournament claims, and result updates
  are persisted transactionally.

## Release-candidate audit

- XSS: provider/team/commentary data is rendered through Svelte text interpolation or readonly
  controls; no raw HTML insertion is used.
- SSRF: custom provider endpoints require an HTTP(S) URL, hostname, and no credentials, query,
  fragment, control character, or encoded hostname. Private/loopback URLs remain intentionally
  allowed for local models; protect control routes from untrusted operators.
- Team input: 50,000-byte limit, control-character rejection, JSON response cap, exact format
  allowlist, no shell/subprocess invocation, and authoritative local Showdown parsing.
- Paths: asset IDs are canonicalized and resolved beneath the configured root; optional assets
  remain read-only in the backend container.
- DTO isolation: control/admin archives and public watch/OBS snapshots are distinct contracts.
- Persistence: Pydantic/JSON only; no pickle/eval, interpolated SQL, or model-supplied command.
- Payloads: model IDs, names, commentary, Strategy Memory, provider responses, Manual responses,
  and teams have explicit bounds. FastAPI/ingress still needs an operator-level total request
  limit when exposed through a reverse proxy.
- CORS/auth: CORS is configured explicitly, but CORS is not authentication. Admin, team, prompt
  playground, and control APIs require a trusted network or an authenticating reverse proxy.

The pinned upstream Pokémon Showdown production dependency audit currently reports 16 findings
(2 low, 3 moderate, 9 high, 2 critical), largely in server features/build/native dependency
trees not exercised by KoalaBattle's validator. The local engine is pinned and isolated; a
blind major `npm audit fix` would change the compatibility target. Upgrade only with the real
Random/custom-team integration gates. KoalaBattle frontend production and development audits
both report zero findings. Python uses `httpx2==2.10.0` for Starlette's supported test client
path; provider SDKs may still independently depend on `httpx`.

Do not use a `PUBLIC_` variable for a provider secret. Do not place a key in a compatible
base URL. Rotate any key that was pasted into a manual response because full audit mode
intentionally preserves operator input.

## Audio boundary

- Speech input is constructed only from bounded public commentary; no prompt, knowledge,
  Strategy Memory, raw response, or provider metadata is accepted by the speech layer.
- Edge neural speech is free and enabled by default, but sends bounded public commentary to
  Microsoft's online speech service; disable it for strict offline operation. Configured OpenAI
  speech providers remain classified as paid and need `allow_paid=true`.
- Cache keys are lowercase SHA-256 only. Resolved paths must remain below the configured audio
  root; media endpoints never accept arbitrary paths.
- WAV payloads are limited to 16 MiB and validated before atomic publication and again before
  serving. Partial or corrupt files return 404.
- Voice text is a subprocess argument, never shell code. System commands use
  `create_subprocess_exec`; voice/text cannot add flags or interpolation.
- Generated audio, operator music, sound packs, and third-party model weights are ignored by
  Git. No copyrighted Pokémon media is added by the production layer.

## Video/render boundary

- Output names are normalized to bounded ASCII stems. Jobs store relative registered paths;
  download routes resolve only beneath `data/videos/exports` or `data/videos/jobs`.
- UI/API users select versioned presets and encoder IDs. Arbitrary FFmpeg flags, shell strings,
  input paths, browser URLs, and JavaScript are not accepted.
- All FFmpeg/FFprobe/Chromium calls use argument arrays. Diagnostics are bounded to 4,000
  characters; progress and request names have model limits.
- Temporary MP4 files stay under the job temp root. FFprobe validates stream, resolution,
  duration, and expected audio before `os.replace` atomically publishes the registered output.
- Playwright blocks network requests except the configured local frontend/API origins. Battle
  commentary remains Svelte text, never HTML. Sprite/audio paths are existing contained APIs.
- OBS password exists only in backend settings. Browser Source URLs and capability responses
  disclose host/port/scene, never the password.
- Renderer access is a trusted self-hosted operator surface like existing admin/control APIs.
  Put authentication and request-size limits at the reverse proxy before network exposure.

## Branding upload boundary

User-supplied production media (logos, backgrounds, watermarks, fonts) is the only path by
which a file enters KoalaBattle from outside. It is bounded as follows.

- **Content is identified from file headers**, not from the filename or a declared MIME
  type. PNG, WebP and JPEG images and WOFF2/TrueType/OpenType fonts are accepted; anything
  else is refused.
- **No decoder runs during validation.** Only a few integers are parsed out of the header,
  so an image parser cannot be attacked through this path.
- **Decompression bombs are refused before decoding.** Dimensions come from the header and
  are checked against an 8192px edge and a pixel budget, so a small file that expands to
  gigabytes never reaches a decoder.
- **Size limits**: 8 MB per image, 4 MB per font, enforced on the encoded payload.
- **SVG is not supported.** A safe subset needs a real sanitizer (scripts, `foreignObject`,
  external references, XML entity expansion); a half-sanitized SVG is worse than none.
- **Paths are generated, never taken from input.** The stored name is
  `<kind>/<server-generated-id>.<ext>`; the uploaded filename is used only as a display
  label with path-shaped characters stripped. Reads resolve the path and refuse anything
  outside the branding root.
- **Styles reference assets by id**, matched against a 32-hex-character pattern, so a style
  document cannot express a filesystem path.
- **Colours are restricted to `#rgb`/`#rrggbb`.** A style can therefore never smuggle
  `url(...)` or any other CSS into a rendering surface, and there is no free-text CSS field
  anywhere in the model.
- **No remote URLs.** Deterministic rendering never fetches from the internet; fonts are
  local stacks or uploaded files, and backgrounds are local assets.
- **Imported style JSON is data.** It is validated by the same frozen, `extra="forbid"`
  pydantic models as any other input; unknown keys are rejected and no value is executed.
- Deleting an asset that a production still references is refused (409) unless forced, and
  a referenced asset that has gone missing degrades to a documented fallback rather than
  being silently replaced.

Production styles are presentation only. They cannot reach battle events, agent decisions,
private strategy memory, raw provider output or prompts, and the team-indicator setting can
only narrow what the public presentation archive already exposes.
