from __future__ import annotations

import asyncio

import pytest

from koalabattle.agents import ApiAgent, ManualAgent, ManualDecisionBroker, RandomAgent
from koalabattle.agents.providers import FakeProvider
from koalabattle.core.models import (
    AgentConfiguration,
    AgentLifecycleState,
    AgentRequest,
    MemoryPolicyId,
    Side,
)
from koalabattle.core.pricing import PricingTable


@pytest.mark.asyncio
async def test_random_agent_always_returns_legal_action(agent_request: AgentRequest) -> None:
    legal = {action.id for action in agent_request.legal_actions}
    agent = RandomAgent(seed=7)
    for _ in range(50):
        assert (await agent.decide(agent_request)).action in legal


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
