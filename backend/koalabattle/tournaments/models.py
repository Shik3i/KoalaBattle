from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from koalabattle.core.models import (
    AgentConfiguration,
    AgentType,
    ContextProfileId,
    MatchLimits,
    MemoryPolicyId,
    PromptProfileId,
    TeamPolicy,
    TeamSource,
)

TOURNAMENT_SCHEMA_VERSION = "1.0"


class FrozenTournamentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TournamentFormat(StrEnum):
    SINGLE_ELIMINATION = "single_elimination"
    ROUND_ROBIN = "round_robin"


class TournamentStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SeriesStatus(StrEnum):
    BLOCKED = "blocked"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AgentPresetSnapshot(FrozenTournamentModel):
    agent_type: AgentType
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)
    team_source: TeamSource = TeamSource.SHOWDOWN_RANDOM
    team_snapshot_id: UUID | None = None
    # Retained for Phase 4 snapshot compatibility; Phase 5 profiles live on the match template.
    prompt_profile: str | None = None
    prompt_version: str | None = None
    fallback_configuration: dict[str, Any] = Field(default_factory=dict)


class MatchTemplateSnapshot(FrozenTournamentModel):
    schema_version: str = TOURNAMENT_SCHEMA_VERSION
    engine: str = Field(default="pokemon-showdown", min_length=1, max_length=80)
    engine_configuration: dict[str, Any] = Field(default_factory=dict)
    format: Literal["gen9randombattle", "gen9ou"] = "gen9randombattle"
    generation: Literal[9] = 9
    fair_prompt_mode: bool = True
    prompt_profile: PromptProfileId = PromptProfileId.STANDARD_COMPETITIVE
    context_profile: ContextProfileId = ContextProfileId.STANDARD
    memory_policy: MemoryPolicyId = MemoryPolicyId.STRATEGY_NOTE
    team_policy: TeamPolicy = TeamPolicy.SHOWDOWN_RANDOM
    limits: MatchLimits = Field(default_factory=MatchLimits)
    presentation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def supported_showdown_format(self) -> MatchTemplateSnapshot:
        if self.format not in {"gen9randombattle", "gen9ou"} or self.generation != 9:
            raise ValueError("Phase 5 supports gen9randombattle and gen9ou only")
        if self.format == "gen9randombattle" and self.team_policy is not TeamPolicy.SHOWDOWN_RANDOM:
            raise ValueError("Random Battle tournaments must use Showdown Random teams")
        if self.format == "gen9ou" and self.team_policy is TeamPolicy.SHOWDOWN_RANDOM:
            raise ValueError("Gen 9 OU tournaments require custom team policy")
        if self.format == "gen9ou" and self.team_policy is not TeamPolicy.FIXED:
            raise ValueError("Phase 5 Gen 9 OU tournaments currently support fixed teams only")
        return self


class TournamentParticipantDraft(FrozenTournamentModel):
    display_name: str = Field(min_length=1, max_length=120)
    seed: int | None = Field(default=None, ge=1)
    agent: AgentPresetSnapshot
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TournamentParticipant(FrozenTournamentModel):
    id: UUID
    tournament_id: UUID
    display_name: str
    seed: int
    agent: AgentPresetSnapshot
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TournamentSeries(FrozenTournamentModel):
    id: UUID
    tournament_id: UUID
    round_number: int = Field(ge=1)
    bracket_position: int = Field(ge=1)
    queue_order: int = Field(ge=1)
    status: SeriesStatus
    participant_a_id: UUID | None = None
    participant_b_id: UUID | None = None
    dependency_a_id: UUID | None = None
    dependency_b_id: UUID | None = None
    best_of: int = Field(ge=1)
    wins_a: int = Field(ge=0)
    wins_b: int = Field(ge=0)
    draws: int = Field(ge=0)
    games_played: int = Field(ge=0)
    max_games: int = Field(ge=1)
    winner_participant_id: UUID | None = None
    match_ids: tuple[UUID, ...] = ()


class TournamentScoring(FrozenTournamentModel):
    win_points: float = Field(default=3, ge=0)
    draw_points: float = Field(default=1, ge=0)
    loss_points: float = Field(default=0, ge=0)


class TournamentPresentation(FrozenTournamentModel):
    theme: str = Field(default="koala-dark", max_length=80)
    layout: str = Field(default="tournament-bracket", max_length=80)
    show_model_names: bool = True
    show_series_score: bool = True
    show_tournament_name: bool = True


class CreateTournament(FrozenTournamentModel):
    name: str = Field(min_length=1, max_length=120)
    format: TournamentFormat
    best_of: int = Field(default=1, ge=1, le=99)
    max_concurrent_matches: int = Field(default=1, ge=1, le=64)
    maximum_total_cost: float | None = Field(default=None, ge=0)
    max_draw_replays: int = Field(default=3, ge=0, le=25)
    manual_scheduling: bool = False
    randomize_seeds: bool = False
    random_seed: int | None = None
    match_template: MatchTemplateSnapshot = Field(default_factory=MatchTemplateSnapshot)
    presentation: TournamentPresentation = Field(default_factory=TournamentPresentation)
    scoring: TournamentScoring = Field(default_factory=TournamentScoring)
    participants: tuple[TournamentParticipantDraft, ...] = Field(min_length=2, max_length=128)

    @model_validator(mode="after")
    def valid_series_and_seeds(self) -> CreateTournament:
        if self.best_of % 2 == 0:
            raise ValueError("best_of must be an odd number")
        explicit = [participant.seed for participant in self.participants if participant.seed]
        if len(explicit) != len(set(explicit)):
            raise ValueError("participant seeds must be unique")
        return self


class TournamentStanding(FrozenTournamentModel):
    participant_id: UUID
    display_name: str
    seed: int
    played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    points: float = 0


class TournamentStatistics(FrozenTournamentModel):
    matches_played: int = 0
    series_played: int = 0
    total_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0
    average_decision_latency_ms: float | None = None


class TournamentArchive(FrozenTournamentModel):
    id: UUID
    name: str
    format: TournamentFormat
    status: TournamentStatus
    best_of: int
    max_concurrent_matches: int
    maximum_total_cost: float | None = None
    max_draw_replays: int
    manual_scheduling: bool
    match_template: MatchTemplateSnapshot
    presentation: TournamentPresentation
    scoring: TournamentScoring
    current_round: int
    winner_participant_id: UUID | None = None
    error: str | None = None
    schema_version: str = TOURNAMENT_SCHEMA_VERSION
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    participants: tuple[TournamentParticipant, ...] = ()
    series: tuple[TournamentSeries, ...] = ()
    standings: tuple[TournamentStanding, ...] = ()
    statistics: TournamentStatistics = Field(default_factory=TournamentStatistics)


class TournamentSummary(FrozenTournamentModel):
    id: UUID
    name: str
    format: TournamentFormat
    status: TournamentStatus
    participant_count: int
    series_count: int
    completed_series: int
    current_round: int
    created_at: datetime
    updated_at: datetime


class StoredTemplate(FrozenTournamentModel):
    id: UUID
    name: str
    snapshot: MatchTemplateSnapshot
    created_at: datetime
    updated_at: datetime


class StoredTournamentPreset(FrozenTournamentModel):
    id: UUID
    name: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


TournamentAction = Literal["start", "pause", "resume", "cancel"]
