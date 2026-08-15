from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

from koalabattle.core.models import AgentDecision, AgentRequest

from .validation import StructuredDecision, parse_structured_decision

NotifyPending = Callable[[AgentRequest], Awaitable[None]]


@dataclass
class _PendingDecision:
    request: AgentRequest
    future: asyncio.Future[tuple[StructuredDecision, str]]
    started_at: float
    attempts: int = 0
    errors: tuple[str, ...] = ()


class ManualDecisionBroker:
    def __init__(self, notify: NotifyPending) -> None:
        self._notify = notify
        self._pending: dict[UUID, _PendingDecision] = {}
        self._lock = asyncio.Lock()

    async def wait(self, request: AgentRequest) -> AgentDecision:
        loop = asyncio.get_running_loop()
        pending = _PendingDecision(request, loop.create_future(), perf_counter())
        async with self._lock:
            self._pending[request.request_id] = pending
        await self._notify(request)
        try:
            response, raw = await pending.future
            return AgentDecision(
                request_id=request.request_id,
                match_id=request.match_id,
                side=request.side,
                turn=request.turn,
                decision_sequence=request.decision_sequence,
                action=response.action,
                commentary=response.commentary,
                raw_response=raw,
                provider_metadata={"agent": "manual"},
                latency_ms=round((perf_counter() - pending.started_at) * 1000),
                validation_attempts=pending.attempts,
                validation_errors=pending.errors,
                provider="manual",
                model="web-chat",
            )
        finally:
            async with self._lock:
                self._pending.pop(request.request_id, None)

    async def validate(self, request_id: UUID, raw_response: str) -> StructuredDecision:
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                raise KeyError("manual decision request is not pending")
            return parse_structured_decision(
                raw_response,
                {action.id for action in pending.request.legal_actions},
            )

    async def submit(self, request_id: UUID, raw_response: str) -> StructuredDecision:
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                raise KeyError("manual decision request is not pending")
            pending.attempts += 1
            if pending.future.done():
                raise KeyError("manual decision request has already been answered")

            try:
                response = parse_structured_decision(
                    raw_response,
                    {action.id for action in pending.request.legal_actions},
                )
            except ValueError as error:
                prefix = (
                    "illegal action"
                    if str(error) == "Selected action is no longer legal."
                    else "invalid structured response"
                )
                message = f"{prefix}: {error}"
                pending.errors = (*pending.errors, message)
                raise ValueError(message) from error
            pending.future.set_result((response, raw_response))
            return response

    async def cancel_match(self, match_id: UUID) -> None:
        async with self._lock:
            pending = [
                entry for entry in self._pending.values() if entry.request.match_id == match_id
            ]
            for entry in pending:
                if not entry.future.done():
                    entry.future.cancel()

    async def pending_for_match(self, match_id: UUID) -> tuple[AgentRequest, ...]:
        async with self._lock:
            return tuple(
                entry.request
                for entry in self._pending.values()
                if entry.request.match_id == match_id and not entry.future.done()
            )


class ManualAgent:
    def __init__(self, broker: ManualDecisionBroker) -> None:
        self._broker = broker

    async def decide(self, request: AgentRequest) -> AgentDecision:
        return await self._broker.wait(request)
