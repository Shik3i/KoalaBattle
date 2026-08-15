from __future__ import annotations

from typing import Any

_EVENT_NAMES = {
    "turn": "turn_started",
    "switch": "pokemon_switched",
    "drag": "pokemon_switched",
    "move": "move_used",
    "-miss": "move_missed",
    "-damage": "damage",
    "-heal": "healing",
    "-crit": "critical_hit",
    "-status": "status_applied",
    "-curestatus": "status_removed",
    "-weather": "weather_changed",
    "faint": "pokemon_fainted",
    "win": "battle_finished",
    "tie": "battle_finished",
    "start": "battle_started",
    "teampreview": "team_preview",
}


def normalize_showdown_message(parts: list[str]) -> tuple[str, dict[str, Any]] | None:
    """Normalize one split Showdown protocol line without exposing poke-env objects."""
    if len(parts) < 2 or not parts[1]:
        return None
    command = parts[1]
    event_type = _EVENT_NAMES.get(command, "showdown_message")
    payload: dict[str, Any] = {"raw": "|".join(parts), "command": command}

    if command == "turn" and len(parts) > 2:
        payload["turn"] = int(parts[2])
    elif command in {"switch", "drag"} and len(parts) > 4:
        payload.update(actor=parts[2], details=parts[3], hp=parts[4])
    elif command == "move" and len(parts) > 4:
        payload.update(actor=parts[2], move=parts[3], target=parts[4])
    elif command == "-miss" and len(parts) > 2:
        payload["actor"] = parts[2]
        if len(parts) > 3:
            payload["target"] = parts[3]
    elif command in {"-damage", "-heal"} and len(parts) > 3:
        payload.update(target=parts[2], hp=parts[3])
    elif command == "-crit" and len(parts) > 2:
        payload["target"] = parts[2]
    elif command in {"-status", "-curestatus"} and len(parts) > 3:
        payload.update(target=parts[2], status=parts[3])
    elif command == "-weather" and len(parts) > 2:
        payload["weather"] = parts[2]
    elif command == "faint" and len(parts) > 2:
        payload["target"] = parts[2]
    elif command == "win" and len(parts) > 2:
        payload["winner_name"] = parts[2]
    elif command == "tie":
        payload["winner_name"] = None
    return event_type, payload
