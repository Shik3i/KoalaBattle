from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Side(StrEnum):
    P1 = "p1"
    P2 = "p2"


class AgentType(StrEnum):
    RANDOM = "random"
    MANUAL = "manual"
    API = "api"


class ProviderKind(StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    OPENAI_COMPATIBLE = "openai-compatible"
    FAKE = "fake"


class FallbackPolicy(StrEnum):
    RANDOM = "random"
    MANUAL = "manual"
    FORFEIT = "forfeit"


class ProviderErrorCategory(StrEnum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    INVALID_REQUEST = "invalid_request"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class AgentLifecycleState(StrEnum):
    IDLE = "idle"
    WAITING = "waiting"
    THINKING = "thinking"
    RETRYING = "retrying"
    DECIDED = "decided"
    EXECUTING = "executing"
    ERROR = "error"
    FINISHED = "finished"


class ActionType(StrEnum):
    MOVE = "move"
    SWITCH = "switch"


class MatchStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class GenericResultStatus(StrEnum):
    COMPLETED = "completed"
    DRAW = "draw"
    CANCELLED = "cancelled"
    FAILED = "failed"


class GenericMatchResult(FrozenModel):
    status: GenericResultStatus
    winner_participant_id: UUID | None = None
    draw: bool = False
    score_metadata: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def result_is_consistent(self) -> GenericMatchResult:
        if self.status is GenericResultStatus.DRAW and not self.draw:
            raise ValueError("draw results must set draw=true")
        if self.draw and self.winner_participant_id is not None:
            raise ValueError("a draw cannot have a winner")
        if self.status is GenericResultStatus.COMPLETED and self.winner_participant_id is None:
            raise ValueError("completed results require a winner")
        return self


class ProviderUsage(FrozenModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    details: dict[str, int | float | str | bool | None] = Field(default_factory=dict)


class EstimatedCost(FrozenModel):
    amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    pricing_version: str | None = Field(default=None, max_length=80)
    available: bool = False


class RetryAttempt(FrozenModel):
    attempt: int = Field(ge=1)
    category: ProviderErrorCategory
    detail: str = Field(max_length=500)


class FallbackRecord(FrozenModel):
    policy: FallbackPolicy
    reason: str = Field(max_length=500)
    used: bool = True


class AgentConfiguration(FrozenModel):
    timeout_seconds: float = Field(default=45.0, ge=1, le=600)
    max_retries: int = Field(default=1, ge=0, le=5)
    fallback: FallbackPolicy = FallbackPolicy.RANDOM
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(default=256, ge=32, le=8192)
    reasoning_effort: Literal["low", "medium", "high", "max"] | None = None
    base_url: str | None = Field(default=None, max_length=500)
    maximum_cost: float | None = Field(default=None, ge=0)
    fake_scenario: Literal[
        "valid",
        "malformed_then_valid",
        "invalid_then_valid",
        "timeout",
        "provider_error",
        "rate_limit_then_valid",
    ] = "valid"

    @field_validator("base_url")
    @classmethod
    def safe_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")) or "@" in normalized:
            raise ValueError("base_url must be an http(s) URL without embedded credentials")
        return normalized


class MatchLimits(FrozenModel):
    maximum_total_cost: float | None = Field(default=None, ge=0)
    maximum_turns: int | None = Field(default=None, ge=1, le=10_000)


class MoveState(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    name: str
    type: str | None = None
    power: int | None = None
    accuracy: float | int | None = None
    disabled: bool = False


class PokemonState(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    name: str
    species: str
    level: int | None = None
    hp_fraction: float = Field(ge=0, le=1)
    status: str | None = None
    types: tuple[str, ...] = ()
    active: bool = False
    fainted: bool = False
    revealed: bool = True
    moves: tuple[MoveState, ...] = ()


class BattleSide(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    side: Side
    display_name: str
    active: PokemonState | None = None
    team: tuple[PokemonState, ...] = ()


class BattleResult(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    winner: Side | None = None
    winner_name: str | None = None
    turns: int = Field(ge=0)
    reason: str = "normal"


class BattleState(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    match_id: UUID
    format: str = "gen9randombattle"
    generation: int = 9
    turn: int = Field(ge=0)
    perspective: Side
    player: BattleSide
    opponent: BattleSide
    weather: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    last_action: str | None = None
    public_history: tuple[str, ...] = ()
    result: BattleResult | None = None


class BattleAction(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    id: str = Field(pattern=r"^(move|switch):[1-9][0-9]*(?::tera)?$")
    type: ActionType
    name: str
    slot: int = Field(ge=1)
    terastallize: bool = False

    @model_validator(mode="after")
    def id_matches_fields(self) -> BattleAction:
        suffix = ":tera" if self.terastallize else ""
        expected = f"{self.type.value}:{self.slot}{suffix}"
        if self.id != expected:
            raise ValueError(f"action id must be {expected!r}")
        if self.type is ActionType.SWITCH and self.terastallize:
            raise ValueError("switch actions cannot terastallize")
        return self


class BattleEvent(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    id: int | None = None
    match_id: UUID
    sequence: int = Field(ge=0)
    turn: int = Field(ge=0)
    event_type: str = Field(min_length=1, max_length=80)
    logical_offset_ms: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    request_id: UUID
    match_id: UUID
    side: Side
    turn: int = Field(ge=0)
    decision_sequence: int = Field(ge=1)
    state: BattleState
    legal_actions: tuple[BattleAction, ...] = Field(min_length=1)
    prompt: str
    prompt_schema_version: str = "3.0"
    prompt_template_version: str = "battle-standard-v1"
    information_profile: Literal["standard"] = "standard"


class AgentDecision(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    request_id: UUID
    match_id: UUID
    side: Side
    turn: int = Field(ge=0)
    decision_sequence: int = Field(ge=1)
    action: str
    commentary: str = Field(default="", max_length=1000)
    raw_response: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = Field(default=None, ge=0)
    validation_attempts: int = Field(default=1, ge=1)
    validation_errors: tuple[str, ...] = ()
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    usage: ProviderUsage | None = None
    estimated_cost: EstimatedCost = Field(default_factory=EstimatedCost)
    retry_attempts: tuple[RetryAttempt, ...] = ()
    fallback: FallbackRecord | None = None
    error_category: ProviderErrorCategory | None = None
    error_detail: str | None = Field(default=None, max_length=500)

    @field_validator("action")
    @classmethod
    def action_is_identifier(cls, value: str) -> str:
        if not value.startswith(("move:", "switch:")):
            raise ValueError("action must be a supplied KoalaBattle action ID")
        return value


class PlayerConfig(FrozenModel):
    side: Side
    display_name: str = Field(min_length=1, max_length=80)
    agent_type: AgentType
    provider: str | None = None
    model: str | None = None
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)

    @model_validator(mode="after")
    def provider_matches_agent_type(self) -> PlayerConfig:
        if self.agent_type is AgentType.API:
            if self.provider not in {item.value for item in ProviderKind}:
                raise ValueError("API agents require a supported provider")
            if not self.model:
                raise ValueError("API agents require a model ID")
            if (
                self.provider == ProviderKind.OPENAI_COMPATIBLE.value
                and not self.configuration.base_url
            ):
                raise ValueError("OpenAI-compatible agents require base_url")
        return self


class MatchConfig(FrozenModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    format: Literal["gen9randombattle"] = "gen9randombattle"
    generation: Literal[9] = 9
    players: tuple[PlayerConfig, PlayerConfig]
    random_seed: int | None = None
    fair_prompt_mode: bool = True
    limits: MatchLimits = Field(default_factory=MatchLimits)

    @model_validator(mode="after")
    def has_two_sides(self) -> MatchConfig:
        if {player.side for player in self.players} != {Side.P1, Side.P2}:
            raise ValueError("players must contain exactly p1 and p2")
        return self


class DecisionRecord(FrozenModel):
    id: int
    request: AgentRequest
    decision: AgentDecision
    generated_prompt: str
    raw_response: str | None = None
    parsed_response: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()


class MatchArchive(FrozenModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    status: MatchStatus
    config: MatchConfig
    engine: str
    engine_version: str | None = None
    showdown_version: str | None = None
    poke_env_version: str | None = None
    schema_version: str = SCHEMA_VERSION
    winner: Side | None = None
    turns: int = 0
    raw_showdown_log: str | None = None
    error: str | None = None
    tournament_id: UUID | None = None
    series_id: UUID | None = None
    queue_position: int | None = None
    events: tuple[BattleEvent, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()


class MatchSummary(FrozenModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    status: MatchStatus
    config: MatchConfig
    engine: str
    winner: Side | None = None
    turns: int = 0
    error: str | None = None
    tournament_id: UUID | None = None
    series_id: UUID | None = None
    queue_position: int | None = None
    estimated_cost: float = 0
