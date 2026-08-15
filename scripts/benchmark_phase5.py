#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter, process_time
from uuid import uuid4

from koalabattle.agents import Agent, ApiAgent, ManualDecisionBroker
from koalabattle.agents.providers import FakeProvider
from koalabattle.core.models import (
    ActionType,
    AgentConfiguration,
    AgentLifecycleState,
    AgentRequest,
    AgentType,
    BattleAction,
    BattleEvent,
    BattleResult,
    BattleSide,
    BattleState,
    ContextProfileId,
    MatchConfig,
    MatchStatus,
    MemoryPolicyId,
    PlayerConfig,
    PokemonState,
    PromptProfileId,
    ProviderKind,
    Side,
)
from koalabattle.core.pricing import PricingTable
from koalabattle.engines.base import BattleEngineContext, EngineEventSink, EngineOutcome
from koalabattle.engines.showdown.context import PokemonShowdownContextProvider
from koalabattle.orchestration.runtime import MatchSupervisor, RealtimeHub
from koalabattle.replay import ReplayCursor
from koalabattle.storage import BattleRepository, Database
from koalabattle.tournaments.domain import round_robin_series, single_elimination_series
from koalabattle.tournaments.models import AgentPresetSnapshot, TournamentParticipant


@dataclass(frozen=True)
class Measurement:
    scenario: str
    scale: int
    elapsed_ms: float
    cpu_ms: float
    peak_rss_mb: float
    details: dict[str, int | float | str]


def _rss_mb() -> float:
    # macOS reports bytes; Linux reports KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if os.uname().sysname == "Darwin" else value / 1024


def _measure(scenario: str, scale: int, callback) -> Measurement:
    started = perf_counter()
    cpu_started = process_time()
    details = callback()
    return Measurement(
        scenario=scenario,
        scale=scale,
        elapsed_ms=round((perf_counter() - started) * 1000, 2),
        cpu_ms=round((process_time() - cpu_started) * 1000, 2),
        peak_rss_mb=round(_rss_mb(), 2),
        details=details,
    )


def benchmark_replay(count: int) -> Measurement:
    match_id = uuid4()
    events = tuple(
        BattleEvent(
            match_id=match_id,
            sequence=index + 1,
            turn=index // 8,
            event_type="move_used",
            payload={"index": index},
        )
        for index in range(count)
    )

    def run() -> dict[str, int]:
        cursor = ReplayCursor(events)
        while cursor.index < len(cursor.events):
            cursor = cursor.advance_event()
        return {"events_reconstructed": cursor.index}

    return _measure("replay", count, run)


def benchmark_tournament(count: int) -> Measurement:
    tournament_id = uuid4()
    participants = tuple(
        TournamentParticipant(
            id=uuid4(),
            tournament_id=tournament_id,
            display_name=f"Fake {index}",
            seed=index,
            agent=AgentPresetSnapshot(
                agent_type=AgentType.API, provider="fake", model="fake"
            ),
        )
        for index in range(1, count + 1)
    )

    def run() -> dict[str, int]:
        elimination = single_elimination_series(participants)
        round_robin = round_robin_series(participants)
        return {
            "single_elimination_series": len(elimination),
            "round_robin_series": len(round_robin),
        }

    return _measure("tournament-generation", count, run)


async def benchmark_history(count: int, root: Path) -> Measurement:
    database = Database(f"sqlite+aiosqlite:///{root / f'history-{count}.db'}")
    await database.create_schema()
    repository = BattleRepository(database)
    config = MatchConfig(
        players=(
            PlayerConfig(
                side=Side.P1, display_name="History A", agent_type=AgentType.RANDOM
            ),
            PlayerConfig(
                side=Side.P2, display_name="History B", agent_type=AgentType.RANDOM
            ),
        )
    )
    for _ in range(count):
        await repository.create_match(
            uuid4(),
            config,
            engine="benchmark",
            engine_version="1",
            showdown_version=None,
            poke_env_version=None,
        )
    started = perf_counter()
    cpu_started = process_time()
    page = await repository.list_matches(limit=100)
    counts = await repository.match_counts()
    elapsed = (perf_counter() - started) * 1000
    measurement = Measurement(
        scenario="historical-list-and-count",
        scale=count,
        elapsed_ms=round(elapsed, 2),
        cpu_ms=round((process_time() - cpu_started) * 1000, 2),
        peak_rss_mb=round(_rss_mb(), 2),
        details={
            "page_rows": len(page),
            "total_rows": sum(counts.values()),
            "page_limit": 100,
        },
    )
    await database.close()
    return measurement


async def benchmark_runtime(count: int, root: Path) -> Measurement:
    database_url = f"sqlite+aiosqlite:///{root / f'runtime-{count}.db'}"
    database = Database(database_url)
    await database.create_schema()
    repository = BattleRepository(database)
    hub = RealtimeHub()
    supervisor = MatchSupervisor(
        repository,
        hub,
        _BenchmarkEngine,
        _benchmark_agents,
        concurrency_limit=count,
    )
    configuration = AgentConfiguration(timeout_seconds=10, max_retries=0)

    def config(index: int) -> MatchConfig:
        return MatchConfig(
            name=f"Phase 5 Fake load {count}-{index}",
            players=(
                PlayerConfig(
                    side=Side.P1,
                    display_name=f"Fake {index}A",
                    agent_type=AgentType.API,
                    provider=ProviderKind.FAKE.value,
                    model="fake-battle-v1",
                    configuration=configuration,
                ),
                PlayerConfig(
                    side=Side.P2,
                    display_name=f"Fake {index}B",
                    agent_type=AgentType.API,
                    provider=ProviderKind.FAKE.value,
                    model="fake-battle-v1",
                    configuration=configuration,
                ),
            ),
            random_seed=20260815 + index,
        )

    started = perf_counter()
    cpu_started = process_time()
    created = await asyncio.gather(
        *(
            supervisor.create_match(
                config(index),
                engine_version="phase5-benchmark-v1",
                showdown_version=None,
                poke_env_version=None,
            )
            for index in range(count)
        )
    )
    subscriber_queues = {match.id: hub.subscribe(match.id) for match in created}
    async with asyncio.timeout(max(120, count * 8)):
        while True:
            archives = await asyncio.gather(
                *(repository.get_match(match.id) for match in created)
            )
            if all(
                archive is not None
                and archive.status
                in {MatchStatus.COMPLETED, MatchStatus.FAILED, MatchStatus.CANCELLED}
                for archive in archives
            ):
                break
            await asyncio.sleep(0.05)
    elapsed = (perf_counter() - started) * 1000
    completed = [
        item for item in archives if item and item.status is MatchStatus.COMPLETED
    ]
    failed = [item for item in archives if item and item.status is MatchStatus.FAILED]
    ordering_errors = sum(
        1
        for archive in completed
        if [event.sequence for event in archive.events]
        != list(range(1, len(archive.events) + 1))
    )
    decisions = sum(len(archive.decisions) for archive in completed)
    events = sum(len(archive.events) for archive in completed)
    hub_messages = sum(queue.qsize() for queue in subscriber_queues.values())
    for match_id, queue in subscriber_queues.items():
        hub.unsubscribe(match_id, queue)
    await supervisor.close()
    leaked_sessions = len(supervisor.sessions)
    leaked_completion_tasks = len(supervisor._completion_tasks)  # noqa: SLF001
    subscriber_groups = len(hub._subscribers)  # noqa: SLF001
    event_locks = len(repository._event_locks)  # noqa: SLF001
    await database.close()
    return Measurement(
        scenario="concurrent-fake-backend-matches",
        scale=count,
        elapsed_ms=round(elapsed, 2),
        cpu_ms=round((process_time() - cpu_started) * 1000, 2),
        peak_rss_mb=round(_rss_mb(), 2),
        details={
            "completed": len(completed),
            "failed": len(failed),
            "decisions": decisions,
            "events": events,
            "event_ordering_errors": ordering_errors,
            "leaked_sessions": leaked_sessions,
            "leaked_completion_tasks": leaked_completion_tasks,
            "subscriber_groups": subscriber_groups,
            "hub_messages": hub_messages,
            "event_locks": event_locks,
            "events_per_second": round(events / (elapsed / 1000), 2),
        },
    )


class _BenchmarkEngine:
    name = "phase5-benchmark"
    version = "1"

    async def run(self, context: BattleEngineContext) -> EngineOutcome:
        providers = {
            Side.P1: PokemonShowdownContextProvider(),
            Side.P2: PokemonShowdownContextProvider(),
        }
        action = BattleAction(
            id="move:1", type=ActionType.MOVE, name="Benchmark Move", slot=1
        )
        for turn in range(1, 5):
            requests: list[AgentRequest] = []
            for side in (Side.P1, Side.P2):
                opponent = Side.P2 if side is Side.P1 else Side.P1
                own = PokemonState(
                    id=f"{side.value}:1",
                    name=f"Own-{context.match_id.hex[:8]}-{side.value}",
                    species="Pikachu",
                    hp_fraction=max(0.1, 1 - turn / 10),
                    active=True,
                )
                opposing = PokemonState(
                    id=f"{opponent.value}:1",
                    name=f"Opponent-{context.match_id.hex[:8]}-{opponent.value}",
                    species="Snorlax",
                    hp_fraction=max(0.1, 1 - turn / 12),
                    active=True,
                )
                state = BattleState(
                    match_id=context.match_id,
                    turn=turn,
                    perspective=side,
                    player=BattleSide(
                        side=side,
                        display_name=context.config.players[
                            0 if side is Side.P1 else 1
                        ].display_name,
                        active=own,
                        team=(own,),
                    ),
                    opponent=BattleSide(
                        side=opponent,
                        display_name=context.config.players[
                            1 if side is Side.P1 else 0
                        ].display_name,
                        active=opposing,
                        team=(opposing,),
                    ),
                    public_history=(
                        f"|move|{side.value}|Benchmark Move|{opponent.value}",
                    ),
                )
                knowledge, snapshot, prompt, metrics = providers[side].build(
                    state,
                    (action,),
                    prompt_profile=PromptProfileId.BENCHMARK_FAIR,
                    context_profile=ContextProfileId.STANDARD,
                    memory_policy=MemoryPolicyId.STRATEGY_NOTE,
                    strategy_memory=None,
                )
                requests.append(
                    AgentRequest(
                        request_id=uuid4(),
                        match_id=context.match_id,
                        side=side,
                        turn=turn,
                        decision_sequence=turn,
                        state=state,
                        legal_actions=(action,),
                        prompt=prompt,
                        knowledge=knowledge,
                        context=snapshot,
                        context_metrics=metrics,
                        prompt_profile_id=PromptProfileId.BENCHMARK_FAIR,
                        prompt_profile_version=snapshot.prompt_profile_version,
                        context_schema_version=snapshot.schema_version,
                        knowledge_schema_version=knowledge.schema_version,
                        history_policy_version=snapshot.history_policy_version,
                        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
                        memory_policy_version=snapshot.memory_policy_version,
                    )
                )
            decisions = await asyncio.gather(
                *(context.agents[request.side].decide(request) for request in requests)
            )
            for request, decision in zip(requests, decisions, strict=True):
                await context.sink.record_decision(request, decision)
                await context.sink.emit(
                    "benchmark_turn",
                    turn,
                    {"side": request.side.value, "match": str(context.match_id)},
                )
        return EngineOutcome(
            result=BattleResult(winner=Side.P1, winner_name="Benchmark", turns=4),
            raw_log="|win|Benchmark",
        )


def _benchmark_agents(
    config: MatchConfig,
    sink: EngineEventSink,
    manual_broker: ManualDecisionBroker,
) -> dict[Side, Agent]:
    del manual_broker

    async def state_callback(
        side: Side, state: AgentLifecycleState, turn: int, metadata: dict[str, object]
    ) -> None:
        await sink.emit(
            "agent_state",
            turn,
            {"side": side.value, "state": state.value, **metadata},
        )

    agents: dict[Side, Agent] = {}
    for player in config.players:
        agents[player.side] = ApiAgent(
            FakeProvider(),
            player.model or "fake-battle-v1",
            player.configuration,
            state_callback=state_callback,
            pricing=PricingTable("{}", "benchmark"),
        )
    return agents


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-runtime", action="store_true")
    args = parser.parse_args()
    measurements: list[Measurement] = []
    with tempfile.TemporaryDirectory(prefix="koalabattle-phase5-benchmark-") as value:
        root = Path(value)
        for count in (1_000, 5_000, 10_000):
            measurements.append(benchmark_replay(count))
        for count in (100, 1_000):
            measurements.append(await benchmark_history(count, root))
        for count in (16, 32):
            measurements.append(benchmark_tournament(count))
        if not args.skip_runtime:
            for count in (1, 10, 25):
                measurements.append(await benchmark_runtime(count, root))
    payload = {
        "schema_version": "phase5-benchmark-v1",
        "measurements": [asdict(item) for item in measurements],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
