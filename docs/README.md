# KoalaBattle documentation

The repository [README](../README.md) is the installation and first-run entry point. This index
routes operators and contributors to the source-of-truth document for each workflow. KoalaBattle
is local-first: admin/control APIs are trusted-operator surfaces, while watch and OBS views use
restricted presentation data.

## Start here

- Run the stack: [Docker services](DOCKER.md)
- Understand supported workflows and current limits: [Release readiness](RELEASE_READINESS.md)
- Configure an LLM or use a no-key agent: [Provider configuration](PROVIDERS.md)
- Use an external browser chat without an API key: [Manual Web Chat](MANUAL_MODE.md)
- Install optional local sprites responsibly: [Optional assets and rights](ASSETS.md)
- Add license-tracked move-effect textures: [Optional move effects](MOVE_EFFECTS.md)
- Develop and run the complete validation gate: [Development](DEVELOPMENT.md)

## Run battles and tournaments

- [Battle formats, generation support, and capability rules](FORMATS.md)
- [Match orchestration, isolation, queueing, and recovery](ORCHESTRATION.md)
- [Tournament formats, series scheduling, and standings](TOURNAMENTS.md)
- [Agent context, knowledge boundaries, and strategy memory](AGENT_CONTEXT.md)
- [Team import, generation, validation, and immutable snapshots](TEAM_BUILDING.md)
- [Usage accounting and cost limits](COST_TRACKING.md)

## Produce streams and video

- [Renderer behavior and spectator-safe state](RENDERER.md)
- [Themes, layouts, effects, and accessibility](THEMES.md)
- [OBS browser sources](OBS.md)
- [Production timeline and live direction](PRODUCTION.md)
- [Production audio and mixer](AUDIO.md)
- [Free Edge neural speech, fallback voices, and paid-provider boundaries](TTS.md)
- [Captions](CAPTIONS.md)
- [Video export jobs and API](VIDEO_EXPORT.md)
- [Deterministic native offline renderer](OFFLINE_RENDERER.md)
- [Automated OBS recording](OBS_RECORDING.md)
- [Measured performance and load limits](PERFORMANCE.md)

## Build and extend

- [System architecture and ownership boundaries](ARCHITECTURE.md)
- [Agent implementation contract](AGENTS.md)
- [Agent API](AGENT_API.md)
- [Battle event model](BATTLE_EVENT_MODEL.md)
- [Replay format and compatibility](REPLAY_FORMAT.md)
- [Prompt contract](PROMPTS.md)
- [Security and exposure boundaries](SECURITY.md)

Detailed documents own their contracts. Keep quick-start commands in the repository README and
avoid duplicating environment-variable tables, lifecycle rules, or compatibility guarantees.
