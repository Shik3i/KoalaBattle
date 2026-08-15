from __future__ import annotations

import asyncio
import signal

from koalabattle.config import get_settings
from koalabattle.production import ProductionService
from koalabattle.storage import BattleRepository, Database

from .service import VideoExportService


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
    try:
        await stop.wait()
    finally:
        await video.close()
        await productions.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(run())
