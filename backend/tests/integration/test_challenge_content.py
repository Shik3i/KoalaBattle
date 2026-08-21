from __future__ import annotations

import os

import pytest

from koalabattle.challenges.service import _definition, _with_level
from koalabattle.teams import ShowdownTeamValidator


@pytest.mark.integration
@pytest.mark.asyncio
async def test_every_kanto_gauntlet_team_is_legal_at_its_stage_level() -> None:
    if os.getenv("KOALABATTLE_RUN_SHOWDOWN_TEST") != "1":
        pytest.skip("set KOALABATTLE_RUN_SHOWDOWN_TEST=1 to run local Showdown integration")
    definition = _definition("kanto-gym-gauntlet")
    validator = ShowdownTeamValidator(
        os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002")
    )

    failures: dict[str, tuple[str, ...]] = {}
    for stage in definition.stages:
        result = await validator.validate(
            _with_level(stage.opponent_team, stage.level), definition.format
        )
        if not result.valid:
            failures[stage.id] = result.errors

    assert failures == {}
