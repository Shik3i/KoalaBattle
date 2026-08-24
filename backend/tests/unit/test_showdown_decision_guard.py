from __future__ import annotations

from types import SimpleNamespace

import pytest
from poke_env.battle import Move, Pokemon
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from koalabattle.engines.showdown.engine import (
    DecisionSubmissionGuard,
    NoProgressBattleError,
    _doubles_order_power,
    _explicit_target_siblings,
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
    assert guard.ambiguous_moves == set()
    assert guard.submission_counts == {}


def test_needs_a_target_error_marks_the_move_ambiguous_by_id() -> None:
    guard = DecisionSubmissionGuard()
    guard.begin("battle:7", "turn-7-active-a")
    guard.register_submission("/choose move outrage, move gigadrain 1")

    guard.reject_pending("[Invalid choice] Can't move: Outrage needs a target")

    assert guard.ambiguous_moves == {"outrage"}


def test_unrelated_rejection_errors_do_not_mark_any_move_ambiguous() -> None:
    guard = DecisionSubmissionGuard()
    guard.begin("battle:7", "turn-7-active-a")
    guard.register_submission("/choose move gigadrain 1")

    guard.reject_pending("[Invalid choice] Can't move: Giga Drain is disabled")

    assert guard.ambiguous_moves == set()


def test_ambiguous_moves_reset_on_the_next_authoritative_request() -> None:
    guard = DecisionSubmissionGuard()
    guard.begin("battle:7", "turn-7-active-a")
    guard.register_submission("/choose move outrage, move gigadrain 1")
    guard.reject_pending("[Invalid choice] Can't move: Outrage needs a target")

    assert guard.begin("battle:8", "turn-8-active-a") is True
    assert guard.ambiguous_moves == set()


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


def test_explicit_target_siblings_added_for_random_normal_moves_with_two_live_foes() -> None:
    """Root cause of the reported bug: poke-env only ever offers Outrage (a
    Target.RANDOM_NORMAL move) with an implicit move_target=0, because Showdown
    normally auto-picks a target for it. But a *continuing* Outrage whose
    original locked target has since switched out demands an explicit target
    and rejects the implicit one ("Outrage needs a target"). Without an explicit-
    target sibling in the candidate pool, the rejected_actions filter has
    nothing else to fall back to for that move at all."""
    alive = SimpleNamespace(fainted=False)
    battle = SimpleNamespace(active_pokemon=[alive, alive], opponent_active_pokemon=[alive, alive])
    outrage = Move("outrage", gen=9)
    tackle = Move("tackle", gen=9)
    implicit_outrage = SingleBattleOrder(outrage, move_target=0)
    explicit_tackle = SingleBattleOrder(tackle, move_target=1)

    expanded = _explicit_target_siblings([[implicit_outrage], [explicit_tackle]], battle)  # type: ignore[arg-type]

    assert {order.move_target for order in expanded[0]} == {0, 1, 2}
    assert all(order.order is outrage for order in expanded[0])
    # A move that already carries an explicit target is left untouched.
    assert expanded[1] == [explicit_tackle]


def test_explicit_target_siblings_drops_the_implicit_form_once_flagged_ambiguous() -> None:
    """Once Showdown has rejected the implicit form this request, it must never be
    recomputed - otherwise max()'s tie-breaking (many implicit-Outrage-plus-some-
    other-move combos vs. only two explicit-target siblings) keeps preferring the
    already-rejected implicit form under a different guise every retry, which is
    exactly the bug this whole mechanism exists to prevent."""
    alive = SimpleNamespace(fainted=False)
    battle = SimpleNamespace(active_pokemon=[alive, alive], opponent_active_pokemon=[alive, alive])
    outrage = Move("outrage", gen=9)
    implicit_outrage = SingleBattleOrder(outrage, move_target=0)

    expanded = _explicit_target_siblings(
        [[implicit_outrage], []], battle, frozenset({"outrage"})
    )  # type: ignore[arg-type]

    assert {order.move_target for order in expanded[0]} == {1, 2}


def test_explicit_target_siblings_skipped_with_only_one_live_foe() -> None:
    alive = SimpleNamespace(fainted=False)
    fainted = SimpleNamespace(fainted=True)
    battle = SimpleNamespace(
        active_pokemon=[alive, alive], opponent_active_pokemon=[alive, fainted]
    )
    per_slot = [[SingleBattleOrder(Move("outrage", gen=9), move_target=0)], []]

    assert _explicit_target_siblings(per_slot, battle) == per_slot  # type: ignore[arg-type]


def test_doubles_rejected_order_is_excluded_from_the_next_selection() -> None:
    """Reproduces the reported bug: Showdown rejects the computed "best" doubles
    order (e.g. an illegal Outrage/Giga Drain pairing), and the engine must adapt
    instead of recomputing the identical order every retry until the no-progress
    guard forfeits the match. This mirrors the singles path's rejected_actions
    filter, which the doubles branch was missing entirely."""
    outrage = Move("outrage", gen=9)
    giga_drain = Move("gigadrain", gen=9)
    tackle = Move("tackle", gen=9)

    best_order = DoubleBattleOrder(
        first_order=SingleBattleOrder(outrage, move_target=0),
        second_order=SingleBattleOrder(giga_drain, move_target=1),
    )
    fallback_order = DoubleBattleOrder(
        first_order=SingleBattleOrder(tackle, move_target=1),
        second_order=SingleBattleOrder(giga_drain, move_target=1),
    )
    orders = [best_order, fallback_order]

    guard = DecisionSubmissionGuard()
    guard.begin("battle:7", "turn-7-active-a")
    guard.register_submission(best_order.message)
    guard.reject_pending()
    guard.begin("battle:7", "turn-7-active-a")

    assert max(orders, key=_doubles_order_power) is best_order

    remaining = [order for order in orders if order.message not in guard.rejected_actions]

    assert remaining == [fallback_order]
    assert max(remaining, key=_doubles_order_power) is fallback_order


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
