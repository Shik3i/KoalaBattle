from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import websockets

from koalabattle.config import Settings
from koalabattle.production.models import ProductionTimeline, Track
from koalabattle.production.speech.cache import SpeechCache

from .filesystem import VideoStorage
from .models import (
    ExportBackend,
    ExportManifest,
    ExportStatus,
    VideoExportJob,
    VideoQuality,
    frame_time_ms,
)

Progress = Callable[[ExportStatus, str, float], Awaitable[None]]
Cancelled = Callable[[], Awaitable[bool]]


async def pipe_frame_batch(stream: Any, images: list[bytes]) -> float:
    """Write an ordered frame batch while honoring subprocess backpressure."""
    started = time.monotonic()
    for image in images:
        stream.write(image)
        await stream.drain()
    return time.monotonic() - started


@dataclass
class FramePipelineMetrics:
    page_workers: int = 1
    setup_seconds: float = 0.0
    frame_loop_seconds: float = 0.0
    state_seconds: float = 0.0
    capture_seconds: float = 0.0
    pipe_seconds: float = 0.0
    encode_finalize_seconds: float = 0.0
    audio_seconds: float = 0.0
    mux_seconds: float = 0.0

    def manifest(self, duration_ms: int) -> dict[str, int | float | str]:
        measured = (
            self.setup_seconds
            + self.frame_loop_seconds
            + self.encode_finalize_seconds
            + self.audio_seconds
            + self.mux_seconds
        )
        return {
            "transport": "parallel-jpeg-image2pipe",
            "page_workers": self.page_workers,
            "setup_seconds": round(self.setup_seconds, 6),
            "frame_loop_seconds": round(self.frame_loop_seconds, 6),
            "state_worker_seconds": round(self.state_seconds, 6),
            "capture_worker_seconds": round(self.capture_seconds, 6),
            "pipe_seconds": round(self.pipe_seconds, 6),
            "encode_finalize_seconds": round(self.encode_finalize_seconds, 6),
            "audio_seconds": round(self.audio_seconds, 6),
            "mux_seconds": round(self.mux_seconds, 6),
            "measured_seconds": round(measured, 6),
            "speed_ratio": round(duration_ms / 1000 / max(0.000001, measured), 6),
        }


@dataclass
class NativePipelineMetrics:
    browser: dict[str, int | float | str]
    setup_seconds: float = 0.0
    container_seconds: float = 0.0
    audio_seconds: float = 0.0
    mux_seconds: float = 0.0

    def manifest(self, duration_ms: int) -> dict[str, int | float | str]:
        browser_total = float(self.browser.get("totalSeconds", 0.0))
        measured = (
            self.setup_seconds
            + browser_total
            + self.container_seconds
            + self.audio_seconds
            + self.mux_seconds
        )
        return {
            "transport": str(self.browser.get("transport", "canvas-webcodecs-stream")),
            "render_plan_version": "1.0",
            "production_scene_version": "2.0",
            "codec": str(self.browser.get("codec", "unknown")),
            "codec_path": str(self.browser.get("codecPath", "unknown")),
            "hardware_acceleration": str(self.browser.get("hardwareAcceleration", "no-preference")),
            "output_frames": int(self.browser.get("outputFrames", 0)),
            "unique_renders": int(self.browser.get("uniqueRenders", 0)),
            "static_held_frames": int(self.browser.get("staticHeldFrames", 0)),
            "animated_frames": int(self.browser.get("animatedFrames", 0)),
            "encoded_bytes": int(self.browser.get("encodedBytes", 0)),
            "max_encode_queue": int(self.browser.get("maxEncodeQueue", 0)),
            "asset_loads": int(self.browser.get("assetLoads", 0)),
            "asset_failures": int(self.browser.get("assetFailures", 0)),
            "cached_assets": int(self.browser.get("cachedAssets", 0)),
            "setup_seconds": round(self.setup_seconds, 6),
            "render_plan_seconds": round(float(self.browser.get("renderPlanSeconds", 0)), 6),
            "raster_seconds": round(float(self.browser.get("rasterSeconds", 0)), 6),
            "frame_create_seconds": round(float(self.browser.get("frameCreateSeconds", 0)), 6),
            "encoder_wait_seconds": round(float(self.browser.get("encoderWaitSeconds", 0)), 6),
            "transfer_seconds": round(float(self.browser.get("transferSeconds", 0)), 6),
            "browser_total_seconds": round(browser_total, 6),
            "container_seconds": round(self.container_seconds, 6),
            "audio_seconds": round(self.audio_seconds, 6),
            "mux_seconds": round(self.mux_seconds, 6),
            "measured_seconds": round(measured, 6),
            "speed_ratio": round(duration_ms / 1000 / max(0.000001, measured), 6),
        }


class WebCodecsChunkWriter:
    """Bounded WebCodecs transport sink for Annex-B H.264 or framed VP9 IVF."""

    def __init__(self, path: Path, *, width: int, height: int, fps: int) -> None:
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.codec_path: str | None = None
        self.frame_count = 0
        self.bytes_written = 0
        self._stream = path.open("w+b")

    def write_packets(self, payload: object) -> None:
        if not isinstance(payload, list) or len(payload) > 256:
            raise ValueError("invalid WebCodecs packet batch")
        for packet in payload:
            if not isinstance(packet, dict):
                raise ValueError("invalid WebCodecs packet")
            codec_path = packet.get("codecPath")
            if codec_path not in {"h264-annexb", "vp9-ivf"}:
                raise ValueError("unsupported WebCodecs packet codec")
            if self.codec_path is None:
                self.codec_path = str(codec_path)
                if codec_path == "vp9-ivf":
                    self._stream.write(self._ivf_header(0))
            elif codec_path != self.codec_path:
                raise ValueError("WebCodecs codec changed during export")
            encoded = packet.get("data")
            if not isinstance(encoded, str) or len(encoded) > 4_000_000:
                raise ValueError("invalid WebCodecs packet payload")
            data = base64.b64decode(encoded, validate=True)
            if codec_path == "vp9-ivf":
                timestamp = int(packet.get("timestamp", 0))
                self._stream.write(struct.pack("<IQ", len(data), timestamp))
            self._stream.write(data)
            self.bytes_written += len(data)
            self.frame_count += 1

    def close(self) -> None:
        if self._stream.closed:
            return
        if self.codec_path == "vp9-ivf":
            self._stream.seek(0)
            self._stream.write(self._ivf_header(self.frame_count))
        self._stream.flush()
        self._stream.close()
        if self.frame_count == 0 or self.bytes_written == 0:
            raise RuntimeError("WebCodecs returned no encoded video frames")

    def abort(self) -> None:
        if not self._stream.closed:
            self._stream.close()

    def _ivf_header(self, frames: int) -> bytes:
        return struct.pack(
            "<4sHH4sHHIIII",
            b"DKIF",
            0,
            32,
            b"VP90",
            self.width,
            self.height,
            1_000_000,
            1,
            frames,
            0,
        )


class RawFramePipe:
    """Bounded RGBA frame sink; static repeats are expanded directly into FFmpeg."""

    def __init__(self, process: asyncio.subprocess.Process, *, frame_bytes: int) -> None:
        self.process = process
        self.frame_bytes = frame_bytes
        self.frame_count = 0
        self.transferred_bytes = 0

    @classmethod
    async def start(
        cls, ffmpeg: str, output: Path, *, width: int, height: int, fps: int
    ) -> RawFramePipe:
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgba",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            "-y",
            str(output),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        return cls(process, frame_bytes=width * height * 4)

    async def write_frame(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("invalid raw-frame payload")
        encoded = payload.get("data")
        repeat = payload.get("repeat")
        max_encoded = (self.frame_bytes + 2) // 3 * 4
        if not isinstance(encoded, str) or len(encoded) > max_encoded:
            raise ValueError("invalid raw-frame data")
        if not isinstance(repeat, int) or repeat < 1 or repeat > 3600:
            raise ValueError("invalid raw-frame repeat")
        data = base64.b64decode(encoded, validate=True)
        if len(data) != self.frame_bytes:
            raise ValueError("raw-frame byte size mismatch")
        stream = self.process.stdin
        if stream is None:
            raise RuntimeError("raw-frame FFmpeg stdin is unavailable")
        for _ in range(repeat):
            stream.write(data)
            await stream.drain()
        self.frame_count += repeat
        self.transferred_bytes += len(data)

    async def close(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.is_closing():
            self.process.stdin.close()
            await self.process.stdin.wait_closed()
        stderr = await self.process.stderr.read() if self.process.stderr is not None else b""
        code = await self.process.wait()
        if code != 0:
            raise RuntimeError(stderr.decode(errors="replace")[-4000:] or "raw-frame FFmpeg failed")
        if self.frame_count == 0:
            raise RuntimeError("raw-frame compositor returned no frames")

    async def abort(self) -> None:
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()


class VideoExporter(ABC):
    backend: ExportBackend

    @abstractmethod
    async def export(
        self,
        job: VideoExportJob,
        production: ProductionTimeline,
        *,
        progress: Progress,
        cancelled: Cancelled,
    ) -> Path: ...


class LegacyScreenshotRendererExporter(VideoExporter):
    backend = ExportBackend.OFFLINE

    def __init__(self, settings: Settings, storage: VideoStorage) -> None:
        self.settings = settings
        self.storage = storage
        self.speech = SpeechCache(settings.speech_audio_root)

    async def export(
        self,
        job: VideoExportJob,
        production: ProductionTimeline,
        *,
        progress: Progress,
        cancelled: Cancelled,
    ) -> Path:
        if importlib.util.find_spec("playwright") is None:
            raise RuntimeError("Playwright is unavailable; install koalabattle[renderer]")
        from playwright.async_api import async_playwright

        await progress(ExportStatus.PREPARING, "Preparing local renderer", 2)
        video_part = self.storage.temporary(job.id, ".video.mp4.part")
        muxed_part = self.storage.temporary(job.id, ".mp4.part")
        audio_part = self.storage.temporary(job.id, ".audio.wav")
        frame_total = job.frame_count
        metrics = FramePipelineMetrics(
            page_workers=min(self.settings.video_frame_workers, max(1, frame_total))
        )
        encoder = await self._encoder(job.encoder)
        command = self._video_command(job, encoder, video_part)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None:
            raise RuntimeError("FFmpeg stdin pipe was not created")
        started = time.monotonic()
        try:
            async with async_playwright() as playwright:
                chromium = self._chromium_path()
                browser = (
                    await playwright.chromium.launch(headless=True, executable_path=str(chromium))
                    if chromium is not None
                    else await playwright.chromium.launch(headless=True)
                )
                context = await browser.new_context(
                    viewport={"width": job.preset.width, "height": job.preset.height},
                    device_scale_factor=1,
                    reduced_motion="no-preference",
                )
                await self._isolate_network(context)
                url = f"{self.settings.video_frontend_url}/render/{production.id}"
                setup_started = time.monotonic()

                async def prepare_page() -> Any:
                    page = await context.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=60_000)
                    await page.wait_for_function(
                        "() => window.__KOALABATTLE_RENDER_READY === true", timeout=60_000
                    )
                    return page

                pages = await asyncio.gather(*(prepare_page() for _ in range(metrics.page_workers)))
                metrics.setup_seconds = time.monotonic() - setup_started
                await progress(ExportStatus.RENDERING, f"Rendering 0 / {frame_total}", 5)
                last_report = 0.0
                loop_started = time.monotonic()
                for batch_start in range(0, frame_total, metrics.page_workers):
                    if await cancelled():
                        raise asyncio.CancelledError

                    async def capture(index: int, page: Any) -> tuple[bytes, float, float]:
                        logical = job.start_ms + frame_time_ms(index, job.preset.fps)
                        state_started = time.monotonic()
                        rendered = await page.evaluate(
                            "time => window.__KOALABATTLE_RENDER_AT(time)", logical
                        )
                        state_seconds = time.monotonic() - state_started
                        if rendered is not True:
                            raise RuntimeError(f"renderer rejected logical frame {index}")
                        capture_started = time.monotonic()
                        image = await page.screenshot(
                            type="jpeg",
                            quality=92,
                            animations="disabled",
                            caret="hide",
                            scale="css",
                        )
                        return image, state_seconds, time.monotonic() - capture_started

                    indexes = range(
                        batch_start, min(batch_start + metrics.page_workers, frame_total)
                    )
                    frames = await asyncio.gather(
                        *(capture(index, pages[offset]) for offset, index in enumerate(indexes))
                    )
                    images: list[bytes] = []
                    for image, state_seconds, capture_seconds in frames:
                        metrics.state_seconds += state_seconds
                        metrics.capture_seconds += capture_seconds
                        images.append(image)
                    metrics.pipe_seconds += await pipe_frame_batch(process.stdin, images)
                    now = time.monotonic()
                    completed = min(batch_start + len(frames), frame_total)
                    if now - last_report >= 0.5 or completed == frame_total:
                        percent = 5 + (completed / max(1, frame_total)) * 75
                        elapsed = max(0.001, now - loop_started)
                        media_seconds = completed / job.preset.fps
                        await progress(
                            ExportStatus.RENDERING,
                            f"Rendering frame {completed} / {frame_total} · "
                            f"{media_seconds / elapsed:.2f}x",
                            percent,
                        )
                        last_report = now
                metrics.frame_loop_seconds = time.monotonic() - loop_started
                await browser.close()
            process.stdin.close()
            await process.stdin.wait_closed()
            encode_started = time.monotonic()
            stderr = (await process.communicate())[1]
            metrics.encode_finalize_seconds = time.monotonic() - encode_started
            if process.returncode != 0:
                raise RuntimeError(self._bounded(stderr))
            await progress(ExportStatus.ENCODING, "Mixing deterministic audio", 83)
            audio_started = time.monotonic()
            has_audio = await self._audio(production, job, audio_part)
            metrics.audio_seconds = time.monotonic() - audio_started
            if has_audio:
                mux_started = time.monotonic()
                await self._mux(video_part, audio_part, muxed_part, job.duration_ms)
                metrics.mux_seconds = time.monotonic() - mux_started
            else:
                os.replace(video_part, muxed_part)
            await progress(ExportStatus.FINALIZING, "Validating MP4", 95)
            final = self.storage.final(job.id, job.output_name)
            metadata = await probe(self.settings.video_ffprobe_path, muxed_part)
            validate_probe(metadata, job, audio_expected=has_audio)
            self.storage.atomic_complete(muxed_part, final)
            await self._sidecars(job, production, encoder, final, metrics)
            _ = started
            return final
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        finally:
            for path in (video_part, audio_part):
                path.unlink(missing_ok=True)

    async def _isolate_network(self, page: Any) -> None:
        allowed = {
            urlparse(self.settings.video_frontend_url).netloc,
            urlparse(self.settings.video_api_url).netloc,
        }

        async def route(handler: Any) -> None:
            target = urlparse(handler.request.url)
            if target.scheme in {"data", "blob"} or target.netloc in allowed:
                await handler.continue_()
            else:
                await handler.abort("blockedbyclient")

        await page.route("**/*", route)

    def _video_command(self, job: VideoExportJob, encoder: str, output: Path) -> list[str]:
        preset_map = {
            VideoQuality.FAST: ("ultrafast", "28"),
            VideoQuality.BALANCED: ("medium", "21"),
            VideoQuality.HIGH: ("slow", "18"),
        }
        speed, quality = preset_map[job.preset.quality]
        args = [
            self.settings.video_ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "image2pipe",
            "-framerate",
            str(job.preset.fps),
            "-vcodec",
            "mjpeg",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            encoder,
        ]
        if encoder == "libx264":
            args.extend(["-preset", speed, "-crf", quality])
        elif encoder == "h264_videotoolbox":
            args.extend(["-q:v", "65" if job.preset.quality is VideoQuality.HIGH else "55"])
        args.extend(
            [
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                "-y",
                str(output),
            ]
        )
        return args

    async def _encoder(self, requested: str) -> str:
        encoders = await detected_encoders(self.settings.video_ffmpeg_path)
        mapping = {
            "software": "libx264",
            "videotoolbox": "h264_videotoolbox",
            "nvenc": "h264_nvenc",
            "vaapi": "h264_vaapi",
            "qsv": "h264_qsv",
        }
        if requested != "auto":
            encoder = mapping[requested]
            if encoder not in encoders:
                raise ValueError(f"requested encoder is unavailable: {encoder}")
            return encoder
        preferred = (
            "h264_videotoolbox",
            "h264_nvenc",
            "h264_qsv",
            "h264_vaapi",
            "libx264",
        )
        return next((name for name in preferred if name in encoders), "")

    async def _audio(
        self, production: ProductionTimeline, job: VideoExportJob, output: Path
    ) -> bool:
        disabled = set(production.overrides.get("disabled_cues", ()))
        custom = production.overrides.get("custom_audio", {})
        custom_audio = custom if isinstance(custom, dict) else {}
        voices: list[tuple[Path, int, int]] = []
        sfx: list[tuple[int, int, int]] = []
        music: list[tuple[Path, int, int, bool]] = []
        voice_ranges: list[tuple[int, int]] = []
        frequencies = {"impact": 120, "critical": 720, "heal": 520, "miss": 180, "result": 660}
        for cue in production.cues:
            if (
                cue.id in disabled
                or cue.start_ms >= job.end_ms
                or cue.start_ms + cue.duration_ms <= job.start_ms
            ):
                continue
            delay = max(0, cue.start_ms - job.start_ms)
            duration = min(cue.duration_ms, job.end_ms - cue.start_ms)
            key = custom_audio.get(cue.id, cue.payload.get("cache_key"))
            valid = self.speech.validate(key) if isinstance(key, str) else None
            if cue.track is Track.VOICE and valid is not None:
                voices.append((valid.path, delay, duration))
                voice_ranges.append((delay, delay + duration))
            elif cue.track is Track.SFX:
                sfx.append((frequencies.get(cue.kind, 260), delay, min(duration, 120)))
            elif cue.track is Track.MUSIC and valid is not None:
                music.append((valid.path, delay, duration, bool(cue.payload.get("loop"))))
        if not voices and not sfx and not music:
            return False
        command = [
            self.settings.video_ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "lavfi",
            "-t",
            f"{job.duration_ms / 1000:.6f}",
            "-i",
            "anullsrc=r=48000:cl=stereo",
        ]
        for path, _, _ in voices:
            command.extend(["-i", str(path)])
        for frequency, _, duration in sfx:
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{duration / 1000:.6f}",
                    "-i",
                    f"sine=frequency={frequency}:sample_rate=48000",
                ]
            )
        for path, _, _, loop in music:
            if loop:
                command.extend(["-stream_loop", "-1"])
            command.extend(["-i", str(path)])
        filters: list[str] = []
        labels = ["[0:a]"]
        index = 1
        for _, delay, duration in voices:
            label = f"v{index}"
            filters.append(
                f"[{index}:a]atrim=0:{duration / 1000:.6f},"
                f"adelay={delay}|{delay},volume=1.0[{label}]"
            )
            labels.append(f"[{label}]")
            index += 1
        for _, delay, duration in sfx:
            label = f"s{index}"
            fade_start = max(0.0, duration / 1000 - 0.1)
            filters.append(
                f"[{index}:a]adelay={delay}|{delay},volume=0.052,afade=t=out:st={fade_start:.6f}:d=0.1[{label}]"
            )
            labels.append(f"[{label}]")
            index += 1
        ducking = 10 ** (production.profile.ducking_db / 20)
        for _, delay, duration, _ in music:
            label = f"m{index}"
            ranges = [
                (max(0, start - delay) / 1000, max(0, end - delay) / 1000)
                for start, end in voice_ranges
                if end > delay and start < delay + duration
            ]
            active = "+".join(f"between(t,{start:.6f},{end:.6f})" for start, end in ranges) or "0"
            filters.append(
                f"[{index}:a]atrim=0:{duration / 1000:.6f},"
                f"volume='0.35*if({active},{ducking:.6f},1)',"
                f"adelay={delay}|{delay}[{label}]"
            )
            labels.append(f"[{label}]")
            index += 1
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[a]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[a]",
                "-t",
                f"{job.duration_ms / 1000:.6f}",
                "-c:a",
                "pcm_s16le",
                "-y",
                str(output),
            ]
        )
        await run_checked(command)
        return True

    async def _mux(self, video: Path, audio: Path, output: Path, duration_ms: int) -> None:
        await run_checked(
            [
                self.settings.video_ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-i",
                str(video),
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-t",
                f"{duration_ms / 1000:.6f}",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                "-y",
                str(output),
            ]
        )

    async def _sidecars(
        self,
        job: VideoExportJob,
        production: ProductionTimeline,
        encoder: str,
        final: Path,
        metrics: FramePipelineMetrics | NativePipelineMetrics,
    ) -> None:
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
            visual_profile_version=job.visual_profile_version,
            preset=job.preset,
            encoder=encoder,
            frame_count=job.frame_count,
            duration_ms=job.duration_ms,
            source_start_ms=job.start_ms,
            source_end_ms=job.end_ms,
            assets={"network": "local-only", "output": final.name},
            renderer_metrics=metrics.manifest(job.duration_ms),
            created_at=datetime.now(UTC),
        )
        self.storage.sidecar(job.id, ".json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        captions_to_srt(production, self.storage.sidecar(job.id, ".srt"))

    @staticmethod
    def _bounded(value: bytes) -> str:
        return value.decode(errors="replace")[-4000:] or "FFmpeg failed without diagnostics"

    def _chromium_path(self) -> Path | None:
        configured = self.settings.video_chromium_path
        if configured is not None and configured.is_file():
            return configured
        candidates = (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
        )
        return next((path for path in candidates if path.is_file()), None)


class OfflineRendererExporter(LegacyScreenshotRendererExporter):
    """Default deterministic Canvas compositor with streaming WebCodecs output."""

    async def export(
        self,
        job: VideoExportJob,
        production: ProductionTimeline,
        *,
        progress: Progress,
        cancelled: Cancelled,
    ) -> Path:
        if job.render_engine == "legacy":
            return await super().export(job, production, progress=progress, cancelled=cancelled)
        if importlib.util.find_spec("playwright") is None:
            raise RuntimeError("Playwright is unavailable; install koalabattle[renderer]")
        from playwright.async_api import async_playwright

        await progress(ExportStatus.PREPARING, "Preparing native production compositor", 2)
        encoded_part = self.storage.temporary(job.id, ".webcodecs.part")
        video_part = self.storage.temporary(job.id, ".video.mp4.part")
        muxed_part = self.storage.temporary(job.id, ".mp4.part")
        audio_part = self.storage.temporary(job.id, ".audio.wav")
        transport = self._native_transport()
        writer = (
            WebCodecsChunkWriter(
                encoded_part,
                width=job.preset.width,
                height=job.preset.height,
                fps=job.preset.fps,
            )
            if transport == "webcodecs"
            else None
        )
        raw_pipe = (
            await RawFramePipe.start(
                self.settings.video_ffmpeg_path,
                video_part,
                width=job.preset.width,
                height=job.preset.height,
                fps=job.preset.fps,
            )
            if transport == "raw-rgba"
            else None
        )
        browser_metrics: dict[str, int | float | str] = {}
        setup_seconds = 0.0
        browser = None
        try:
            async with async_playwright() as playwright:
                chromium = self._chromium_path()
                browser = (
                    await playwright.chromium.launch(
                        headless=True,
                        executable_path=str(chromium),
                        args=self._native_chromium_args(),
                    )
                    if chromium is not None
                    else await playwright.chromium.launch(
                        headless=True, args=self._native_chromium_args()
                    )
                )
                context = await browser.new_context(
                    viewport={"width": job.preset.width, "height": job.preset.height},
                    device_scale_factor=1,
                    reduced_motion="no-preference",
                )
                await self._isolate_network(context)
                page = await context.new_page()

                async def write_chunks(_: object, payload: object) -> None:
                    if writer is None:
                        raise RuntimeError("WebCodecs transport was not selected")
                    writer.write_packets(payload)

                async def write_raw_frame(_: object, payload: object) -> None:
                    if raw_pipe is None:
                        raise RuntimeError("raw-frame transport was not selected")
                    await raw_pipe.write_frame(payload)

                async def render_progress(_: object, payload: object) -> None:
                    if not isinstance(payload, dict):
                        return
                    completed = int(payload.get("completed", 0))
                    total = int(payload.get("total", job.frame_count))
                    speed = float(payload.get("speedRatio", 0.0))
                    percent = 5 + completed / max(1, total) * 75
                    await progress(
                        ExportStatus.RENDERING,
                        f"Native compositor {completed} / {total} · {speed:.2f}x",
                        percent,
                    )

                async def render_cancelled(_: object) -> bool:
                    return await cancelled()

                await page.expose_binding("__KOALABATTLE_WRITE_CHUNKS", write_chunks)
                await page.expose_binding("__KOALABATTLE_WRITE_RAW_FRAME", write_raw_frame)
                await page.expose_binding("__KOALABATTLE_RENDER_PROGRESS", render_progress)
                await page.expose_binding("__KOALABATTLE_RENDER_CANCELLED", render_cancelled)
                setup_started = time.monotonic()
                url = f"{self.settings.video_frontend_url}/render/{production.id}?engine=native"
                await page.goto(url, wait_until="networkidle", timeout=60_000)
                await page.wait_for_function(
                    "() => window.__KOALABATTLE_RENDER_READY === true", timeout=60_000
                )
                setup_seconds = time.monotonic() - setup_started
                await progress(ExportStatus.RENDERING, "Native compositor 0 frames", 5)
                request = {
                    "width": job.preset.width,
                    "height": job.preset.height,
                    "fps": job.preset.fps,
                    "bitrate": self._native_bitrate(job),
                    "startMs": job.start_ms,
                    "endMs": job.end_ms,
                    "hardwareAcceleration": self._hardware_preference(job.encoder),
                    "assetApiBase": self.settings.video_api_url.rstrip("/"),
                    "transport": transport,
                }
                try:
                    result = await page.evaluate(
                        "request => window.__KOALABATTLE_NATIVE_RENDER(request)", request
                    )
                except Exception:
                    if await cancelled():
                        raise asyncio.CancelledError from None
                    raise
                if not isinstance(result, dict):
                    raise RuntimeError("native compositor returned invalid metrics")
                browser_metrics = {
                    str(key): value
                    for key, value in result.items()
                    if isinstance(value, int | float | str)
                }
                await browser.close()
                browser = None
            metrics = NativePipelineMetrics(browser=browser_metrics, setup_seconds=setup_seconds)
            await progress(ExportStatus.ENCODING, "Finalizing deterministic video stream", 82)
            codec_path: str | None
            if raw_pipe is not None:
                await raw_pipe.close()
                if raw_pipe.frame_count != job.frame_count:
                    raise RuntimeError(
                        f"raw-frame count mismatch: {raw_pipe.frame_count} != {job.frame_count}"
                    )
                ffmpeg_encoder = "libx264"
                codec_path = "raw-rgba"
            else:
                if writer is None:
                    raise RuntimeError("native compositor transport was not initialized")
                writer.close()
                if writer.frame_count != job.frame_count:
                    raise RuntimeError(
                        f"WebCodecs frame count mismatch: {writer.frame_count} != {job.frame_count}"
                    )
                container_started = time.monotonic()
                ffmpeg_encoder = await self._container_video(
                    encoded_part, video_part, job, writer.codec_path
                )
                metrics.container_seconds = time.monotonic() - container_started
                codec_path = writer.codec_path
                if codec_path is None:
                    raise RuntimeError("WebCodecs compositor returned no codec path")
            await progress(ExportStatus.ENCODING, "Mixing deterministic audio", 87)
            audio_started = time.monotonic()
            has_audio = await self._audio(production, job, audio_part)
            metrics.audio_seconds = time.monotonic() - audio_started
            if has_audio:
                mux_started = time.monotonic()
                await self._mux(video_part, audio_part, muxed_part, job.duration_ms)
                metrics.mux_seconds = time.monotonic() - mux_started
            else:
                os.replace(video_part, muxed_part)
            await progress(ExportStatus.FINALIZING, "Validating native H.264 MP4", 95)
            final = self.storage.final(job.id, job.output_name)
            metadata = await probe(self.settings.video_ffprobe_path, muxed_part)
            validate_probe(metadata, job, audio_expected=has_audio)
            video_stream = next(
                stream
                for stream in metadata.get("streams", [])
                if stream.get("codec_type") == "video"
            )
            if video_stream.get("codec_name") != "h264":
                raise ValueError("native production output is not H.264")
            self.storage.atomic_complete(muxed_part, final)
            encoder_label = (
                "canvas-raw-rgba+libx264"
                if codec_path == "raw-rgba"
                else "webcodecs-h264"
                if codec_path == "h264-annexb"
                else f"webcodecs-vp9+{ffmpeg_encoder}"
            )
            await self._sidecars(job, production, encoder_label, final, metrics)
            return final
        finally:
            if browser is not None:
                await browser.close()
            if writer is not None:
                writer.abort()
            if raw_pipe is not None:
                await raw_pipe.abort()
            for path in (encoded_part, video_part, muxed_part, audio_part):
                path.unlink(missing_ok=True)

    async def _container_video(
        self,
        encoded: Path,
        output: Path,
        job: VideoExportJob,
        codec_path: str | None,
    ) -> str:
        if codec_path == "h264-annexb":
            await run_checked(
                [
                    self.settings.video_ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-fflags",
                    "+genpts",
                    "-r",
                    str(job.preset.fps),
                    "-f",
                    "h264",
                    "-i",
                    str(encoded),
                    "-an",
                    "-c:v",
                    "copy",
                    "-movflags",
                    "+faststart",
                    "-f",
                    "mp4",
                    "-y",
                    str(output),
                ]
            )
            return "copy"
        if codec_path != "vp9-ivf":
            raise RuntimeError("native compositor returned no supported codec")
        encoder = await self._encoder(job.encoder)
        command = [
            self.settings.video_ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "ivf",
            "-i",
            str(encoded),
            "-an",
            "-c:v",
            encoder,
        ]
        if encoder == "libx264":
            command.extend(["-preset", "medium", "-crf", "21"])
        command.extend(
            [
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                "-y",
                str(output),
            ]
        )
        await run_checked(command)
        return encoder

    @staticmethod
    def _hardware_preference(encoder: str) -> str:
        if encoder == "software":
            return "prefer-software"
        if encoder in {"videotoolbox", "nvenc", "vaapi", "qsv"}:
            return "prefer-hardware"
        return "no-preference"

    @staticmethod
    def _native_bitrate(job: VideoExportJob) -> int:
        base = {
            VideoQuality.FAST: 6_000_000,
            VideoQuality.BALANCED: 12_000_000,
            VideoQuality.HIGH: 20_000_000,
        }[job.preset.quality]
        scale = job.preset.width * job.preset.height / (1920 * 1080)
        frame_scale = job.preset.fps / 60
        return round(base * max(0.45, scale) * max(0.65, frame_scale))

    def _native_chromium_args(self) -> list[str]:
        target = urlparse(self.settings.video_frontend_url)
        if target.scheme != "http" or target.hostname in {"localhost", "127.0.0.1", "::1"}:
            return []
        origin = f"{target.scheme}://{target.netloc}"
        return [f"--unsafely-treat-insecure-origin-as-secure={origin}"]

    def _native_transport(self) -> str:
        configured = self.settings.video_native_transport
        if configured != "auto":
            return configured
        return "raw-rgba" if sys.platform.startswith("linux") else "webcodecs"


class OBSRecorderExporter(VideoExporter):
    backend = ExportBackend.OBS

    def __init__(self, settings: Settings, storage: VideoStorage) -> None:
        self.settings = settings
        self.storage = storage

    async def export(
        self,
        job: VideoExportJob,
        production: ProductionTimeline,
        *,
        progress: Progress,
        cancelled: Cancelled,
    ) -> Path:
        client = OBSWebSocketClient(
            self.settings.obs_host, self.settings.obs_port, self.settings.obs_password
        )
        await progress(ExportStatus.PREPARING, "Connecting to OBS WebSocket v5", 3)
        await client.connect()
        started = False
        original_settings: dict[str, Any] | None = None
        try:
            scenes = await client.request("GetSceneList")
            names = {scene.get("sceneName") for scene in scenes.get("scenes", [])}
            if self.settings.obs_scene not in names:
                raise RuntimeError(f"OBS scene not found: {self.settings.obs_scene}")
            items = await client.request("GetSceneItemList", {"sceneName": self.settings.obs_scene})
            sources = {item.get("sourceName") for item in items.get("sceneItems", [])}
            if self.settings.obs_browser_source not in sources:
                raise RuntimeError(
                    f"OBS Browser Source not found in scene: {self.settings.obs_browser_source}"
                )
            input_data = await client.request(
                "GetInputSettings", {"inputName": self.settings.obs_browser_source}
            )
            if "browser" not in str(input_data.get("inputKind", "")).lower():
                raise RuntimeError("configured OBS input is not a Browser Source")
            original_settings = dict(input_data.get("inputSettings", {}))
            await client.request("StartRecord")
            started = True
            render_url = (
                f"{self.settings.video_frontend_url}/render/{production.id}"
                f"?autoplay=1&session={job.id}"
            )
            await client.request(
                "SetInputSettings",
                {
                    "inputName": self.settings.obs_browser_source,
                    "inputSettings": {**original_settings, "url": render_url},
                    "overlay": False,
                },
            )
            start = time.monotonic()
            while True:
                elapsed = (time.monotonic() - start) * 1000
                if await cancelled():
                    raise asyncio.CancelledError
                if elapsed >= job.duration_ms:
                    break
                await progress(
                    ExportStatus.RENDERING,
                    "OBS realtime recording",
                    min(90, 5 + elapsed / max(1, job.duration_ms) * 85),
                )
                await asyncio.sleep(min(0.5, (job.duration_ms - elapsed) / 1000))
            result = await client.request("StopRecord")
            started = False
            output = Path(str(result.get("outputPath", ""))).resolve()
            if not output.is_file():
                raise RuntimeError("OBS stopped but did not return a readable recording path")
            temporary = self.storage.temporary(job.id, ".mp4.part")
            final = self.storage.final(job.id, job.output_name)
            shutil.copy2(output, temporary)
            await progress(ExportStatus.FINALIZING, "Validating OBS recording", 95)
            metadata = await probe(self.settings.video_ffprobe_path, temporary)
            validate_probe(metadata, job, audio_expected=False)
            self.storage.atomic_complete(temporary, final)
            return final
        finally:
            if started:
                try:
                    await client.request("StopRecord")
                except Exception:
                    pass
            if original_settings is not None:
                try:
                    await client.request(
                        "SetInputSettings",
                        {
                            "inputName": self.settings.obs_browser_source,
                            "inputSettings": original_settings,
                            "overlay": False,
                        },
                    )
                except Exception:
                    pass
            await client.close()


class WebSocketLike(Protocol):
    async def send(self, value: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...


class OBSWebSocketClient:
    def __init__(self, host: str, port: int, password: str | None) -> None:
        self.url = f"ws://{host}:{port}"
        self.password = password or ""
        self.socket: WebSocketLike | None = None
        self.sequence = 0

    async def connect(self) -> None:
        self.socket = cast(WebSocketLike, await websockets.connect(self.url, open_timeout=5))
        hello = await self._receive()
        if hello.get("op") != 0:
            raise RuntimeError("OBS did not send protocol v5 Hello")
        authentication = hello.get("d", {}).get("authentication")
        identify: dict[str, Any] = {"rpcVersion": 1}
        if authentication:
            if not self.password:
                raise PermissionError("OBS authentication is enabled but no password is configured")
            secret = base64.b64encode(
                hashlib.sha256((self.password + authentication["salt"]).encode()).digest()
            ).decode()
            identify["authentication"] = base64.b64encode(
                hashlib.sha256((secret + authentication["challenge"]).encode()).digest()
            ).decode()
        await self.socket.send(json.dumps({"op": 1, "d": identify}))
        identified = await self._receive()
        if identified.get("op") != 2:
            raise PermissionError("OBS WebSocket authentication/identification failed")

    async def request(
        self, request_type: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self.socket is None:
            raise RuntimeError("OBS WebSocket is not connected")
        self.sequence += 1
        request_id = str(self.sequence)
        await self.socket.send(
            json.dumps(
                {
                    "op": 6,
                    "d": {
                        "requestType": request_type,
                        "requestId": request_id,
                        "requestData": data or {},
                    },
                }
            )
        )
        while True:
            response = await self._receive()
            body = response.get("d", {})
            if response.get("op") == 7 and body.get("requestId") == request_id:
                status = body.get("requestStatus", {})
                if not status.get("result"):
                    code = status.get("code")
                    comment = status.get("comment", "")
                    raise RuntimeError(f"OBS {request_type} failed ({code}): {comment}")
                return cast(dict[str, Any], body.get("responseData", {}))

    async def close(self) -> None:
        if self.socket is not None:
            await self.socket.close()
            self.socket = None

    async def _receive(self) -> dict[str, Any]:
        if self.socket is None:
            raise RuntimeError("OBS WebSocket is not connected")
        value = await self.socket.recv()
        if isinstance(value, bytes):
            value = value.decode()
        return cast(dict[str, Any], json.loads(value))


async def run_checked(command: list[str]) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace")[-4000:])
    return stdout


async def detected_encoders(ffmpeg: str) -> tuple[str, ...]:
    if shutil.which(ffmpeg) is None and not Path(ffmpeg).is_file():
        return ()
    output = (await run_checked([ffmpeg, "-hide_banner", "-encoders"])).decode(errors="replace")
    wanted = ("libx264", "h264_videotoolbox", "h264_nvenc", "h264_vaapi", "h264_qsv")
    return tuple(name for name in wanted if name in output)


async def probe(ffprobe: str, path: Path) -> dict[str, Any]:
    output = await run_checked(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    return cast(dict[str, Any], json.loads(output))


def validate_probe(metadata: dict[str, Any], job: VideoExportJob, *, audio_expected: bool) -> None:
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError("encoded output has no video stream")
    if video.get("width") != job.preset.width or video.get("height") != job.preset.height:
        raise ValueError("encoded output resolution differs from preset")
    if audio_expected and audio is None:
        raise ValueError("encoded output is missing its expected audio stream")
    duration = float(metadata.get("format", {}).get("duration", 0))
    tolerance = max(0.1, 1 / job.preset.fps + 0.05)
    if abs(duration - job.duration_ms / 1000) > tolerance:
        raise ValueError("encoded output duration differs from production range")


def captions_to_srt(production: ProductionTimeline, output: Path) -> None:
    entries: list[tuple[int, int, str]] = []
    for cue in production.cues:
        if cue.track is not Track.CAPTIONS:
            continue
        segments = cue.payload.get("segments", [])
        if not isinstance(segments, list):
            continue
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            entries.append(
                (
                    cue.start_ms + int(segment.get("start_ms", 0)),
                    cue.start_ms + int(segment.get("end_ms", cue.duration_ms)),
                    str(segment.get("text", "")).replace("\n", " "),
                )
            )
    lines: list[str] = []
    for index, (start, end, text) in enumerate(entries, 1):
        lines.extend([str(index), f"{srt_time(start)} --> {srt_time(end)}", text, ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
