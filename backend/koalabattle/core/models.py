from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from koalabattle.formats import FormatMechanics, describe_format

SCHEMA_VERSION = "1.0"

#: Public commentary is read on the overlay and spoken by TTS: one sentence, not an essay.
MAX_COMMENTARY_CHARACTERS = 240
#: Optional opponent-facing banter is shorter than commentary and is also spoken by TTS.
MAX_BANTER_CHARACTERS = 160
#: Private strategy memory the agent carries between turns. Never shown to spectators.
MAX_STRATEGY_MEMORY_CHARACTERS = 400
#: Historical archives predate the shorter public limit and must still load.
MAX_STORED_COMMENTARY_CHARACTERS = 1_000


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


class PromptProfileId(StrEnum):
    STANDARD_COMPETITIVE = "standard-competitive"
    BENCHMARK_FAIR = "benchmark-fair"


class ContextProfileId(StrEnum):
    STANDARD = "pokemon-standard"
    COMPACT = "pokemon-compact"


class MemoryPolicyId(StrEnum):
    DISABLED = "disabled"
    STRATEGY_NOTE = "strategy-note"


class TeamSource(StrEnum):
    SHOWDOWN_RANDOM = "showdown-random"
    IMPORTED = "imported"
    AGENT_GENERATED = "agent-generated"
    PRESET = "preset"


class TeamPolicy(StrEnum):
    SHOWDOWN_RANDOM = "showdown-random"
    FIXED = "fixed"
    FRESH_PER_MATCH = "fresh-per-match"
    FRESH_PER_SERIES = "fresh-per-series"
    FIXED_PER_TOURNAMENT = "fixed-per-tournament"


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
    timeout_seconds: float = Field(default=300.0, ge=1, le=600)
    max_retries: int = Field(default=1, ge=0, le=5)
    fallback: FallbackPolicy = FallbackPolicy.RANDOM
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=32, le=8192)
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
        try:
            parsed = urlsplit(normalized)
            _ = parsed.port
        except ValueError as error:
            raise ValueError("base_url is not a valid URL") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(character.isspace() or ord(character) < 32 for character in normalized)
            or "%" in parsed.hostname
        ):
            raise ValueError(
                "base_url must be an http(s) URL without credentials, query, or fragment"
            )
        return normalized


class MatchLimits(FrozenModel):
    maximum_total_cost: float | None = Field(default=None, ge=0)
    maximum_turns: int | None = Field(default=200, ge=1, le=10_000)


class MoveState(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    name: str
    type: str | None = None
    category: Literal["physical", "special", "status"] | None = None
    power: int | None = None
    accuracy: float | int | None = None
    current_pp: int | None = Field(default=None, ge=0)
    max_pp: int | None = Field(default=None, ge=0)
    # Absent on archives recorded before move metadata was enriched.
    priority: int | None = None
    disabled: bool = False


class PokemonState(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    name: str
    species: str
    level: int | None = None
    current_hp: int | float | None = Field(default=None, ge=0)
    max_hp: int | float | None = Field(default=None, ge=0)
    hp_fraction: float = Field(ge=0, le=1)
    status: str | None = None
    types: tuple[str, ...] = ()
    item: str | None = None
    ability: str | None = None
    tera_type: str | None = None
    terastallized: bool = False
    boosts: dict[str, int] = Field(default_factory=dict)
    effects: tuple[str, ...] = ()
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
    side_conditions: tuple[str, ...] = ()
    can_terastallize: bool = False
    terastallization_used: bool = False


class KnownPokemon(FrozenModel):
    """Player-visible knowledge. It intentionally has no slots for unrevealed data."""

    schema_version: str = "1.0"
    id: str
    species: str
    display_name: str
    hp_fraction: float | None = Field(default=None, ge=0, le=1)
    status: str | None = None
    active: bool = False
    fainted: bool = False
    revealed_moves: tuple[MoveState, ...] = ()
    revealed_item: str | None = None
    revealed_ability: str | None = None
    revealed_tera_type: str | None = None
    types: tuple[str, ...] = ()


class PlayerKnowledgeState(FrozenModel):
    schema_version: str = "1.0"
    match_id: UUID
    side: Side
    turn: int = Field(ge=0)
    own_side: BattleSide
    opponent_active: KnownPokemon | None = None
    known_opponent: tuple[KnownPokemon, ...] = ()
    # Hazards and screens on the opponent's half of the field are public information.
    opponent_side_conditions: tuple[str, ...] = ()
    weather: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()


class ContextMetrics(FrozenModel):
    rendered_characters: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    estimate_method: Literal["characters-divided-by-four"] = "characters-divided-by-four"
    history_event_count: int = Field(ge=0)
    knowledge_entries: int = Field(ge=0)
    context_profile_version: str
    history_policy_version: str


class AgentContextSnapshot(FrozenModel):
    schema_version: str = "1.0"
    match_id: UUID
    format: str
    # Format presentation and mechanics come from the pinned Showdown registry. Historical
    # archives predate these fields, so they stay optional with Gen 9 singles defaults.
    format_name: str | None = None
    game_type: str = "singles"
    mechanics: FormatMechanics = Field(default_factory=FormatMechanics)
    generation: int
    turn: int = Field(ge=0)
    #: The match ends when this turn is reached, so it changes how a position should be played.
    #: Absent on archives recorded before the limit was part of the prompt.
    maximum_turns: int | None = Field(default=None, ge=1)
    #: Optional public opponent-facing line. It is never enabled implicitly.
    banter_enabled: bool = False
    side: Side
    knowledge: PlayerKnowledgeState
    recent_events: tuple[str, ...] = ()
    strategy_memory: str | None = Field(default=None, max_length=400)
    legal_actions: tuple[BattleAction, ...]
    prompt_profile_id: PromptProfileId
    prompt_profile_version: str
    context_profile_id: ContextProfileId
    context_profile_version: str
    history_policy_version: str
    memory_policy: MemoryPolicyId
    memory_policy_version: str
    output_schema_version: str


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
    # Optional public metadata so an agent can compare choices without cross-referencing
    # another part of the prompt. Absent on archives recorded before this pass.
    move_type: str | None = None
    category: Literal["physical", "special", "status"] | None = None
    power: int | None = Field(default=None, ge=0)
    accuracy: float | int | None = None
    current_pp: int | None = Field(default=None, ge=0)
    max_pp: int | None = Field(default=None, ge=0)
    priority: int | None = None
    species: str | None = None
    hp_fraction: float | None = Field(default=None, ge=0, le=1)
    status: str | None = None

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
    #: Self-contained prompt for Manual Web Chat: one block that can be pasted into a fresh chat.
    prompt: str
    #: The same prompt split for providers with a real system channel. Absent on old archives.
    system_prompt: str | None = None
    user_prompt: str | None = None
    knowledge: PlayerKnowledgeState | None = None
    context: AgentContextSnapshot | None = None
    context_metrics: ContextMetrics | None = None
    prompt_profile_id: PromptProfileId = PromptProfileId.STANDARD_COMPETITIVE
    prompt_profile_version: str = "1.0"
    context_schema_version: str = "1.0"
    knowledge_schema_version: str = "1.0"
    history_policy_version: str = "relevant-v1"
    memory_policy: MemoryPolicyId = MemoryPolicyId.DISABLED
    memory_policy_version: str = "1.0"
    prompt_schema_version: str = "5.0"
    prompt_template_version: str = "pokemon-battle-v2"
    information_profile: Literal["standard"] = "standard"
    banter_enabled: bool = False


class AgentDecision(FrozenModel):
    schema_version: str = SCHEMA_VERSION
    request_id: UUID
    match_id: UUID
    side: Side
    turn: int = Field(ge=0)
    decision_sequence: int = Field(ge=1)
    action: str
    # Stored archives keep the historical ceiling; new decisions are trimmed to
    # MAX_COMMENTARY_CHARACTERS when the response is parsed.
    commentary: str = Field(default="", max_length=MAX_STORED_COMMENTARY_CHARACTERS)
    banter: str = Field(default="", max_length=MAX_BANTER_CHARACTERS)
    strategy_memory: str | None = Field(default=None, max_length=MAX_STRATEGY_MEMORY_CHARACTERS)
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
    team_source: TeamSource = TeamSource.SHOWDOWN_RANDOM
    team_snapshot_id: UUID | None = None
    team_export: str | None = Field(default=None, max_length=50_000)
    team_packed: str | None = Field(default=None, max_length=50_000)

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
        if self.team_source is TeamSource.SHOWDOWN_RANDOM:
            if self.team_snapshot_id is not None or self.team_export or self.team_packed:
                raise ValueError("Showdown Random team source cannot contain a custom team")
        elif self.team_snapshot_id is None:
            raise ValueError("custom team sources require a validated snapshot ID")
        elif (self.team_export is None) is not (self.team_packed is None):
            raise ValueError("custom team export and packed representations must be paired")
        return self

    @field_validator("display_name", "model")
    @classmethod
    def safe_single_line_identifier(cls, value: str | None) -> str | None:
        if value is not None and any(ord(character) < 32 for character in value):
            raise ValueError("display names and model IDs cannot contain control characters")
        return value


class MatchConfig(FrozenModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    format: str = Field(default="gen9randombattle", min_length=1, max_length=80)
    generation: int = Field(default=9, ge=1, le=9)
    players: tuple[PlayerConfig, PlayerConfig]
    random_seed: int | None = None
    fair_prompt_mode: bool = True
    prompt_profile: PromptProfileId = PromptProfileId.STANDARD_COMPETITIVE
    context_profile: ContextProfileId = ContextProfileId.STANDARD
    memory_policy: MemoryPolicyId = MemoryPolicyId.STRATEGY_NOTE
    banter_enabled: bool = False
    team_policy: TeamPolicy = TeamPolicy.SHOWDOWN_RANDOM
    limits: MatchLimits = Field(default_factory=MatchLimits)

    @model_validator(mode="before")
    @classmethod
    def derive_generation(cls, data: Any) -> Any:
        """Take the generation from Showdown's registry so callers never have to supply it."""
        if not isinstance(data, dict):
            return data
        descriptor = describe_format(str(data.get("format") or "gen9randombattle"))
        if descriptor is not None:
            data = {**data, "generation": descriptor.generation}
        return data

    @model_validator(mode="after")
    def format_and_teams_are_consistent(self) -> MatchConfig:
        if {player.side for player in self.players} != {Side.P1, Side.P2}:
            raise ValueError("players must contain exactly p1 and p2")
        descriptor = describe_format(self.format)
        if descriptor is None:
            raise ValueError(
                f"{self.format!r} is not a format in the pinned Pokemon Showdown registry"
            )
        if not descriptor.supported:
            raise ValueError(f"{descriptor.name} is not runnable: {descriptor.unsupported_reason}")
        random_sources = [
            player.team_source is TeamSource.SHOWDOWN_RANDOM for player in self.players
        ]
        if descriptor.random_team:
            if self.team_policy is not TeamPolicy.SHOWDOWN_RANDOM:
                raise ValueError(f"{descriptor.name} supplies its own teams; use showdown-random")
            if not all(random_sources):
                raise ValueError(f"{descriptor.name} players cannot supply custom teams")
        else:
            if self.team_policy is TeamPolicy.SHOWDOWN_RANDOM:
                raise ValueError(f"{descriptor.name} requires validated custom teams")
            if self.team_policy not in {TeamPolicy.FIXED, TeamPolicy.FIXED_PER_TOURNAMENT}:
                raise ValueError(f"{descriptor.name} matches currently support fixed teams only")
            if any(player.team_snapshot_id is None for player in self.players):
                raise ValueError(
                    f"{descriptor.name} requires a validated team snapshot for each player"
                )
        return self

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str | None) -> str | None:
        if value is not None and any(ord(character) < 32 for character in value):
            raise ValueError("match name cannot contain control characters")
        return value


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
