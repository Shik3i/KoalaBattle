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


@pytest.mark.asyncio
async def test_decision_audit_keeps_the_prompt_without_duplicating_it(
    tmp_path, match_config: MatchConfig, agent_request: AgentRequest
) -> None:
    """`request_json` already carries the state, the legal actions and the rendered
    prompt, so mirroring them into their own columns cost ~380MB on a real archive
    with no reader for the copies. The prompt must still survive a round trip, and
    the retired columns must stay gone."""
    from sqlalchemy import inspect as sa_inspect

    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    await database.create_schema()
    repository = BattleRepository(database)
    match_id = agent_request.match_id
    await repository.create_match(
        match_id,
        match_config,
        engine="test-engine",
        engine_version="1",
        showdown_version=None,
        poke_env_version=None,
    )
    decision = await RandomAgent(7).decide(agent_request)
    live = await repository.record_decision(agent_request, decision)

    archive = await repository.get_match(match_id)
    assert archive is not None
    stored = archive.decisions[0]
    assert stored.generated_prompt == agent_request.prompt
    assert stored.generated_prompt == live.generated_prompt
    # The request itself still round-trips in full, prompt and legal actions included.
    assert stored.request == agent_request
    assert stored.request.legal_actions == agent_request.legal_actions

    async with database.sessions() as session:
        columns = await session.run_sync(
            lambda sync_session: {
                column["name"]
                for column in sa_inspect(sync_session.get_bind()).get_columns("agent_decisions")
            }
        )
    assert {"state_json", "legal_actions_json", "generated_prompt"}.isdisjoint(columns)
    assert "request_json" in columns
    await database.close()


@pytest.mark.asyncio
async def test_pruning_drops_old_audits_but_keeps_replays_and_recent_matches(
    tmp_path, match_config: MatchConfig, agent_request: AgentRequest
) -> None:
    """The audit is the largest thing this database stores, but pruning it must not
    cost the replay or the result — those live in `battle_events` and the match row."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'prune.db'}")
    await database.create_schema()
    repository = BattleRepository(database)

    created: list = []
    for index in range(3):
        match_id = uuid4()
        await repository.create_match(
            match_id,
            match_config,
            engine="test-engine",
            engine_version="1",
            showdown_version=None,
            poke_env_version=None,
        )
        await repository.append_event(
            BattleEvent(match_id=match_id, sequence=index, turn=1, event_type="turn_started")
        )
        request = agent_request.model_copy(update={"match_id": match_id, "request_id": uuid4()})
        await repository.record_decision(request, await RandomAgent(index).decide(request))
        created.append(match_id)
    oldest, _middle, newest = created

    # A dry run reports without deleting.
    matches, decisions = await repository.prune_decision_audits(
        keep_recent_matches=1, dry_run=True
    )
    assert (matches, decisions) == (2, 2)
    archive = await repository.get_match(oldest)
    assert archive is not None and len(archive.decisions) == 1, "dry run must not delete"

    matches, decisions = await repository.prune_decision_audits(keep_recent_matches=1)
    assert (matches, decisions) == (2, 2)

    pruned = await repository.get_match(oldest)
    assert pruned is not None
    assert pruned.decisions == (), "the old audit is gone"
    assert len(pruned.events) == 1, "but its replay events remain"
    assert pruned.config == match_config, "and so does the match itself"

    kept = await repository.get_match(newest)
    assert kept is not None and len(kept.decisions) == 1, "the newest match keeps its audit"

    # Running again is a no-op rather than an error.
    assert await repository.prune_decision_audits(keep_recent_matches=1) == (0, 0)
    # Retention off means never touch anything.
    assert await repository.prune_decision_audits(keep_recent_matches=0) == (0, 0)
    await database.close()
