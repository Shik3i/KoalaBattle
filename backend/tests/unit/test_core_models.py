from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from koalabattle.core.models import (
    ActionType,
    AgentDecision,
    BattleAction,
    BattleEvent,
    BattleState,
    Side,
)


def test_battle_state_round_trip(state: BattleState) -> None:
    assert BattleState.model_validate_json(state.model_dump_json()) == state


def test_battle_event_round_trip(match_id) -> None:
    event = BattleEvent(
        match_id=match_id, sequence=3, turn=2, event_type="damage", payload={"hp": "50/100"}
    )
    assert BattleEvent.model_validate_json(event.model_dump_json()) == event


def test_action_id_must_match_slot_and_type() -> None:
    with pytest.raises(ValidationError, match="action id must be"):
        BattleAction(id="move:2", type=ActionType.MOVE, name="Tackle", slot=1)


def test_agent_decision_rejects_raw_showdown_command(match_id) -> None:
    with pytest.raises(ValidationError, match="supplied KoalaBattle action ID"):
        AgentDecision(
            request_id=uuid4(),
            match_id=match_id,
            side=Side.P1,
            turn=1,
            decision_sequence=1,
            action="/choose move thunderbolt",
        )
