from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

VIDEO_SCHEMA_VERSION = "1.1"
RENDERER_VERSION = "0.9.0-native-compositor-v1"
AUDIO_PIPELINE_VERSION = "1.1"
VISUAL_PROFILE_VERSION = "2.0"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExportBackend(StrEnum):
    OFFLINE = "offline"
    OBS = "obs"


class RenderEngine(StrEnum):
    NATIVE = "native"
    LEGACY = "legacy"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RENDERING = "rendering"
    ENCODING = "encoding"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class VideoQuality(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    HIGH = "high"


class PacingProfile(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,59}$")
    display_name: str = Field(max_length=100)
    version: str = "1.0"
    event_gap_ms: int = Field(ge=0, le=5000)
    thinking_ms: int = Field(ge=0, le=5000)
    result_ms: int = Field(ge=250, le=30_000)
    commentary_policy: str = Field(pattern=r"^(full|concise|minimal)$")


PACING_PROFILES: dict[str, PacingProfile] = {
    profile.id: profile
    for profile in (
        PacingProfile(
            id="full-replay",
            display_name="Full Replay",
            event_gap_ms=220,
            thinking_ms=1200,
            result_ms=5000,
            commentary_policy="full",
        ),
        PacingProfile(
            id="youtube",
            display_name="YouTube",
            event_gap_ms=180,
            thinking_ms=1000,
            result_ms=3500,
            commentary_policy="full",
        ),
        PacingProfile(
            id="fast",
            display_name="Fast",
            event_gap_ms=30,
            thinking_ms=250,
            result_ms=1500,
            commentary_policy="concise",
        ),
        PacingProfile(
            id="shorts",
            display_name="Shorts",
            event_gap_ms=20,
            thinking_ms=150,
            result_ms=1200,
            commentary_policy="minimal",
        ),
    )
}


class VideoExportPreset(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,59}$")
    display_name: str = Field(max_length=100)
    version: str = "1.0"
    width: int = Field(ge=320, le=3840)
    height: int = Field(ge=240, le=3840)
    fps: int = Field(ge=1, le=60)
    codec: str = Field(default="h264", pattern=r"^(h264|hevc|av1)$")
    quality: VideoQuality = VideoQuality.BALANCED
    pacing_profile: str = Field(max_length=60)
    layout: str = Field(pattern=r"^(16:9|9:16)$")


PRESETS: dict[str, VideoExportPreset] = {
    preset.id: preset
    for preset in (
        VideoExportPreset(
            id="youtube-1080p60",
            display_name="YouTube 1080p60",
            width=1920,
            height=1080,
            fps=60,
            pacing_profile="youtube",
            layout="16:9",
        ),
        VideoExportPreset(
            id="youtube-1080p30",
            display_name="YouTube 1080p30",
            width=1920,
            height=1080,
            fps=30,
            pacing_profile="youtube",
            layout="16:9",
        ),
        VideoExportPreset(
            id="youtube-1440p60",
            display_name="YouTube 1440p60",
            width=2560,
            height=1440,
            fps=60,
            quality=VideoQuality.HIGH,
            pacing_profile="youtube",
            layout="16:9",
        ),
        VideoExportPreset(
            id="youtube-4k60",
            display_name="YouTube 4K60",
            width=3840,
            height=2160,
            fps=60,
            quality=VideoQuality.HIGH,
            pacing_profile="youtube",
            layout="16:9",
        ),
        VideoExportPreset(
            id="vertical-1080p60",
            display_name="Vertical 1080x1920",
            width=1080,
            height=1920,
            fps=60,
            pacing_profile="shorts",
            layout="9:16",
        ),
        VideoExportPreset(
            id="vertical-1080p30",
            display_name="Vertical 1080x1920 30 FPS",
            width=1080,
            height=1920,
            fps=30,
            pacing_profile="shorts",
            layout="9:16",
        ),
        VideoExportPreset(
            id="fast-preview",
            display_name="Fast Preview",
            width=1280,
            height=720,
            fps=30,
            quality=VideoQuality.FAST,
            pacing_profile="fast",
            layout="16:9",
        ),
    )
}


class CreateVideoExport(FrozenModel):
    production_id: UUID
    backend: ExportBackend = ExportBackend.OFFLINE
    preset_id: str = "youtube-1080p60"
    output_name: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(
        default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    priority: int = Field(default=0, ge=-10, le=10)
    start_ms: int = Field(default=0, ge=0)
    end_ms: int | None = Field(default=None, gt=0)
    encoder: str = Field(default="auto", pattern=r"^(auto|software|videotoolbox|nvenc|vaapi|qsv)$")
    render_engine: RenderEngine = RenderEngine.NATIVE

    @model_validator(mode="after")
    def valid_range(self) -> CreateVideoExport:
        if self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class VideoExportJob(FrozenModel):
    id: UUID
    production_id: UUID
    match_id: UUID
    backend: ExportBackend
    preset: VideoExportPreset
    output_name: str
    idempotency_key: str | None = None
    priority: int = 0
    start_ms: int = 0
    end_ms: int
    status: ExportStatus = ExportStatus.QUEUED
    stage: str = "Queued"
    progress: float = Field(default=0.0, ge=0, le=100)
    cancel_requested: bool = False
    attempt: int = Field(default=1, ge=1)
    renderer_version: str = RENDERER_VERSION
    pacing_profile_version: str = "1.0"
    frontend_version: str = "0.9.0"
    production_schema_version: str = "2.0"
    audio_pipeline_version: str = AUDIO_PIPELINE_VERSION
    visual_profile_version: str = VISUAL_PROFILE_VERSION
    encoder: str = "auto"
    render_engine: RenderEngine = RenderEngine.NATIVE
    encoder_information: str | None = None
    output_relative_path: str | None = None
    manifest_relative_path: str | None = None
    subtitle_relative_path: str | None = None
    video_duration_ms: int | None = None
    render_duration_ms: int | None = None
    output_frame_count: int | None = None
    unique_rendered_frames: int | None = None
    static_held_frames: int | None = None
    animated_frames: int | None = None
    renderer_transport: str | None = None
    selected_encoder: str | None = None
    output_file_size: int | None = None
    output_sha256: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    error_category: str | None = Field(default=None, max_length=80)
    error_detail: str | None = Field(default=None, max_length=4000)
    diagnostics: tuple[str, ...] = Field(default=(), max_length=100)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def frame_count(self) -> int:
        return frame_count(self.duration_ms, self.preset.fps)


class RendererCapabilities(FrozenModel):
    offline_available: bool
    obs_configured: bool
    ffmpeg_available: bool
    ffmpeg_version: str | None = None
    ffprobe_available: bool
    chromium_available: bool
    chromium_version: str | None = None
    playwright_available: bool
    native_compositor_available: bool = False
    webcodecs_available: bool = False
    webcodecs_h264: bool = False
    webcodecs_vp9: bool = False
    raw_frame_available: bool = False
    legacy_renderer_available: bool = False
    default_render_engine: RenderEngine = RenderEngine.NATIVE
    compositor_backend: str = "canvas2d"
    encoders: tuple[str, ...] = ()
    output_writable: bool
    output_root: str
    free_bytes: int
    storage_bytes: int
    concurrency: int
    obs_host: str
    obs_port: int
    obs_scene: str
    detail: tuple[str, ...] = ()


class ExportPreflight(FrozenModel):
    ready: bool
    checks: dict[str, str]
    missing_speech: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class ExportManifest(FrozenModel):
    schema_version: str = VIDEO_SCHEMA_VERSION
    job_id: UUID
    match_id: UUID
    production_id: UUID
    production_content_sha256: str | None
    production_version: str
    renderer_version: str
    pacing_profile_version: str
    frontend_version: str
    audio_pipeline_version: str
    visual_profile_version: str = VISUAL_PROFILE_VERSION
    preset: VideoExportPreset
    encoder: str
    frame_count: int
    duration_ms: int
    source_start_ms: int
    source_end_ms: int
    assets: dict[str, Any] = Field(default_factory=dict)
    renderer_metrics: dict[str, int | float | str] = Field(default_factory=dict)
    created_at: datetime


def frame_time_ms(index: int, fps: int) -> float:
    if index < 0 or fps <= 0:
        raise ValueError("frame index must be non-negative and fps positive")
    return index * 1000 / fps


def frame_count(duration_ms: int, fps: int) -> int:
    if duration_ms <= 0 or fps <= 0:
        return 0
    return math.ceil(duration_ms * fps / 1000)
