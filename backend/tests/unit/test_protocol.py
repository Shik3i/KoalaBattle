from __future__ import annotations

from koalabattle.events import normalize_showdown_message


def test_normalizes_known_showdown_messages() -> None:
    assert normalize_showdown_message(["", "turn", "7"]) == (
        "turn_started",
        {"raw": "|turn|7", "command": "turn", "turn": 7},
    )
    event_type, payload = normalize_showdown_message(
        ["", "move", "p1a: Pikachu", "Thunderbolt", "p2a: Snorlax"]
    ) or (None, {})
    assert event_type == "move_used"
    assert payload["move"] == "Thunderbolt"

    _, missed = normalize_showdown_message(["", "-miss", "p1a: Pikachu", "p2a: Snorlax"]) or (
        None,
        {},
    )
    assert missed == {
        "raw": "|-miss|p1a: Pikachu|p2a: Snorlax",
        "command": "-miss",
        "actor": "p1a: Pikachu",
        "target": "p2a: Snorlax",
    }

    _, critical = normalize_showdown_message(["", "-crit", "p2a: Snorlax"]) or (
        None,
        {},
    )
    assert critical["target"] == "p2a: Snorlax"


def test_preserves_unknown_showdown_message_as_untrusted_raw_data() -> None:
    event_type, payload = normalize_showdown_message(["", "future-command", "value"]) or (
        None,
        {},
    )
    assert event_type == "showdown_message"
    assert payload["raw"] == "|future-command|value"


def test_normalizes_effectiveness_and_field_visual_events() -> None:
    effective = normalize_showdown_message(["", "-supereffective", "p2a: Target"])
    terrain = normalize_showdown_message(["", "-fieldstart", "move: Electric Terrain"])
    barrier = normalize_showdown_message(["", "-sidestart", "p1: Alpha", "Reflect"])
    assert effective == (
        "super_effective",
        {
            "raw": "|-supereffective|p2a: Target",
            "command": "-supereffective",
            "target": "p2a: Target",
        },
    )
    assert terrain is not None and terrain[0] == "terrain_started"
    assert terrain[1]["field"] == "move: Electric Terrain"
    assert barrier is not None and barrier[0] == "side_condition_started"
    assert barrier[1]["condition"] == "Reflect"
