from __future__ import annotations

from koalabattle.core.models import BattleEvent, BattleState
from koalabattle.replay import ReplayCursor


def test_replay_advances_from_recorded_events_only(state: BattleState) -> None:
    events = (
        BattleEvent(
            match_id=state.match_id,
            sequence=1,
            turn=0,
            event_type="battle_started",
        ),
        BattleEvent(
            match_id=state.match_id,
            sequence=2,
            turn=state.turn,
            event_type="state_snapshot",
            payload={"state": state.model_dump(mode="json")},
        ),
    )
    cursor = ReplayCursor(events).advance_turn()
    assert cursor.index == 1
    cursor = cursor.advance_event()
    assert cursor.state == state
    assert cursor.reset().state is None


def test_replay_speed_is_bounded() -> None:
    cursor = ReplayCursor(())
    assert cursor.with_speed(4).speed == 4
