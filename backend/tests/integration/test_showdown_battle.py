from __future__ import annotations

import asyncio
import os

import pytest

from koalabattle.config import Settings
from koalabattle.core.models import (
    AgentType,
    MatchConfig,
    MatchLimits,
    MatchStatus,
    PlayerConfig,
    Side,
)
from koalabattle.replay import ReplayCursor
from koalabattle.service import BattleService
from koalabattle.storage import BattleRepository, Database

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("KOALABATTLE_RUN_SHOWDOWN_TEST") != "1",
    reason="set KOALABATTLE_RUN_SHOWDOWN_TEST=1 with local Showdown running",
)
@pytest.mark.asyncio
async def test_two_random_matches_use_independent_showdown_rooms(tmp_path) -> None:
    database_path = tmp_path / "showdown.db"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        showdown_websocket_url=os.getenv(
            "KOALABATTLE_SHOWDOWN_WEBSOCKET_URL",
            "ws://localhost:8000/showdown/websocket",
        ),
        asset_root=tmp_path / "assets",
    )
    database = Database(settings.database_url)
    await database.create_schema()
    repository = BattleRepository(database)
    service = BattleService(repository, settings)
    def config(index: int) -> MatchConfig:
        return MatchConfig(
            name=f"Concurrent room {index}",
            players=(
                PlayerConfig(
                    side=Side.P1,
                    display_name=f"Random {index}A",
                    agent_type=AgentType.RANDOM,
                ),
                PlayerConfig(
                    side=Side.P2,
                    display_name=f"Random {index}B",
                    agent_type=AgentType.RANDOM,
                ),
            ),
            random_seed=20260814 + index,
            limits=MatchLimits(maximum_turns=8),
        )

    created = [await service.create_match(config(index)) for index in (1, 2)]
    seen_both_running = False

    async with asyncio.timeout(90):
        while True:
            archives = [await repository.get_match(item.id) for item in created]
            assert all(archive is not None for archive in archives)
            statuses = {archive.status for archive in archives if archive is not None}
            seen_both_running |= all(
                archive is not None
                and archive.status
                in {MatchStatus.STARTING, MatchStatus.RUNNING, MatchStatus.WAITING}
                for archive in archives
            )
            if statuses <= {MatchStatus.COMPLETED, MatchStatus.FAILED}:
                break
            await asyncio.sleep(0.1)

    completed = [archive for archive in archives if archive is not None]
    assert seen_both_running
    assert len(completed) == 2
    for archive in completed:
        assert archive.status is MatchStatus.COMPLETED, archive.error
        assert archive.turns > 0
        assert archive.winner in {Side.P1, Side.P2}
        assert archive.raw_showdown_log and "|win|" in archive.raw_showdown_log
        assert len(archive.decisions) >= 2
        assert [event.sequence for event in archive.events] == list(
            range(1, len(archive.events) + 1)
        )
        assert archive.events[-1].event_type == "battle_finished"
        assert all(event.match_id == archive.id for event in archive.events)

        cursor = ReplayCursor(archive.events)
        while cursor.index < len(cursor.events):
            cursor = cursor.advance_event()
        assert cursor.state is not None
        assert cursor.state.result is not None
        assert cursor.state.result.winner == archive.winner

    await service.close()
    await database.close()

    reopened = Database(settings.database_url)
    reopened_repository = BattleRepository(reopened)
    for archive in completed:
        persisted = await reopened_repository.get_match(archive.id)
        assert persisted is not None and persisted.events == archive.events
    await reopened.close()
