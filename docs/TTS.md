# Speech providers and voices

Speech uses a separate `SpeechProvider` interface. It never calls an LLM and receives only the
normalized public `AgentDecision.commentary`. Prompts, raw responses, player knowledge,
Strategy Memory, provider metadata, and hidden state are outside the speech request boundary.

## Providers

- `system` (default): free Edge neural speech using `edge-tts`, with distinct Emma and Brian
  multilingual neural voices at a restrained 0.96× delivery rate plus a separate Guy narrator
  voice at 1.02×. It requires Internet access
  and sends only normalized public commentary to Microsoft's
  online speech service. No API key is required. It is an unofficial service integration, not an
  Azure Speech SLA.
- `system` offline presets: macOS `say` is preferred where available; `espeak-ng` remains the
  basic Linux/Docker fallback. The external executable is GPL-3.0-or-later and is not relicensed
  as KoalaBattle source.
- `fake`: deterministic tone WAV for tests, cache QA, and zero-network preview.
- `openai`: optional `/v1/audio/speech` adapter. It is treated as paid and refuses generation
  unless the request explicitly sets `allow_paid=true`.
- `openai-compatible`: optional configured `/v1/audio/speech` endpoint. It is conservatively
  treated as paid because KoalaBattle cannot infer the operator's endpoint billing.

Edge audio is converted locally through FFmpeg to the same validated PCM WAV boundary. Video
mixes are peak-limited and normalized to 48 kHz stereo so a low-rate fallback source cannot
silently dictate the final export format. OpenAI
speech returns audio but KoalaBattle does not claim word timestamps. Captions use
deterministic proportional timing and are normalized to actual cached WAV duration after
synthesis. WAV is the only internal format; FFmpeg is not required.

The SHA-256 cache key covers normalized text, provider, model, voice, speed, language,
instructions, and format as canonical JSON. Identical concurrent requests share one task.
All missing replay cues are scheduled immediately when preparation starts. Generation is
bounded by `KOALABATTLE_SPEECH_MAX_CONCURRENCY` (default `8`); cancellation does not expose a
partial artifact. Text and payload size limits apply before publication.

VoicePresets persist a provider-neutral participant assignment. The same `p1`/`p2`/`narrator`
assignment is reused across replay and rebuild until an operator creates a different production.
The narrator is event-driven and deterministic; it never calls an LLM. Configure its Edge voice
with `KOALABATTLE_SPEECH_EDGE_VOICE_NARRATOR` or disable narrator speech by leaving narrator
disabled in the production settings.

Set `KOALABATTLE_SPEECH_EDGE_ENABLED=false` for strictly offline operation. Offline quality then
depends on installed host voices and is intentionally labeled basic. Sherpa-ONNX remains a future
offline option; model weights are not bundled because each model has separate provenance and
license obligations.
