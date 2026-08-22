from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from koalabattle.core.models import (
    ActionType,
    AgentConfiguration,
    AgentDecision,
    AgentType,
    BattleAction,
    BattleEvent,
    BattleState,
    MatchArchive,
    MatchConfig,
    MatchStatus,
    PlayerConfig,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.core.public import presentation_archive
from koalabattle.engines.showdown.mapper import action_to_order


def test_battle_state_round_trip(state: BattleState) -> None:
    assert BattleState.model_validate_json(state.model_dump_json()) == state


def test_llm_defaults_allow_slow_models_one_recovery_attempt() -> None:
    configuration = AgentConfiguration()
    assert configuration.timeout_seconds == 300
    assert configuration.max_retries == 1


def test_battle_event_round_trip(match_id) -> None:
    event = BattleEvent(
        match_id=match_id, sequence=3, turn=2, event_type="damage", payload={"hp": "50/100"}
    )
    assert BattleEvent.model_validate_json(event.model_dump_json()) == event


def test_action_id_must_match_slot_and_type() -> None:
    with pytest.raises(ValidationError, match="action id must be"):
        BattleAction(id="move:2", type=ActionType.MOVE, name="Tackle", slot=1)


def test_mega_action_is_explicit_and_mutually_exclusive_with_tera() -> None:
    action = BattleAction(
        id="move:1:mega",
        type=ActionType.MOVE,
        name="Flamethrower + Mega Evolve",
        slot=1,
        mega_evolve=True,
    )
    assert action.mega_evolve is True

    with pytest.raises(ValidationError, match="cannot Terastallize and Mega Evolve"):
        BattleAction(
            id="move:1:tera",
            type=ActionType.MOVE,
            name="Illegal",
            slot=1,
            terastallize=True,
            mega_evolve=True,
        )


def test_mega_action_serializes_to_a_real_showdown_mega_order() -> None:
    move = object()
    battle = SimpleNamespace(available_moves=[move])
    action = BattleAction(
        id="move:1:mega",
        type=ActionType.MOVE,
        name="Flamethrower + Mega Evolve",
        slot=1,
        mega_evolve=True,
    )

    order = action_to_order(action, battle)

    assert order.order is move
    assert order.mega is True
    assert order.terastallize is False


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


def test_public_presentation_never_contains_fixed_team_secrets() -> None:
    snapshot_id = uuid4()
    config = MatchConfig(
        format="gen9ou",
        team_policy=TeamPolicy.FIXED,
        players=(
            PlayerConfig(
                side=Side.P1,
                display_name="Alpha",
                agent_type=AgentType.RANDOM,
                team_source=TeamSource.IMPORTED,
                team_snapshot_id=snapshot_id,
                team_export="SECRET TEAM ONE",
                team_packed="secret-packed-one",
            ),
            PlayerConfig(
                side=Side.P2,
                display_name="Beta",
                agent_type=AgentType.RANDOM,
                team_source=TeamSource.IMPORTED,
                team_snapshot_id=snapshot_id,
                team_export="SECRET TEAM TWO",
                team_packed="secret-packed-two",
            ),
        ),
    )
    now = datetime.now(UTC)
    payload = presentation_archive(
        MatchArchive(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            status=MatchStatus.CREATED,
            config=config,
            engine="pokemon-showdown",
        )
    )
    serialized = str(payload)
    assert "SECRET TEAM" not in serialized
    assert "secret-packed" not in serialized
    assert str(snapshot_id) not in serialized
