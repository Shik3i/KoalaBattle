from __future__ import annotations

import os

import pytest

from koalabattle.challenges.models import ChallengeDifficulty, opponent_stage_level
from koalabattle.challenges.service import (
    _definition,
    _opponent_stage_team,
    _prepare_opponent_stage_team,
    _with_level,
    _with_unique_duplicate_nicknames,
)
from koalabattle.challenges.species import ShowdownSpeciesCatalog, showdown_id
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
        for mode in ("original", "filled"):
            team = _opponent_stage_team(stage, mode)
            result = await validator.validate(
                _with_unique_duplicate_nicknames(_with_level(team, stage.level)),
                definition.format,
            )
            if not result.valid:
                failures[f"{stage.id}/{mode}"] = result.errors

    assert failures == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_every_regional_campaign_team_is_legal_after_dex_enrichment() -> None:
    """Canonical regional rosters must remain validator-legal in every shipped route."""
    _skip_unless_showdown()
    definition_ids = (
        "johto-gym-gauntlet",
        "hoenn-gym-gauntlet",
        "sinnoh-gym-gauntlet",
        "unova-gym-gauntlet",
        "kalos-gym-gauntlet",
        "alola-trial-gauntlet",
        "galar-gym-gauntlet",
        "paldea-gym-gauntlet",
        "all-generations-gauntlet",
    )
    validator = _validator()
    catalog = ShowdownSpeciesCatalog(
        os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002")
    )

    failures: dict[str, tuple[str, ...]] = {}
    for definition_id in definition_ids:
        definition = _definition(definition_id)
        species_by_id = {
            showdown_id(entry.id): entry for entry in await catalog.entries(definition.format)
        }
        minimum_levels = {
            showdown_id(entry.id): entry.minimum_level for entry in species_by_id.values()
        }
        for stage in definition.stages:
            for mode in ("original", "filled"):
                team = _prepare_opponent_stage_team(
                    _opponent_stage_team(stage, mode), species_by_id
                )
                result = await validator.validate(
                    _with_unique_duplicate_nicknames(
                        _with_level(team, stage.level, minimum_levels)
                    ),
                    definition.format,
                )
                if not result.valid:
                    failures[f"{definition_id}/{stage.id}/{mode}"] = result.errors

    assert failures == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_shipped_opponent_sets_keep_their_items_abilities_and_natures() -> None:
    """The pinned validator, not the JSON text, is the authority on what actually applies."""
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    validator = _validator()

    for stage in definition.stages:
        assert stage.filled_opponent_team is not None
        result = await validator.validate(
            _with_unique_duplicate_nicknames(
                _with_level(stage.filled_opponent_team, stage.level)
            ),
            definition.format,
        )
        assert result.valid, (stage.id, result.errors)
        assert result.structured_team is not None
        assert len(result.structured_team) == len(stage.filled_opponent_team.split("\n\n"))
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
async def test_opponent_teams_stay_legal_while_difficulty_raises_their_level() -> None:
    """Difficulty only ever raises the opponent above the campaign curve, never the player."""
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    validator = _validator()

    for stage in definition.stages:
        for mode in ("original", "filled"):
            team = _opponent_stage_team(stage, mode)
            for difficulty in ChallengeDifficulty:
                opponent_level = opponent_stage_level(stage.level, difficulty)
                assert opponent_level >= stage.level
                result = await validator.validate(
                    _with_unique_duplicate_nicknames(_with_level(team, opponent_level)),
                    definition.format,
                )
                assert result.valid, (stage.id, mode, difficulty, result.errors)
                assert all(
                    entry.get("level") == opponent_level for entry in result.structured_team or ()
                )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_every_draftable_species_gets_at_least_one_legal_recommended_move() -> None:
    """A species with no recommended move kills the run at automatic team preparation.

    The scaffold has to emit *some* move, so an empty list makes it fall back to one the
    species cannot learn. Pokemon with no legal attacking move at all (Cosmoem, Ditto,
    Wobbuffet, Smeargle) are the ones that hit this.
    """
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    catalog = ShowdownSpeciesCatalog(
        os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002")
    )
    species = await catalog.entries(definition.format)

    draftable = [
        entry
        for entry in species
        if not entry.is_mega
        and not entry.is_gmax
        and not entry.battle_only
        and not entry.cosmetic
        and not entry.unavailable
    ]
    assert draftable, "the draft pool must not be empty"
    assert len(draftable) > 1200
    missing = sorted(entry.name for entry in draftable if not entry.recommended_moves)
    assert missing == [], missing
    assert all(entry.showdown_set is not None for entry in draftable)
    assert all(
        entry.showdown_set.source
        in {"showdown-battle-factory", "showdown-random-battle", "showdown-dex-validated"}
        for entry in draftable
        if entry.showdown_set is not None
    )
    short_sets = {
        entry.name: entry.showdown_set.moves
        for entry in draftable
        if entry.showdown_set is not None and len(entry.showdown_set.moves) < 4
    }
    assert set(short_sets) == {"Ditto", "Unown", "Cosmog", "Cosmoem"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ninjask_and_shedinja_use_distinct_authoritative_showdown_data() -> None:
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    catalog = ShowdownSpeciesCatalog(
        os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002")
    )
    by_name = {entry.name: entry for entry in await catalog.entries(definition.format)}

    ninjask = by_name["Ninjask"]
    shedinja = by_name["Shedinja"]
    assert ninjask.base_stats is not None and ninjask.base_stats.hp == 61
    assert shedinja.base_stats is not None and shedinja.base_stats.hp == 1
    assert {ability.name for ability in ninjask.abilities} == {"Speed Boost", "Infiltrator"}
    assert {ability.name for ability in shedinja.abilities} == {"Wonder Guard"}
    assert ninjask.showdown_set is not None
    assert shedinja.showdown_set is not None
    assert ninjask.showdown_set.ability == "Speed Boost"
    assert shedinja.showdown_set.ability == "Wonder Guard"
    assert ninjask.max_hp is None
    assert shedinja.max_hp == 1
    for level in (1, 35, 50, 70, 100):
        # Showdown's maxHP override takes precedence over the ordinary HP formula.
        shedinja_hp = shedinja.max_hp or (
            ((2 * shedinja.base_stats.hp + 31) * level) // 100 + level + 10
        )
        assert shedinja_hp == 1
    # Level 70, 31 HP IV, 0 HP EV: Showdown's ordinary formula yields 187 for Ninjask.
    assert ((2 * ninjask.base_stats.hp + 31) * 70) // 100 + 70 + 10 == 187


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recommended_moves_prefer_the_right_category_and_real_coverage() -> None:
    _skip_unless_showdown()
    definition = _definition("kanto-gym-gauntlet")
    catalog = ShowdownSpeciesCatalog(
        os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://127.0.0.1:8002")
    )
    by_name = {entry.name: entry for entry in await catalog.entries(definition.format)}

    # A special attacker must not be handed four identical-type moves any more.
    greninja = by_name["Greninja"]
    assert len(greninja.recommended_moves) == 4
    assert len(set(greninja.recommended_moves)) == 4
    # Recharge moves used to win on raw power alone.
    assert "Hyper Beam" not in greninja.recommended_moves
    assert "Giga Impact" not in greninja.recommended_moves
