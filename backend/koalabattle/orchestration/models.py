from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from koalabattle.core.models import AgentConfiguration, ProviderKind
from koalabattle.video.models import RenderEngine

ORCHESTRATOR_SCHEMA_VERSION = "1.0"


class OrchestratorFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OrchestratorStatus(StrEnum):
    QUEUED = "queued"
    BUILDING_TEAMS = "building-teams"
    QUEUED_MATCH = "queued-match"
    RUNNING_MATCH = "running-match"
    PREPARING_PRODUCTION = "preparing-production"
    QUEUED_VIDEO = "queued-video"
    RENDERING_VIDEO = "rendering-video"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OrchestratorPlayer(OrchestratorFrozenModel):
    display_name: str = Field(min_length=1, max_length=80)
    provider: ProviderKind = ProviderKind.OPENAI_COMPATIBLE
    model: str = Field(default="google/gemma-4-e4b", min_length=1, max_length=200)
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)
    team_snapshot_id: UUID | None = None


def _default_players() -> tuple[OrchestratorPlayer, OrchestratorPlayer]:
    return (
        OrchestratorPlayer(display_name="Gemma 4 · Player One"),
        OrchestratorPlayer(display_name="Gemma 4 · Player Two"),
    )


class OrchestratorSettings(OrchestratorFrozenModel):
    format: str | None = Field(default=None, min_length=1, max_length=80)
    best_of: int = Field(default=1, ge=1, le=7)
    players: tuple[OrchestratorPlayer, OrchestratorPlayer] = Field(default_factory=_default_players)
    build_teams: bool = True
    banter_enabled: bool = False
    auto_render: bool = True
    video_preset_id: str = Field(default="fast-preview", min_length=1, max_length=60)
    render_engine: RenderEngine = RenderEngine.NATIVE
    encoder: Literal["auto", "software", "videotoolbox", "nvenc", "vaapi", "qsv"] = "software"
    production_profile_id: str = Field(default="live-stream", min_length=1, max_length=60)
    narrator_enabled: bool = False
    narrator_profile_id: str = Field(default="stadium-broadcast-v1", min_length=1, max_length=80)
    narrator_mode: Literal["off", "highlights", "broadcast", "full"] = "highlights"
    narrator_voice_preset_id: str = Field(
        default="edge-neural-narrator", min_length=1, max_length=80
    )
    voice_pool_id: str | None = Field(default=None, max_length=80)
    voice_selection_mode: Literal["explicit", "random", "balanced-random"] = "explicit"
    voice_selection_seed: int | None = None


class OrchestratorRequest(OrchestratorFrozenModel):
    """Natural-language intent plus optional explicit settings for external agents."""

    instruction: str = Field(default="", max_length=4_000)
    settings: OrchestratorSettings = Field(default_factory=OrchestratorSettings)


class OrchestratorQuestion(OrchestratorFrozenModel):
    field: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=400)


class OrchestratorPlan(OrchestratorFrozenModel):
    schema_version: str = ORCHESTRATOR_SCHEMA_VERSION
    ready: bool
    settings: OrchestratorSettings
    questions: tuple[OrchestratorQuestion, ...] = ()
    warnings: tuple[str, ...] = ()
    format_name: str | None = None


class OrchestratorTeamResult(OrchestratorFrozenModel):
    participant: str
    audit_id: UUID | None = None
    snapshot_id: UUID | None = None
    success: bool = False
    errors: tuple[str, ...] = ()


class OrchestratorRun(OrchestratorFrozenModel):
    schema_version: str = ORCHESTRATOR_SCHEMA_VERSION
    id: UUID
    status: OrchestratorStatus
    stage: str
    progress: float = Field(ge=0, le=100)
    settings: OrchestratorSettings
    teams: tuple[OrchestratorTeamResult, ...] = ()
    match_id: UUID | None = None
    production_id: UUID | None = None
    video_job_id: UUID | None = None
    error: str | None = Field(default=None, max_length=4_000)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def completed_run_has_timestamp(self) -> OrchestratorRun:
        if (
            self.status
            in {
                OrchestratorStatus.COMPLETED,
                OrchestratorStatus.FAILED,
                OrchestratorStatus.CANCELLED,
            }
            and self.completed_at is None
        ):
            raise ValueError("terminal orchestrator runs require completed_at")
        return self


class OrchestratorCapabilities(OrchestratorFrozenModel):
    schema_version: str = ORCHESTRATOR_SCHEMA_VERSION
    endpoint: str = "/api/orchestrator/runs"
    planning_endpoint: str = "/api/orchestrator/plan"
    default_format: str = "gen9ou"
    default_model: str = "google/gemma-4-e4b"
    default_timeout_seconds: float = 300.0
    default_max_retries: int = 1
    supports_team_building: bool = True
    supports_banter: bool = True
    supports_video_render: bool = True
    supports_narrator: bool = True
    narrator_modes: tuple[str, ...] = ("off", "highlights", "broadcast", "full")
    narrator_profiles: tuple[str, ...] = (
        "stadium-broadcast-v1",
        "battle-revolution-v1",
        "minimal-highlights-v1",
    )
    supported_best_of: tuple[int, ...] = (1,)
