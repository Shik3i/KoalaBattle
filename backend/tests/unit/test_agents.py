from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from koalabattle.agents import (
    ApiAgent,
    ManualAgent,
    ManualDecisionBroker,
    RandomAgent,
    TacticalAgent,
)
from koalabattle.agents.api_agent import _CommentaryPreview
from koalabattle.agents.providers import DeepSeekProvider, FakeProvider
from koalabattle.agents.providers.base import ProviderRequest
from koalabattle.core.models import (
    ActionType,
    AgentConfiguration,
    AgentLifecycleState,
    AgentRequest,
    BattleAction,
    BattleSide,
    MemoryPolicyId,
    MoveState,
    PokemonState,
    Side,
)
from koalabattle.core.pricing import PricingTable


def test_streamed_preview_exposes_only_public_commentary() -> None:
    preview = _CommentaryPreview()
    assert preview.feed('{"action":"move:1","commentary":"Choose ') == "Choose "
    assert (
        preview.feed('the safe line.","strategy_memory":"Keep this private."}')
        == "Choose the safe line."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-v4-pro"])
async def test_deepseek_v4_models_use_documented_json_and_thinking_controls(
    model: str,
) -> None:
    provider = DeepSeekProvider("sk-deepseek-test-only")
    calls: list[dict[str, object]] = []

    async def create(**arguments: object) -> object:
        calls.append(arguments)
        return SimpleNamespace(
            id="deepseek-request",
            model=model,
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"action":"move:1"}'),
                    finish_reason="stop",
                )
            ],
        )

    provider._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    response = await provider.generate(
        ProviderRequest(
            prompt="Return JSON.",
            model=model,
            timeout_seconds=30,
            max_output_tokens=256,
            temperature=0.7,
            reasoning_effort="max",
        )
    )

    assert response.model == model
    assert calls == [
        {
            "model": model,
            "messages": [{"role": "user", "content": "Return JSON."}],
            "max_tokens": 256,
            "timeout": 30.0,
            "extra_body": {"thinking": {"type": "enabled"}},
            "reasoning_effort": "max",
            "response_format": {"type": "json_object"},
        }
    ]


@pytest.mark.asyncio
async def test_random_agent_always_returns_legal_action(agent_request: AgentRequest) -> None:
    legal = {action.id for action in agent_request.legal_actions}
    agent = RandomAgent(seed=7)
    for _ in range(50):
        assert (await agent.decide(agent_request)).action in legal


@pytest.mark.asyncio
async def test_tactical_agent_prefers_stab_super_effective_damage(
    agent_request: AgentRequest,
) -> None:
    opponent = agent_request.state.opponent.active
    assert opponent is not None
    state = agent_request.state.model_copy(
        update={
            "opponent": agent_request.state.opponent.model_copy(
                update={"active": opponent.model_copy(update={"types": ("water",)})}
            )
        }
    )
    actions = (
        agent_request.legal_actions[0].model_copy(
            update={"move_type": "electric", "category": "special", "power": 90, "accuracy": 100}
        ),
        agent_request.legal_actions[0].model_copy(
            update={
                "id": "move:2",
                "slot": 2,
                "name": "Quick Attack",
                "move_type": "normal",
                "category": "physical",
                "power": 40,
                "accuracy": 100,
            }
        ),
    )
    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": state, "legal_actions": actions})
    )
    assert decision.action == "move:1"
    assert decision.estimated_cost.amount in {None, 0}
    assert decision.provider_metadata == {"agent": "tactical-auto", "local": True, "cost": 0}


@pytest.mark.asyncio
async def test_tactical_agent_uses_recovery_only_when_low(agent_request: AgentRequest) -> None:
    active = agent_request.state.player.active
    assert active is not None
    low_state = agent_request.state.model_copy(
        update={
            "player": agent_request.state.player.model_copy(
                update={"active": active.model_copy(update={"hp_fraction": 0.2})}
            )
        }
    )
    actions = (
        agent_request.legal_actions[0].model_copy(
            update={"name": "Recover", "category": "status", "power": 0, "accuracy": 100}
        ),
        agent_request.legal_actions[0].model_copy(
            update={
                "id": "move:2",
                "slot": 2,
                "name": "Tackle",
                "move_type": "normal",
                "category": "physical",
                "power": 40,
                "accuracy": 100,
            }
        ),
    )
    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": low_state, "legal_actions": actions})
    )
    assert decision.action == "move:1"


def _brock_matchup(agent_request: AgentRequest, *, active_fainted: bool = False) -> AgentRequest:
    pikachu = PokemonState(
        id="p1: Pikachu",
        name="Pikachu",
        species="Pikachu",
        hp_fraction=0 if active_fainted else 1,
        fainted=active_fainted,
        active=True,
        types=("electric",),
        moves=(
            MoveState(
                id="thunderbolt",
                name="Thunderbolt",
                type="electric",
                category="special",
                power=90,
                accuracy=100,
            ),
        ),
    )
    charizard = PokemonState(
        id="p1: Charizard",
        name="Charizard",
        species="Charizard",
        hp_fraction=1,
        types=("fire", "flying"),
        moves=(
            MoveState(
                id="flamethrower",
                name="Flamethrower",
                type="fire",
                category="special",
                power=90,
                accuracy=100,
            ),
        ),
    )
    blastoise = PokemonState(
        id="p1: Blastoise",
        name="Blastoise",
        species="Blastoise",
        hp_fraction=1,
        types=("water",),
        moves=(
            MoveState(
                id="surf",
                name="Surf",
                type="water",
                category="special",
                power=90,
                accuracy=100,
            ),
        ),
    )
    onix = PokemonState(
        id="p2: Onix",
        name="Onix",
        species="Onix",
        hp_fraction=1,
        active=True,
        types=("rock", "ground"),
        moves=(
            MoveState(
                id="rockthrow",
                name="Rock Throw",
                type="rock",
                category="physical",
                power=50,
                accuracy=90,
            ),
        ),
    )
    state = agent_request.state.model_copy(
        update={
            "player": BattleSide(
                side=Side.P1,
                display_name="Draft",
                active=pikachu,
                team=(pikachu, charizard, blastoise),
            ),
            "opponent": BattleSide(
                side=Side.P2,
                display_name="Brock",
                active=onix,
                team=(onix,),
            ),
        }
    )
    actions = (
        BattleAction(
            id="move:1",
            type=ActionType.MOVE,
            name="Thunderbolt",
            slot=1,
            move_type="electric",
            category="special",
            power=90,
            accuracy=100,
        ),
        BattleAction(
            id="switch:1",
            type=ActionType.SWITCH,
            name="Charizard",
            species="Charizard",
            slot=1,
            hp_fraction=1,
        ),
        BattleAction(
            id="switch:2",
            type=ActionType.SWITCH,
            name="Blastoise",
            species="Blastoise",
            slot=2,
            hp_fraction=1,
        ),
    )
    if active_fainted:
        actions = actions[1:]
    return agent_request.model_copy(update={"state": state, "legal_actions": actions})


@pytest.mark.asyncio
async def test_tactical_agent_switches_pikachu_out_of_brock_matchup(
    agent_request: AgentRequest,
) -> None:
    decision = await TacticalAgent().decide(_brock_matchup(agent_request))
    assert decision.action == "switch:2"


@pytest.mark.asyncio
async def test_tactical_agent_uses_matchup_scoring_for_forced_switch_and_lead(
    agent_request: AgentRequest,
) -> None:
    request = _brock_matchup(agent_request, active_fainted=True)
    first = await TacticalAgent().decide(request)
    second = await TacticalAgent().decide(request)
    assert first.action == second.action == "switch:2"


@pytest.mark.asyncio
async def test_tactical_agent_leads_grass_into_a_known_water_roster(
    agent_request: AgentRequest,
) -> None:
    grass = PokemonState(
        id="p1: Ivysaur",
        name="Ivysaur",
        species="Ivysaur",
        hp_fraction=1,
        active=False,
        types=("grass", "poison"),
        moves=(
            MoveState(
                id="gigadrain",
                name="Giga Drain",
                type="grass",
                category="special",
                power=75,
                accuracy=100,
            ),
        ),
    )
    water = grass.model_copy(
        update={
            "id": "p1: Wartortle",
            "name": "Wartortle",
            "species": "Wartortle",
            "types": ("water",),
            "moves": (
                MoveState(
                    id="waterpulse",
                    name="Water Pulse",
                    type="water",
                    category="special",
                    power=60,
                    accuracy=100,
                ),
            ),
        }
    )
    starmie = water.model_copy(
        update={
            "id": "p2: Starmie",
            "name": "Starmie",
            "species": "Starmie",
            "types": ("water", "psychic"),
        }
    )
    golduck = water.model_copy(
        update={"id": "p2: Golduck", "name": "Golduck", "species": "Golduck"}
    )
    state = agent_request.state.model_copy(
        update={
            "player": agent_request.state.player.model_copy(
                update={"active": None, "team": (water, grass)}
            ),
            "opponent": agent_request.state.opponent.model_copy(
                update={"active": None, "team": (starmie, golduck)}
            ),
        }
    )
    actions = (
        BattleAction(
            id="switch:1",
            type=ActionType.SWITCH,
            name="Wartortle",
            species="Wartortle",
            slot=1,
            hp_fraction=1,
        ),
        BattleAction(
            id="switch:2",
            type=ActionType.SWITCH,
            name="Ivysaur",
            species="Ivysaur",
            slot=2,
            hp_fraction=1,
        ),
    )

    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": state, "legal_actions": actions})
    )
    assert decision.action == "switch:2"


@pytest.mark.asyncio
async def test_tactical_agent_scores_duplicate_species_by_unique_nickname(
    agent_request: AgentRequest,
) -> None:
    base = _brock_matchup(agent_request, active_fainted=True)
    template = base.state.player.team[1]
    healthy = template.model_copy(
        update={
            "id": "p1: Koffing 1",
            "name": "Koffing 1",
            "species": "Koffing",
            "hp_fraction": 1.0,
        }
    )
    weak = template.model_copy(
        update={
            "id": "p1: Koffing 2",
            "name": "Koffing 2",
            "species": "Koffing",
            "hp_fraction": 0.05,
        }
    )
    request = base.model_copy(
        update={
            "state": base.state.model_copy(
                update={
                    "player": base.state.player.model_copy(
                        update={"team": (healthy, weak)}
                    )
                }
            ),
            "legal_actions": (
                BattleAction(
                    id="switch:1",
                    type=ActionType.SWITCH,
                    name="Koffing 1",
                    species="Koffing",
                    slot=1,
                    hp_fraction=1,
                ),
                BattleAction(
                    id="switch:2",
                    type=ActionType.SWITCH,
                    name="Koffing 2",
                    species="Koffing",
                    slot=2,
                    hp_fraction=0.05,
                ),
            ),
        }
    )

    decision = await TacticalAgent().decide(request)

    assert decision.action == "switch:1"


@pytest.mark.asyncio
async def test_manual_agent_rejects_malformed_and_illegal_json(
    agent_request: AgentRequest,
) -> None:
    notified = asyncio.Event()

    async def notify(_: AgentRequest) -> None:
        notified.set()

    broker = ManualDecisionBroker(notify)
    task = asyncio.create_task(ManualAgent(broker).decide(agent_request))
    await notified.wait()

    with pytest.raises(ValueError, match="invalid structured response"):
        await broker.submit(agent_request.request_id, "not-json")
    with pytest.raises(ValueError, match="illegal action"):
        await broker.submit(agent_request.request_id, '{"action":"move:99","commentary":"No"}')

    await broker.submit(
        agent_request.request_id,
        '{"action":"move:1","commentary":"Public explanation"}',
    )
    decision = await task
    assert decision.action == "move:1"
    assert decision.validation_attempts == 3
    assert len(decision.validation_errors) == 2


@pytest.mark.asyncio
async def test_manual_agent_accepts_fenced_json(agent_request: AgentRequest) -> None:
    notified = asyncio.Event()

    async def notify(_: AgentRequest) -> None:
        notified.set()

    broker = ManualDecisionBroker(notify)
    task = asyncio.create_task(ManualAgent(broker).decide(agent_request))
    await notified.wait()
    await broker.submit(
        agent_request.request_id,
        'Here is the choice:\n```json\n{"action":"move:1","commentary":"Safe line."}\n```',
    )
    assert (await task).action == "move:1"


@pytest.mark.asyncio
async def test_human_direct_action_uses_the_same_exact_legal_action_boundary(
    agent_request: AgentRequest,
) -> None:
    notified = asyncio.Event()

    async def notify(_: AgentRequest) -> None:
        notified.set()

    broker = ManualDecisionBroker(notify)
    task = asyncio.create_task(ManualAgent(broker).decide(agent_request))
    await notified.wait()
    with pytest.raises(ValueError, match="illegal action"):
        await broker.submit_action(agent_request.request_id, "move:99")
    await broker.submit_action(agent_request.request_id, "switch:1")
    decision = await task
    assert decision.action == "switch:1"
    assert decision.commentary == ""
    assert decision.provider == "human"
    assert decision.model == "direct-control"
    assert decision.provider_metadata == {"agent": "human"}


@pytest.mark.asyncio
async def test_manual_double_submission_is_rejected_and_memory_is_replaced(
    agent_request: AgentRequest,
) -> None:
    notified = asyncio.Event()

    async def notify(_: AgentRequest) -> None:
        notified.set()

    broker = ManualDecisionBroker(notify)
    task = asyncio.create_task(ManualAgent(broker).decide(agent_request))
    await notified.wait()
    raw = '{"action":"move:1","commentary":"Safe.","strategy_memory":"Replace the prior note."}'
    await broker.submit(agent_request.request_id, raw)
    with pytest.raises(KeyError):
        await broker.submit(agent_request.request_id, raw)
    assert (await task).strategy_memory == "Replace the prior note."


@pytest.mark.asyncio
async def test_api_agent_retries_invalid_response_and_records_audit(
    agent_request: AgentRequest,
) -> None:
    states: list[AgentLifecycleState] = []

    async def state_callback(
        _: Side, state: AgentLifecycleState, __: int, ___: dict[str, object]
    ) -> None:
        states.append(state)

    agent = ApiAgent(
        FakeProvider("invalid_then_valid"),
        "fake-battle-v1",
        AgentConfiguration(max_retries=1),
        state_callback=state_callback,
        pricing=PricingTable(
            '{"fake:fake-battle-v1":{"input_per_million":1,"output_per_million":2}}',
            "test-v1",
        ),
    )
    decision = await agent.decide(agent_request)
    assert decision.action == "move:1"
    assert decision.provider == "fake"
    assert decision.usage is not None and decision.usage.total_tokens == 144
    assert decision.estimated_cost.available
    assert decision.retry_attempts[0].category.value == "invalid_response"
    assert states == [
        AgentLifecycleState.THINKING,
        AgentLifecycleState.RETRYING,
        AgentLifecycleState.DECIDED,
    ]
    assert decision.strategy_memory == "Preserve healthy switch options for the next turn."


@pytest.mark.asyncio
async def test_strategy_memory_is_ignored_when_policy_is_disabled(
    agent_request: AgentRequest,
) -> None:
    async def state_callback(
        _: Side, __: AgentLifecycleState, ___: int, ____: dict[str, object]
    ) -> None:
        return None

    disabled = agent_request.model_copy(update={"memory_policy": MemoryPolicyId.DISABLED})
    decision = await ApiAgent(
        FakeProvider(),
        "fake-battle-v1",
        AgentConfiguration(),
        state_callback=state_callback,
        pricing=PricingTable("{}", "test-v1"),
    ).decide(disabled)
    assert decision.strategy_memory is None


def _status_action(request: AgentRequest, name: str) -> BattleAction:
    return request.legal_actions[0].model_copy(
        update={"name": name, "category": "status", "power": 0, "accuracy": 100}
    )


@pytest.mark.asyncio
async def test_tactical_agent_lays_hazards_only_while_the_opponent_can_still_switch(
    agent_request: AgentRequest,
) -> None:
    bench = tuple(
        PokemonState(
            id=f"p2: Bench {index}",
            name=f"Bench {index}",
            species=f"bench{index}",
            hp_fraction=1.0,
            types=("Normal",),
        )
        for index in range(1, 3)
    )
    with_bench = agent_request.state.model_copy(
        update={"opponent": agent_request.state.opponent.model_copy(update={"team": bench})}
    )
    actions = (
        _status_action(agent_request, "Stealth Rock"),
        agent_request.legal_actions[0].model_copy(
            update={"name": "Tackle", "category": "physical", "power": 40, "accuracy": 100}
        ),
    )
    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": with_bench, "legal_actions": actions})
    )
    assert decision.action == actions[0].id

    # With the hazard already down there is nothing to gain from setting it again.
    already = with_bench.model_copy(
        update={
            "opponent": with_bench.opponent.model_copy(
                update={"side_conditions": ("Stealth Rock",)}
            )
        }
    )
    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": already, "legal_actions": actions})
    )
    assert decision.action == actions[1].id


@pytest.mark.asyncio
async def test_tactical_agent_does_not_stack_a_second_major_status(
    agent_request: AgentRequest,
) -> None:
    opponent = agent_request.state.opponent.active
    assert opponent is not None
    poisoned = agent_request.state.model_copy(
        update={
            "opponent": agent_request.state.opponent.model_copy(
                update={"active": opponent.model_copy(update={"status": "tox"})}
            )
        }
    )
    actions = (
        _status_action(agent_request, "Thunder Wave"),
        agent_request.legal_actions[0].model_copy(
            update={"name": "Tackle", "category": "physical", "power": 40, "accuracy": 100}
        ),
    )
    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": poisoned, "legal_actions": actions})
    )
    assert decision.action == actions[1].id


@pytest.mark.asyncio
async def test_tactical_agent_clears_its_own_hazards_when_they_are_down(
    agent_request: AgentRequest,
) -> None:
    hazarded = agent_request.state.model_copy(
        update={
            "player": agent_request.state.player.model_copy(
                update={"side_conditions": ("Stealth Rock", "Spikes")}
            )
        }
    )
    actions = (
        _status_action(agent_request, "Rapid Spin"),
        _status_action(agent_request, "Light Screen"),
    )
    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": hazarded, "legal_actions": actions})
    )
    assert decision.action == actions[0].id

    clean = agent_request.state
    decision = await TacticalAgent().decide(
        agent_request.model_copy(update={"state": clean, "legal_actions": actions})
    )
    assert decision.action == actions[1].id
