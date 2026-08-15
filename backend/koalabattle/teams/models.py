from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from koalabattle.core.models import (
    AgentConfiguration,
    ProviderKind,
    ProviderUsage,
    TeamSource,
)

TEAM_SCHEMA_VERSION = "1.0"
TEAM_BUILD_PROFILE_VERSION = "gen9ou-builder-v1"
SUPPORTED_CUSTOM_FORMAT = "gen9ou"
MAX_TEAM_TEXT_LENGTH = 50_000


class FrozenTeamModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TeamValidationResult(FrozenTeamModel):
    schema_version: str = TEAM_SCHEMA_VERSION
    format: Literal["gen9ou"] = "gen9ou"
    valid: bool
    errors: tuple[str, ...] = ()
    normalized_export: str | None = None
    packed_team: str | None = None
    structured_team: tuple[dict[str, Any], ...] = ()


class TeamSnapshot(FrozenTeamModel):
    schema_version: str = TEAM_SCHEMA_VERSION
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    format: Literal["gen9ou"] = "gen9ou"
    source: TeamSource
    submitted_text: str = Field(max_length=MAX_TEAM_TEXT_LENGTH)
    normalized_export: str = Field(max_length=MAX_TEAM_TEXT_LENGTH)
    packed_team: str = Field(max_length=MAX_TEAM_TEXT_LENGTH)
    structured_team: tuple[dict[str, Any], ...]
    generation_audit: dict[str, Any] | None = None
    created_at: datetime


class TeamBuildRequest(FrozenTeamModel):
    name: str = Field(min_length=1, max_length=120)
    participant: str = Field(min_length=1, max_length=80)
    format: Literal["gen9ou"] = "gen9ou"
    provider: ProviderKind
    model: str = Field(min_length=1, max_length=200)
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)
    max_repair_attempts: int = Field(default=2, ge=0, le=3)


class TeamBuildAudit(FrozenTeamModel):
    schema_version: str = TEAM_SCHEMA_VERSION
    id: UUID
    participant: str
    provider: str
    model: str
    format: Literal["gen9ou"] = "gen9ou"
    prompt_profile_version: str = TEAM_BUILD_PROFILE_VERSION
    rendered_prompt: str
    raw_responses: tuple[str, ...]
    validation_errors: tuple[tuple[str, ...], ...]
    repair_attempts: int = Field(ge=0)
    success: bool
    team_snapshot_id: UUID | None = None
    usage: ProviderUsage | None = None
    latency_ms: int = Field(ge=0)
    created_at: datetime
