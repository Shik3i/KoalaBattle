from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import shutil
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


class OfflineRendererExporter(VideoExporter):
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

                pages = await asyncio.gather(
                    *(prepare_page() for _ in range(metrics.page_workers))
                )
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
        metrics: FramePipelineMetrics,
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
