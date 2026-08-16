from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from koalabattle.core.models import (
    ActionType,
    AgentRequest,
    AgentType,
    BattleAction,
    BattleSide,
    BattleState,
    ContextProfileId,
    MatchConfig,
    MemoryPolicyId,
    PlayerConfig,
    PokemonState,
    PromptProfileId,
    Side,
)
from koalabattle.engines.showdown.context import PokemonShowdownContextProvider


@pytest.fixture
def match_id() -> UUID:
    return uuid4()


@pytest.fixture
def state(match_id: UUID) -> BattleState:
    own = PokemonState(
        id="p1:1",
        name="Pikachu",
        species="Pikachu",
        hp_fraction=0.75,
        status=None,
        types=("electric",),
        active=True,
    )
    opponent = PokemonState(
        id="p2:1",
        name="Snorlax",
        species="Snorlax",
        hp_fraction=0.5,
        status="par",
        types=("normal",),
        active=True,
    )
    return BattleState(
        match_id=match_id,
        turn=4,
        perspective=Side.P1,
        player=BattleSide(side=Side.P1, display_name="Alpha", active=own, team=(own,)),
        opponent=BattleSide(side=Side.P2, display_name="Beta", active=opponent, team=(opponent,)),
    )


@pytest.fixture
def actions() -> tuple[BattleAction, ...]:
    return (
        BattleAction(id="move:1", type=ActionType.MOVE, name="Thunderbolt", slot=1),
        BattleAction(id="switch:1", type=ActionType.SWITCH, name="Charizard", slot=1),
    )


@pytest.fixture
def agent_request(
    match_id: UUID, state: BattleState, actions: tuple[BattleAction, ...]
) -> AgentRequest:
    knowledge, context, prompt, metrics = PokemonShowdownContextProvider().build(
        state,
        actions,
        prompt_profile=PromptProfileId.STANDARD_COMPETITIVE,
        context_profile=ContextProfileId.STANDARD,
        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
        strategy_memory=None,
    )
    return AgentRequest(
        request_id=uuid4(),
        match_id=match_id,
        side=Side.P1,
        turn=state.turn,
        decision_sequence=1,
        state=state,
        legal_actions=actions,
        prompt=prompt.combined,
        system_prompt=prompt.system,
        user_prompt=prompt.user,
        knowledge=knowledge,
        context=context,
        context_metrics=metrics,
        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
    )


@pytest.fixture
def match_config() -> MatchConfig:
    return MatchConfig(
        players=(
            PlayerConfig(side=Side.P1, display_name="Alpha", agent_type=AgentType.RANDOM),
            PlayerConfig(side=Side.P2, display_name="Beta", agent_type=AgentType.RANDOM),
        ),
        random_seed=42,
    )
