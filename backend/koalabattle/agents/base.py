from __future__ import annotations

from typing import Protocol

from koalabattle.core.models import AgentDecision, AgentRequest


class Agent(Protocol):
    async def decide(self, request: AgentRequest) -> AgentDecision: ...
