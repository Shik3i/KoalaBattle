from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from functools import partial
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from koalabattle.agents import Agent, ManualDecisionBroker
from koalabattle.core.models import (
    AgentDecision,
    AgentLifecycleState,
    AgentRequest,
    BattleEvent,
    MatchArchive,
    MatchConfig,
    MatchStatus,
    MatchSummary,
    Side,
)
from koalabattle.core.public import public_decision
from koalabattle.engines.base import BattleEngine, BattleEngineContext, EngineEventSink
from koalabattle.storage import BattleRepository

from .lifecycle import TERMINAL_MATCH_STATUSES

LOGGER = logging.getLogger(__name__)


class EngineFactory(Protocol):
    def __call__(self) -> BattleEngine: ...


class AgentFactory(Protocol):
    def __call__(
        self,
        config: MatchConfig,
        sink: EngineEventSink,
        manual_broker: ManualDecisionBroker,
    ) -> dict[Side, Agent]: ...


TerminalCallback = Callable[[UUID, MatchArchive], Awaitable[None]]
EligibilityCallback = Callable[[MatchSummary], Awaitable[bool]]
StartCallback = Callable[[MatchSummary], Awaitable[None]]


class RealtimeHub:
    def __init__(self) -> None:
        self._subscribers: defaultdict[UUID, set[asyncio.Queue[dict[str, object]]]] = defaultdict(
            set
        )
        self._overview_subscribers: set[asyncio.Queue[dict[str, object]]] = set()

    def subscribe(self, match_id: UUID) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=256)
        self._subscribers[match_id].add(queue)
        return queue

    def unsubscribe(self, match_id: UUID, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers[match_id].discard(queue)
        if not self._subscribers[match_id]:
            self._subscribers.pop(match_id, None)

    def subscribe_overview(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=256)
        self._overview_subscribers.add(queue)
        return queue

    def unsubscribe_overview(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._overview_subscribers.discard(queue)

    async def publish(self, match_id: UUID, message: dict[str, object]) -> None:
        self._publish_to(tuple(self._subscribers.get(match_id, ())), message)

    async def publish_overview(self, message: dict[str, object]) -> None:
        self._publish_to(tuple(self._overview_subscribers), message)

    @staticmethod
    def _publish_to(
        queues: tuple[asyncio.Queue[dict[str, object]], ...], message: dict[str, object]
    ) -> None:
        for queue in queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Overview and presentation clients must never block orchestration, so a
                # slow subscriber's queue can overflow. Silently dropping just this message
                # leaves a sequence gap the client has no way to detect (stuck endscreens,
                # sprites reappearing, stale action feed text). Instead, discard this
                # subscriber's whole backlog and replace it with one explicit resync
                # signal: the client's job on receiving it is to refetch a fresh snapshot
                # rather than try to reason about a now-discontinuous event stream.
                RealtimeHub._force_resync(queue)

    @staticmethod
    def _force_resync(queue: asyncio.Queue[dict[str, object]]) -> None:
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            queue.put_nowait({"kind": "resync_required"})
        except asyncio.QueueFull:
            pass


class MatchEventSink(EngineEventSink):
    def __init__(self, repository: BattleRepository, hub: RealtimeHub, match_id: UUID) -> None:
        self.repository = repository
        self.hub = hub
        self.match_id = match_id
        self.started_at = perf_counter()

    async def emit(self, event_type: str, turn: int, payload: dict[str, object]) -> None:
        event = BattleEvent(
            match_id=self.match_id,
            sequence=0,
            turn=turn,
            event_type=event_type,
            logical_offset_ms=round((perf_counter() - self.started_at) * 1000),
            payload=payload,
        )
        stored = await self.repository.append_event(event)
        await self.hub.publish(
            self.match_id, {"kind": "battle_event", "event": stored.model_dump(mode="json")}
        )

    async def record_decision(self, request: AgentRequest, decision: AgentDecision) -> None:
        record = await self.repository.record_decision(request, decision)
        await self.hub.publish(
            self.match_id,
            {"kind": "agent_submitted", "decision": public_decision(record)},
        )


class _BoundaryAgent:
    def __init__(self, agent: Agent, resume_gate: asyncio.Event) -> None:
        self.agent = agent
        self.resume_gate = resume_gate

    async def decide(self, request: AgentRequest) -> AgentDecision:
        await self.resume_gate.wait()
        decision = await self.agent.decide(request)
        await self.resume_gate.wait()
        return decision


class MatchSession:
    def __init__(
        self,
        archive: MatchArchive,
        repository: BattleRepository,
        hub: RealtimeHub,
        engine_factory: EngineFactory,
        agent_factory: AgentFactory,
    ) -> None:
        self.archive = archive
        self.repository = repository
        self.hub = hub
        self.engine = engine_factory()
        self.sink = MatchEventSink(repository, hub, archive.id)
        self.resume_gate = asyncio.Event()
        self.resume_gate.set()
        self.manual_broker = ManualDecisionBroker(self._manual_waiting)
        base_agents = agent_factory(archive.config, self.sink, self.manual_broker)
        self.agents: dict[Side, Agent] = {
            side: _BoundaryAgent(agent, self.resume_gate) for side, agent in base_agents.items()
        }
        self.task: asyncio.Task[None] | None = None
        self.paused = False

    def start(self) -> asyncio.Task[None]:
        if self.task is not None:
            raise RuntimeError("match session has already started")
        self.task = asyncio.create_task(self.run(), name=f"match-session-{self.archive.id}")
        return self.task

    async def run(self) -> None:
        config = self.archive.config
        try:
            current = await self.repository.get_match(self.archive.id)
            if current is not None and current.status in TERMINAL_MATCH_STATUSES:
                return
            await self.repository.set_status(self.archive.id, MatchStatus.RUNNING)
            await self.sink.emit(
                "battle_started",
                0,
                {
                    "format": config.format,
                    "generation": config.generation,
                    "engine": self.engine.name,
                },
            )
            outcome = await self.engine.run(
                BattleEngineContext(
                    match_id=self.archive.id,
                    config=config,
                    agents=self.agents,
                    sink=self.sink,
                )
            )
            for player in config.players:
                await self.sink.emit(
                    "agent_state",
                    outcome.result.turns,
                    {"side": player.side.value, "state": AgentLifecycleState.FINISHED.value},
                )
            await self.sink.emit(
                "battle_finished",
                outcome.result.turns,
                {"result": outcome.result.model_dump(mode="json")},
            )
            await self.repository.complete_match(
                self.archive.id,
                winner=outcome.result.winner,
                turns=outcome.result.turns,
                raw_showdown_log=outcome.raw_log,
            )
            await self.hub.publish(self.archive.id, {"kind": "match_completed"})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            current = await self.repository.get_match(self.archive.id)
            if current is not None and current.status in TERMINAL_MATCH_STATUSES:
                return
            LOGGER.exception("Match %s failed", self.archive.id)
            message = f"{type(error).__name__}: {error}"
            try:
                await self.sink.emit("battle_failed", 0, {"error": message})
                await self.repository.fail_match(self.archive.id, message)
                await self.hub.publish(self.archive.id, {"kind": "match_failed", "error": message})
            except Exception:
                LOGGER.exception("Could not persist failure for match %s", self.archive.id)

    async def pause(self) -> None:
        archive = await self.repository.get_match(self.archive.id)
        if archive is None:
            raise KeyError(str(self.archive.id))
        if archive.status is MatchStatus.PAUSED:
            return
        if archive.status not in {MatchStatus.RUNNING, MatchStatus.WAITING}:
            raise ValueError(f"match cannot pause while {archive.status.value}")
        self.paused = True
        self.resume_gate.clear()
        await self.repository.set_status(self.archive.id, MatchStatus.PAUSED)
        await self.hub.publish(self.archive.id, {"kind": "match_paused"})

    async def resume(self) -> None:
        archive = await self.repository.get_match(self.archive.id)
        if archive is None:
            raise KeyError(str(self.archive.id))
        if archive.status in {MatchStatus.RUNNING, MatchStatus.WAITING}:
            return
        if archive.status is not MatchStatus.PAUSED:
            raise ValueError(f"match cannot resume while {archive.status.value}")
        pending = await self.manual_broker.pending_for_match(self.archive.id)
        target = MatchStatus.WAITING if pending else MatchStatus.RUNNING
        await self.repository.set_status(self.archive.id, target)
        self.paused = False
        self.resume_gate.set()
        await self.hub.publish(self.archive.id, {"kind": "match_resumed"})

    async def _manual_waiting(self, request: AgentRequest) -> None:
        if not self.paused:
            archive = await self.repository.get_match(request.match_id)
            if archive is not None and archive.status is MatchStatus.RUNNING:
                await self.repository.set_status(request.match_id, MatchStatus.WAITING)
        await self.hub.publish(
            request.match_id,
            {"kind": "agent_waiting", "request": request.model_dump(mode="json")},
        )
        await self.sink.emit(
            "agent_state",
            request.turn,
            {
                "side": request.side.value,
                "state": AgentLifecycleState.WAITING.value,
                "request_id": str(request.request_id),
            },
        )

    async def submit_manual_decision(self, request_id: UUID, raw_response: str) -> None:
        pending = await self.pending_request(request_id)
        await self.manual_broker.submit(request_id, raw_response)
        if not self.paused:
            remaining = await self.manual_broker.pending_for_match(pending.match_id)
            target = MatchStatus.WAITING if remaining else MatchStatus.RUNNING
            await self.repository.set_status(pending.match_id, target)
        await self._publish_state(
            pending.side,
            pending.turn,
            AgentLifecycleState.EXECUTING,
        )
        await self.hub.publish(
            pending.match_id,
            {"kind": "manual_response_accepted", "request_id": str(request_id)},
        )

    async def pending_request(self, request_id: UUID) -> AgentRequest:
        for request in await self.manual_broker.pending_for_match(self.archive.id):
            if request.request_id == request_id:
                return request
        raise KeyError(str(request_id))

    async def _publish_state(self, side: Side, turn: int, state: AgentLifecycleState) -> None:
        await self.sink.emit(
            "agent_state",
            turn,
            {"side": side.value, "state": state.value},
        )


class MatchSupervisor:
    def __init__(
        self,
        repository: BattleRepository,
        hub: RealtimeHub,
        engine_factory: EngineFactory,
        agent_factory: AgentFactory,
        *,
        concurrency_limit: int,
        eligible: EligibilityCallback | None = None,
        on_start: StartCallback | None = None,
        on_terminal: TerminalCallback | None = None,
    ) -> None:
        self.repository = repository
        self.hub = hub
        self.engine_factory = engine_factory
        self.agent_factory = agent_factory
        self.concurrency_limit = concurrency_limit
        self.eligible = eligible
        self.on_start = on_start
        self.on_terminal = on_terminal
        self.sessions: dict[UUID, MatchSession] = {}
        self._wake = asyncio.Event()
        self._start_lock = asyncio.Lock()
        self._dispatcher: asyncio.Task[None] | None = None
        self._completion_tasks: set[asyncio.Task[None]] = set()
        self._closing = False

    async def start(self) -> tuple[UUID, ...]:
        async with self._start_lock:
            if self._dispatcher is not None:
                return ()
            interrupted = await self.repository.reconcile_interrupted_matches()
            self._dispatcher = asyncio.create_task(
                self._dispatch_loop(), name="match-supervisor-dispatch"
            )
            self._wake.set()
            return interrupted

    async def create_match(
        self,
        config: MatchConfig,
        *,
        engine_version: str | None,
        showdown_version: str | None,
        poke_env_version: str | None,
        tournament_id: UUID | None = None,
        series_id: UUID | None = None,
        challenge_run_id: UUID | None = None,
        challenge_stage_id: str | None = None,
    ) -> MatchArchive:
        if self._dispatcher is None:
            await self.start()
        engine = self.engine_factory()
        archive = await self.repository.create_match(
            uuid4(),
            config,
            engine=engine.name,
            engine_version=engine_version,
            showdown_version=showdown_version,
            poke_env_version=poke_env_version,
            tournament_id=tournament_id,
            series_id=series_id,
            challenge_run_id=challenge_run_id,
            challenge_stage_id=challenge_stage_id,
        )
        await self.repository.enqueue_match(archive.id)
        self._wake.set()
        queued = await self.repository.get_match(archive.id)
        assert queued is not None
        await self.hub.publish_overview({"kind": "match_queued", "match_id": str(archive.id)})
        return queued

    async def _dispatch_loop(self) -> None:
        while not self._closing:
            await self._wake.wait()
            self._wake.clear()
            try:
                await self._dispatch_available()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Match dispatcher recovered from an unexpected failure")

    async def _dispatch_available(self) -> None:
        while not self._closing and len(self.sessions) < self.concurrency_limit:
            queued = await self.repository.queued_matches()
            selected: MatchSummary | None = None
            for summary in queued:
                if self.eligible is None or await self.eligible(summary):
                    selected = summary
                    break
            if selected is None:
                return
            try:
                await self.repository.set_status(selected.id, MatchStatus.STARTING)
                if self.on_start is not None:
                    await self.on_start(selected)
                archive = await self.repository.get_match(selected.id)
                if archive is None:
                    raise RuntimeError("queued match disappeared before dispatch")
                session = MatchSession(
                    archive,
                    self.repository,
                    self.hub,
                    self.engine_factory,
                    self.agent_factory,
                )
                self.sessions[selected.id] = session
                task = session.start()
                task.add_done_callback(partial(self._schedule_session_done, selected.id))
                await self.hub.publish_overview(
                    {"kind": "match_started", "match_id": str(selected.id)}
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOGGER.exception("Could not dispatch match %s", selected.id)
                await self.repository.fail_match(
                    selected.id, f"DispatchError: {type(error).__name__}: {error}"
                )
                await self.hub.publish_overview(
                    {"kind": "match_terminal", "match_id": str(selected.id), "status": "failed"}
                )

    async def _session_done(self, match_id: UUID, task: asyncio.Task[None]) -> None:
        self.sessions.pop(match_id, None)
        if not task.cancelled():
            exception = task.exception()
            if exception is not None:
                LOGGER.error("Match session task failed: %s", exception)
        archive = await self.repository.get_match(match_id)
        if archive is not None and archive.status in TERMINAL_MATCH_STATUSES:
            if self.on_terminal is not None and not self._closing:
                await self.on_terminal(match_id, archive)
            await self.hub.publish_overview(
                {
                    "kind": "match_terminal",
                    "match_id": str(match_id),
                    "status": archive.status.value,
                }
            )
            self.repository.release_event_lock(match_id)
        self._wake.set()

    def _schedule_session_done(self, match_id: UUID, task: asyncio.Task[None]) -> None:
        completion = asyncio.create_task(
            self._session_done(match_id, task), name=f"match-session-cleanup-{match_id}"
        )
        self._completion_tasks.add(completion)
        completion.add_done_callback(self._completion_tasks.discard)

    async def pending_for_match(self, match_id: UUID) -> tuple[AgentRequest, ...]:
        session = self.sessions.get(match_id)
        return await session.manual_broker.pending_for_match(match_id) if session else ()

    async def find_pending(self, request_id: UUID) -> tuple[MatchSession, AgentRequest]:
        for session in tuple(self.sessions.values()):
            try:
                return session, await session.pending_request(request_id)
            except KeyError:
                continue
        raise KeyError(str(request_id))

    async def pause_match(self, match_id: UUID) -> None:
        session = self.sessions.get(match_id)
        if session is None:
            raise ValueError("match has no active runtime session")
        await session.pause()
        await self.hub.publish_overview({"kind": "match_paused", "match_id": str(match_id)})

    async def resume_match(self, match_id: UUID) -> None:
        session = self.sessions.get(match_id)
        if session is not None:
            await session.resume()
            await self.hub.publish_overview({"kind": "match_resumed", "match_id": str(match_id)})
            return
        archive = await self.repository.get_match(match_id)
        if archive is None:
            raise KeyError(str(match_id))
        if archive.status not in (
            MatchStatus.INTERRUPTED,
            MatchStatus.FAILED,
            MatchStatus.CANCELLED,
        ):
            raise ValueError(f"cannot resume match with status {archive.status.value}")
        await self.repository.enqueue_match(match_id)
        self._wake.set()
        await self.hub.publish_overview({"kind": "match_resumed", "match_id": str(match_id)})

    async def cancel_match(self, match_id: UUID) -> None:
        archive = await self.repository.get_match(match_id)
        if archive is None:
            raise KeyError(str(match_id))
        if archive.status is MatchStatus.CANCELLED:
            return
        if archive.status in TERMINAL_MATCH_STATUSES:
            raise ValueError(f"match is already {archive.status.value}")
        session = self.sessions.get(match_id)
        if session is not None:
            await session.manual_broker.cancel_match(match_id)
            if session.task is not None:
                session.task.cancel()
                await asyncio.gather(session.task, return_exceptions=True)
        await self.repository.cancel_match(match_id)
        event = BattleEvent(
            match_id=match_id,
            sequence=0,
            turn=archive.turns,
            event_type="match_cancelled",
            payload={"reason": "operator"},
        )
        stored = await self.repository.append_event(event)
        await self.hub.publish(
            match_id,
            {"kind": "battle_event", "event": stored.model_dump(mode="json")},
        )
        await self.hub.publish(match_id, {"kind": "match_cancelled"})
        terminal = await self.repository.get_match(match_id)
        if session is None and terminal is not None and self.on_terminal is not None:
            await self.on_terminal(match_id, terminal)
        self.repository.release_event_lock(match_id)
        self._wake.set()

    async def close(self) -> None:
        self._closing = True
        if self._dispatcher is not None:
            self._dispatcher.cancel()
            await asyncio.gather(self._dispatcher, return_exceptions=True)
        sessions = tuple(self.sessions.items())
        for _, session in sessions:
            await session.manual_broker.cancel_match(session.archive.id)
            if session.task is not None:
                session.task.cancel()
        if sessions:
            await asyncio.gather(
                *(session.task for _, session in sessions if session.task is not None),
                return_exceptions=True,
            )
        await asyncio.sleep(0)
        while self._completion_tasks:
            await asyncio.gather(*tuple(self._completion_tasks), return_exceptions=True)
            await asyncio.sleep(0)
        for match_id, _ in sessions:
            archive = await self.repository.get_match(match_id)
            if archive is not None and archive.status not in TERMINAL_MATCH_STATUSES:
                await self.repository.set_status(match_id, MatchStatus.INTERRUPTED)
        self.sessions.clear()
