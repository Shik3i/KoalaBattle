from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from koalabattle.agents import Agent, ManualDecisionBroker, RandomAgent
from koalabattle.core.models import (
    AgentType,
    BattleResult,
    MatchConfig,
    MatchStatus,
    PlayerConfig,
    Side,
)
from koalabattle.engines.base import BattleEngineContext, EngineEventSink, EngineOutcome
from koalabattle.orchestration.runtime import MatchSupervisor, RealtimeHub
from koalabattle.storage import BattleRepository, Database


@dataclass
class _ConcurrencyTracker:
    active: int = 0
    maximum: int = 0


class _DeterministicEngine:
    name = "generic-test"
    version = "1"

    def __init__(self, tracker: _ConcurrencyTracker) -> None:
        self.tracker = tracker

    async def run(self, context: BattleEngineContext) -> EngineOutcome:
        self.tracker.active += 1
        self.tracker.maximum = max(self.tracker.maximum, self.tracker.active)
        try:
            await context.sink.emit("generic_started", 0, {"match": str(context.match_id)})
            if context.config.name == "failure":
                raise RuntimeError("isolated engine failure")
            await asyncio.sleep(0.15 if context.config.name == "slow" else 0.04)
            await context.sink.emit("generic_finished", 1, {"match": str(context.match_id)})
            return EngineOutcome(BattleResult(winner=Side.P1, turns=1))
        finally:
            self.tracker.active -= 1


def _config(name: str) -> MatchConfig:
    return MatchConfig(
        name=name,
        players=(
            PlayerConfig(side=Side.P1, display_name=f"{name} A", agent_type=AgentType.RANDOM),
            PlayerConfig(side=Side.P2, display_name=f"{name} B", agent_type=AgentType.RANDOM),
        ),
    )


def _agents(
    config: MatchConfig,
    sink: EngineEventSink,
    manual_broker: ManualDecisionBroker,
) -> dict[Side, Agent]:
    del config, sink, manual_broker
    return {Side.P1: RandomAgent(1), Side.P2: RandomAgent(2)}


async def _wait_terminal(repository: BattleRepository, match_ids: list[UUID]) -> None:
    async with asyncio.timeout(5):
        while True:
            archives = [await repository.get_match(match_id) for match_id in match_ids]
            if all(
                archive is not None
                and archive.status
                in {
                    MatchStatus.COMPLETED,
                    MatchStatus.FAILED,
                    MatchStatus.CANCELLED,
                }
                for archive in archives
            ):
                return
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_supervisor_runs_isolated_matches_with_global_limit(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'orchestration.db'}")
    await database.create_schema()
    repository = BattleRepository(database)
    tracker = _ConcurrencyTracker()
    supervisor = MatchSupervisor(
        repository,
        RealtimeHub(),
        lambda: _DeterministicEngine(tracker),
        _agents,
        concurrency_limit=2,
    )
    created = list(
        await asyncio.gather(
            *(
                supervisor.create_match(
                    _config(f"match-{index}"),
                    engine_version="1",
                    showdown_version=None,
                    poke_env_version=None,
                )
                for index in range(3)
            )
        )
    )
    await _wait_terminal(repository, [item.id for item in created])
    assert tracker.maximum == 2
    for item in created:
        archive = await repository.get_match(item.id)
        assert archive is not None and archive.status is MatchStatus.COMPLETED
        assert [event.sequence for event in archive.events] == list(
            range(1, len(archive.events) + 1)
        )
        assert all(event.match_id == item.id for event in archive.events)
    await supervisor.close()
    await database.close()


@pytest.mark.asyncio
async def test_cancellation_and_failure_do_not_cross_match_boundaries(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'isolation.db'}")
    await database.create_schema()
    repository = BattleRepository(database)
    tracker = _ConcurrencyTracker()
    supervisor = MatchSupervisor(
        repository,
        RealtimeHub(),
        lambda: _DeterministicEngine(tracker),
        _agents,
        concurrency_limit=3,
    )
    slow = await supervisor.create_match(
        _config("slow"), engine_version="1", showdown_version=None, poke_env_version=None
    )
    failed = await supervisor.create_match(
        _config("failure"), engine_version="1", showdown_version=None, poke_env_version=None
    )
    healthy = await supervisor.create_match(
        _config("healthy"), engine_version="1", showdown_version=None, poke_env_version=None
    )
    async with asyncio.timeout(2):
        while slow.id not in supervisor.sessions:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    await supervisor.cancel_match(slow.id)
    await _wait_terminal(repository, [slow.id, failed.id, healthy.id])
    assert (await repository.get_match(slow.id)).status is MatchStatus.CANCELLED  # type: ignore[union-attr]
    assert (await repository.get_match(failed.id)).status is MatchStatus.FAILED  # type: ignore[union-attr]
    assert (await repository.get_match(healthy.id)).status is MatchStatus.COMPLETED  # type: ignore[union-attr]
    await supervisor.close()
    await database.close()


@pytest.mark.asyncio
async def test_restart_reconciliation_marks_only_active_runtime_interrupted(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'restart.db'}")
    await database.create_schema()
    repository = BattleRepository(database)
    active = await repository.create_match(
        uuid4(),
        _config("active"),
        engine="test",
        engine_version="1",
        showdown_version=None,
        poke_env_version=None,
    )
    await repository.enqueue_match(active.id)
    await repository.set_status(active.id, MatchStatus.STARTING)
    await repository.set_status(active.id, MatchStatus.RUNNING)
    historical = await repository.create_match(
        uuid4(),
        _config("historical"),
        engine="test",
        engine_version="1",
        showdown_version=None,
        poke_env_version=None,
    )
    await repository.enqueue_match(historical.id)
    await repository.set_status(historical.id, MatchStatus.STARTING)
    await repository.set_status(historical.id, MatchStatus.RUNNING)
    await repository.complete_match(historical.id, winner=Side.P1, turns=1, raw_showdown_log=None)
    interrupted = await repository.reconcile_interrupted_matches()
    assert interrupted == (active.id,)
    assert (await repository.get_match(active.id)).status is MatchStatus.INTERRUPTED  # type: ignore[union-attr]
    assert (await repository.get_match(historical.id)).status is MatchStatus.COMPLETED  # type: ignore[union-attr]
    await database.close()
