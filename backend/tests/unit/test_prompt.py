from __future__ import annotations

import json

from koalabattle.core.models import AgentRequest, BattleAction, BattleState


def test_prompt_is_structured_and_contains_only_normalized_request(
    agent_request: AgentRequest, actions: tuple[BattleAction, ...], state: BattleState
) -> None:
    payload = json.loads(agent_request.prompt)
    assert payload["battle"] == state.model_dump(mode="json")
    assert [item["id"] for item in payload["legal_actions"]] == [item.id for item in actions]
    assert "poke_env" not in agent_request.prompt
    assert "chain-of-thought" not in agent_request.prompt
    assert payload["response_schema"]["action"] == "one exact id from legal_actions"
