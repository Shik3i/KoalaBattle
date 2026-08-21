from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from koalabattle.core.models import AgentConfiguration, AgentType, ProviderKind

CHALLENGE_SCHEMA_VERSION = "1.0"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChallengeStatus(StrEnum):
    DRAFTING = "drafting"
    TRAINING = "training"
    TEAM_REVIEW = "team_review"
    READY = "ready"
    BATTLE_QUEUED = "battle_queued"
    BATTLING = "battling"
    STAGE_RESULT = "stage_result"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class DraftControllerKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    RANDOM = "random"


class DraftControllerSnapshot(FrozenModel):
    kind: DraftControllerKind
    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)

    @model_validator(mode="after")
    def agent_is_configured(self) -> DraftControllerSnapshot:
        if self.kind is DraftControllerKind.AGENT:
            if self.provider is None or not self.model:
                raise ValueError("agent draft controllers require provider and model")
            if self.provider is ProviderKind.OPENAI_COMPATIBLE and not self.configuration.base_url:
                raise ValueError("OpenAI-compatible draft agents require base_url")
        elif self.provider is not None or self.model is not None:
            raise ValueError("only agent draft controllers may set provider or model")
        return self


class BattleControllerSnapshot(FrozenModel):
    agent_type: AgentType
    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)

    @model_validator(mode="after")
    def agent_is_configured(self) -> BattleControllerSnapshot:
        if self.agent_type is AgentType.API:
            if self.provider is None or not self.model:
                raise ValueError("API battle controllers require provider and model")
            if self.provider is ProviderKind.OPENAI_COMPATIBLE and not self.configuration.base_url:
                raise ValueError("OpenAI-compatible battle agents require base_url")
        elif self.provider is not None or self.model is not None:
            raise ValueError("only API battle controllers may set provider or model")
        return self


class DraftRules(FrozenModel):
    roster_size: int = Field(default=6, ge=1, le=12)
    starting_credits: int = Field(default=68, ge=1, le=500)
    rerolls: int = Field(default=2, ge=0, le=20)
    choice_count: int = Field(default=3, ge=2, le=8)
    species_clause: bool = True


class TrainingRules(FrozenModel):
    global_ev_budget: int = Field(default=1200, ge=0, le=3060)
    per_pokemon_max: int = Field(default=510, ge=0, le=510)
    per_stat_max: int = Field(default=252, ge=0, le=252)


class EvSpread(FrozenModel):
    hp: int = Field(default=0, ge=0, le=252)
    atk: int = Field(default=0, ge=0, le=252)
    defense: int = Field(default=0, ge=0, le=252, alias="def")
    spa: int = Field(default=0, ge=0, le=252)
    spd: int = Field(default=0, ge=0, le=252)
    spe: int = Field(default=0, ge=0, le=252)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @property
    def total(self) -> int:
        return self.hp + self.atk + self.defense + self.spa + self.spd + self.spe


class ChallengeStage(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=60)
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    theme: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=1, le=100)
    opponent_team: str = Field(min_length=1, max_length=50_000)


class ChallengeSource(FrozenModel):
    game: str = Field(min_length=1, max_length=120)
    generation: int = Field(ge=1, le=9)
    variant: str = Field(min_length=1, max_length=160)
    references: tuple[str, ...] = Field(min_length=1)
    compatibility_note: str = Field(min_length=1, max_length=500)


class ChallengeDefinition(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=60)
    version: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=500)
    format: str = Field(default="gen9natdexdraft", max_length=80)
    mechanics_assumptions: tuple[str, ...] = ()
    source: ChallengeSource | None = None
    draft_rules: DraftRules = Field(default_factory=DraftRules)
    training_rules: TrainingRules = Field(default_factory=TrainingRules)
    stages: tuple[ChallengeStage, ...] = Field(min_length=1)


class DraftCandidate(FrozenModel):
    entry_id: str
    species: str
    showdown_id: str
    base_species_id: str
    national_dex_number: int = Field(ge=1)
    introduction_generation: int = Field(ge=1, le=9)
    types: tuple[str, ...] = Field(min_length=1, max_length=2)
    base_stat_total: int | None = Field(default=None, ge=1, le=2000)
    points: int = Field(ge=1)


class DraftOffer(FrozenModel):
    round: int = Field(ge=1)
    nonce: int = Field(ge=0)
    generation: int = Field(ge=1, le=9)
    type: str = Field(min_length=1, max_length=20)
    options: tuple[DraftCandidate, ...] = Field(min_length=1)
    fingerprint: str = Field(min_length=64, max_length=64)


class DraftPick(FrozenModel):
    round: int = Field(ge=1)
    offer_fingerprint: str = Field(min_length=64, max_length=64)
    candidate: DraftCandidate
    selected_by: DraftControllerKind
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PricingCatalogSnapshot(FrozenModel):
    schema_version: str
    parser_version: str
    board_name: str
    context: str
    imported_at: datetime
    source_sha256: str = Field(min_length=64, max_length=64)
    catalog_hash: str = Field(min_length=64, max_length=64)
    parsed_entries: int = Field(ge=0)
    mechanics_assumptions: tuple[str, ...] = ()
    candidates: tuple[DraftCandidate, ...]


class ChallengeStageResult(FrozenModel):
    stage_id: str
    stage_index: int = Field(ge=0)
    match_id: UUID
    status: Literal["won", "lost", "draw", "failed", "cancelled", "interrupted"]
    winner: str | None = None
    turns: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0, ge=0)
    average_decision_latency_ms: float | None = Field(default=None, ge=0)
    decision_count: int = Field(default=0, ge=0)
    started_at: datetime
    completed_at: datetime


class ChallengeRun(FrozenModel):
    id: UUID
    schema_version: str = CHALLENGE_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=120)
    definition: ChallengeDefinition
    status: ChallengeStatus
    revision: int = Field(default=1, ge=1)
    seed: int
    pricing: PricingCatalogSnapshot
    draft_controller: DraftControllerSnapshot
    draft_controller_history: tuple[DraftControllerSnapshot, ...] = ()
    battle_controller: BattleControllerSnapshot
    opponent_controller: BattleControllerSnapshot
    credits_remaining: int = Field(ge=0)
    rerolls_remaining: int = Field(ge=0)
    offer_nonce: int = Field(default=0, ge=0)
    current_offer: DraftOffer | None = None
    picks: tuple[DraftPick, ...] = ()
    ev_allocations: dict[str, EvSpread] = Field(default_factory=dict)
    team_snapshot_id: UUID | None = None
    current_stage_index: int = Field(default=0, ge=0)
    active_match_id: UUID | None = None
    stage_results: tuple[ChallengeStageResult, ...] = ()
    error: str | None = Field(default=None, max_length=1000)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class PublicChallengeStage(FrozenModel):
    id: str
    name: str
    title: str
    theme: str
    level: int


class ChallengeRunStats(FrozenModel):
    stages_cleared: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    draws: int = Field(ge=0)
    total_battles: int = Field(ge=0)
    technical_failures: int = Field(ge=0)
    total_turns: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    estimated_cost: float = Field(ge=0)
    average_decision_latency_ms: float | None = Field(default=None, ge=0)
    credits_spent: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    rerolls_used: int = Field(ge=0)
    ev_used: int = Field(ge=0)


class ChallengeRunView(FrozenModel):
    run: ChallengeRun
    stages: tuple[PublicChallengeStage, ...]
    statistics: ChallengeRunStats
    current_stage: PublicChallengeStage | None = None
    team_export_scaffold: str | None = None
    minimum_completion_cost: int = Field(default=0, ge=0)


class ChallengeRunSummary(FrozenModel):
    id: UUID
    name: str
    definition_name: str
    definition_version: str
    status: ChallengeStatus
    current_stage_index: int
    stage_count: int
    stages_cleared: int
    created_at: datetime
    updated_at: datetime


class CreateChallengeRun(FrozenModel):
    name: str = Field(default="Kanto Draft Gauntlet", min_length=1, max_length=120)
    definition_id: Literal["kanto-gym-gauntlet"] = "kanto-gym-gauntlet"
    seed: int
    draft_controller: DraftControllerSnapshot
    battle_controller: BattleControllerSnapshot
    opponent_controller: BattleControllerSnapshot
    draft_rules: DraftRules | None = None
    training_rules: TrainingRules | None = None
    expected_catalog_hash: str | None = Field(default=None, min_length=64, max_length=64)


class DraftPickInput(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    offer_fingerprint: str = Field(min_length=64, max_length=64)
    expected_revision: int = Field(ge=1)


class DraftRerollInput(FrozenModel):
    offer_fingerprint: str = Field(min_length=64, max_length=64)
    expected_revision: int = Field(ge=1)


class TrainingInput(FrozenModel):
    allocations: dict[str, EvSpread]
    expected_revision: int = Field(ge=1)


class FinalizeTeamInput(FrozenModel):
    team_text: str = Field(min_length=1, max_length=50_000)
    expected_revision: int = Field(ge=1)


class RevisionInput(FrozenModel):
    expected_revision: int = Field(ge=1)


class PricingStatus(FrozenModel):
    available: bool
    ready: bool
    path: str
    catalog_hash: str | None = None
    board_name: str | None = None
    context: str | None = None
    imported_at: datetime | None = None
    parsed_entries: int = 0
    eligible_entries: int = 0
    priced_entries: int = 0
    banned_entries: int = 0
    missing_entries: int = 0
    unsupported_entries: int = 0
    source_verified: bool = False
    verification_detail: str = "No source file is installed."
    excluded_entries: tuple[dict[str, str], ...] = ()
    errors: tuple[str, ...] = ()
