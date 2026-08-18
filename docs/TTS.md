# Speech providers and voices

Speech uses a separate `SpeechProvider` interface. It never calls an LLM and receives only the
normalized public `AgentDecision.commentary`. Prompts, raw responses, player knowledge,
Strategy Memory, provider metadata, and hidden state are outside the speech request boundary.

## Providers

- `qwen-local`: local Qwen3-TTS through a configurable OpenAI-shaped audio endpoint. The
  `Qwen3-TTS-12Hz-1.7B-Base` model uses a stored WAV reference and transcript for voice cloning;
  it does not create a stable persona from `instructions` alone. References live below ignored
  `data/audio/voices/` and can be assigned through a deterministic voice pool.

### Windows and Docker

The KoalaBattle backend has no MLX import and does not require `mlx-audio`. On Windows, leave
`KOALABATTLE_SPEECH_PROVIDER=system` for Edge neural speech plus the bundled/basic offline
fallback, or configure `openai-compatible` with a Windows TTS server. Docker Desktop exposes
host services through `host.docker.internal`; the Compose backend image includes `ffmpeg` and
`espeak-ng`.

`qwen-local` is only an HTTP adapter and can point to any compatible TTS service on Windows.
The repository's `tools/qwen_tts_server.py` is a separate Apple-Silicon MLX bridge. If it is
started on Windows or Intel macOS, `/healthz` reports `mlx_supported: false` and synthesis
returns `503` with the alternative-provider instruction.

LM Studio may show the MLX model in its library while rejecting it at load time with
`Model type qwen3_tts not supported`. That is not an LM Studio bug to route around — the
`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` checkpoint only runs through MLX, which is
Apple Silicon only. On an Apple Silicon Mac, run the repository's MLX bridge instead of
loading the model through LM Studio:

```bash
python -m pip install -r tools/requirements-qwen-tts.txt
python tools/qwen_tts_server.py
```

The bridge uses the local `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` checkpoint and exposes
`http://127.0.0.1:8890/v1/audio/speech`. Docker reaches it through
`http://host.docker.internal:8890/v1`. LM Studio remains the LLM endpoint on port `1234`.

#### Windows with an NVIDIA GPU

`tools/qwen_tts_server_windows.py` is the CUDA equivalent: it loads the official
`Qwen/Qwen3-TTS-12Hz-1.7B-Base` checkpoint (not the MLX quantization) through the `qwen-tts`
PyPI package and exposes the identical `/healthz`, `/v1/models`, `/v1/audio/speech` contract, so
`qwen-local`'s configuration does not change between platforms. Requires an NVIDIA GPU (bf16
capable; any Ampere-or-newer card comfortably fits the 1.7B model) and a recent driver.

```bash
python -m venv tools/.venv-qwen-tts
tools/.venv-qwen-tts/Scripts/python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
tools/.venv-qwen-tts/Scripts/python.exe -m pip install -r tools/requirements-qwen-tts-windows.txt
tools/.venv-qwen-tts/Scripts/python.exe tools/qwen_tts_server_windows.py
```

Set `KOALABATTLE_SPEECH_QWEN_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-Base` (the unquantized HF id, not
the `mlx-community` one) so the payload's `model` field matches what the bridge actually loaded.
The Base checkpoint has no built-in preset voices — it only clones from a reference WAV plus its
transcript, so requests without `reference_audio` get a 422. `KOALABATTLE_QWEN_TTS_ATTN`
defaults to `sdpa` (ships with PyTorch, no extra build step); set it to `flash_attention_2` only
if `flash-attn` has been built separately, which is a non-trivial compile on Windows.

The bridge runs on the Windows host, not in Docker (Compose reaches it through
`host.docker.internal:8890`), so it needs to start on its own rather than depending on someone
remembering to launch it. Run once:

```bash
powershell -ExecutionPolicy Bypass -File tools/install_qwen_tts_task.ps1
```

It registers a Task Scheduler entry that starts the bridge at logon and restarts it if it
crashes. If Task Scheduler refuses without admin rights (it does on some machines even for a
task that only ever runs as your own account), it falls back automatically to a silent launcher
in your per-user Startup folder — that one starts at logon too, just without the auto-restart.
Either way, no admin rights are required and nothing needs to be run by hand afterward.
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
instructions, reference-audio hash, clone mode, and format as canonical JSON. Identical
concurrent requests share one task. Qwen generation defaults to one active request to avoid
loading multiple 1.7B speech generations into RAM at once.
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

## Voice pools

Voice pools contain enabled `VoicePreset` IDs. A production can select explicit, random, or
balanced-random voices. Selection happens once when the production is created; selected IDs and
the seed are persisted in the timeline so rebuilds and video exports remain identical. Use
`POST /api/production/voices/reference` for a validated local WAV reference and
`POST /api/production/voice-pools` to save a pool.
