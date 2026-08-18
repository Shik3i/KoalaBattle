# Orchestrator API

The orchestrator exposes one asynchronous workflow for external agents:

1. Build one legal Pokémon Showdown team per LLM.
2. Run a deterministic Bo1 through the local Showdown engine.
3. Keep optional opponent-facing banter in the battle JSON and production timeline.
4. Queue the replay for the selected video renderer.

Generated media stays under `data/videos/`, which is ignored by Git.

## Ask for a plan

Use the plan endpoint when an agent wants KoalaBattle to identify missing settings instead of
starting immediately:

```bash
curl -sS -X POST http://127.0.0.1:8001/api/orchestrator/plan \
  -H 'content-type: application/json' \
  --data '{"instruction":"Gib mir ein Gen1 Battle mit selbst gebauten Teams"}'
```

The response contains `ready`, normalized `settings`, `warnings`, and `questions`. Submit the
resolved settings to `/api/orchestrator/runs` after the user or another agent has answered those
questions.

## Start the requested run

The natural-language instruction is enough for the requested local Gemma-4 workflow:

```bash
curl -sS -X POST http://127.0.0.1:8001/api/orchestrator/runs \
  -H 'content-type: application/json' \
  --data '{
    "instruction":"Gib mir ein Gen1 battle, beide AIs Gemma4, sie bauen sich selbst ein Team im Showdown-Format, danach Bo1 mit Banter und direkt als Video rendern"
  }'
```

The local defaults are:

- format `gen1ou` when team building is requested;
- model `google/gemma-4-e4b`;
- OpenAI-compatible LM Studio API;
- `http://host.docker.internal:1234/v1` from Docker, configurable through
  `KOALABATTLE_ORCHESTRATOR_LOCAL_BASE_URL`;
- 300 seconds per LLM request and one retry;
- `fast-preview`, native compositor, software H.264 export.

For an explicit request, pass `settings`:

```json
{
  "instruction": "Gen1 Bo1 with banter and video",
  "settings": {
    "format": "gen1ou",
    "best_of": 1,
        "banter_enabled": true,
        "auto_render": true,
        "voice_pool_id": "pokemon-broadcast-v1",
        "voice_selection_mode": "balanced-random",
        "voice_selection_seed": 42,
        "video_preset_id": "fast-preview",
    "players": [
      {
        "display_name": "Gemma 4 · A",
        "provider": "openai-compatible",
        "model": "google/gemma-4-e4b",
        "configuration": {
          "base_url": "http://host.docker.internal:1234/v1",
          "timeout_seconds": 300,
          "max_retries": 1
        }
      },
      {
        "display_name": "Gemma 4 · B",
        "provider": "openai-compatible",
        "model": "google/gemma-4-e4b",
        "configuration": {
          "base_url": "http://host.docker.internal:1234/v1",
          "timeout_seconds": 300,
          "max_retries": 1
        }
      }
    ]
  }
}
```

## Track the run

The `202` response contains a run ID. Poll it until `status` is `completed`, `failed`, or
`cancelled`:

```bash
curl -sS http://127.0.0.1:8001/api/orchestrator/runs/<run-id>
```

The response exposes `teams`, `match_id`, `production_id`, `video_job_id`, current `stage`, and
`progress`. Once `video_job_id` exists, the normal video API remains available:

```bash
curl -sS http://127.0.0.1:8001/api/video/jobs/<video-job-id>
curl -fL -o replay.mp4 http://127.0.0.1:8001/api/video/jobs/<video-job-id>/download
```

Cancel an active workflow with:

```bash
curl -sS -X POST http://127.0.0.1:8001/api/orchestrator/runs/<run-id>/cancel
```

Use `GET /api/orchestrator/capabilities` for the machine-readable defaults and supported
features.
