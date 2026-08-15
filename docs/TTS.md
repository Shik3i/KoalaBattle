# Speech providers and voices

Speech uses a separate `SpeechProvider` interface. It never calls an LLM and receives only the
normalized public `AgentDecision.commentary`. Prompts, raw responses, player knowledge,
Strategy Memory, provider metadata, and hidden state are outside the speech request boundary.

## Providers

- `system` (default): zero-cost local `espeak-ng`; macOS `say` is a fallback. The Docker backend
  installs Debian's `espeak-ng` package. The external executable is GPL-3.0-or-later and is not
  relicensed as KoalaBattle source.
- `fake`: deterministic tone WAV for tests, cache QA, and zero-network preview.
- `openai`: optional `/v1/audio/speech` adapter. It is treated as paid and refuses generation
  unless the request explicitly sets `allow_paid=true`.
- `openai-compatible`: optional configured `/v1/audio/speech` endpoint. It is conservatively
  treated as paid because KoalaBattle cannot infer the operator's endpoint billing.

OpenAI speech returns audio but KoalaBattle does not claim word timestamps. Captions use
deterministic proportional timing and are normalized to actual cached WAV duration after
synthesis. WAV is the only internal format; FFmpeg is not required.

The SHA-256 cache key covers normalized text, provider, model, voice, speed, language,
instructions, and format as canonical JSON. Identical concurrent requests share one task.
Generation is bounded by `KOALABATTLE_SPEECH_MAX_CONCURRENCY`; cancellation does not expose a
partial artifact. Text and payload size limits apply before publication.

VoicePresets persist a provider-neutral participant assignment. The same `p1`/`p2` assignment
is reused across replay and rebuild until an operator creates a different production.

The system provider is suitable as the initial free path, but voice availability and quality
depend on the host. Sherpa-ONNX was evaluated as a maintained offline engine; model weights
are not bundled because each selected model has separate provenance and license obligations.
Edge-TTS is not a default because its unofficial service dependency is not a stable production
contract.
