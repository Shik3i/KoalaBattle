from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from koalabattle.core.models import (
    AgentType,
    GenericMatchResult,
    GenericResultStatus,
    MatchConfig,
    PlayerConfig,
    Side,
)
from koalabattle.storage import BattleRepository, Database
from koalabattle.tournaments.domain import round_robin_series, single_elimination_series
from koalabattle.tournaments.models import (
    AgentPresetSnapshot,
    CreateTournament,
    MatchTemplateSnapshot,
    TournamentFormat,
    TournamentParticipant,
    TournamentParticipantDraft,
    TournamentStatus,
)
from koalabattle.tournaments.repository import TournamentRepository


def _participants(count: int) -> tuple[TournamentParticipantDraft, ...]:
    return tuple(
        TournamentParticipantDraft(
            display_name=f"Generic {index}",
            seed=index,
            agent=AgentPresetSnapshot(agent_type=AgentType.RANDOM),
        )
        for index in range(1, count + 1)
    )


def _stored_participants(count: int) -> tuple[TournamentParticipant, ...]:
    tournament_id = uuid4()
    return tuple(
        TournamentParticipant(
            id=uuid4(),
            tournament_id=tournament_id,
            display_name=f"Generic {index}",
            seed=index,
            agent=AgentPresetSnapshot(agent_type=AgentType.RANDOM),
        )
        for index in range(1, count + 1)
    )


def _create_payload(
    format: TournamentFormat,
    *,
    count: int = 4,
    best_of: int = 1,
) -> CreateTournament:
    return CreateTournament(
        name=f"Generic {format.value}",
        format=format,
        best_of=best_of,
        max_concurrent_matches=2,
        match_template=MatchTemplateSnapshot(engine="generic-test"),
        participants=_participants(count),
    )


@pytest.mark.parametrize("count", [2, 3, 4, 5, 6])
def test_generic_brackets_are_deterministic_and_persist_byes(count: int) -> None:
    participants = _stored_participants(count)
    first = single_elimination_series(participants)
    second = single_elimination_series(participants)
    assert [
        (item.round_number, item.bracket_position, item.participant_a_id, item.participant_b_id)
        for item in first
    ] == [
        (item.round_number, item.bracket_position, item.participant_a_id, item.participant_b_id)
        for item in second
    ]
    bracket_size = 1 << (count - 1).bit_length()
    assert len(first) == bracket_size - 1
    assert sum(item.winner_participant_id is not None for item in first) == bracket_size - count
    assert len(round_robin_series(participants)) == count * (count - 1) // 2


async def _record_game(
    battle_repository: BattleRepository,
    tournaments: TournamentRepository,
    series_id: UUID,
    winner: UUID | None,
) -> UUID:
    tournament_id, _, participant_a, participant_b, game = await tournaments.series_execution(
        series_id
    )
    config = MatchConfig(
        name=f"Generic game {game}",
        players=(
            PlayerConfig(
                side=Side.P1,
                display_name=participant_a.display_name,
                agent_type=AgentType.RANDOM,
            ),
            PlayerConfig(
                side=Side.P2,
                display_name=participant_b.display_name,
                agent_type=AgentType.RANDOM,
            ),
        ),
    )
    match_id = uuid4()
    await battle_repository.create_match(
        match_id,
        config,
        engine="generic-test",
        engine_version="1",
        showdown_version=None,
        poke_env_version=None,
        tournament_id=tournament_id,
        series_id=series_id,
    )
    result = (
        GenericMatchResult(status=GenericResultStatus.COMPLETED, winner_participant_id=winner)
        if winner
        else GenericMatchResult(status=GenericResultStatus.DRAW, draw=True)
    )
    await tournaments.record_match_result(match_id, result)
    return match_id


@pytest.mark.asyncio
async def test_single_elimination_best_of_three_advances_from_generic_results(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'elimination.db'}")
    await database.create_schema()
    tournaments = TournamentRepository(database)
    battles = BattleRepository(database)
    created = await tournaments.create(
        _create_payload(TournamentFormat.SINGLE_ELIMINATION, best_of=3)
    )
    await tournaments.start(created.id)
    assert len(await tournaments.ready_series(created.id)) == 2

    while True:
        archive = await tournaments.get(created.id)
        assert archive is not None
        if archive.status is TournamentStatus.COMPLETED:
            break
        ready = await tournaments.ready_series(created.id)
        assert ready
        for series_id in ready:
            _, _, participant_a, _, _ = await tournaments.series_execution(series_id)
            await _record_game(battles, tournaments, series_id, participant_a.id)
            await _record_game(battles, tournaments, series_id, participant_a.id)

    assert archive.winner_participant_id is not None
    assert archive.statistics.series_played == 3
    assert archive.statistics.matches_played == 0
    reopened = TournamentRepository(database)
    persisted = await reopened.get(created.id)
    assert persisted is not None and persisted.series == archive.series
    await database.close()


@pytest.mark.asyncio
async def test_round_robin_schedule_draws_and_standings_are_generic(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'round-robin.db'}")
    await database.create_schema()
    tournaments = TournamentRepository(database)
    battles = BattleRepository(database)
    created = await tournaments.create(_create_payload(TournamentFormat.ROUND_ROBIN))
    await tournaments.start(created.id)
    ready = await tournaments.ready_series(created.id)
    assert len(ready) == 6
    for index, series_id in enumerate(ready):
        _, _, participant_a, _, _ = await tournaments.series_execution(series_id)
        await _record_game(
            battles,
            tournaments,
            series_id,
            None if index == 0 else participant_a.id,
        )
    archive = await tournaments.get(created.id)
    assert archive is not None and archive.status is TournamentStatus.COMPLETED
    assert sum(item.played for item in archive.standings) == 12
    assert sum(item.draws for item in archive.standings) == 2
    assert sum(item.wins for item in archive.standings) == 5
    await database.close()


@pytest.mark.asyncio
async def test_simultaneous_branch_results_advance_final_once(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    await database.create_schema()
    tournaments = TournamentRepository(database)
    battles = BattleRepository(database)
    created = await tournaments.create(_create_payload(TournamentFormat.SINGLE_ELIMINATION))
    await tournaments.start(created.id)
    branches = await tournaments.ready_series(created.id)
    assert len(branches) == 2
    executions = await asyncio.gather(
        *(tournaments.series_execution(series_id) for series_id in branches)
    )
    await asyncio.gather(
        *(
            _record_game(battles, tournaments, series_id, execution[2].id)
            for series_id, execution in zip(branches, executions, strict=True)
        )
    )
    archive = await tournaments.get(created.id)
    assert archive is not None
    finals = [item for item in archive.series if item.round_number == 2]
    assert len(finals) == 1
    assert finals[0].status.value == "ready"
    assert finals[0].participant_a_id is not None
    assert finals[0].participant_b_id is not None
    assert len(await tournaments.ready_series(created.id)) == 1
    await database.close()
