#!/usr/bin/env python3
"""Run a reproducible offline-renderer benchmark against a stored production."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from koalabattle.config import Settings
from koalabattle.production import ProductionService
from koalabattle.storage import BattleRepository, Database
from koalabattle.video.exporters import OfflineRendererExporter
from koalabattle.video.filesystem import VideoStorage
from koalabattle.video.models import PRESETS, ExportBackend, ExportStatus, VideoExportJob


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("production_id", type=UUID)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="youtube-1080p60")
    parser.add_argument("--database-url", default="sqlite+aiosqlite:///./data/koalabattle.db")
    parser.add_argument("--frontend-url", default="http://localhost:5173")
    parser.add_argument("--api-url", default="http://localhost:8001")
    parser.add_argument("--output-root", type=Path, default=Path("data/videos/benchmarks"))
    parser.add_argument("--encoder", default="software")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--start-ms", type=int, default=0)
    parser.add_argument("--end-ms", type=int)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    settings = Settings(
        database_url=args.database_url,
        video_root=args.output_root,
        video_frontend_url=args.frontend_url,
        video_api_url=args.api_url,
        video_frame_workers=args.workers,
        video_worker_enabled=False,
    )
    database = Database(settings.database_url)
    battles = BattleRepository(database)
    productions = ProductionService(database, battles, settings)
    storage = VideoStorage(settings.video_root)
    storage.prepare()
    try:
        production = await productions.require(args.production_id)
        archive = await battles.get_match(production.match_id)
        if archive is None:
            raise RuntimeError(f"match not found: {production.match_id}")
        preset = PRESETS[args.preset]
        if preset.layout != production.profile.aspect_ratio:
            raise ValueError(
                f"preset {preset.id} requires {preset.layout}, production uses "
                f"{production.profile.aspect_ratio}"
            )
        production_end_ms = production.duration_ms or max(
            (cue.start_ms + cue.duration_ms for cue in production.cues), default=0
        )
        end_ms = args.end_ms or production_end_ms
        if not 0 <= args.start_ms < end_ms <= production_end_ms:
            raise ValueError(
                f"invalid range {args.start_ms}:{end_ms}; production duration is "
                f"{production_end_ms}ms"
            )
        now = datetime.now(UTC)
        job = VideoExportJob(
            id=uuid4(),
            production_id=production.id,
            match_id=production.match_id,
            backend=ExportBackend.OFFLINE,
            preset=preset,
            output_name=f"benchmark-{preset.id}-{str(production.id)[:8]}",
            start_ms=args.start_ms,
            end_ms=end_ms,
            encoder=args.encoder,
            created_at=now,
            updated_at=now,
        )

        async def progress(status: ExportStatus, stage: str, percent: float) -> None:
            print(f"{status.value:>10} {percent:6.2f}% {stage}", flush=True)

        async def cancelled() -> bool:
            return False

        started = time.monotonic()
        output = await OfflineRendererExporter(settings, storage).export(
            job, production, progress=progress, cancelled=cancelled
        )
        wall_seconds = time.monotonic() - started
        manifest_path = storage.sidecar(job.id, ".json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = {
            "production_id": str(production.id),
            "match_id": str(production.match_id),
            "preset": preset.id,
            "encoder_request": args.encoder,
            "frame_workers": args.workers,
            "frames": job.frame_count,
            "duration_ms": job.duration_ms,
            "wall_seconds": round(wall_seconds, 6),
            "wall_speed_ratio": round(job.duration_ms / 1000 / wall_seconds, 6),
            "output": str(output),
            "output_bytes": output.stat().st_size,
            "renderer_metrics": manifest["renderer_metrics"],
        }
        print(json.dumps(result, indent=2))
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(run(arguments()))
