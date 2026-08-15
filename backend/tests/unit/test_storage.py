from __future__ import annotations

from uuid import uuid4

import pytest

from koalabattle.agents import RandomAgent
from koalabattle.core.models import (
    AgentRequest,
    BattleEvent,
    MatchConfig,
    ProviderErrorCategory,
    RetryAttempt,
)
from koalabattle.replay import ReplayCursor
from koalabattle.storage import BattleRepository, Database


@pytest.mark.asyncio
async def test_archive_preserves_event_order_and_complete_decision(
    tmp_path, match_config: MatchConfig, agent_request: AgentRequest
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'archive.db'}")
    await database.create_schema()
    repository = BattleRepository(database)
    match_id = agent_request.match_id
    await repository.create_match(
        match_id,
        match_config,
        engine="test-engine",
        engine_version="1",
        showdown_version="test-sha",
        poke_env_version="0.15.0",
    )
    second = await repository.append_event(
        BattleEvent(
            match_id=match_id,
            sequence=99,
            turn=1,
            event_type="state_snapshot",
            payload={"state": agent_request.state.model_dump(mode="json")},
        )
    )
    first = await repository.append_event(
        BattleEvent(match_id=match_id, sequence=1, turn=1, event_type="move_used")
    )
    assert (second.sequence, first.sequence) == (1, 2)

    decision = await RandomAgent(2).decide(agent_request)
    decision = decision.model_copy(
        update={
            "retry_attempts": (
                RetryAttempt(
                    attempt=1,
                    category=ProviderErrorCategory.INVALID_RESPONSE,
                    detail="test repair",
                ),
            )
        }
    )
    await repository.record_decision(agent_request, decision)
    archive = await repository.get_match(match_id)
    assert archive is not None
    assert [event.sequence for event in archive.events] == [1, 2]
    assert archive.decisions[0].request == agent_request
    assert archive.decisions[0].decision == decision
    assert ReplayCursor(archive.events).advance_event().state == agent_request.state
    summaries = await repository.list_matches()
    assert summaries[0].id == match_id
    assert not hasattr(summaries[0], "events")
    await database.close()


@pytest.mark.asyncio
async def test_archive_survives_database_reopen(tmp_path, match_config: MatchConfig) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'persistent.db'}"
    match_id = uuid4()
    database = Database(url)
    await database.create_schema()
    await BattleRepository(database).create_match(
        match_id,
        match_config,
        engine="test-engine",
        engine_version="1",
        showdown_version="sha",
        poke_env_version="0.15.0",
    )
    await database.close()
    reopened = Database(url)
    assert await BattleRepository(reopened).get_match(match_id) is not None
    await reopened.close()
