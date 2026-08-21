from __future__ import annotations

import os

import pytest

from koalabattle.challenges.models import ChallengeDifficulty, player_stage_level
from koalabattle.challenges.service import (
    _definition,
    _with_level,
    _with_unique_duplicate_nicknames,
)
from koalabattle.teams import ShowdownTeamValidator


def _validator() -> ShowdownTeamValidator:
    return ShowdownTeamValidator(
        os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002")
    )


def _skip_unless_showdown() -> None:
    if os.getenv("KOALABATTLE_RUN_SHOWDOWN_TEST") != "1":
        pytest.skip("set KOALABATTLE_RUN_SHOWDOWN_TEST=1 to run local Showdown integration")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_every_kanto_gauntlet_team_is_legal_at_its_stage_level() -> None:
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    validator = _validator()

    failures: dict[str, tuple[str, ...]] = {}
    for stage in definition.stages:
        result = await validator.validate(
            _with_unique_duplicate_nicknames(_with_level(stage.opponent_team, stage.level)),
            definition.format,
        )
        if not result.valid:
            failures[stage.id] = result.errors

    assert failures == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_shipped_opponent_sets_keep_their_items_abilities_and_natures() -> None:
    """The pinned validator, not the JSON text, is the authority on what actually applies."""
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    validator = _validator()

    for stage in definition.stages:
        result = await validator.validate(
            _with_unique_duplicate_nicknames(_with_level(stage.opponent_team, stage.level)),
            definition.format,
        )
        assert result.valid, (stage.id, result.errors)
        assert result.structured_team is not None
        assert len(result.structured_team) == len(stage.opponent_team.split("\n\n"))
        for entry in result.structured_team:
            label = f"{stage.id}/{entry.get('species') or entry.get('name')}"
            assert entry.get("ability"), label
            assert entry.get("item"), label
            assert entry.get("nature") not in (None, "", "Serious"), label
            assert len(entry.get("moves") or ()) == 4, label
            assert entry.get("level") == stage.level, label
            evs = entry.get("evs") or {}
            assert sum(int(value) for value in evs.values()) >= 500, label


@pytest.mark.integration
@pytest.mark.asyncio
async def test_opponent_teams_stay_legal_while_the_player_takes_the_level_penalty() -> None:
    """Difficulty must never move an opponent off its campaign level."""
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    validator = _validator()

    for difficulty in ChallengeDifficulty:
        stage = definition.stages[0]
        assert player_stage_level(stage.level, difficulty) <= stage.level
        result = await validator.validate(
            _with_unique_duplicate_nicknames(_with_level(stage.opponent_team, stage.level)),
            definition.format,
        )
        assert result.valid, (difficulty, result.errors)
        assert all(entry.get("level") == stage.level for entry in result.structured_team or ())
