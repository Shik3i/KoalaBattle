# Docker services

Core stack:

```bash
docker compose up --build
```

The backend remains lightweight and starts without Chromium or FFmpeg. In Compose its embedded
video worker is disabled; live battles, replay, production, TTS, and OBS Browser Sources remain
available.

Optional isolated renderer:

```bash
docker compose --profile renderer up --build
```

`Dockerfile.renderer` adds Chromium, FFmpeg/FFprobe, Playwright, `espeak-ng`, and local DejaVu
fonts. It shares only `data/` metadata/media and the read-only asset directory. Its browser
loads the Svelte frontend and backend through Docker-internal origins; arbitrary network
requests are blocked during frames. One renderer worker is the supported SQLite configuration.
The backend CORS list includes the exact internal renderer origin `http://frontend:3000`; it is
not a wildcard and is required for Chromium to read production and match snapshots.

Generated media stays in the host-mounted ignored paths `data/videos/` and `data/audio/`.
Stop writers or use SQLite backup before copying `data/koalabattle.db`; do not inspect a live
WAL database with a separate unsafe writer.
