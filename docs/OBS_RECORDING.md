# Automated OBS recording

KoalaBattle speaks obs-websocket protocol v5 over `ws://HOST:PORT` (default 4455). OBS Studio
28 and newer includes this WebSocket server; no legacy plugin is required. OBS recommends
password protection. Current reference: <https://obsproject.com/kb/remote-control-guide>.

Settings remain server-side:

```text
KOALABATTLE_OBS_HOST
KOALABATTLE_OBS_PORT
KOALABATTLE_OBS_PASSWORD
KOALABATTLE_OBS_SCENE
KOALABATTLE_OBS_BROWSER_SOURCE
```

The exporter identifies/authenticates, verifies the named existing scene and Browser Source,
calls `StartRecord`, temporarily points that source at the selected production's local
`/render/:productionId?autoplay=1` URL, waits on its clock in realtime, calls `StopRecord`, and
restores the original input settings. This modification happens only after the explicit Start
Recording action. It never deletes a scene/source or changes the scene collection permanently.

A ten-minute Production needs approximately ten minutes. Use this backend when exact live/OBS
effects matter or offline rendering is unavailable. Cancellation stops recording only when
KoalaBattle started it. Connection/authentication, missing-scene, recording, path, or source
failures mark the export failed without changing battle history.
