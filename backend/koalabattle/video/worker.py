from __future__ import annotations

import asyncio
import signal

from koalabattle.config import get_settings
from koalabattle.production import ProductionService
from koalabattle.storage import BattleRepository, Database

from .service import VideoExportService


async def renderer_heartbeat(video: VideoExportService, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await video.publish_renderer_heartbeat()
        try:
            await asyncio.wait_for(stop.wait(), timeout=10)
        except TimeoutError:
            pass


async def run() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    battles = BattleRepository(database)
    productions = ProductionService(database, battles, settings)
    video = VideoExportService(database, battles, productions, settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            loop.add_signal_handler(getattr(signal, name), stop.set)
    await productions.start()
    await video.start()
    heartbeat = asyncio.create_task(
        renderer_heartbeat(video, stop), name="video-renderer-heartbeat"
    )
    try:
        await stop.wait()
    finally:
        stop.set()
        await heartbeat
        video.clear_renderer_heartbeat()
        await video.close()
        await productions.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(run())
