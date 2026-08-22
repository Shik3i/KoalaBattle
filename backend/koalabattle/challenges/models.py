from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from koalabattle.core.models import AgentConfiguration, AgentType, ProviderKind

from .rarity import DraftRarity

CHALLENGE_SCHEMA_VERSION = "2.0"
DRAFT_RULES_VERSION: Literal["draft-rules-v2"] = "draft-rules-v2"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChallengeStatus(StrEnum):
    DRAFTING = "drafting"
    PREPARING = "preparing"
    TRAINING = "training"
    TEAM_REVIEW = "team_review"
    READY = "ready"
    BATTLE_QUEUED = "battle_queued"
    BATTLING = "battling"
    STAGE_RESULT = "stage_result"
    MEGA_SELECTION = "mega_selection"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class ChallengeDifficulty(StrEnum):
    NORMAL = "normal"
    HARD = "hard"
    EXPERT = "expert"
    NIGHTMARE = "nightmare"


# The player always follows the campaign's own level curve (see ChallengeStage.level on
# each stage) — difficulty never lowers the player below it. Difficulty instead raises the
# opponent above that same curve, capped at the format's level ceiling. This keeps evolution
# and levelling honest: harder modes never quietly undo the player's own progression to
# create an artificial disadvantage.
DIFFICULTY_LEVEL_MODIFIERS: dict[ChallengeDifficulty, int] = {
    ChallengeDifficulty.NORMAL: 0,
    ChallengeDifficulty.HARD: 5,
    ChallengeDifficulty.EXPERT: 10,
    ChallengeDifficulty.NIGHTMARE: 15,
}


def opponent_stage_level(stage_level: int, difficulty: ChallengeDifficulty) -> int:
    """Derive the opponent's level for one stage without mutating any stored snapshot."""
    return max(1, min(100, stage_level + DIFFICULTY_LEVEL_MODIFIERS[difficulty]))


# Any evolution trigger other than a real level-up (item, trade, friendship, a special
# condition, ...) has no level of its own in the source games. The campaign maps every one
# of them to this single fixed stage index instead of a level: reachable starting with the
# stage-transition into this stage (index 2 = Lt. Surge), the same for every such species, so
# evolution timing stays deterministic and does not depend on the player's own choices.
NON_LEVEL_EVOLUTION_MILESTONE_STAGE_INDEX = 2


class EvolutionTrigger(FrozenModel):
    """One reachable next species and how the campaign resolves reaching it.

    `trigger_kind == "level"` means `trigger_level` is a real level-up requirement. Every
    other kind (item/trade/friendship/condition/etc.) has no level of its own in the source
    games; the challenge service maps every such case to
    `NON_LEVEL_EVOLUTION_MILESTONE_STAGE_INDEX` instead, so evolution timing stays
    deterministic and reproducible.
    """

    id: str
    name: str
    trigger_level: int | None = Field(default=None, ge=1, le=100)
    trigger_kind: str = Field(min_length=1, max_length=40)


class MegaEvolutionOption(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9]+$", max_length=80)
    species: str = Field(min_length=1, max_length=120)
    required_item: str = Field(min_length=1, max_length=120)


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
    # Persisted name retained for Draft V2 saves; this is the Pokemon-only reroll power.
    rerolls: int = Field(default=3, ge=0, le=20)
    type_rerolls: int = Field(default=1, ge=0, le=20)
    generation_rerolls: int = Field(default=1, ge=0, le=20)
    choice_count: int = Field(default=3, ge=2, le=8)
    species_clause: bool = True


class TrainingRules(FrozenModel):
    # Read-only compatibility for persisted Draft V2 snapshots. New runs have no
    # shared EV pool; legality is scoped to each Pokemon and each stat.
    global_ev_budget: int | None = Field(default=None, ge=0, le=3060)
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
    specialty: str | None = Field(default=None, min_length=1, max_length=40)
    trainer_asset_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=80
    )
    visual_accent: str = Field(default="#7bf0a2", pattern=r"^#[0-9a-fA-F]{6}$")
    # False makes this stage part of the preceding gauntlet: Pokemon knocked out in the
    # previous stage stay out. The Elite Four is fought in one sitting in the source games.
    full_heal_before: bool = True
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


class PokemonBaseStats(FrozenModel):
    hp: int = Field(ge=1, le=255)
    atk: int = Field(ge=1, le=255)
    defense: int = Field(ge=1, le=255)
    spa: int = Field(ge=1, le=255)
    spd: int = Field(ge=1, le=255)
    spe: int = Field(ge=1, le=255)


class PokemonAbility(FrozenModel):
    slot: Literal["0", "1", "H", "S"]
    id: str = Field(pattern=r"^[a-z0-9]+$", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    hidden: bool = False


class PokemonIvSpread(FrozenModel):
    hp: int = Field(default=31, ge=0, le=31)
    atk: int = Field(default=31, ge=0, le=31)
    defense: int = Field(default=31, ge=0, le=31, alias="def")
    spa: int = Field(default=31, ge=0, le=31)
    spd: int = Field(default=31, ge=0, le=31)
    spe: int = Field(default=31, ge=0, le=31)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ShowdownCompetitiveSet(FrozenModel):
    source: Literal[
        "showdown-battle-factory", "showdown-random-battle", "showdown-dex-validated"
    ]
    source_generation: int = Field(ge=1, le=9)
    source_tier: str = Field(min_length=1, max_length=40)
    species: str = Field(min_length=1, max_length=120)
    item: str = Field(max_length=120)
    ability: str = Field(min_length=1, max_length=120)
    nature: str = Field(min_length=1, max_length=40)
    moves: tuple[str, ...] = Field(min_length=1, max_length=4)
    evs: EvSpread
    ivs: PokemonIvSpread
    tera_type: str | None = Field(default=None, min_length=1, max_length=40)


class DraftCandidate(FrozenModel):
    entry_id: str
    species: str
    showdown_id: str
    base_species_id: str
    national_dex_number: int = Field(ge=1)
    introduction_generation: int = Field(ge=1, le=9)
    types: tuple[str, ...] = Field(min_length=1, max_length=2)
    base_stat_total: int | None = Field(default=None, ge=1, le=2000)
    base_stats: PokemonBaseStats | None = None
    max_hp: int | None = Field(default=None, ge=1, le=999)
    abilities: tuple[PokemonAbility, ...] = ()
    recommended_moves: tuple[str, ...] = Field(default=(), max_length=4)
    recommended_move: str | None = Field(default=None, min_length=1, max_length=120, exclude=True)
    required_item: str | None = Field(default=None, min_length=1, max_length=120)
    showdown_set: ShowdownCompetitiveSet | None = None
    evolves_to: tuple[EvolutionTrigger, ...] = ()
    mega_evolutions: tuple[MegaEvolutionOption, ...] = ()
    # Zero is a base form. Already-evolved forms stay legal Draft candidates, but are
    # deliberately much rarer because a drafted base form progresses during the campaign.
    evolution_stage: int = Field(default=0, ge=0, le=8)
    # Defaults keep Draft V2 save files readable; every newly generated pool receives the
    # exact values from the committed Smogon snapshot.
    draft_points: int = Field(default=1, ge=1, le=20)
    draft_rarity: DraftRarity = DraftRarity.COMMON

    @model_validator(mode="after")
    def migrate_single_recommended_move(self) -> DraftCandidate:
        if not self.recommended_moves and self.recommended_move:
            return self.model_copy(update={"recommended_moves": (self.recommended_move,)})
        return self


class DraftPoolSnapshot(FrozenModel):
    schema_version: str = "1.0"
    showdown_version: str = Field(min_length=1, max_length=100)
    format: str = Field(min_length=1, max_length=80)
    format_generation: int = Field(ge=1, le=9)
    abilities_supported: bool
    catalog_hash: str = Field(min_length=64, max_length=64)
    draft_points_catalog_hash: str | None = Field(default=None, min_length=64, max_length=64)
    draft_points_source: str | None = Field(default=None, min_length=1, max_length=200)
    draft_points_updated_on: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    candidates: tuple[DraftCandidate, ...]


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
    # The full resolved species chain this pick will walk, drafted form first. Empty means
    # unresolved (a saved run from before evolution existed): the pick then never evolves,
    # which is the correct, non-breaking behavior for that older data. A branching chain
    # (Eevee, Tyrogue, Scyther, ...) is resolved once at draft time via `evolution_choice`.
    evolution_path: tuple[str, ...] = ()
    # Index into `evolution_path` for the species this pick currently is. Advances by at most
    # one per stage transition, never mid-battle, never more than one step per win.
    evolution_stage_index: int = Field(default=0, ge=0)
    # Display data for the current (post-evolution) species, set only once this pick has
    # actually evolved past its drafted form. `None`/`()` means "same as drafted" — read
    # `candidate.species`/`candidate.types` instead. Kept directly on the pick so the browser
    # never needs a species-catalog round trip just to render the roster.
    current_species: str | None = Field(default=None, min_length=1, max_length=120)
    current_types: tuple[str, ...] = Field(default=(), max_length=2)


class DraftHistoryEntry(FrozenModel):
    offer: DraftOffer
    outcome: Literal[
        "picked", "rerolled", "pokemon_rerolled", "type_rerolled", "generation_rerolled"
    ]
    selected_entry_id: str | None = None
    decided_by: DraftControllerKind
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def picked_entry_matches_offer(self) -> DraftHistoryEntry:
        offered = {candidate.entry_id for candidate in self.offer.options}
        if self.outcome == "picked" and self.selected_entry_id not in offered:
            raise ValueError("picked draft history must reference one offered entry")
        if self.outcome != "picked" and self.selected_entry_id is not None:
            raise ValueError("rerolled draft history cannot select an entry")
        return self


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


class ChallengeBattleSummary(FrozenModel):
    match_id: UUID
    player_participants: tuple[str, ...] = ()
    opponent_participants: tuple[str, ...] = ()
    player_fainted: tuple[str, ...] = ()
    opponent_fainted: tuple[str, ...] = ()


class EvolutionEvent(FrozenModel):
    """One pick evolving at one stage transition, for the browser's evolution reveal."""

    entry_id: str
    from_species: str
    to_species: str


class ChallengeMegaOption(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    from_species: str = Field(min_length=1, max_length=120)
    mega_species_id: str = Field(pattern=r"^[a-z0-9]+$", max_length=80)
    mega_species: str = Field(min_length=1, max_length=120)
    required_item: str = Field(min_length=1, max_length=120)


class ChallengeMegaSelection(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    from_species: str = Field(min_length=1, max_length=120)
    mega_species_id: str = Field(pattern=r"^[a-z0-9]+$", max_length=80)
    mega_species: str = Field(min_length=1, max_length=120)
    required_item: str = Field(min_length=1, max_length=120)
    selected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChallengeRun(FrozenModel):
    id: UUID
    schema_version: str = CHALLENGE_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=120)
    definition: ChallengeDefinition
    status: ChallengeStatus
    revision: int = Field(default=1, ge=1)
    seed: int
    draft_rules_version: Literal["draft-rules-v2", "draft-rules-v1-incompatible"] = (
        DRAFT_RULES_VERSION
    )
    draft_pool: DraftPoolSnapshot
    draft_controller: DraftControllerSnapshot
    draft_controller_history: tuple[DraftControllerSnapshot, ...] = ()
    battle_controller: BattleControllerSnapshot
    opponent_controller: BattleControllerSnapshot
    battle_experience: Literal["quick-sim", "fast-watch", "normal"] = "quick-sim"
    difficulty: ChallengeDifficulty = ChallengeDifficulty.NORMAL
    rerolls_remaining: int = Field(default=3, ge=0)
    type_rerolls_remaining: int = Field(default=1, ge=0)
    generation_rerolls_remaining: int = Field(default=1, ge=0)
    offer_nonce: int = Field(default=0, ge=0)
    consumed_species_ids: tuple[str, ...] = ()
    current_offer: DraftOffer | None = None
    draft_history: tuple[DraftHistoryEntry, ...] = ()
    picks: tuple[DraftPick, ...] = ()
    ev_allocations: dict[str, EvSpread] = Field(default_factory=dict)
    ability_selections: dict[str, str | None] = Field(default_factory=dict)
    team_snapshot_id: UUID | None = None
    current_stage_index: int = Field(default=0, ge=0)
    active_match_id: UUID | None = None
    stage_results: tuple[ChallengeStageResult, ...] = ()
    auto_run_paused: bool = False
    auto_advance_at: datetime | None = None
    # Drafted entries knocked out earlier in the current gauntlet section. Cleared by any
    # stage that heals before it, and by any result that is not a win.
    downed_entry_ids: tuple[str, ...] = ()
    # Evolutions applied at the most recent stage transition only, overwritten (not
    # appended) every transition. The browser shows this once, the same reload-safe way it
    # already shows the next-opponent transition: only when it observes the stage index
    # advance while the page is open, never replayed from a cold load.
    recent_evolutions: tuple[EvolutionEvent, ...] = ()
    # Persisted when the run reaches Blue. Empty means the final roster has no legal Mega;
    # a non-empty tuple with no selection is the only state that pauses Tactical Auto.
    mega_options: tuple[ChallengeMegaOption, ...] = ()
    mega_selection: ChallengeMegaSelection | None = None
    error: str | None = Field(default=None, max_length=1000)
    compatibility_notice: str | None = Field(default=None, max_length=1000)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class PublicChallengeStage(FrozenModel):
    id: str
    name: str
    title: str
    theme: str
    level: int
    player_level: int = Field(default=0, ge=0, le=100)
    opponent_level: int = Field(default=0, ge=0, le=100)
    full_heal_before: bool = True
    specialty: str | None = None
    trainer_asset_id: str | None = None
    visual_accent: str = "#7bf0a2"


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
    rerolls_used: int = Field(ge=0)
    ev_used: int = Field(ge=0)


class CurrentPickView(FrozenModel):
    """A pick's present species — after any evolution — for display only.

    The drafted roster snapshot (`DraftPick.candidate`) never changes; this is the
    read-only, current-state view of it that the browser actually renders.
    """

    entry_id: str
    species: str
    showdown_id: str
    types: tuple[str, ...] = Field(min_length=1, max_length=2)
    evolved: bool = False
    drafted_species: str


class ChallengeRunView(FrozenModel):
    run: ChallengeRun
    stages: tuple[PublicChallengeStage, ...]
    statistics: ChallengeRunStats
    current_stage: PublicChallengeStage | None = None
    latest_battle_summary: ChallengeBattleSummary | None = None
    team_export_scaffold: str | None = None
    can_reroll: bool = False
    can_reroll_type: bool = False
    can_reroll_generation: bool = False
    unseen_candidate_count: int = Field(default=0, ge=0)
    current_roster: tuple[CurrentPickView, ...] = ()


class ChallengeRunSummary(FrozenModel):
    id: UUID
    name: str
    definition_name: str
    definition_version: str
    status: ChallengeStatus
    difficulty: ChallengeDifficulty = ChallengeDifficulty.NORMAL
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
    battle_experience: Literal["quick-sim", "fast-watch", "normal"] = "quick-sim"
    difficulty: ChallengeDifficulty = ChallengeDifficulty.NORMAL
    draft_rules: DraftRules | None = None
    training_rules: TrainingRules | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_opponent_controller(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        opponent = value.get("opponent_controller")
        if isinstance(opponent, BattleControllerSnapshot):
            if opponent.agent_type is AgentType.TACTICAL_AUTO:
                return value
            normalized: object = BattleControllerSnapshot(
                agent_type=AgentType.TACTICAL_AUTO,
                configuration=opponent.configuration,
            )
        elif isinstance(opponent, dict):
            if opponent.get("agent_type") == AgentType.TACTICAL_AUTO.value:
                return value
            normalized = {
                "agent_type": AgentType.TACTICAL_AUTO.value,
                "configuration": opponent.get("configuration", {}),
            }
        else:
            return value
        return {**value, "opponent_controller": normalized}

    @model_validator(mode="after")
    def validate_human_draft(self) -> CreateChallengeRun:
        if self.draft_controller.kind is not DraftControllerKind.HUMAN:
            raise ValueError("new Challenge drafts are always human-controlled")
        return self


class DraftPickInput(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    offer_fingerprint: str = Field(min_length=64, max_length=64)
    expected_revision: int = Field(ge=1)
    # Required only when the picked species' evolution chain branches (multiple reachable
    # final forms); the id of the chosen destination species. Ignored for a non-branching
    # chain.
    evolution_choice: str | None = Field(default=None, min_length=1, max_length=60)


class MegaSelectionInput(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    mega_species_id: str = Field(pattern=r"^[a-z0-9]+$", max_length=80)
    expected_revision: int = Field(ge=1)


class DraftRerollInput(FrozenModel):
    offer_fingerprint: str = Field(min_length=64, max_length=64)
    expected_revision: int = Field(ge=1)
    kind: Literal["pokemon", "type", "generation"] = "pokemon"


class TrainingInput(FrozenModel):
    allocations: dict[str, EvSpread]
    expected_revision: int = Field(ge=1)


class TeamAbilityInput(FrozenModel):
    abilities: dict[str, str | None]
    expected_revision: int = Field(ge=1)


class FinalizeTeamInput(FrozenModel):
    team_text: str = Field(min_length=1, max_length=50_000)
    expected_revision: int = Field(ge=1)


class RevisionInput(FrozenModel):
    expected_revision: int = Field(ge=1)
