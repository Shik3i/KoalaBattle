from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from koalabattle.agents.base import Agent
from koalabattle.core.models import AgentDecision, AgentRequest, BattleResult, MatchConfig, Side


class EngineEventSink(Protocol):
    async def emit(self, event_type: str, turn: int, payload: dict[str, object]) -> None: ...

    async def record_decision(self, request: AgentRequest, decision: AgentDecision) -> None: ...


@dataclass(frozen=True, slots=True)
class BattleEngineContext:
    match_id: UUID
    config: MatchConfig
    agents: dict[Side, Agent]
    sink: EngineEventSink


@dataclass(frozen=True, slots=True)
class EngineOutcome:
    result: BattleResult
    raw_log: str | None = None


class BattleEngine(Protocol):
    name: str
    version: str

    async def run(self, context: BattleEngineContext) -> EngineOutcome: ...
