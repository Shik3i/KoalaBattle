from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from koalabattle.core.models import (
    AgentConfiguration,
    AgentType,
    ContextProfileId,
    MatchConfig,
    MatchLimits,
    MemoryPolicyId,
    PlayerConfig,
    PromptProfileId,
    ProviderKind,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.teams.models import DEFAULT_CUSTOM_FORMAT, MAX_TEAM_TEXT_LENGTH


class PlayerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=80)
    agent_type: AgentType
    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)
    team_source: TeamSource = TeamSource.SHOWDOWN_RANDOM
    team_snapshot_id: UUID | None = None


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    format: str = Field(default="gen9randombattle", min_length=1, max_length=80)
    player1: PlayerInput
    player2: PlayerInput
    random_seed: int | None = None
    fair_prompt_mode: bool = True
    prompt_profile: PromptProfileId = PromptProfileId.STANDARD_COMPETITIVE
    context_profile: ContextProfileId = ContextProfileId.STANDARD
    memory_policy: MemoryPolicyId = MemoryPolicyId.STRATEGY_NOTE
    team_policy: TeamPolicy = TeamPolicy.SHOWDOWN_RANDOM
    limits: MatchLimits = Field(default_factory=MatchLimits)

    def to_config(self) -> MatchConfig:
        return MatchConfig(
            name=self.name,
            format=self.format,
            players=(
                PlayerConfig(
                    side=Side.P1,
                    display_name=self.player1.display_name,
                    agent_type=self.player1.agent_type,
                    provider=self.player1.provider.value if self.player1.provider else None,
                    model=self.player1.model,
                    configuration=self.player1.configuration,
                    team_source=self.player1.team_source,
                    team_snapshot_id=self.player1.team_snapshot_id,
                ),
                PlayerConfig(
                    side=Side.P2,
                    display_name=self.player2.display_name,
                    agent_type=self.player2.agent_type,
                    provider=self.player2.provider.value if self.player2.provider else None,
                    model=self.player2.model,
                    configuration=self.player2.configuration,
                    team_source=self.player2.team_source,
                    team_snapshot_id=self.player2.team_snapshot_id,
                ),
            ),
            random_seed=self.random_seed,
            fair_prompt_mode=self.fair_prompt_mode,
            prompt_profile=self.prompt_profile,
            context_profile=self.context_profile,
            memory_policy=self.memory_policy,
            team_policy=self.team_policy,
            limits=self.limits,
        )


class TeamValidationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    format: str = Field(default=DEFAULT_CUSTOM_FORMAT, min_length=1, max_length=80)
    team_text: str = Field(min_length=1, max_length=MAX_TEAM_TEXT_LENGTH)
    source: Literal[TeamSource.IMPORTED, TeamSource.PRESET] = TeamSource.IMPORTED
    save: bool = True


class PromptRenderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_id: UUID
    decision_id: int = Field(ge=1)
    prompt_profile: PromptProfileId | None = None
    context_profile: ContextProfileId | None = None


class ManualDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_response: str = Field(min_length=2, max_length=10_000)


class ProviderModelsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderKind
    base_url: str | None = Field(default=None, max_length=500)


class StoredTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    snapshot: dict[str, object]


class StoredPresetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, object]
