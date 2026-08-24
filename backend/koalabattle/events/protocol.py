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
    "-ability": "ability_activated",
    "-item": "item_activated",
    "-enditem": "item_consumed",
    "-activate": "effect_activated",
    "-boost": "stat_changed",
    "-unboost": "stat_changed",
    "-setboost": "stat_changed",
    "-clearboost": "stat_reset",
    "-clearallboost": "stat_reset",
    "-weather": "weather_changed",
    "-supereffective": "super_effective",
    "-resisted": "resisted",
    "-immune": "immune",
    "-fieldstart": "terrain_started",
    "-fieldend": "terrain_ended",
    "-sidestart": "side_condition_started",
    "-sideend": "side_condition_ended",
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
        payload.update(
            actor=parts[2], details=parts[3], hp=parts[4], forced=command == "drag"
        )
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
    elif command == "-ability" and len(parts) > 3:
        payload.update(target=parts[2], ability=parts[3])
    elif command in {"-item", "-enditem"} and len(parts) > 3:
        payload.update(target=parts[2], item=parts[3])
    elif command == "-activate" and len(parts) > 3:
        payload.update(target=parts[2], effect=parts[3])
        if parts[3].lower().startswith("ability:"):
            event_type = "ability_activated"
            payload["ability"] = parts[3].split(":", 1)[1].strip()
        elif parts[3].lower().startswith("item:"):
            event_type = "item_activated"
            payload["item"] = parts[3].split(":", 1)[1].strip()
    elif command in {"-boost", "-unboost", "-setboost"} and len(parts) > 4:
        amount = int(parts[4])
        payload.update(
            target=parts[2],
            stat=parts[3],
            amount=-amount if command == "-unboost" else amount,
            absolute=command == "-setboost",
        )
    elif command == "-clearboost" and len(parts) > 2:
        payload["target"] = parts[2]
    elif command == "-clearallboost":
        payload["target"] = "all"
    elif command == "-weather" and len(parts) > 2:
        payload["weather"] = parts[2]
    elif command in {"-supereffective", "-resisted", "-immune"} and len(parts) > 2:
        payload["target"] = parts[2]
    elif command in {"-fieldstart", "-fieldend"} and len(parts) > 2:
        payload["field"] = parts[2]
    elif command in {"-sidestart", "-sideend"} and len(parts) > 3:
        payload.update(target=parts[2], condition=parts[3])
    elif command == "faint" and len(parts) > 2:
        payload["target"] = parts[2]
    elif command == "win" and len(parts) > 2:
        payload["winner_name"] = parts[2]
    elif command == "tie":
        payload["winner_name"] = None
    for token in parts[2:]:
        if token.startswith("[from] "):
            payload["source"] = token.removeprefix("[from] ")
        elif token.startswith("[of] "):
            payload["source_actor"] = token.removeprefix("[of] ")
        elif token == "[upkeep]":
            # Showdown repeats `|-weather|Sandstorm|[upkeep]` every turn the weather
            # merely persists. Without this marker the presentation cannot tell a
            # genuine change from the residual tick and narrates it once per turn.
            payload["upkeep"] = True
    return event_type, payload
