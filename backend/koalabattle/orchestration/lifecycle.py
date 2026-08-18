from __future__ import annotations

from koalabattle.core.models import MatchStatus

TERMINAL_MATCH_STATUSES = frozenset(
    {MatchStatus.COMPLETED, MatchStatus.CANCELLED, MatchStatus.FAILED, MatchStatus.INTERRUPTED}
)
ACTIVE_MATCH_STATUSES = frozenset(
    {MatchStatus.STARTING, MatchStatus.RUNNING, MatchStatus.WAITING, MatchStatus.PAUSED}
)

_TRANSITIONS: dict[MatchStatus, frozenset[MatchStatus]] = {
    MatchStatus.CREATED: frozenset({MatchStatus.QUEUED, MatchStatus.CANCELLED}),
    MatchStatus.QUEUED: frozenset(
        {MatchStatus.STARTING, MatchStatus.CANCELLED, MatchStatus.INTERRUPTED}
    ),
    MatchStatus.STARTING: frozenset(
        {MatchStatus.RUNNING, MatchStatus.FAILED, MatchStatus.CANCELLED, MatchStatus.INTERRUPTED}
    ),
    MatchStatus.RUNNING: frozenset(
        {
            MatchStatus.WAITING,
            MatchStatus.PAUSED,
            MatchStatus.COMPLETED,
            MatchStatus.FAILED,
            MatchStatus.CANCELLED,
            MatchStatus.INTERRUPTED,
        }
    ),
    MatchStatus.WAITING: frozenset(
        {
            MatchStatus.RUNNING,
            MatchStatus.PAUSED,
            MatchStatus.FAILED,
            MatchStatus.CANCELLED,
            MatchStatus.INTERRUPTED,
        }
    ),
    MatchStatus.PAUSED: frozenset(
        {
            MatchStatus.RUNNING,
            MatchStatus.WAITING,
            MatchStatus.CANCELLED,
            MatchStatus.INTERRUPTED,
        }
    ),
    MatchStatus.COMPLETED: frozenset(),
    MatchStatus.CANCELLED: frozenset({MatchStatus.QUEUED}),
    MatchStatus.FAILED: frozenset({MatchStatus.QUEUED}),
    MatchStatus.INTERRUPTED: frozenset({MatchStatus.QUEUED}),
}


def validate_transition(current: MatchStatus, target: MatchStatus) -> None:
    if current is target:
        return
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"invalid match lifecycle transition: {current.value} -> {target.value}")
