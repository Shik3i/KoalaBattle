from __future__ import annotations

import random

from koalabattle.core.models import AgentDecision, AgentRequest


class RandomAgent:
    def __init__(self, seed: int | None = None) -> None:
        self._random = random.Random(seed)

    async def decide(self, request: AgentRequest) -> AgentDecision:
        selected = self._random.choice(request.legal_actions)
        return AgentDecision(
            request_id=request.request_id,
            match_id=request.match_id,
            side=request.side,
            turn=request.turn,
            decision_sequence=request.decision_sequence,
            action=selected.id,
            commentary=f"Randomly selected {selected.name}.",
            provider_metadata={"agent": "random"},
        )
