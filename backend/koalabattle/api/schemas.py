from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from koalabattle.core.models import (
    AgentConfiguration,
    AgentType,
    MatchConfig,
    MatchLimits,
    PlayerConfig,
    ProviderKind,
    Side,
)


class PlayerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=80)
    agent_type: AgentType
    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    configuration: AgentConfiguration = Field(default_factory=AgentConfiguration)


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    player1: PlayerInput
    player2: PlayerInput
    random_seed: int | None = None
    fair_prompt_mode: bool = True
    limits: MatchLimits = Field(default_factory=MatchLimits)

    def to_config(self) -> MatchConfig:
        return MatchConfig(
            name=self.name,
            players=(
                PlayerConfig(
                    side=Side.P1,
                    display_name=self.player1.display_name,
                    agent_type=self.player1.agent_type,
                    provider=self.player1.provider.value if self.player1.provider else None,
                    model=self.player1.model,
                    configuration=self.player1.configuration,
                ),
                PlayerConfig(
                    side=Side.P2,
                    display_name=self.player2.display_name,
                    agent_type=self.player2.agent_type,
                    provider=self.player2.provider.value if self.player2.provider else None,
                    model=self.player2.model,
                    configuration=self.player2.configuration,
                ),
            ),
            random_seed=self.random_seed,
            fair_prompt_mode=self.fair_prompt_mode,
            limits=self.limits,
        )


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
