from __future__ import annotations

import asyncio
import os

import pytest

from koalabattle.agents.providers.fake import _FAKE_GEN9OU_TEAM
from koalabattle.config import Settings
from koalabattle.core.models import (
    AgentType,
    MatchConfig,
    MatchLimits,
    MatchStatus,
    PlayerConfig,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.replay import ReplayCursor
from koalabattle.service import BattleService
from koalabattle.storage import BattleRepository, Database
from koalabattle.teams import ShowdownTeamValidator, TeamRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pinned_showdown_parses_validates_normalizes_and_packs_gen9ou_team() -> None:
    if os.getenv("KOALABATTLE_RUN_SHOWDOWN_TEST") != "1":
        pytest.skip("set KOALABATTLE_RUN_SHOWDOWN_TEST=1 to run local Showdown integration")
    validator = ShowdownTeamValidator(
        os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002")
    )
    valid = await validator.validate(_FAKE_GEN9OU_TEAM, "gen9ou")
    assert valid.valid
    assert len(valid.structured_team) == 6
    assert valid.normalized_export is not None and "Great Tusk" in valid.normalized_export
    assert valid.packed_team

    invalid = await validator.validate(
        "Pikachu @ Leftovers\nAbility: Static\n- V-create",
        "gen9ou",
    )
    assert not invalid.valid
    assert any("V-create" in error or "V-create" in error for error in invalid.errors)

    banned = await validator.validate(
        "Rayquaza-Mega @ Life Orb\nAbility: Delta Stream\n- Dragon Ascent",
        "gen9ou",
    )
    assert not banned.valid


@pytest.mark.integration
@pytest.mark.asyncio
async def test_validated_fixed_teams_complete_persist_and_replay_real_match(tmp_path) -> None:
    if os.getenv("KOALABATTLE_RUN_SHOWDOWN_TEST") != "1":
        pytest.skip("set KOALABATTLE_RUN_SHOWDOWN_TEST=1 to run local Showdown integration")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'custom.db'}",
        showdown_websocket_url=os.getenv(
            "KOALABATTLE_SHOWDOWN_WEBSOCKET_URL",
            "ws://localhost:8000/showdown/websocket",
        ),
        team_validator_url=os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002"),
        asset_root=tmp_path / "assets",
    )
    database = Database(settings.database_url)
    await database.create_schema()
    repository = BattleRepository(database)
    teams = TeamRepository(database)
    validation = await ShowdownTeamValidator(settings.team_validator_url).validate(
        _FAKE_GEN9OU_TEAM, "gen9ou"
    )
    alpha = await teams.create_snapshot(
        name="Alpha fixed",
        source=TeamSource.IMPORTED,
        submitted_text=_FAKE_GEN9OU_TEAM,
        validation=validation,
    )
    beta = await teams.create_snapshot(
        name="Beta fixed",
        source=TeamSource.PRESET,
        submitted_text=_FAKE_GEN9OU_TEAM,
        validation=validation,
    )
    service = BattleService(repository, settings)
    created = await service.create_match(
        MatchConfig(
            name="Real Gen 9 OU fixture",
            format="gen9ou",
            team_policy=TeamPolicy.FIXED,
            players=(
                PlayerConfig(
                    side=Side.P1,
                    display_name="Fixed Alpha",
                    agent_type=AgentType.RANDOM,
                    team_source=TeamSource.IMPORTED,
                    team_snapshot_id=alpha.id,
                ),
                PlayerConfig(
                    side=Side.P2,
                    display_name="Fixed Beta",
                    agent_type=AgentType.RANDOM,
                    team_source=TeamSource.PRESET,
                    team_snapshot_id=beta.id,
                ),
            ),
            random_seed=20260815,
            limits=MatchLimits(maximum_turns=20),
        )
    )
    async with asyncio.timeout(90):
        while True:
            archive = await repository.get_match(created.id)
            assert archive is not None
            if archive.status in {MatchStatus.COMPLETED, MatchStatus.FAILED}:
                break
            await asyncio.sleep(0.1)
    assert archive.status is MatchStatus.COMPLETED, archive.error
    assert archive.turns > 0
    assert archive.raw_showdown_log and "|start" in archive.raw_showdown_log
    assert len(archive.decisions) >= 2
    cursor = ReplayCursor(archive.events)
    while cursor.index < len(cursor.events):
        cursor = cursor.advance_event()
    assert cursor.state is not None and cursor.state.result is not None
    await service.close()
    await database.close()

    reopened = Database(settings.database_url)
    persisted = await BattleRepository(reopened).get_match(created.id)
    assert persisted is not None and persisted.status is MatchStatus.COMPLETED
    assert persisted.config.players[0].team_snapshot_id == alpha.id
    await reopened.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_campaign_doubles_format_completes_a_real_two_active_match(tmp_path) -> None:
    if os.getenv("KOALABATTLE_RUN_SHOWDOWN_TEST") != "1":
        pytest.skip("set KOALABATTLE_RUN_SHOWDOWN_TEST=1 to run local Showdown integration")
    format_id = "gen9koalabattlecanonicalnatdexdraftdoubles"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'doubles.db'}",
        showdown_websocket_url=os.getenv(
            "KOALABATTLE_SHOWDOWN_WEBSOCKET_URL",
            "ws://localhost:8000/showdown/websocket",
        ),
        team_validator_url=os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002"),
        asset_root=tmp_path / "assets",
    )
    database = Database(settings.database_url)
    await database.create_schema()
    repository = BattleRepository(database)
    teams = TeamRepository(database)
    validation = await ShowdownTeamValidator(settings.team_validator_url).validate(
        _FAKE_GEN9OU_TEAM, format_id
    )
    assert validation.valid, validation.errors
    alpha = await teams.create_snapshot(
        name="Doubles Alpha",
        source=TeamSource.PRESET,
        submitted_text=_FAKE_GEN9OU_TEAM,
        validation=validation,
    )
    beta = await teams.create_snapshot(
        name="Doubles Beta",
        source=TeamSource.PRESET,
        submitted_text=_FAKE_GEN9OU_TEAM,
        validation=validation,
    )
    service = BattleService(repository, settings)
    created = await service.create_match(
        MatchConfig(
            name="Real campaign Doubles fixture",
            format=format_id,
            team_policy=TeamPolicy.FIXED,
            players=(
                PlayerConfig(
                    side=Side.P1,
                    display_name="Duo Alpha",
                    agent_type=AgentType.TACTICAL_AUTO,
                    team_source=TeamSource.PRESET,
                    team_snapshot_id=alpha.id,
                ),
                PlayerConfig(
                    side=Side.P2,
                    display_name="Duo Beta",
                    agent_type=AgentType.TACTICAL_AUTO,
                    team_source=TeamSource.PRESET,
                    team_snapshot_id=beta.id,
                ),
            ),
            random_seed=20260823,
            limits=MatchLimits(maximum_turns=40),
        )
    )
    async with asyncio.timeout(120):
        while True:
            archive = await repository.get_match(created.id)
            assert archive is not None
            if archive.status in {MatchStatus.COMPLETED, MatchStatus.FAILED}:
                break
            await asyncio.sleep(0.1)
    assert archive.status is MatchStatus.COMPLETED, archive.error
    assert archive.turns > 0
    assert archive.raw_showdown_log is not None
    assert "p1b:" in archive.raw_showdown_log and "p2b:" in archive.raw_showdown_log
    snapshots = [event for event in archive.events if event.event_type == "state_snapshot"]
    assert any(
        len(event.payload["state"]["player"]["active_slots"]) == 2
        and len(event.payload["state"]["opponent"]["active_slots"]) == 2
        for event in snapshots
    )
    await service.close()
    await database.close()
