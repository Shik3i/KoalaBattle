# LLM providers

KoalaBattle 0.10.0 supports five battle-decision provider shapes and one test-only provider.
Credentials are backend environment variables; the API exposes only a boolean
`configured` status.

| Provider | Backend variable | Default transport | Model discovery |
| --- | --- | --- | --- |
| OpenAI | `KOALABATTLE_OPENAI_API_KEY` | Responses API with strict JSON Schema | Yes |
| Google Gemini | `KOALABATTLE_GEMINI_API_KEY` | `google-genai` structured output | Yes |
| Anthropic | `KOALABATTLE_ANTHROPIC_API_KEY` | Messages API structured output | Yes |
| DeepSeek | `KOALABATTLE_DEEPSEEK_API_KEY` | OpenAI-compatible chat completion | Yes |
| OpenAI-compatible | `KOALABATTLE_OPENAI_COMPATIBLE_API_KEY` (optional) | User-supplied HTTP(S) `/v1` base URL | Best effort |
| Fake | none | Deterministic in-process test adapter | Yes |

The fake adapter is disabled by default. Enable it only in development with
`KOALABATTLE_ENABLE_FAKE_PROVIDER=true`. It supports valid, malformed, illegal,
rate-limited, unavailable, and timeout scenarios.

Custom model IDs are always accepted. Discovery failures do not invalidate a custom
ID. The compatible adapter negotiates JSON Schema, then JSON object mode, then plain
text with the same local parser and legal-action validation.

The New match player builder includes ready-to-select local endpoint presets for LM Studio,
Ollama, and llama.cpp. Docker runs provider calls from the backend container, so these presets
use `http://host.docker.internal:<port>/v1` rather than `localhost`. The LM Studio Gemma preset
uses model ID `google/gemma-4-e4b`; use **Discover models** to replace it with another model
currently available from the local server. All LLM presets use a five-minute request timeout
and one automatic retry, which gives slow local models enough time to finish while retaining a
single recovery attempt.

OpenAI-compatible providers that expose token streaming also publish a live, viewer-safe
commentary preview and prompt-size metrics to the battle view. Raw prompts, model output outside
the public commentary field, and private strategy memory are never streamed to spectators.

Provider reference contracts: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[OpenAI models](https://developers.openai.com/api/reference/resources/models/methods/list),
[Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output),
[Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[DeepSeek JSON output](https://api-docs.deepseek.com/guides/json_mode),
[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility), and
[LM Studio OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat).

The provider SDKs are pinned in `backend/pyproject.toml`. A provider call uses an
application timeout, SDK retries are disabled where supported, and KoalaBattle owns the
bounded retry/repair/fallback policy.

Every match owns independent adapter/agent instances. The global match scheduler bounds total
concurrency; per-player limits and an optional tournament budget stop future calls after the
recorded threshold is reached. Tests use Random, Manual, or Fake agents and spend no API credit.

All battle providers receive a fresh full prompt every turn. Adapters do not maintain provider
conversation state. Team generation is a separate explicit structured-output operation with
its own bounded Showdown-validation repair loop and audit; see [Team building](TEAM_BUILDING.md).
