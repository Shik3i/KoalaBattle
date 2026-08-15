from __future__ import annotations

from dataclasses import dataclass, replace

from koalabattle.core.models import BattleEvent, BattleState


def apply_event(state: BattleState | None, event: BattleEvent) -> BattleState | None:
    """Pure replay reducer. It never invokes Showdown or an agent."""
    if event.event_type == "state_snapshot":
        return BattleState.model_validate(event.payload["state"])
    return state


@dataclass(frozen=True, slots=True)
class ReplayCursor:
    events: tuple[BattleEvent, ...]
    index: int = 0
    state: BattleState | None = None
    playing: bool = False
    speed: float = 1.0

    def reset(self) -> ReplayCursor:
        return replace(self, index=0, state=None, playing=False)

    def advance_event(self) -> ReplayCursor:
        if self.index >= len(self.events):
            return replace(self, playing=False)
        event = self.events[self.index]
        return replace(
            self,
            index=self.index + 1,
            state=apply_event(self.state, event),
            playing=self.playing and self.index + 1 < len(self.events),
        )

    def advance_turn(self) -> ReplayCursor:
        if self.index >= len(self.events):
            return replace(self, playing=False)
        starting_turn = self.events[self.index].turn
        cursor = self
        while cursor.index < len(cursor.events):
            cursor = cursor.advance_event()
            if (
                cursor.index < len(cursor.events)
                and cursor.events[cursor.index].turn > starting_turn
            ):
                break
        return cursor

    def with_speed(self, speed: float) -> ReplayCursor:
        if not 0.25 <= speed <= 4:
            raise ValueError("replay speed must be between 0.25 and 4")
        return replace(self, speed=speed)
