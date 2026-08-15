from __future__ import annotations

import asyncio
import importlib.util
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from koalabattle.config import Settings
from koalabattle.production import ProductionService
from koalabattle.production.models import ProductionStatus, Track
from koalabattle.storage import BattleRepository, Database

from .exporters import (
    OBSRecorderExporter,
    OfflineRendererExporter,
    captions_to_srt,
    detected_encoders,
    probe,
)
from .filesystem import VideoStorage, file_sha256, safe_stem
from .models import (
    PACING_PROFILES,
    PRESETS,
    CreateVideoExport,
    ExportBackend,
    ExportManifest,
    ExportPreflight,
    ExportStatus,
    PacingProfile,
    RendererCapabilities,
    VideoExportJob,
    VideoExportPreset,
)
from .repository import VideoExportRepository

_RUNNING = {
    ExportStatus.PREPARING,
    ExportStatus.RENDERING,
    ExportStatus.ENCODING,
    ExportStatus.FINALIZING,
}


class VideoExportService:
    def __init__(
        self,
        database: Database,
        battles: BattleRepository,
        productions: ProductionService,
        settings: Settings,
    ) -> None:
        self.repository = VideoExportRepository(database)
        self.battles = battles
        self.productions = productions
        self.settings = settings
        self.storage = VideoStorage(settings.video_root)
        self.exporters = {
            ExportBackend.OFFLINE: OfflineRendererExporter(settings, self.storage),
            ExportBackend.OBS: OBSRecorderExporter(settings, self.storage),
        }
        self._dispatcher: asyncio.Task[None] | None = None
        self._active: dict[UUID, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._closing = False

    async def start(self) -> None:
        self.storage.prepare()
        await self.repository.reconcile_interrupted()
        if self.settings.video_worker_enabled:
            self._dispatcher = asyncio.create_task(self._dispatch(), name="video-export-dispatch")

    async def close(self) -> None:
        self._closing = True
        self._wake.set()
        if self._dispatcher is not None:
            self._dispatcher.cancel()
            await asyncio.gather(self._dispatcher, return_exceptions=True)
        for task in self._active.values():
            task.cancel()
        if self._active:
            await asyncio.gather(*tuple(self._active.values()), return_exceptions=True)

    def presets(self) -> tuple[VideoExportPreset, ...]:
        return tuple(PRESETS.values())

    def pacing_profiles(self) -> tuple[PacingProfile, ...]:
        return tuple(PACING_PROFILES.values())

    async def create(
        self, request: CreateVideoExport, *, attempt: int = 1
    ) -> VideoExportJob:
        production = await self.productions.require(request.production_id)
        if production.status not in {
            ProductionStatus.FINALIZED,
            ProductionStatus.READY,
            ProductionStatus.PARTIAL,
        }:
            raise ValueError("production must be finalized before export")
        try:
            preset = PRESETS[request.preset_id]
        except KeyError as error:
            raise ValueError(f"unknown export preset: {request.preset_id}") from error
        if preset.layout != production.profile.aspect_ratio:
            raise ValueError(
                f"preset requires {preset.layout}; create a matching production profile first"
            )
        end_ms = (
            request.end_ms
            or production.duration_ms
            or max((cue.start_ms + cue.duration_ms for cue in production.cues), default=0)
        )
        if end_ms <= request.start_ms:
            raise ValueError("export range is empty")
        if end_ms > production.duration_ms and production.duration_ms:
            raise ValueError("export range exceeds finalized production duration")
        archive = await self.battles.get_match(production.match_id)
        if archive is None:
            raise KeyError(str(production.match_id))
        players = "-vs-".join(player.display_name for player in archive.config.players)
        generated = (
            f"{archive.created_at.date().isoformat()}_{players}_{archive.config.format}_"
            f"{str(archive.id)[:8]}_{preset.id}"
        )
        now = datetime.now(UTC)
        job = VideoExportJob(
            id=uuid4(),
            production_id=production.id,
            match_id=production.match_id,
            backend=request.backend,
            preset=preset,
            output_name=safe_stem(request.output_name or generated),
            idempotency_key=request.idempotency_key,
            priority=request.priority,
            start_ms=request.start_ms,
            end_ms=end_ms,
            encoder=request.encoder,
            attempt=attempt,
            pacing_profile_version=PACING_PROFILES[preset.pacing_profile].version,
            created_at=now,
            updated_at=now,
        )
        stored = await self.repository.create(job)
        self._wake.set()
        return stored

    async def list(self, match_id: UUID | None = None) -> tuple[VideoExportJob, ...]:
        return await self.repository.list(match_id=match_id)

    async def require(self, job_id: UUID) -> VideoExportJob:
        job = await self.repository.get(job_id)
        if job is None:
            raise KeyError(str(job_id))
        return job

    async def cancel(self, job_id: UUID) -> VideoExportJob:
        job = await self.require(job_id)
        if job.status in {ExportStatus.COMPLETED, ExportStatus.FAILED, ExportStatus.CANCELLED}:
            return job
        now = datetime.now(UTC)
        if job.status is ExportStatus.QUEUED:
            updated = job.model_copy(
                update={
                    "status": ExportStatus.CANCELLED,
                    "stage": "Cancelled",
                    "cancel_requested": True,
                    "completed_at": now,
                    "updated_at": now,
                }
            )
        else:
            updated = job.model_copy(
                update={"cancel_requested": True, "stage": "Cancelling", "updated_at": now}
            )
        return await self.repository.save(updated)

    async def retry(self, job_id: UUID) -> VideoExportJob:
        previous = await self.require(job_id)
        if previous.status not in {ExportStatus.FAILED, ExportStatus.CANCELLED}:
            raise ValueError("only failed or cancelled exports can be retried")
        return await self.create(
            CreateVideoExport(
                production_id=previous.production_id,
                backend=previous.backend,
                preset_id=previous.preset.id,
                output_name=previous.output_name,
                priority=previous.priority,
                start_ms=previous.start_ms,
                end_ms=previous.end_ms,
                encoder=previous.encoder,
            ),
            attempt=previous.attempt + 1,
        )

    async def preflight(self, production_id: UUID, backend: ExportBackend) -> ExportPreflight:
        production = await self.productions.require(production_id)
        capabilities = await self.capabilities()
        missing: list[str] = []
        commentary_sequences = {
            cue.event_sequence
            for cue in production.cues
            if cue.track is Track.COMMENTARY and cue.event_sequence is not None
        }
        voiced_sequences = {
            cue.event_sequence
            for cue in production.cues
            if cue.track is Track.VOICE and cue.event_sequence is not None
        }
        for sequence in sorted(commentary_sequences - voiced_sequences):
            missing.append(f"event-{sequence}")
        checks = {
            "production": production.status.value,
            "speech": (
                f"{len(commentary_sequences) - len(missing)}/{len(commentary_sequences)} cached"
            ),
            "sprites": "local asset provider",
            "music": "optional / local only",
            "sound_pack": "optional / local only",
            "ffmpeg": "available" if capabilities.ffmpeg_available else "missing",
            "chromium": "available" if capabilities.chromium_available else "missing",
            "playwright": "available" if capabilities.playwright_available else "missing",
            "disk": f"{capabilities.free_bytes} bytes free",
        }
        backend_ready = (
            capabilities.offline_available
            if backend is ExportBackend.OFFLINE
            else capabilities.obs_configured
        )
        speech_required = production.profile.speech_enabled and production.profile.wait_for_speech
        ready = (
            production.status
            in {ProductionStatus.FINALIZED, ProductionStatus.READY, ProductionStatus.PARTIAL}
            and backend_ready
            and capabilities.ffprobe_available
            and capabilities.output_writable
            and capabilities.free_bytes >= self.settings.video_min_free_bytes
            and (not speech_required or not missing)
        )
        warnings = (
            () if not missing or speech_required else ("Missing speech will render silently.",)
        )
        return ExportPreflight(
            ready=ready, checks=checks, missing_speech=tuple(missing), warnings=warnings
        )

    async def capabilities(self) -> RendererCapabilities:
        self.storage.prepare()
        ffmpeg = self._command_exists(self.settings.video_ffmpeg_path)
        ffprobe = self._command_exists(self.settings.video_ffprobe_path)
        playwright = importlib.util.find_spec("playwright") is not None
        chromium_path = self._chromium_path()
        chromium = chromium_path is not None or playwright
        ffmpeg_version = await self._version(self.settings.video_ffmpeg_path) if ffmpeg else None
        chromium_version = await self._version(str(chromium_path)) if chromium_path else None
        encoders = await detected_encoders(self.settings.video_ffmpeg_path) if ffmpeg else ()
        free, storage = self.storage.disk()
        writable = os_access(self.storage.root)
        details: list[str] = []
        if not ffmpeg:
            details.append("Install FFmpeg and ensure `ffmpeg` is on PATH.")
        if not playwright:
            details.append("Install `koalabattle[renderer]` and run `playwright install chromium`.")
        if not chromium:
            details.append("No compatible Chromium executable was detected.")
        return RendererCapabilities(
            offline_available=(
                ffmpeg and ffprobe and playwright and chromium and writable and bool(encoders)
            ),
            obs_configured=bool(self.settings.obs_host and self.settings.obs_scene),
            ffmpeg_available=ffmpeg,
            ffmpeg_version=ffmpeg_version,
            ffprobe_available=ffprobe,
            chromium_available=chromium,
            chromium_version=chromium_version,
            playwright_available=playwright,
            encoders=encoders,
            output_writable=writable,
            output_root=str(self.storage.root),
            free_bytes=free,
            storage_bytes=storage,
            concurrency=self.settings.video_max_concurrency,
            obs_host=self.settings.obs_host,
            obs_port=self.settings.obs_port,
            obs_scene=self.settings.obs_scene,
            detail=tuple(details),
        )

    async def registered_file(self, job_id: UUID, kind: str) -> Path | None:
        job = await self.require(job_id)
        relative = {
            "video": job.output_relative_path,
            "manifest": job.manifest_relative_path,
            "captions": job.subtitle_relative_path,
        }.get(kind)
        return self.storage.registered(relative) if relative else None

    async def _dispatch(self) -> None:
        while not self._closing:
            self._active = {
                job_id: task for job_id, task in self._active.items() if not task.done()
            }
            while len(self._active) < self.settings.video_max_concurrency:
                job = await self.repository.next_queued()
                if job is None or job.id in self._active:
                    break
                claimed = job.model_copy(
                    update={
                        "status": ExportStatus.PREPARING,
                        "stage": "Preparing",
                        "progress": 1.0,
                        "started_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    }
                )
                await self.repository.save(claimed)
                task = asyncio.create_task(self._run(claimed), name=f"video-export-{job.id}")
                self._active[job.id] = task
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=0.5)
            except TimeoutError:
                pass

    async def _run(self, job: VideoExportJob) -> None:
        started = time.monotonic()
        last_persisted = 0.0

        async def progress(status: ExportStatus, stage: str, percent: float) -> None:
            nonlocal last_persisted
            now_clock = time.monotonic()
            if now_clock - last_persisted < 0.25 and percent < 100:
                return
            current = await self.require(job.id)
            if current.status in {ExportStatus.CANCELLED, ExportStatus.COMPLETED}:
                return
            await self.repository.save(
                current.model_copy(
                    update={
                        "status": status,
                        "stage": stage[:160],
                        "progress": min(99.9, max(current.progress, percent)),
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
            last_persisted = now_clock

        async def cancelled() -> bool:
            return (await self.require(job.id)).cancel_requested

        try:
            preflight = await self.preflight(job.production_id, job.backend)
            if not preflight.ready:
                raise RuntimeError(
                    "preflight failed: "
                    + "; ".join(f"{key}={value}" for key, value in preflight.checks.items())
                )
            production = await self.productions.require(job.production_id)
            output = await self.exporters[job.backend].export(
                job, production, progress=progress, cancelled=cancelled
            )
            if await cancelled():
                output.unlink(missing_ok=True)
                raise asyncio.CancelledError
            manifest_path = self.storage.sidecar(job.id, ".json")
            if not manifest_path.exists():
                manifest = ExportManifest(
                    job_id=job.id,
                    match_id=job.match_id,
                    production_id=job.production_id,
                    production_content_sha256=production.content_sha256,
                    production_version=production.timeline_version,
                    renderer_version=job.renderer_version,
                    pacing_profile_version=job.pacing_profile_version,
                    frontend_version=job.frontend_version,
                    audio_pipeline_version=job.audio_pipeline_version,
                    preset=job.preset,
                    encoder="obs",
                    frame_count=job.frame_count,
                    duration_ms=job.duration_ms,
                    source_start_ms=job.start_ms,
                    source_end_ms=job.end_ms,
                    created_at=datetime.now(UTC),
                )
                manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            caption_path = self.storage.sidecar(job.id, ".srt")
            if not caption_path.exists():
                captions_to_srt(production, caption_path)
            metadata = await probe(self.settings.video_ffprobe_path, output)
            streams = metadata.get("streams", [])
            video = next(stream for stream in streams if stream.get("codec_type") == "video")
            audio = next(
                (stream for stream in streams if stream.get("codec_type") == "audio"), None
            )
            output_size = output.stat().st_size
            output_digest = await asyncio.to_thread(file_sha256, output)
            now = datetime.now(UTC)
            current = await self.require(job.id)
            completed = current.model_copy(
                update={
                    "status": ExportStatus.COMPLETED,
                    "stage": "Complete",
                    "progress": 100.0,
                    "output_relative_path": self.storage.relative(output),
                    "manifest_relative_path": self.storage.relative(
                        self.storage.sidecar(job.id, ".json")
                    ),
                    "subtitle_relative_path": self.storage.relative(
                        self.storage.sidecar(job.id, ".srt")
                    ),
                    "video_duration_ms": round(
                        float(metadata.get("format", {}).get("duration", 0)) * 1000
                    ),
                    "render_duration_ms": round((time.monotonic() - started) * 1000),
                    "output_file_size": output_size,
                    "output_sha256": output_digest,
                    "width": int(video["width"]),
                    "height": int(video["height"]),
                    "fps": parse_rate(str(video.get("avg_frame_rate", "0/1"))),
                    "video_codec": str(video.get("codec_name")),
                    "audio_codec": str(audio.get("codec_name")) if audio else None,
                    "encoder_information": str(video.get("codec_long_name", "")),
                    "completed_at": now,
                    "updated_at": now,
                }
            )
            await self.repository.save(completed)
        except asyncio.CancelledError:
            self.storage.cleanup_job(job.id)
            current = await self.require(job.id)
            now = datetime.now(UTC)
            await self.repository.save(
                current.model_copy(
                    update={
                        "status": ExportStatus.CANCELLED,
                        "stage": "Cancelled",
                        "completed_at": now,
                        "updated_at": now,
                    }
                )
            )
        except Exception as error:
            self.storage.cleanup_job(job.id)
            current = await self.require(job.id)
            now = datetime.now(UTC)
            await self.repository.save(
                current.model_copy(
                    update={
                        "status": ExportStatus.FAILED,
                        "stage": "Failed",
                        "error_category": type(error).__name__.lower(),
                        "error_detail": str(error)[:4000],
                        "completed_at": now,
                        "updated_at": now,
                    }
                )
            )
        finally:
            self._wake.set()

    def _chromium_path(self) -> Path | None:
        if self.settings.video_chromium_path and self.settings.video_chromium_path.is_file():
            return self.settings.video_chromium_path
        candidates = (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
        )
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def _command_exists(command: str) -> bool:
        return shutil.which(command) is not None or Path(command).is_file()

    @staticmethod
    async def _version(command: str) -> str | None:
        try:
            process = await asyncio.create_subprocess_exec(
                command,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout=3)
            return output.decode(errors="replace").splitlines()[0][:240]
        except (OSError, TimeoutError, IndexError):
            return None


def os_access(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe_path = root / ".write-probe"
        probe_path.touch(exist_ok=False)
        probe_path.unlink()
        return True
    except OSError:
        return False


def parse_rate(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(value)
    return float(numerator) / float(denominator or 1)
