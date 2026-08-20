from __future__ import annotations

from dataclasses import dataclass

from koalabattle.core.models import MatchArchive, Side


@dataclass(frozen=True)
class PostMatchInterview:
    side: Side
    text: str


def _side(value: object) -> Side | None:
    text = str(value or "")
    if text.startswith("p1"):
        return Side.P1
    if text.startswith("p2"):
        return Side.P2
    return None


def _target_side(event_payload: dict[str, object]) -> Side | None:
    return _side(event_payload.get("target")) or _side(event_payload.get("pokemon"))


def _actor_side(event_payload: dict[str, object]) -> Side | None:
    return _side(event_payload.get("side")) or _side(event_payload.get("actor"))


def build_post_match_interviews(archive: MatchArchive) -> tuple[PostMatchInterview, ...]:
    """Create short, evidence-backed player reflections without another model request."""

    interviews: list[PostMatchInterview] = []
    for side in (Side.P1, Side.P2):
        decisions = [record for record in archive.decisions if record.decision.side is side]
        pressure = 0
        knockouts = 0
        own_knockouts = 0
        switches = 0
        criticals = 0
        for event in archive.events:
            target = _target_side(event.payload)
            actor = _actor_side(event.payload)
            if event.event_type == "damage" and target is not None and target is not side:
                pressure += 1
            elif event.event_type == "pokemon_fainted":
                if target is not None and target is not side:
                    knockouts += 1
                elif target is side:
                    own_knockouts += 1
            elif event.event_type == "pokemon_switched" and actor is side:
                switches += 1
            elif event.event_type == "critical_hit" and target is not None and target is not side:
                criticals += 1

        won = archive.winner is side
        outcome = "I closed out the win" if won else "I kept the game competitive"
        worked = (
            f"I created {pressure} damaging openings and converted {knockouts} knockout(s)"
            if pressure or knockouts
            else "I kept the early plan stable"
        )
        if criticals:
            worked += f", including {criticals} critical hit(s)"
        weak = (
            f"I gave up {own_knockouts} knockout(s) and had to switch {switches} time(s)"
            if own_knockouts or switches
            else "I did not create enough decisive pressure"
        )
        change = (
            "Next time I would commit to the strongest line one turn earlier."
            if decisions
            else "Next time I would prepare a clearer opening plan."
        )
        text = (
            f"Post-match interview. What worked? {outcome}: {worked}. "
            f"What was weak? {weak}. What would I change? {change}"
        )
        interviews.append(PostMatchInterview(side=side, text=text))
    return tuple(interviews)
