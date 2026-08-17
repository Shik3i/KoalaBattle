"""Real Pokemon Showdown battles across generations.

Run against the pinned local Showdown container:

    docker compose up -d showdown team-validator
    KOALABATTLE_RUN_SHOWDOWN_TEST=1 pytest tests/integration/test_showdown_generations.py
"""

from __future__ import annotations

import asyncio
import os

import pytest

from koalabattle.config import Settings
from koalabattle.core.models import (
    AgentType,
    MatchArchive,
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

pytestmark = pytest.mark.integration

requires_showdown = pytest.mark.skipif(
    os.getenv("KOALABATTLE_RUN_SHOWDOWN_TEST") != "1",
    reason="set KOALABATTLE_RUN_SHOWDOWN_TEST=1 with local Showdown running",
)

#: A minimal but legal Gen 1 OU team. Gen 1 exports need explicit EVs to satisfy the
#: validator's "did you forget to EV it?" check.
GEN1_OU_TEAM = """Tauros
EVs: 252 HP / 252 Atk / 252 Def / 252 SpA / 252 Spe
- Body Slam
- Hyper Beam
- Blizzard
- Earthquake

Snorlax
EVs: 252 HP / 252 Atk / 252 Def / 252 SpA / 252 Spe
- Body Slam
- Hyper Beam
- Earthquake
- Self-Destruct

Chansey
EVs: 252 HP / 252 Atk / 252 Def / 252 SpA / 252 Spe
- Ice Beam
- Thunder Wave
- Soft-Boiled
- Counter

Exeggutor
EVs: 252 HP / 252 Atk / 252 Def / 252 SpA / 252 Spe
- Psychic
- Sleep Powder
- Explosion
- Double-Edge

Starmie
EVs: 252 HP / 252 Atk / 252 Def / 252 SpA / 252 Spe
- Psychic
- Blizzard
- Thunder Wave
- Recover

Alakazam
EVs: 252 HP / 252 Atk / 252 Def / 252 SpA / 252 Spe
- Psychic
- Seismic Toss
- Thunder Wave
- Recover
"""


def _settings(tmp_path, name: str) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}",
        showdown_websocket_url=os.getenv(
            "KOALABATTLE_SHOWDOWN_WEBSOCKET_URL", "ws://localhost:8000/showdown/websocket"
        ),
        team_validator_url=os.getenv("KOALABATTLE_TEAM_VALIDATOR_URL", "http://localhost:8002"),
        asset_root=tmp_path / "assets",
    )


async def _await_terminal(
    repository: BattleRepository, match_id, deadline_seconds: float
) -> MatchArchive:
    async with asyncio.timeout(deadline_seconds):
        while True:
            archive = await repository.get_match(match_id)
            assert archive is not None
            if archive.status in {MatchStatus.COMPLETED, MatchStatus.FAILED}:
                return archive
            await asyncio.sleep(0.2)


def _assert_battle_is_complete(archive: MatchArchive) -> None:
    assert archive.status is MatchStatus.COMPLETED, archive.error
    assert archive.turns > 0
    assert archive.winner in {Side.P1, Side.P2}
    assert archive.raw_showdown_log and "|win|" in archive.raw_showdown_log
    kinds = {event.event_type for event in archive.events}
    # A real battle exercises actions, switching and damage, not just start and finish.
    assert {"move_used", "damage", "pokemon_switched", "turn_started"} <= kinds
    assert archive.events[-1].event_type == "battle_finished"
    cursor = ReplayCursor(archive.events)
    while cursor.index < len(cursor.events):
        cursor = cursor.advance_event()
    assert cursor.state is not None and cursor.state.result is not None
    assert cursor.state.result.winner == archive.winner


def _assert_prompt_is_generation_correct(archive: MatchArchive, generation: int) -> None:
    """A mechanic must never appear before the generation that introduced it."""
    record = archive.decisions[min(3, len(archive.decisions) - 1)]
    assert record.request.context is not None
    context = record.request.context
    assert context.generation == generation
    prompt = record.generated_prompt
    assert f"Generation {generation}" in prompt
    assert "LEGAL ACTIONS" in prompt and "YOUR ACTIVE POKEMON" in prompt

    mechanics = context.mechanics
    assert mechanics.items is (generation >= 2)
    assert mechanics.abilities is (generation >= 3)
    assert mechanics.physical_special_split is (generation >= 4)
    assert mechanics.z_moves is (generation == 7)
    assert mechanics.mega_evolution is (6 <= generation <= 7)

    # A field is only rendered when the generation actually has that mechanic.
    assert ("Item:" in prompt) is mechanics.items
    assert ("Known item" in prompt) is mechanics.items
    assert ("Ability:" in prompt) is mechanics.abilities
    assert ("Known ability" in prompt) is mechanics.abilities

    # A mechanic is only advertised as available when a legal action can actually carry it.
    advertised = prompt.split("Available mechanics: ", 1)
    if len(advertised) > 1:
        offered = advertised[1].splitlines()[0]
        for never_actionable in ("Mega Evolution", "Z-Move", "Dynamax", "Gigantamax"):
            assert never_actionable not in offered, (
                f"gen {generation} advertises {never_actionable}, which has no action"
            )
    for label in mechanics.unavailable():
        assert "KoalaBattle cannot select it" in prompt, (
            f"gen {generation} has {label} but the prompt does not say it is unselectable"
        )
    if not mechanics.terastallization:
        assert "Terastallize" not in prompt
        assert "Tera type" not in prompt
    assert all(
        action.terastallize is False or mechanics.terastallization
        for action in record.request.legal_actions
    )
    if generation < 4:
        # Before the split, naming a per-move damage class would state a rule that does
        # not exist in that generation.
        assert " · Physical · " not in prompt
        assert " · Special · " not in prompt

    # Switch actions use display names, never machine species IDs.
    for action in record.request.legal_actions:
        if action.type.value == "switch":
            assert action.species and action.species[0].isupper()


def _assert_bench_is_actionable(archive: MatchArchive, generation: int) -> None:
    """An agent that cannot see what its bench does cannot switch well."""
    record = next(
        (
            item
            for item in archive.decisions
            if item.request.context is not None
            and any(action.type.value == "switch" for action in item.request.legal_actions)
        ),
        None,
    )
    assert record is not None, "no decision offered a switch"
    context = record.request.context
    assert context is not None
    bench = [
        item for item in context.knowledge.own_side.team if not item.active and not item.fainted
    ]
    assert bench, "no healthy bench Pokemon to describe"
    prompt = record.generated_prompt
    bench_section = prompt.split("YOUR BENCH", 1)[1].split("OPPONENT ACTIVE", 1)[0]
    for member in bench:
        assert member.name in bench_section, f"{member.name} missing from the bench block"
        assert member.moves, f"{member.name} has no moves in the snapshot"
        for move in member.moves:
            assert move.name in bench_section, f"{move.name} missing for {member.name}"
            assert move.type, f"{move.name} has no type"
            if move.max_pp is not None:
                assert f"{move.current_pp}/{move.max_pp} PP" in bench_section
        assert f"Type: {'/'.join(part.capitalize() for part in member.types)}" in bench_section
    if generation >= 2:
        assert "Item:" in bench_section
    if generation >= 3:
        assert "Ability:" in bench_section


@requires_showdown
@pytest.mark.asyncio
@pytest.mark.parametrize("generation", list(range(1, 10)))
async def test_random_battles_run_across_generations(tmp_path, generation) -> None:
    """One real local Showdown Random Battle per generation, start to persisted replay."""
    format_id = f"gen{generation}randombattle"
    settings = _settings(tmp_path, format_id)
    database = Database(settings.database_url)
    await database.create_schema()
    repository = BattleRepository(database)
    service = BattleService(repository, settings)
    await service.start()

    created = await service.create_match(
        MatchConfig(
            name=f"{format_id} integration",
            format=format_id,
            players=(
                PlayerConfig(side=Side.P1, display_name="Alpha", agent_type=AgentType.RANDOM),
                PlayerConfig(side=Side.P2, display_name="Beta", agent_type=AgentType.RANDOM),
            ),
            random_seed=2026,
            limits=MatchLimits(maximum_turns=80),
        )
    )
    archive = await _await_terminal(repository, created.id, 240)
    _assert_battle_is_complete(archive)
    assert archive.config.generation == generation
    _assert_prompt_is_generation_correct(archive, generation)
    _assert_bench_is_actionable(archive, generation)
    await service.close()
    await database.close()

    # The archive must survive a reopen, which is what replay and the UI read back.
    reopened = Database(settings.database_url)
    persisted = await BattleRepository(reopened).get_match(archive.id)
    assert persisted is not None and persisted.events == archive.events
    await reopened.close()


@requires_showdown
@pytest.mark.asyncio
async def test_gen1_ou_runs_with_validated_imported_teams(tmp_path) -> None:
    settings = _settings(tmp_path, "gen1ou")
    database = Database(settings.database_url)
    await database.create_schema()
    repository = BattleRepository(database)
    service = BattleService(repository, settings)
    await service.start()

    snapshots = []
    for index in (1, 2):
        validation, snapshot = await service.validate_team(
            name=f"Gen 1 OU integration {index}",
            team_text=GEN1_OU_TEAM,
            format_id="gen1ou",
            source=TeamSource.IMPORTED,
            save=True,
        )
        assert validation.valid, validation.errors
        assert snapshot is not None and snapshot.format == "gen1ou"
        snapshots.append(snapshot)

    created = await service.create_match(
        MatchConfig(
            name="gen1ou integration",
            format="gen1ou",
            team_policy=TeamPolicy.FIXED,
            players=(
                PlayerConfig(
                    side=Side.P1,
                    display_name="Alpha",
                    agent_type=AgentType.RANDOM,
                    team_source=TeamSource.IMPORTED,
                    team_snapshot_id=snapshots[0].id,
                ),
                PlayerConfig(
                    side=Side.P2,
                    display_name="Beta",
                    agent_type=AgentType.RANDOM,
                    team_source=TeamSource.IMPORTED,
                    team_snapshot_id=snapshots[1].id,
                ),
            ),
            random_seed=7,
            limits=MatchLimits(maximum_turns=100),
        )
    )
    archive = await _await_terminal(repository, created.id, 300)
    _assert_battle_is_complete(archive)
    assert archive.config.generation == 1
    _assert_prompt_is_generation_correct(archive, 1)
    await service.close()
    await database.close()


@requires_showdown
@pytest.mark.asyncio
async def test_live_format_catalog_matches_the_bundled_snapshot(tmp_path) -> None:
    """The committed snapshot must stay in step with the pinned Showdown build."""
    from koalabattle.formats import FormatCatalogService, load_snapshot

    settings = _settings(tmp_path, "catalog")
    service = FormatCatalogService(settings.team_validator_url)
    live = await service.refresh()
    assert live.source == "showdown-live"
    snapshot = load_snapshot()
    assert {item.id for item in live.formats} == {item.id for item in snapshot.formats}
    live_mechanics = {item.id: item.mechanics for item in live.formats}
    assert all(live_mechanics[item.id] == item.mechanics for item in snapshot.formats)
