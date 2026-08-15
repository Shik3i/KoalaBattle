from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from .models import SeriesStatus, TournamentParticipant


@dataclass(frozen=True, slots=True)
class SeriesSeedSpec:
    id: UUID
    round_number: int
    bracket_position: int
    queue_order: int
    status: SeriesStatus
    participant_a_id: UUID | None
    participant_b_id: UUID | None
    dependency_a_id: UUID | None = None
    dependency_b_id: UUID | None = None
    winner_participant_id: UUID | None = None


def seeded_participants(
    participants: tuple[TournamentParticipant, ...],
) -> tuple[TournamentParticipant, ...]:
    return tuple(sorted(participants, key=lambda item: (item.seed, str(item.id))))


def _bracket_size(participant_count: int) -> int:
    size = 1
    while size < participant_count:
        size *= 2
    return size


def _seed_positions(size: int) -> tuple[int, ...]:
    positions = [1, 2]
    while len(positions) < size:
        complement = len(positions) * 2 + 1
        positions = [value for seed in positions for value in (seed, complement - seed)]
    return tuple(positions[:size])


def single_elimination_series(
    participants: tuple[TournamentParticipant, ...],
) -> tuple[SeriesSeedSpec, ...]:
    ordered = seeded_participants(participants)
    size = _bracket_size(len(ordered))
    by_seed = {index + 1: participant.id for index, participant in enumerate(ordered)}
    slots = tuple(by_seed.get(seed) for seed in _seed_positions(size))
    all_rounds: list[list[SeriesSeedSpec]] = []
    queue_order = 1

    first: list[SeriesSeedSpec] = []
    for index in range(0, size, 2):
        participant_a = slots[index]
        participant_b = slots[index + 1]
        winner = (
            participant_a
            if participant_b is None
            else participant_b
            if participant_a is None
            else None
        )
        status = SeriesStatus.COMPLETED if winner else SeriesStatus.READY
        first.append(
            SeriesSeedSpec(
                id=uuid4(),
                round_number=1,
                bracket_position=index // 2 + 1,
                queue_order=queue_order,
                status=status,
                participant_a_id=participant_a,
                participant_b_id=participant_b,
                winner_participant_id=winner,
            )
        )
        queue_order += 1
    all_rounds.append(first)

    previous = first
    round_number = 2
    while len(previous) > 1:
        current: list[SeriesSeedSpec] = []
        for index in range(0, len(previous), 2):
            left = previous[index]
            right = previous[index + 1]
            participant_a = left.winner_participant_id
            participant_b = right.winner_participant_id
            status = (
                SeriesStatus.READY
                if participant_a is not None and participant_b is not None
                else SeriesStatus.BLOCKED
            )
            current.append(
                SeriesSeedSpec(
                    id=uuid4(),
                    round_number=round_number,
                    bracket_position=index // 2 + 1,
                    queue_order=queue_order,
                    status=status,
                    participant_a_id=participant_a,
                    participant_b_id=participant_b,
                    dependency_a_id=left.id,
                    dependency_b_id=right.id,
                )
            )
            queue_order += 1
        all_rounds.append(current)
        previous = current
        round_number += 1

    return tuple(series for round_items in all_rounds for series in round_items)


def round_robin_series(
    participants: tuple[TournamentParticipant, ...],
) -> tuple[SeriesSeedSpec, ...]:
    ordered: list[UUID | None] = [item.id for item in seeded_participants(participants)]
    if len(ordered) % 2:
        ordered.append(None)
    count = len(ordered)
    rounds: list[SeriesSeedSpec] = []
    queue_order = 1
    rotating = ordered[:]
    for round_index in range(count - 1):
        for position in range(count // 2):
            participant_a = rotating[position]
            participant_b = rotating[count - 1 - position]
            if participant_a is None or participant_b is None:
                continue
            rounds.append(
                SeriesSeedSpec(
                    id=uuid4(),
                    round_number=round_index + 1,
                    bracket_position=position + 1,
                    queue_order=queue_order,
                    status=SeriesStatus.READY,
                    participant_a_id=participant_a,
                    participant_b_id=participant_b,
                )
            )
            queue_order += 1
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
    return tuple(rounds)
