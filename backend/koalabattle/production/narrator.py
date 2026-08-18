from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from koalabattle.core.models import BattleEvent

from .models import NarratorMode, NarratorProfile, NarratorSettings


@dataclass(frozen=True)
class NarratorCandidate:
    rule_id: str
    text: str
    priority: int
    duration_ms: int
    event_sequence: int


_HIGHLIGHT_EVENTS: Final = {
    "battle_started",
    "battle_finished",
    "critical_hit",
    "super_effective",
    "resisted",
    "immune",
    "status_applied",
    "pokemon_fainted",
}

NARRATOR_PROFILES: Final = (
    NarratorProfile(
        id="stadium-broadcast-v1",
        display_name="Stadium Broadcast",
        description="Short, energetic highlight calls for the whole match.",
        recommended_mode=NarratorMode.HIGHLIGHTS,
        recommended_cooldown_ms=2_800,
        recommended_max_lines_per_match=24,
    ),
    NarratorProfile(
        id="battle-revolution-v1",
        display_name="Colosseum Broadcast",
        description="More arena framing and momentum commentary between highlights.",
        recommended_mode=NarratorMode.BROADCAST,
        recommended_cooldown_ms=2_400,
        recommended_max_lines_per_match=32,
    ),
    NarratorProfile(
        id="minimal-highlights-v1",
        display_name="Minimal Highlights",
        description="Only decisive swings, critical hits, status and knockouts.",
        recommended_mode=NarratorMode.HIGHLIGHTS,
        recommended_cooldown_ms=3_500,
        recommended_max_lines_per_match=12,
    ),
)
_NARRATOR_PROFILE_BY_ID: Final = {profile.id: profile for profile in NARRATOR_PROFILES}


def narrator_profiles() -> tuple[NarratorProfile, ...]:
    return NARRATOR_PROFILES


def _effective_settings(settings: NarratorSettings) -> NarratorSettings:
    """Apply profile recommendations without overwriting explicit custom values."""

    profile = _NARRATOR_PROFILE_BY_ID.get(settings.profile_id)
    if profile is None:
        return settings
    defaults = NarratorSettings()
    updates: dict[str, object] = {}
    if settings.mode is defaults.mode:
        updates["mode"] = profile.recommended_mode
    if settings.cooldown_ms == defaults.cooldown_ms:
        updates["cooldown_ms"] = profile.recommended_cooldown_ms
    if settings.max_lines_per_match == defaults.max_lines_per_match:
        updates["max_lines_per_match"] = profile.recommended_max_lines_per_match
    return settings.model_copy(update=updates)


def _event_time(event: BattleEvent) -> int:
    return event.logical_offset_ms if event.logical_offset_ms > 0 else event.sequence * 1_000


def _clean_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.split(":", 1)[-1].strip()
    return value.split(",", 1)[0].strip()


def _pokemon(event: BattleEvent) -> str:
    payload = event.payload
    return _clean_name(payload.get("pokemon") or payload.get("actor") or payload.get("target"))


def _hp_fraction(event: BattleEvent) -> float | None:
    raw = event.payload.get("hp_fraction")
    if isinstance(raw, int | float):
        return max(0.0, min(1.0, float(raw)))
    raw = event.payload.get("hp")
    if not isinstance(raw, str) or "/" not in raw:
        return None
    current, maximum = raw.split("/", 1)
    try:
        numerator = float(current)
        denominator = float(maximum)
    except ValueError:
        return None
    return numerator / denominator if denominator > 0 else None


def _has_nearby(events: tuple[BattleEvent, ...], index: int, event_type: str) -> bool:
    sequence = events[index].sequence
    return any(
        abs(candidate.sequence - sequence) <= 4 and candidate.event_type == event_type
        for candidate in events[index + 1 : index + 5]
    )


def _switch_count(events: tuple[BattleEvent, ...], current: BattleEvent) -> int:
    minimum_turn = max(0, current.turn - 3)
    return sum(
        1
        for event in events
        if event.event_type == "pokemon_switched" and event.turn >= minimum_turn
    )


def _candidate(
    events: tuple[BattleEvent, ...], index: int, settings: NarratorSettings
) -> tuple[str, str, int] | None:
    event = events[index]
    event_type = event.event_type
    name = _pokemon(event)
    move = str(event.payload.get("move") or "")
    status = str(event.payload.get("status") or "the status condition")
    winner = str(event.payload.get("winner_name") or "")

    if event_type == "battle_started":
        return "battle-start", "The battle is underway!", 60
    if event_type == "battle_finished":
        if winner:
            return "battle-finished", f"The battle is decided — {winner} takes the victory!", 120
        return "battle-finished", "The battle ends in a draw!", 120
    if event_type == "critical_hit":
        if _has_nearby(events, index, "super_effective"):
            return (
                "critical-hit-super-effective",
                "A devastating critical hit — and it found the weakness!",
                110,
            )
        return "critical-hit", "A pinpoint strike — right on target!", 100
    if event_type == "pokemon_fainted":
        if index > 0 and events[index - 1].event_type in {"damage", "critical_hit"}:
            return "one-hit-knockout", "Taken down in a single blow!", 110
        return "pokemon-fainted", "That Pokémon can battle no longer!", 95
    if event_type == "super_effective":
        return "super-effective", "That hit found a weakness!", 90
    if event_type == "immune":
        return "immune", "The typing shuts it down completely!", 85
    if event_type == "resisted":
        return "resisted", "That attack made almost no impression!", 75
    if event_type == "status_applied":
        return "status-applied", f"{status.capitalize()} could decide this battle!", 80
    if event_type == "move_missed":
        return "move-missed", "It fails to connect!", 65
    if event_type == "pokemon_switched":
        if _switch_count(events, event) >= 3:
            return "switch-streak", "Both trainers are searching for the right opening.", 70
        switched_name = name if settings.include_pokemon_names else "A fresh Pokémon"
        return "pokemon-switched", f"{switched_name or 'A fresh Pokémon'} takes the field!", 48
    hp_fraction = _hp_fraction(event)
    if event_type == "damage" and hp_fraction is not None and hp_fraction <= 0.25:
        danger_name = name if settings.include_pokemon_names else "That Pokémon"
        return "critical-health", f"{danger_name or 'That Pokémon'} is in serious danger!", 72
    if event_type == "turn_started" and event.turn == 1:
        return "opening-turn", "Here comes the opening turn!", 50
    if event_type == "move_used":
        if move and settings.include_move_names:
            return "move-used", f"Here comes {move}!", 38
        return "move-used", "Here comes the next move!", 35
    if event_type == "damage":
        return "direct-hit", "That’s a direct hit!", 35
    return None


def build_narrator_plan(
    events: tuple[BattleEvent, ...], settings: NarratorSettings
) -> dict[int, NarratorCandidate]:
    """Create a stable, rate-limited narrator plan from public replay events."""

    settings = _effective_settings(settings)
    if not settings.enabled or settings.mode is NarratorMode.OFF:
        return {}
    plan: dict[int, NarratorCandidate] = {}
    last_emitted_at = -settings.cooldown_ms
    last_rule = ""
    events = tuple(events)
    candidates_by_turn: dict[int, list[tuple[int, NarratorCandidate]]] = {}
    for index, event in enumerate(events):
        if event.event_type not in _HIGHLIGHT_EVENTS and settings.mode is NarratorMode.HIGHLIGHTS:
            # Switching and low-HP rules are allowed to promote themselves below.
            if event.event_type not in {
                "pokemon_switched",
                "damage",
                "move_missed",
                "turn_started",
            }:
                continue
        selected = _candidate(events, index, settings)
        if selected is None:
            continue
        rule_id, text, priority = selected
        mode_floor = {
            NarratorMode.HIGHLIGHTS: settings.minimum_priority,
            NarratorMode.BROADCAST: max(35, settings.minimum_priority - 10),
            NarratorMode.FULL: 0,
            NarratorMode.OFF: 121,
        }[settings.mode]
        if priority < mode_floor:
            continue
        candidates_by_turn.setdefault(event.turn, []).append(
            (
                index,
                NarratorCandidate(
                    rule_id=rule_id,
                    text=text,
                    priority=priority,
                    duration_ms=max(900, min(4_500, len(text) * 52)),
                    event_sequence=event.sequence,
                ),
            )
        )

    selected_candidates = [
        candidate
        for turn_candidates in candidates_by_turn.values()
        for _, candidate in sorted(
            turn_candidates,
            key=lambda item: (-item[1].priority, item[0]),
        )[: settings.max_lines_per_turn]
    ]
    selected_candidates.sort(key=lambda candidate: candidate.event_sequence)
    for candidate in selected_candidates:
        event = next(event for event in events if event.sequence == candidate.event_sequence)
        timestamp = _event_time(event)
        if timestamp - last_emitted_at < settings.cooldown_ms:
            continue
        if (
            candidate.rule_id == last_rule
            and timestamp - last_emitted_at < settings.repeat_window_ms
        ):
            continue
        if len(plan) >= settings.max_lines_per_match:
            break
        plan[event.sequence] = NarratorCandidate(
            rule_id=candidate.rule_id,
            text=candidate.text,
            priority=candidate.priority,
            duration_ms=candidate.duration_ms,
            event_sequence=candidate.event_sequence,
        )
        last_emitted_at = timestamp
        last_rule = candidate.rule_id
    return plan
