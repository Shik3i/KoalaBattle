from __future__ import annotations

from types import SimpleNamespace

import pytest
from poke_env.battle import Pokemon
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from koalabattle.engines.showdown.engine import (
    DecisionSubmissionGuard,
    NoProgressBattleError,
    _doubles_order_power,
    _viable_doubles_order,
    reconcile_duplicate_request_identities,
)


def test_same_authoritative_request_cannot_schedule_two_pending_decisions() -> None:
    guard = DecisionSubmissionGuard()

    assert guard.begin("battle:7", "turn-7-active-a") is True
    guard.register_submission("switch:2")

    assert guard.begin("battle:7", "turn-7-active-a") is False
    assert guard.pending_action == "switch:2"


def test_rejected_switch_retries_once_with_a_different_legal_action() -> None:
    guard = DecisionSubmissionGuard()
    guard.begin("battle:7", "turn-7-active-a")
    guard.register_submission("switch:2")

    assert guard.reject_pending() == "switch:2"
    assert guard.begin("battle:7", "turn-7-active-a") is True
    assert guard.rejected_actions == {"switch:2"}

    guard.register_submission("switch:1")
    assert guard.pending_action == "switch:1"


def test_no_progress_guard_stops_the_third_identical_submission() -> None:
    guard = DecisionSubmissionGuard()
    guard.begin("battle:7", "turn-7-active-a")
    guard.register_submission("switch:2")
    guard.register_submission("switch:2")

    with pytest.raises(NoProgressBattleError, match="no authoritative progress"):
        guard.register_submission("switch:2")


def test_authoritative_next_request_clears_forced_switch_retry_state() -> None:
    guard = DecisionSubmissionGuard()
    guard.begin("battle:7", "turn-7-fainted-active")
    guard.register_submission("switch:2")
    guard.reject_pending()

    assert guard.begin("battle:8", "turn-7-replacement-active") is True
    assert guard.is_current("battle:8")
    assert not guard.is_current("battle:7")
    assert guard.pending_action is None
    assert guard.rejected_actions == set()
    assert guard.submission_counts == {}


def test_doubles_orders_cannot_target_a_fainted_field_slot() -> None:
    alive = SimpleNamespace(fainted=False)
    fainted = SimpleNamespace(fainted=True)
    battle = SimpleNamespace(
        active_pokemon=[alive, fainted], opponent_active_pokemon=[alive, fainted]
    )
    shadow_ball = SimpleNamespace(base_power=80)
    invalid_ally = DoubleBattleOrder(
        first_order=SingleBattleOrder(shadow_ball, move_target=-2)
    )
    invalid_opponent = DoubleBattleOrder(
        first_order=SingleBattleOrder(shadow_ball, move_target=2)
    )
    valid_opponent = DoubleBattleOrder(
        first_order=SingleBattleOrder(shadow_ball, move_target=1)
    )

    assert not _viable_doubles_order(battle, invalid_ally)  # type: ignore[arg-type]
    assert not _viable_doubles_order(battle, invalid_opponent)  # type: ignore[arg-type]
    assert _viable_doubles_order(battle, valid_opponent)  # type: ignore[arg-type]


def test_doubles_power_prefers_an_opponent_over_an_alive_ally() -> None:
    shadow_ball = SimpleNamespace(base_power=80)
    ally_target = DoubleBattleOrder(
        first_order=SingleBattleOrder(shadow_ball, move_target=-2)
    )
    opponent_target = DoubleBattleOrder(
        first_order=SingleBattleOrder(shadow_ball, move_target=1)
    )

    assert _doubles_order_power(opponent_target) > _doubles_order_power(ally_target)


def test_duplicate_request_identities_get_distinct_pokemon_objects() -> None:
    original = Pokemon(species="Koffing", name="Koffing", gen=9)
    muk = Pokemon(species="Muk", name="Muk", gen=9)

    class FakeBattle:
        gen = 9
        _team = {"p2: Koffing": original, "p2: Muk": muk}

    request = {
        "side": {
            "pokemon": [
                {
                    "ident": "p2: Koffing 1",
                    "details": "Koffing, L70",
                    "condition": "157/157",
                    "active": True,
                    "stats": {},
                    "moves": ["tackle"],
                    "baseAbility": "levitate",
                    "item": "",
                    "pokeball": "pokeball",
                    "ability": "levitate",
                },
                {
                    "ident": "p2: Koffing 2",
                    "details": "Koffing, L70",
                    "condition": "157/157",
                    "active": False,
                    "stats": {},
                    "moves": ["smog"],
                    "baseAbility": "levitate",
                    "item": "",
                    "pokeball": "pokeball",
                    "ability": "levitate",
                },
            ]
        }
    }

    reconcile_duplicate_request_identities(FakeBattle(), request)  # type: ignore[arg-type]

    assert set(FakeBattle._team) == {"p2: Koffing 1", "p2: Koffing 2", "p2: Muk"}
    assert FakeBattle._team["p2: Koffing 1"] is not FakeBattle._team["p2: Koffing 2"]
    assert FakeBattle._team["p2: Muk"] is muk
