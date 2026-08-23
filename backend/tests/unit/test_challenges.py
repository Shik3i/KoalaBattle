from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from koalabattle.agents.providers.base import ProviderRequest
from koalabattle.agents.providers.fake import FakeProvider
from koalabattle.challenges.domain import (
    attach_offer,
    candidate_identity,
    feasible_candidates,
    generate_offer,
)
from koalabattle.challenges.models import (
    DIFFICULTY_LEVEL_MODIFIERS,
    BattleControllerSnapshot,
    ChallengeBattleSummary,
    ChallengeDefinition,
    ChallengeDifficulty,
    ChallengeRun,
    ChallengeSource,
    ChallengeStage,
    ChallengeStatus,
    CreateChallengeRun,
    DraftCandidate,
    DraftControllerKind,
    DraftControllerSnapshot,
    DraftHistoryEntry,
    DraftPick,
    DraftPoolSnapshot,
    DraftRules,
    EvSpread,
    PokemonAbility,
    PokemonIvSpread,
    ShowdownCompetitiveSet,
    TrainingRules,
    opponent_stage_level,
)
from koalabattle.challenges.repository import (
    LEGACY_NOTICE,
    ChallengeRepository,
    _deserialize_run,
)
from koalabattle.challenges.service import (
    AUTO_ADVANCE_DELAYS,
    ChallengeService,
    _eligible_draft_candidates,
    _knocked_out_entry_ids,
    _opponent_stage_team,
    _resolve_draft_action,
    _team_scaffold,
    _with_level,
    _with_unique_duplicate_nicknames,
    _with_zero_ev_confirmation,
    _without_downed,
    derive_battle_summary,
    redact_challenge_match,
)
from koalabattle.challenges.service import (
    _definition as load_definition,
)
from koalabattle.challenges.species import ShowdownSpeciesCatalog, SpeciesMetadata
from koalabattle.core.models import (
    AgentType,
    BattleEvent,
    MatchArchive,
    MatchConfig,
    MatchStatus,
    PlayerConfig,
    ProviderKind,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.storage import BattleRepository, Database
from koalabattle.teams.models import TeamSnapshot, TeamValidationResult


def _abilities(index: int) -> tuple[PokemonAbility, ...]:
    return (
        PokemonAbility(slot="0", id=f"ability{index}a", name=f"Ability {index} A"),
        PokemonAbility(slot="H", id=f"ability{index}h", name=f"Ability {index} H", hidden=True),
    )


def test_new_challenge_drafts_reject_non_human_controllers() -> None:
    with pytest.raises(ValueError, match="always human-controlled"):
        CreateChallengeRun(
            seed=1,
            draft_controller=DraftControllerSnapshot(kind=DraftControllerKind.RANDOM),
            battle_controller=BattleControllerSnapshot(agent_type=AgentType.TACTICAL_AUTO),
            opponent_controller=BattleControllerSnapshot(agent_type=AgentType.RANDOM),
        )


def test_new_challenge_opponents_are_always_local_tactical_auto() -> None:
    payload = CreateChallengeRun(
        seed=1,
        draft_controller=DraftControllerSnapshot(kind=DraftControllerKind.HUMAN),
        battle_controller=BattleControllerSnapshot(agent_type=AgentType.TACTICAL_AUTO),
        opponent_controller=BattleControllerSnapshot(agent_type=AgentType.RANDOM),
    )

    assert payload.opponent_controller.agent_type is AgentType.TACTICAL_AUTO


def test_base_form_pool_removes_evolved_entries_without_replacing_them() -> None:
    base = _candidate(1).model_copy(update={"evolution_stage": 0})
    evolved = _candidate(2).model_copy(update={"evolution_stage": 1})
    single_stage = _candidate(3).model_copy(update={"evolution_stage": 0, "evolves_to": ()})
    rules = DraftRules(draft_pool_mode="base-forms-only")

    filtered = _eligible_draft_candidates((base, evolved, single_stage), rules)

    assert filtered == (base, single_stage)
    assert all(candidate.entry_id != evolved.entry_id for candidate in filtered)
    assert _eligible_draft_candidates(
        (base, evolved, single_stage), DraftRules(draft_pool_mode="all-forms")
    ) == (base, evolved, single_stage)


def test_opponent_team_mode_selects_original_or_filled_team() -> None:
    stage = ChallengeStage(
        id="brock",
        name="Brock",
        title="Gym Leader",
        theme="Rock",
        level=50,
        opponent_team="Geodude\n- Tackle",
        filled_opponent_team="Onix\n- Rock Slide\n\nGolem\n- Earthquake",
    )

    assert _opponent_stage_team(stage, "original").startswith("Geodude")
    assert _opponent_stage_team(stage, "filled").startswith("Onix")


def _candidate(
    index: int,
    *,
    base_species_id: str | None = None,
    types: tuple[str, ...] = ("Normal",),
    abilities: tuple[PokemonAbility, ...] | None = None,
    generation: int = 1,
) -> DraftCandidate:
    primary_ability = _abilities(index) if abilities is None else abilities
    return DraftCandidate(
        entry_id=f"mon{index}",
        species=f"Mon {index}",
        showdown_id=f"mon{index}",
        base_species_id=base_species_id or f"mon{index}",
        national_dex_number=index,
        introduction_generation=generation,
        types=types,
        base_stat_total=300 + index,
        abilities=primary_ability,
        recommended_moves=("Tackle", "Protect", "Rest", "Sleep Talk"),
        showdown_set=ShowdownCompetitiveSet(
            source="showdown-battle-factory",
            source_generation=9,
            source_tier="Unit",
            species=f"Mon {index}",
            item="Leftovers",
            ability=primary_ability[0].name if primary_ability else "No Ability",
            nature="Serious",
            moves=("Tackle", "Protect", "Rest", "Sleep Talk"),
            evs=EvSpread(hp=252, defense=252, spd=4),
            ivs=PokemonIvSpread(),
        ),
    )


def _definition(rules: DraftRules | None = None) -> ChallengeDefinition:
    return ChallengeDefinition(
        id="fixture",
        version="2",
        name="Fixture Challenge",
        description="Synthetic test campaign.",
        format="gen9natdexdraft",
        source=ChallengeSource(
            game="Synthetic fixture",
            generation=9,
            variant="Unit test",
            references=("https://example.invalid/fixture",),
            compatibility_note="Synthetic test data.",
        ),
        draft_rules=rules or DraftRules(roster_size=3, rerolls=2, choice_count=3),
        training_rules=TrainingRules(),
        stages=(
            ChallengeStage(
                id="stage-one",
                name="Fixture Leader",
                title="Test Stage",
                theme="Deterministic",
                level=50,
                opponent_team="Mon 99\n- Tackle",
            ),
        ),
    )


def _run(
    *,
    candidates: tuple[DraftCandidate, ...] | None = None,
    rules: DraftRules | None = None,
    status: ChallengeStatus = ChallengeStatus.DRAFTING,
    abilities_supported: bool = True,
    seed: int = 987654,
) -> ChallengeRun:
    now = datetime.now(UTC)
    definition = _definition(rules)
    pool = candidates or tuple(_candidate(index) for index in range(1, 16))
    return ChallengeRun(
        id=uuid4(),
        name="Fixture run",
        definition=definition,
        status=status,
        seed=seed,
        draft_pool=DraftPoolSnapshot(
            showdown_version="unit-test",
            format=definition.format,
            format_generation=9 if abilities_supported else 2,
            abilities_supported=abilities_supported,
            catalog_hash="b" * 64,
            candidates=pool,
        ),
        draft_controller=DraftControllerSnapshot(kind=DraftControllerKind.HUMAN),
        battle_controller=BattleControllerSnapshot(agent_type=AgentType.HUMAN),
        opponent_controller=BattleControllerSnapshot(agent_type=AgentType.RANDOM),
        rerolls_remaining=definition.draft_rules.rerolls,
        type_rerolls_remaining=definition.draft_rules.type_rerolls,
        generation_rerolls_remaining=definition.draft_rules.generation_rerolls,
        created_at=now,
        updated_at=now,
    )


def _picked_run(*, abilities_supported: bool = True) -> ChallengeRun:
    candidates = tuple(
        _candidate(index, abilities=() if not abilities_supported else None)
        for index in range(1, 4)
    )
    run = _run(
        candidates=candidates,
        status=ChallengeStatus.TEAM_REVIEW,
        abilities_supported=abilities_supported,
    )
    picks = tuple(
        DraftPick(
            round=index,
            offer_fingerprint="c" * 64,
            candidate=candidate,
            selected_by=DraftControllerKind.HUMAN,
        )
        for index, candidate in enumerate(candidates, start=1)
    )
    return run.model_copy(
        update={
            "picks": picks,
            "ev_allocations": {candidate.entry_id: EvSpread() for candidate in candidates},
            "ability_selections": {
                candidate.entry_id: candidate.abilities[0].id if abilities_supported else None
                for candidate in candidates
            },
        }
    )


def test_seeded_offer_is_reproducible_and_consumes_every_displayed_species() -> None:
    run = _run()
    assert generate_offer(run) == generate_offer(run)

    attached = attach_offer(run)
    assert attached.current_offer is not None
    displayed = {
        candidate_identity(candidate, True) for candidate in attached.current_offer.options
    }
    assert displayed <= set(attached.consumed_species_ids)
    assert displayed.isdisjoint(
        {candidate_identity(candidate, True) for candidate in feasible_candidates(attached)}
    )


def test_offer_size_degrades_only_as_needed_to_leave_enough_roster_slots() -> None:
    run = _run(
        candidates=tuple(_candidate(index) for index in range(1, 5)),
        rules=DraftRules(roster_size=3, rerolls=0, choice_count=3),
    )
    first = attach_offer(run)
    assert first.current_offer is not None
    assert len(first.current_offer.options) == 2

    selected = first.current_offer.options[0]
    progressed = first.model_copy(
        update={
            "picks": (
                DraftPick(
                    round=1,
                    offer_fingerprint=first.current_offer.fingerprint,
                    candidate=selected,
                    selected_by=DraftControllerKind.HUMAN,
                ),
            ),
            "current_offer": None,
        }
    )
    second = attach_offer(progressed)
    assert second.current_offer is not None
    assert len(second.current_offer.options) == 1


def test_authoritative_base_species_identity_consumes_alternate_forms() -> None:
    candidates = (
        _candidate(1, base_species_id="rotom"),
        _candidate(2, base_species_id="rotom"),
        _candidate(3),
        _candidate(4),
    )
    run = _run(
        candidates=candidates,
        rules=DraftRules(roster_size=2, rerolls=0, choice_count=2),
    )
    attached = attach_offer(run)
    offered_bases = [item.base_species_id for item in attached.current_offer.options]  # type: ignore[union-attr]
    assert len(offered_bases) == len(set(offered_bases))
    if "rotom" in offered_bases:
        assert not any(item.base_species_id == "rotom" for item in feasible_candidates(attached))


@pytest.mark.asyncio
async def test_pick_and_reroll_never_reoffer_consumed_species_and_survive_restart(
    tmp_path: Path,
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'draft.db'}"
    database = Database(url)
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = attach_offer(_run())
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    original = run.current_offer
    assert original is not None
    rerolled = await service.reroll(run.id, original.fingerprint, run.revision)
    assert rerolled.current_offer is not None
    assert {item.base_species_id for item in original.options}.isdisjoint(
        {item.base_species_id for item in rerolled.current_offer.options}
    )
    assert rerolled.draft_history[-1].outcome == "pokemon_rerolled"
    selected_offer = rerolled.current_offer
    picked = await service.pick(
        run.id,
        selected_offer.options[0].entry_id,
        selected_offer.fingerprint,
        rerolled.revision,
    )
    assert picked.draft_history[-1].selected_entry_id == selected_offer.options[0].entry_id
    assert picked.current_offer is not None
    all_prior = {
        item.base_species_id for history in picked.draft_history for item in history.offer.options
    }
    assert all_prior.isdisjoint({item.base_species_id for item in picked.current_offer.options})
    await database.close()

    reopened = Database(url)
    persisted = await ChallengeRepository(reopened).get(run.id)
    assert persisted is not None
    assert persisted.current_offer == picked.current_offer
    assert persisted.consumed_species_ids == picked.consumed_species_ids
    assert persisted.draft_history == picked.draft_history
    await reopened.close()


@pytest.mark.asyncio
async def test_type_and_generation_rerolls_preserve_one_axis_and_consume_offers(
    tmp_path: Path,
) -> None:
    candidates = tuple(
        _candidate(index, generation=generation, types=(type_name,))
        for index, generation, type_name in (
            (1, 1, "Water"),
            (2, 1, "Water"),
            (3, 1, "Water"),
            (4, 1, "Fire"),
            (5, 1, "Fire"),
            (6, 1, "Fire"),
            (7, 2, "Water"),
            (8, 2, "Water"),
            (9, 2, "Water"),
            (10, 2, "Fire"),
            (11, 2, "Fire"),
            (12, 2, "Fire"),
        )
    )
    rules = DraftRules(
        roster_size=2,
        rerolls=3,
        type_rerolls=1,
        generation_rerolls=1,
        choice_count=2,
    )
    run = attach_offer(_run(candidates=candidates, rules=rules))
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'axis-rerolls.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, _Battles(()))
    )
    original = run.current_offer
    assert original is not None

    type_rerolled = await service.reroll(run.id, original.fingerprint, run.revision, kind="type")
    type_offer = type_rerolled.current_offer
    assert type_offer is not None
    assert type_offer.generation == original.generation
    assert type_offer.type != original.type
    assert type_rerolled.type_rerolls_remaining == 0
    assert type_rerolled.draft_history[-1].outcome == "type_rerolled"

    generation_rerolled = await service.reroll(
        run.id,
        type_offer.fingerprint,
        type_rerolled.revision,
        kind="generation",
    )
    generation_offer = generation_rerolled.current_offer
    assert generation_offer is not None
    assert generation_offer.type == type_offer.type
    assert generation_offer.generation != type_offer.generation
    assert generation_rerolled.generation_rerolls_remaining == 0
    assert generation_rerolled.rerolls_remaining == 3
    assert generation_rerolled.draft_history[-1].outcome == "generation_rerolled"
    consumed = {
        candidate.base_species_id
        for history in generation_rerolled.draft_history
        for candidate in history.offer.options
    }
    assert consumed <= set(generation_rerolled.consumed_species_ids)
    assert consumed.isdisjoint(
        {candidate.base_species_id for candidate in generation_offer.options}
    )
    await database.close()


@pytest.mark.asyncio
async def test_complete_draft_has_no_repeated_offer_and_initializes_abilities(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'complete.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = attach_offer(_run())
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, _Battles(()))
    )
    while run.status is ChallengeStatus.DRAFTING:
        offer = run.current_offer
        assert offer is not None
        run = await service.pick(run.id, offer.options[0].entry_id, offer.fingerprint, run.revision)
    offered = [
        candidate.base_species_id
        for history in run.draft_history
        for candidate in history.offer.options
    ]
    assert len(offered) == len(set(offered))
    assert run.status is ChallengeStatus.READY
    assert run.team_snapshot_id is not None
    assert len(run.picks) == 3
    assert run.ability_selections == {
        pick.candidate.entry_id: pick.candidate.abilities[0].id for pick in run.picks
    }
    assert set(run.ev_allocations) == {pick.candidate.entry_id for pick in run.picks}
    assert all(spread.total == 508 for spread in run.ev_allocations.values())
    assert sum(spread.total for spread in run.ev_allocations.values()) == 1524
    public = service.view(run)
    assert {item.entry_id for item in public.run.draft_pool.candidates} == {
        candidate.entry_id for history in run.draft_history for candidate in history.offer.options
    }
    legacy_completed = run.model_copy(
        update={
            "status": ChallengeStatus.COMPLETED,
            "picks": tuple(
                pick.model_copy(
                    update={"candidate": pick.candidate.model_copy(update={"showdown_set": None})}
                )
                for pick in run.picks
            ),
        }
    )
    assert service.view(legacy_completed).team_export_scaffold is None
    await database.close()


@pytest.mark.asyncio
async def test_single_legal_ability_is_selected_automatically(tmp_path: Path) -> None:
    single = (PokemonAbility(slot="0", id="levitate", name="Levitate"),)
    candidates = tuple(_candidate(index, abilities=single) for index in range(1, 4))
    run = attach_offer(
        _run(
            candidates=candidates,
            rules=DraftRules(roster_size=1, rerolls=0, choice_count=2),
        )
    )
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'single-ability.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, _Battles(()))
    )
    offer = run.current_offer
    assert offer is not None
    completed = await service.pick(
        run.id, offer.options[0].entry_id, offer.fingerprint, run.revision
    )
    assert completed.ability_selections == {offer.options[0].entry_id: "levitate"}
    assert "Ability: Levitate" in cast(str, _team_scaffold(completed))
    await database.close()


def test_team_scaffold_includes_pinned_legal_defaults() -> None:
    candidate = _candidate(1).model_copy(
        update={
            "required_item": "Magnet",
            "showdown_set": _candidate(1).showdown_set.model_copy(
                update={
                    "moves": ("Thunderbolt", "Volt Switch", "Protect", "Rest"),
                    "item": "Choice Specs",
                    "nature": "Timid",
                    "evs": EvSpread(spa=252, spd=4, spe=252),
                    "ivs": PokemonIvSpread(atk=0),
                }
            ),
        }
    )
    run = _run(
        candidates=(candidate,),
        rules=DraftRules(roster_size=1, rerolls=0, choice_count=2),
    ).model_copy(
        update={
            "picks": (
                DraftPick(
                    round=1,
                    offer_fingerprint="a" * 64,
                    candidate=candidate,
                    selected_by=DraftControllerKind.HUMAN,
                ),
            )
        }
    )

    scaffold = cast(str, _team_scaffold(run))

    assert scaffold.startswith(f"{candidate.species} @ Magnet")
    assert "- Thunderbolt" in scaffold
    assert "- Volt Switch" in scaffold
    assert "Timid Nature" in scaffold
    assert "IVs: 0 Atk" in scaffold


def _simulate(seed: int) -> tuple[tuple[str, ...], ...]:
    run = _run(seed=seed)
    offers: list[tuple[str, ...]] = []
    while len(run.picks) < run.definition.draft_rules.roster_size:
        run = attach_offer(run)
        offer = run.current_offer
        assert offer is not None
        offers.append(tuple(item.entry_id for item in offer.options))
        selected = offer.options[0]
        run = run.model_copy(
            update={
                "picks": (
                    *run.picks,
                    DraftPick(
                        round=offer.round,
                        offer_fingerprint=offer.fingerprint,
                        candidate=selected,
                        selected_by=DraftControllerKind.HUMAN,
                    ),
                ),
                "draft_history": (
                    *run.draft_history,
                    DraftHistoryEntry(
                        offer=offer,
                        outcome="picked",
                        selected_entry_id=selected.entry_id,
                        decided_by=DraftControllerKind.HUMAN,
                    ),
                ),
                "current_offer": None,
            }
        )
    return tuple(offers)


def test_same_seed_and_rules_produce_the_same_complete_offer_history() -> None:
    assert _simulate(42) == _simulate(42)
    assert _simulate(42) != _simulate(43)


@pytest.mark.asyncio
async def test_ability_selection_validates_exact_form_and_persists(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'ability.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run()
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    abilities = dict(run.ability_selections)
    abilities["mon1"] = "ability1h"
    saved = await service.save_abilities(run.id, abilities, run.revision)
    assert saved.ability_selections["mon1"] == "ability1h"
    with pytest.raises(ValueError, match="invalid ability for Mon 1"):
        await service.save_abilities(run.id, {**abilities, "mon1": "ability2a"}, saved.revision)
    restored = await repository.get(run.id)
    assert restored is not None and restored.ability_selections == saved.ability_selections
    await database.close()


@pytest.mark.asyncio
async def test_generation_two_format_has_no_ability_selection(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'gen2.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run(abilities_supported=False)
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    saved = await service.save_abilities(run.id, dict(run.ability_selections), run.revision)
    assert all(value is None for value in saved.ability_selections.values())
    assert "Ability:" not in cast(str, _team_scaffold(saved))
    with pytest.raises(ValueError, match="does not support Pokemon abilities"):
        await service.save_abilities(
            run.id, {**saved.ability_selections, "mon1": "ability1a"}, saved.revision
        )
    await database.close()


class _Teams:
    def __init__(self) -> None:
        self.created: TeamSnapshot | None = None
        self.snapshots: dict[UUID, TeamSnapshot] = {}

    async def create_snapshot(self, **kwargs: Any) -> TeamSnapshot:
        validation = cast(TeamValidationResult, kwargs["validation"])
        self.created = TeamSnapshot(
            id=uuid4(),
            name=kwargs["name"],
            format=validation.format,
            source=kwargs["source"],
            submitted_text=kwargs["submitted_text"],
            normalized_export=validation.normalized_export or "",
            packed_team=validation.packed_team or "",
            structured_team=validation.structured_team,
            created_at=datetime.now(UTC),
        )
        self.snapshots[self.created.id] = self.created
        return self.created

    async def get(self, snapshot_id: UUID) -> TeamSnapshot | None:
        return self.snapshots.get(snapshot_id)


class _Validator:
    def __init__(self, structured: tuple[dict[str, object], ...]) -> None:
        self.structured = structured
        self.submitted = ""
        self.submissions: list[str] = []

    async def validate(self, team_text: str, format_id: str) -> TeamValidationResult:
        self.submitted = team_text
        self.submissions.append(team_text)
        return TeamValidationResult(
            format=format_id,
            valid=True,
            normalized_export=team_text,
            packed_team="packed",
            structured_team=self.structured,
        )


class _Battles:
    def __init__(
        self,
        structured: tuple[dict[str, object], ...],
        repository: BattleRepository | None = None,
    ) -> None:
        self.teams = _Teams()
        self.team_validator = _Validator(structured)
        self.repository = repository
        self.cancelled: list[UUID] = []

    async def cancel_match(self, match_id: UUID) -> None:
        self.cancelled.append(match_id)

    async def create_match(
        self,
        config: MatchConfig,
        *,
        challenge_run_id: UUID,
        challenge_stage_id: str,
    ) -> MatchArchive:
        assert self.repository is not None
        match_id = uuid4()
        await self.repository.create_match(
            match_id,
            config,
            engine="test",
            engine_version="unit-test",
            showdown_version="unit-test",
            poke_env_version="unit-test",
            challenge_run_id=challenge_run_id,
            challenge_stage_id=challenge_stage_id,
        )
        match = await self.repository.get_match(match_id)
        assert match is not None
        return match


def _won_archive(run: ChallengeRun, match_id: UUID, stage_id: str) -> MatchArchive:
    now = datetime.now(UTC)
    return MatchArchive(
        id=match_id,
        created_at=now,
        updated_at=now,
        status=MatchStatus.COMPLETED,
        winner=Side.P1,
        turns=7,
        config=MatchConfig(
            players=(
                PlayerConfig(
                    side=Side.P1, display_name="Player", agent_type=AgentType.TACTICAL_AUTO
                ),
                PlayerConfig(
                    side=Side.P2, display_name="Leader", agent_type=AgentType.TACTICAL_AUTO
                ),
            )
        ),
        engine="test",
        challenge_run_id=run.id,
        challenge_stage_id=stage_id,
    )


def test_battle_summary_uses_only_participants_and_authoritative_faints() -> None:
    run = _run()
    match_id = uuid4()
    archive = _won_archive(run, match_id, "stage-one").model_copy(
        update={
            "events": (
                BattleEvent(
                    match_id=match_id,
                    sequence=1,
                    turn=0,
                    event_type="pokemon_switched",
                    payload={"actor": "p1a: Sparky", "details": "Pikachu, L50"},
                ),
                BattleEvent(
                    match_id=match_id,
                    sequence=2,
                    turn=0,
                    event_type="pokemon_switched",
                    payload={"actor": "p2a: Rocky", "details": "Geodude, L12"},
                ),
                BattleEvent(
                    match_id=match_id,
                    sequence=3,
                    turn=3,
                    event_type="pokemon_switched",
                    payload={"actor": "p1a: Shell", "details": "Blastoise, L50"},
                ),
                BattleEvent(
                    match_id=match_id,
                    sequence=4,
                    turn=4,
                    event_type="pokemon_fainted",
                    payload={"target": "p2a: Rocky"},
                ),
                BattleEvent(
                    match_id=match_id,
                    sequence=5,
                    turn=7,
                    event_type="pokemon_fainted",
                    payload={"target": "p1a: Sparky"},
                ),
            )
        }
    )

    summary = derive_battle_summary(archive)

    assert summary.player_participants == ("Pikachu", "Blastoise")
    assert summary.opponent_participants == ("Geodude",)
    assert summary.player_fainted == ("Pikachu",)
    assert summary.opponent_fainted == ("Geodude",)


def _auto_match_config() -> MatchConfig:
    return MatchConfig(
        players=(
            PlayerConfig(side=Side.P1, display_name="Player", agent_type=AgentType.TACTICAL_AUTO),
            PlayerConfig(side=Side.P2, display_name="Leader", agent_type=AgentType.TACTICAL_AUTO),
        )
    )


@pytest.mark.asyncio
async def test_brock_victory_advances_to_misty_once_and_survives_restart(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'brock.db'}"
    database = Database(url)
    await database.create_schema()
    repository = ChallengeRepository(database)
    definition = load_definition("kanto-gym-gauntlet")
    match_id = uuid4()
    run = _run(status=ChallengeStatus.READY).model_copy(update={"definition": definition})
    await repository.create(run)
    await BattleRepository(database).create_match(
        match_id,
        _auto_match_config(),
        engine="test",
        engine_version="unit-test",
        showdown_version="unit-test",
        poke_env_version="unit-test",
        challenge_run_id=run.id,
        challenge_stage_id="brock",
    )
    run = await repository.save(
        run.model_copy(update={"status": ChallengeStatus.BATTLING, "active_match_id": match_id}),
        expected_revision=run.revision,
    )
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    archive = _won_archive(run, match_id, "brock")
    await service.on_match_terminal(match_id, archive)
    await service.on_match_terminal(match_id, archive)
    advanced = await service.require(run.id)
    assert advanced.current_stage_index == 1
    assert advanced.definition.stages[advanced.current_stage_index].id == "misty"
    assert [result.stage_id for result in advanced.stage_results] == ["brock"]
    await database.close()

    reopened = Database(url)
    restored = await ChallengeRepository(reopened).get(run.id)
    assert restored is not None
    assert restored.current_stage_index == 1
    assert restored.definition.stages[restored.current_stage_index].id == "misty"
    await reopened.close()


@pytest.mark.asyncio
async def test_fast_watch_waits_for_the_browser_before_launching_another_stage(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'fast-watch-gate.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    definition = load_definition("kanto-gym-gauntlet")
    match_id = uuid4()
    run = _run(status=ChallengeStatus.READY).model_copy(
        update={
            "definition": definition,
            "battle_experience": "fast-watch",
        }
    )
    await repository.create(run)
    await BattleRepository(database).create_match(
        match_id,
        _auto_match_config(),
        engine="test",
        engine_version="unit-test",
        showdown_version="unit-test",
        poke_env_version="unit-test",
        challenge_run_id=run.id,
        challenge_stage_id="brock",
    )
    run = await repository.save(
        run.model_copy(update={"status": ChallengeStatus.BATTLING, "active_match_id": match_id}),
        expected_revision=run.revision,
    )
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )

    await service.on_match_terminal(match_id, _won_archive(run, match_id, "brock"))
    stored = await service.require(run.id)

    assert stored.status is ChallengeStatus.STAGE_RESULT
    assert stored.current_stage_index == 1
    assert stored.active_match_id is None
    assert stored.auto_advance_at is None
    await asyncio.sleep(0.05)
    assert (await service.require(run.id)).active_match_id is None
    await database.close()


@pytest.mark.asyncio
async def test_fast_watch_loss_never_auto_retries_the_stage(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'fast-watch-loss.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    definition = load_definition("kanto-gym-gauntlet")
    match_id = uuid4()
    run = _run(status=ChallengeStatus.READY).model_copy(
        update={"definition": definition, "battle_experience": "fast-watch"}
    )
    await repository.create(run)
    await BattleRepository(database).create_match(
        match_id,
        _auto_match_config(),
        engine="test",
        engine_version="unit-test",
        showdown_version="unit-test",
        poke_env_version="unit-test",
        challenge_run_id=run.id,
        challenge_stage_id="brock",
    )
    run = await repository.save(
        run.model_copy(update={"status": ChallengeStatus.BATTLING, "active_match_id": match_id}),
        expected_revision=run.revision,
    )
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    lost = _won_archive(run, match_id, "brock").model_copy(update={"winner": Side.P2})

    await service.on_match_terminal(match_id, lost)
    stopped = await service.require(run.id)
    advanced, retry = await service.auto_advance(run.id)

    assert stopped.status is ChallengeStatus.STAGE_RESULT
    assert stopped.stage_results[-1].status == "lost"
    assert stopped.auto_advance_at is None
    assert advanced.id == stopped.id
    assert advanced.revision == stopped.revision
    assert advanced.active_match_id is None
    assert retry is None
    await database.close()


@pytest.mark.asyncio
async def test_no_progress_technical_failure_does_not_count_as_gym_defeat(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'no-progress.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    match_id = uuid4()
    run = _run(status=ChallengeStatus.BATTLING).model_copy(update={"active_match_id": match_id})
    await BattleRepository(database).create_match(
        match_id,
        _auto_match_config(),
        engine="test",
        engine_version="unit-test",
        showdown_version="unit-test",
        poke_env_version="unit-test",
    )
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    archive = _won_archive(run, match_id, "stage-one").model_copy(
        update={
            "status": MatchStatus.FAILED,
            "winner": None,
            "error": "NoProgressBattleError: repeated 'switch:2' submissions",
        }
    )

    await service.on_match_terminal(match_id, archive)

    failed = await service.require(run.id)
    assert failed.status is ChallengeStatus.STAGE_RESULT
    assert failed.current_stage_index == 0
    assert failed.stage_results[-1].status == "failed"
    assert failed.error == archive.error
    await database.close()


@pytest.mark.asyncio
async def test_complete_kanto_stage_chain_is_strict_and_idempotent(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'chain.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    definition = load_definition("kanto-gym-gauntlet")
    expected = (
        "brock",
        "misty",
        "lt-surge",
        "erika",
        "koga",
        "sabrina",
        "blaine",
        "giovanni",
        "lorelei",
        "bruno",
        "agatha",
        "lance",
        "champion-blue",
    )
    assert tuple(stage.id for stage in definition.stages) == expected
    run = _run(status=ChallengeStatus.READY).model_copy(update={"definition": definition})
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    for index, stage_id in enumerate(expected):
        current = await service.require(run.id)
        match_id = uuid4()
        await BattleRepository(database).create_match(
            match_id,
            _auto_match_config(),
            engine="test",
            engine_version="unit-test",
            showdown_version="unit-test",
            poke_env_version="unit-test",
            challenge_run_id=run.id,
            challenge_stage_id=stage_id,
        )
        current = await repository.save(
            current.model_copy(
                update={"status": ChallengeStatus.BATTLING, "active_match_id": match_id}
            ),
            expected_revision=current.revision,
        )
        archive = _won_archive(current, match_id, stage_id)
        await service.on_match_terminal(match_id, archive)
        await service.on_match_terminal(match_id, archive)
        advanced = await service.require(run.id)
        assert advanced.current_stage_index == index + 1
        assert len(advanced.stage_results) == index + 1
    completed = await service.require(run.id)
    assert completed.status is ChallengeStatus.COMPLETED
    assert tuple(result.stage_id for result in completed.stage_results) == expected
    await database.close()


@pytest.mark.asyncio
async def test_final_team_enforces_abilities_then_creates_first_campaign_match(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'team.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run().model_copy(
        update={
            "ability_selections": {"mon1": "ability1h", "mon2": "ability2a", "mon3": "ability3a"}
        }
    )
    await repository.create(run)
    structured = (
        {"species": "Mon 1", "ability": "Ability 1 H", "evs": {"hp": 1}},
        {"species": "Mon 2", "ability": "Ability 2 A", "evs": {"hp": 1}},
        {"species": "Mon 3", "ability": "Ability 3 A", "evs": {"hp": 1}},
    )
    battles = _Battles(structured, BattleRepository(database))
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    export = "\n\n".join(f"Mon {index}\nAbility: Wrong\n- Tackle" for index in range(1, 4))
    finalized = await service.finalize_team(run.id, export, run.revision)
    assert finalized.status is ChallengeStatus.READY
    assert finalized.team_snapshot_id == battles.teams.created.id  # type: ignore[union-attr]
    assert "Ability: Ability 1 H" in battles.team_validator.submitted
    assert "Ability: Wrong" not in battles.team_validator.submitted
    launched, match = await service.launch_stage(run.id, finalized.revision)
    assert launched.status is ChallengeStatus.BATTLE_QUEUED
    assert launched.active_match_id == match.id
    assert match.challenge_run_id == run.id
    assert match.challenge_stage_id == "stage-one"
    assert launched.opponent_controller.agent_type is AgentType.TACTICAL_AUTO
    assert match.config.players[1].agent_type is AgentType.TACTICAL_AUTO
    await database.close()


@pytest.mark.asyncio
async def test_auto_run_pause_continue_and_duplicate_advance_create_one_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'auto-run.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    base = _picked_run()
    second_stage = base.definition.stages[0].model_copy(
        update={"id": "stage-two", "name": "Second Leader"}
    )
    run = base.model_copy(
        update={
            "battle_controller": BattleControllerSnapshot(agent_type=AgentType.RANDOM),
            "definition": base.definition.model_copy(
                update={"stages": (*base.definition.stages, second_stage)}
            ),
        }
    )
    await repository.create(run)
    structured = tuple(
        {"species": f"Mon {index}", "ability": f"Ability {index} A", "evs": {"hp": 1}}
        for index in range(1, 4)
    )
    battles = _Battles(structured, BattleRepository(database))
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    export = "\n\n".join(
        f"Mon {index}\nAbility: Ability {index} A\n- Tackle" for index in range(1, 4)
    )
    finalized = await service.finalize_team(run.id, export, run.revision)
    assert finalized.auto_advance_at is not None

    paused = await service.pause_auto_run(run.id, finalized.revision - 1)
    assert paused.auto_run_paused is True
    assert paused.auto_advance_at is None
    await asyncio.sleep(1.05)
    assert (await service.require(run.id)).active_match_id is None

    continued, first_match = await service.continue_auto_run(run.id, paused.revision)
    assert first_match is not None
    duplicate, duplicate_match = await service.auto_advance(run.id)
    assert duplicate.active_match_id == continued.active_match_id == first_match.id
    assert duplicate_match is not None
    assert duplicate_match.id == first_match.id

    monkeypatch.setitem(AUTO_ADVANCE_DELAYS, "quick-sim", 0.01)
    await service.on_match_terminal(
        first_match.id, _won_archive(duplicate, first_match.id, "stage-one")
    )
    for _ in range(20):
        advanced = await service.require(run.id)
        if advanced.active_match_id not in {None, first_match.id}:
            break
        await asyncio.sleep(0.05)
    assert advanced.current_stage_index == 1
    assert advanced.active_match_id is not None
    assert advanced.active_match_id != first_match.id
    await database.close()


class _CapturingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request: ProviderRequest | None = None
        self.generate_calls = 0
        self.delay = 0.0

    async def generate(self, request: ProviderRequest, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.request = request
        self.generate_calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return await super().generate(request, **kwargs)


@pytest.mark.asyncio
async def test_duplicate_agent_draft_requests_share_one_provider_call(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'agent-coalescing.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = attach_offer(_run()).model_copy(
        update={
            "draft_controller": DraftControllerSnapshot(
                kind=DraftControllerKind.AGENT,
                provider=ProviderKind.FAKE,
                model="fake-battle-v1",
            )
        }
    )
    await repository.create(run)
    provider = _CapturingProvider()
    provider.delay = 0.05
    battles = type(
        "DraftBattleStub", (), {"provider_for_draft": lambda self, controller: provider}
    )()
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )

    first, duplicate = await asyncio.gather(
        service.agent_action(run.id, run.revision),
        service.agent_action(run.id, run.revision),
    )

    assert provider.generate_calls == 1
    assert first == duplicate
    assert len(first.picks) == 1
    await database.close()


@pytest.mark.asyncio
async def test_agent_prompt_explains_consumption_and_contains_no_credit_logic(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'agent.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = attach_offer(_run()).model_copy(
        update={
            "draft_controller": DraftControllerSnapshot(
                kind=DraftControllerKind.AGENT,
                provider=ProviderKind.FAKE,
                model="fake-battle-v1",
            )
        }
    )
    await repository.create(run)
    provider = _CapturingProvider()
    battles = type(
        "DraftBattleStub", (), {"provider_for_draft": lambda self, controller: provider}
    )()
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    await service.agent_action(run.id, run.revision)
    assert provider.request is not None
    assert "disappears after this decision" in provider.request.prompt
    assert "credit" not in provider.request.prompt.lower()
    await database.close()


@pytest.mark.asyncio
async def test_agent_drafter_is_offered_every_reroll_power_a_human_has(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'agent-rerolls.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    # A broad pool so every reroll flavour can actually produce a follow-up offer.
    candidates = tuple(
        _candidate(
            index,
            types=(("Normal",), ("Water",), ("Fire",))[index % 3],
            generation=((index // 3) % 3) + 1,
        )
        for index in range(1, 91)
    )
    run = attach_offer(_run(candidates=candidates)).model_copy(
        update={
            "draft_controller": DraftControllerSnapshot(
                kind=DraftControllerKind.AGENT,
                provider=ProviderKind.FAKE,
                model="fake-battle-v1",
            )
        }
    )
    await repository.create(run)
    provider = _CapturingProvider()
    battles = type(
        "DraftBattleStub", (), {"provider_for_draft": lambda self, controller: provider}
    )()
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )

    await service.agent_action(run.id, run.revision)

    assert provider.request is not None
    schema = provider.request.output_schema or {}
    offered = set(schema["properties"]["action"]["enum"])
    assert {"reroll", "reroll:type", "reroll:generation"} <= offered
    assert "reroll:type" in provider.request.prompt
    await database.close()


def test_legacy_credit_run_is_explicitly_abandoned_instead_of_reinterpreted() -> None:
    run = attach_offer(_run())
    payload = run.model_dump(mode="json")
    pool = payload.pop("draft_pool")
    payload["schema_version"] = "1.0"
    payload.pop("draft_rules_version")
    payload.pop("consumed_species_ids")
    payload.pop("draft_history")
    payload.pop("ability_selections")
    payload["definition"]["draft_rules"]["starting_credits"] = 68
    payload["credits_remaining"] = 68
    payload["pricing"] = {
        "catalog_hash": pool["catalog_hash"],
        "candidates": [{**candidate, "points": 1} for candidate in pool["candidates"]],
    }

    restored = _deserialize_run(json.dumps(payload))

    assert restored.status is ChallengeStatus.ABANDONED
    assert restored.draft_rules_version == "draft-rules-v1-incompatible"
    assert restored.compatibility_notice == LEGACY_NOTICE
    assert restored.current_offer is None


def test_level_and_zero_ev_derivations_do_not_mutate_source() -> None:
    source = "Mon One\nLevel: 37\nEVs: 252 Atk / 4 SpD / 252 Spe\n- Tackle\n\nMon Two\n- Splash"
    derived = _with_level(source, 85)
    assert derived.count("Level: 85") == 2
    assert "Level: 37" not in derived
    assert "EVs: 252 Atk / 5 SpD / 252 Spe" in derived
    assert "EVs: 1 HP" in derived
    assert source.startswith("Mon One\nLevel: 37")
    assert _with_zero_ev_confirmation("Mon One\n- Tackle") == ("Mon One\nEVs: 1 HP\n- Tackle")


def test_duplicate_opponent_species_receive_distinct_showdown_identities() -> None:
    team = "Koffing\n- Tackle\n\nMuk\n- Sludge\n\nKoffing\n- Smog"

    updated = _with_unique_duplicate_nicknames(team)

    assert updated.split("\n\n")[0].splitlines()[0] == "Koffing 1 (Koffing)"
    assert updated.split("\n\n")[1].splitlines()[0] == "Muk"
    assert updated.split("\n\n")[2].splitlines()[0] == "Koffing 2 (Koffing)"


def test_challenge_match_payload_redacts_only_the_opponent_team() -> None:
    now = datetime.now(UTC)
    snapshot_id = uuid4()
    config = MatchConfig(
        format="gen9ou",
        team_policy=TeamPolicy.FIXED,
        players=tuple(
            PlayerConfig(
                side=side,
                display_name=side.value,
                agent_type=AgentType.RANDOM,
                team_source=TeamSource.PRESET,
                team_snapshot_id=snapshot_id,
                team_export=f"{side.value} secret",
                team_packed=f"{side.value} packed",
            )
            for side in (Side.P1, Side.P2)
        ),
    )
    archive = MatchArchive(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        status=MatchStatus.QUEUED,
        config=config,
        engine="test",
        challenge_run_id=uuid4(),
        challenge_stage_id="brock",
    )
    redacted = redact_challenge_match(archive)
    assert redacted.config.players[0].team_export == "p1 secret"
    assert redacted.config.players[0].team_snapshot_id == snapshot_id
    assert redacted.config.players[1].team_export is None
    assert redacted.config.players[1].team_packed is None
    assert redacted.config.players[1].team_snapshot_id is None


def test_species_catalog_filters_temporary_forms_but_keeps_legal_hidden_abilities() -> None:
    metadata = (
        SpeciesMetadata(
            id="rotomwash",
            name="Rotom-Wash",
            base_species_id="rotom",
            national_dex_number=479,
            introduction_generation=4,
            types=("Electric", "Water"),
            abilities=(PokemonAbility(slot="0", id="levitate", name="Levitate"),),
            showdown_set=ShowdownCompetitiveSet(
                source="showdown-battle-factory",
                source_generation=9,
                source_tier="OU",
                species="Rotom-Wash",
                item="Leftovers",
                ability="Levitate",
                nature="Bold",
                moves=("Volt Switch", "Hydro Pump", "Will-O-Wisp", "Protect"),
                evs=EvSpread(hp=252, defense=252, spa=4),
                ivs=PokemonIvSpread(atk=0),
            ),
        ),
        SpeciesMetadata(
            id="charizardmega",
            name="Charizard-Mega",
            base_species_id="charizard",
            national_dex_number=6,
            introduction_generation=6,
            types=("Fire", "Dragon"),
            abilities=(PokemonAbility(slot="0", id="toughclaws", name="Tough Claws"),),
            is_mega=True,
        ),
    )
    candidates, excluded = ChallengeService._candidates(metadata, abilities_supported=True)
    assert [item.entry_id for item in candidates] == ["rotomwash"]
    assert candidates[0].abilities[0].id == "levitate"
    assert excluded[0]["species"] == "Charizard-Mega"


def test_difficulty_modifiers_only_raise_the_opponent_level() -> None:
    assert DIFFICULTY_LEVEL_MODIFIERS[ChallengeDifficulty.NORMAL] == 0
    assert DIFFICULTY_LEVEL_MODIFIERS[ChallengeDifficulty.HARD] == 5
    assert DIFFICULTY_LEVEL_MODIFIERS[ChallengeDifficulty.EXPERT] == 10
    assert DIFFICULTY_LEVEL_MODIFIERS[ChallengeDifficulty.NIGHTMARE] == 15
    assert opponent_stage_level(75, ChallengeDifficulty.NORMAL) == 75
    assert opponent_stage_level(75, ChallengeDifficulty.HARD) == 80
    assert opponent_stage_level(75, ChallengeDifficulty.EXPERT) == 85
    assert opponent_stage_level(75, ChallengeDifficulty.NIGHTMARE) == 90
    assert opponent_stage_level(95, ChallengeDifficulty.NIGHTMARE) == 100


def test_difficulty_defaults_to_normal_and_survives_a_saved_run() -> None:
    default = _run()
    assert default.difficulty is ChallengeDifficulty.NORMAL

    stored = _run().model_copy(update={"difficulty": ChallengeDifficulty.NIGHTMARE})
    restored = _deserialize_run(stored.model_dump_json())

    assert restored.difficulty is ChallengeDifficulty.NIGHTMARE
    # Runs saved before difficulty existed keep working and read as Normal.
    payload = json.loads(stored.model_dump_json())
    payload.pop("difficulty")
    assert ChallengeRun.model_validate(payload).difficulty is ChallengeDifficulty.NORMAL


def test_oversized_saved_error_is_bounded_during_deserialization() -> None:
    payload = json.loads(_run().model_dump_json())
    payload["error"] = "Showdown validation failed. " * 100

    restored = _deserialize_run(json.dumps(payload))

    assert restored.error is not None
    assert len(restored.error) == 1000


@pytest.mark.asyncio
async def test_expert_difficulty_raises_only_the_derived_opponent_stage_team(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'difficulty.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run().model_copy(
        update={
            "difficulty": ChallengeDifficulty.EXPERT,
            "ability_selections": {"mon1": "ability1h", "mon2": "ability2a", "mon3": "ability3a"},
        }
    )
    await repository.create(run)
    structured = (
        {"species": "Mon 1", "ability": "Ability 1 H", "evs": {"hp": 1}},
        {"species": "Mon 2", "ability": "Ability 2 A", "evs": {"hp": 1}},
        {"species": "Mon 3", "ability": "Ability 3 A", "evs": {"hp": 1}},
    )
    battles = _Battles(structured, BattleRepository(database))
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    export = "\n\n".join(f"Mon {index}\nAbility: Wrong\n- Tackle" for index in range(1, 4))
    finalized = await service.finalize_team(run.id, export, run.revision)
    battles.team_validator.submissions.clear()
    launched, _ = await service.launch_stage(run.id, finalized.revision)

    player_text, opponent_text = battles.team_validator.submissions[:2]
    assert "Level: 50" in player_text and "Level: 60" not in player_text
    assert "Level: 60" in opponent_text and "Level: 50" not in opponent_text
    # The immutable drafted snapshot is untouched; only the derived export moved.
    source = await battles.teams.get(launched.team_snapshot_id)
    assert source is not None and "Level: 60" not in source.normalized_export
    await database.close()


@pytest.mark.asyncio
async def test_normal_difficulty_keeps_both_sides_on_the_stage_level(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'difficulty-normal.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run().model_copy(
        update={
            "ability_selections": {"mon1": "ability1h", "mon2": "ability2a", "mon3": "ability3a"}
        }
    )
    await repository.create(run)
    structured = (
        {"species": "Mon 1", "ability": "Ability 1 H", "evs": {"hp": 1}},
        {"species": "Mon 2", "ability": "Ability 2 A", "evs": {"hp": 1}},
        {"species": "Mon 3", "ability": "Ability 3 A", "evs": {"hp": 1}},
    )
    battles = _Battles(structured, BattleRepository(database))
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    export = "\n\n".join(f"Mon {index}\nAbility: Wrong\n- Tackle" for index in range(1, 4))
    finalized = await service.finalize_team(run.id, export, run.revision)
    battles.team_validator.submissions.clear()
    await service.launch_stage(run.id, finalized.revision)

    player_text, opponent_text = battles.team_validator.submissions[:2]
    assert "Level: 50" in player_text
    assert "Level: 50" in opponent_text


def test_public_stages_publish_the_derived_opponent_level() -> None:
    normal = _public_stage_levels(ChallengeDifficulty.NORMAL)
    nightmare = _public_stage_levels(ChallengeDifficulty.NIGHTMARE)

    assert normal == [(50, 50, 50)]
    assert nightmare == [(50, 50, 65)]


def _public_stage_levels(difficulty: ChallengeDifficulty) -> list[tuple[int, int, int]]:
    run = _run().model_copy(update={"difficulty": difficulty})
    service = ChallengeService(
        cast(Any, None), ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    view = service.view(run)
    return [(stage.level, stage.player_level, stage.opponent_level) for stage in view.stages]


def test_automatic_team_preparation_ships_a_complete_set() -> None:
    run = _picked_run()
    run = run.model_copy(
        update={
            "ev_allocations": {
                pick.candidate.entry_id: EvSpread(atk=252, spd=4, spe=252) for pick in run.picks
            }
        }
    )
    scaffold = _team_scaffold(run)
    assert scaffold is not None

    for block in scaffold.split("\n\n"):
        lines = block.splitlines()
        assert "@" in lines[0], block
        assert any(line.endswith(" Nature") for line in lines), block
        assert any(line.startswith("EVs:") for line in lines), block
        assert any(line.startswith("- ") for line in lines), block


@pytest.mark.asyncio
async def test_deleting_a_run_removes_it_and_cancels_its_active_match(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'delete.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run().model_copy(
        update={
            "ability_selections": {"mon1": "ability1h", "mon2": "ability2a", "mon3": "ability3a"}
        }
    )
    await repository.create(run)
    structured = (
        {"species": "Mon 1", "ability": "Ability 1 H", "evs": {"hp": 1}},
        {"species": "Mon 2", "ability": "Ability 2 A", "evs": {"hp": 1}},
        {"species": "Mon 3", "ability": "Ability 3 A", "evs": {"hp": 1}},
    )
    battles = _Battles(structured, BattleRepository(database))
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    export = "\n\n".join(f"Mon {index}\nAbility: Wrong\n- Tackle" for index in range(1, 4))
    finalized = await service.finalize_team(run.id, export, run.revision)
    launched, match = await service.launch_stage(run.id, finalized.revision)

    await service.delete(run.id, launched.revision)

    assert await repository.get(run.id) is None
    assert battles.cancelled == [match.id]
    with pytest.raises(KeyError):
        await service.require(run.id)
    await database.close()


@pytest.mark.asyncio
async def test_deleting_a_run_rejects_a_stale_revision(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'delete-stale.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run()
    await repository.create(run)
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, _Battles(()))
    )

    with pytest.raises(ValueError, match="stale challenge revision"):
        await service.delete(run.id, run.revision + 5)
    assert await repository.get(run.id) is not None
    await database.close()


@pytest.mark.asyncio
async def test_unreachable_validator_parks_preparation_in_team_review(tmp_path: Path) -> None:
    """A validator outage must never strand a finished draft in `preparing` with no state."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'prepare-outage.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _picked_run().model_copy(update={"status": ChallengeStatus.PREPARING})
    await repository.create(run)
    battles = _Battles((), BattleRepository(database))

    async def unavailable(team_text: str, format_id: str) -> TeamValidationResult:
        raise RuntimeError("Showdown team validator is unavailable")

    battles.team_validator.validate = unavailable  # type: ignore[assignment]
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )

    prepared = await service._auto_prepare_team(run.id)

    assert prepared.status is ChallengeStatus.TEAM_REVIEW
    assert prepared.error is not None
    assert "validator" in prepared.error
    assert prepared.team_snapshot_id is None
    await database.close()


def test_agent_draft_actions_survive_providers_without_schema_enforcement() -> None:
    """DeepSeek documents `json_object`, so the enum is not enforced on the wire.

    A correct decision arriving as a bare entry id, a species name or different case used
    to be rejected as "not legal" and surfaced as a provider failure.
    """
    run = attach_offer(_run())
    offer = run.current_offer
    assert offer is not None
    first = offer.options[0]
    legal = [f"pick:{option.entry_id}" for option in offer.options] + [
        "reroll",
        "reroll:type",
        "reroll:generation",
    ]

    assert _resolve_draft_action(f"pick:{first.entry_id}", legal, offer) == f"pick:{first.entry_id}"
    assert _resolve_draft_action(f"  PICK:{first.entry_id.upper()} ", legal, offer) == (
        f"pick:{first.entry_id}"
    )
    assert _resolve_draft_action(first.entry_id, legal, offer) == f"pick:{first.entry_id}"
    assert _resolve_draft_action(first.species.upper(), legal, offer) == f"pick:{first.entry_id}"
    assert _resolve_draft_action("reroll pokemon", legal, offer) == "reroll"
    assert _resolve_draft_action("type reroll", legal, offer) == "reroll:type"
    assert _resolve_draft_action("Generation Reroll", legal, offer) == "reroll:generation"
    # Anything that still cannot be mapped is rejected rather than guessed at.
    assert _resolve_draft_action("pick:not-in-this-offer", legal, offer) is None
    assert _resolve_draft_action("", legal, offer) is None
    # A reroll the run can no longer afford is not offered and must not be invented.
    assert _resolve_draft_action("type reroll", [f"pick:{first.entry_id}"], offer) is None


@pytest.mark.asyncio
async def test_agent_draft_gives_reasoning_models_room_to_answer(tmp_path: Path) -> None:
    """A 256-token cap left reasoning models no budget for the answer itself."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'agent-tokens.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = attach_offer(_run()).model_copy(
        update={
            "draft_controller": DraftControllerSnapshot(
                kind=DraftControllerKind.AGENT,
                provider=ProviderKind.FAKE,
                model="fake-battle-v1",
            )
        }
    )
    await repository.create(run)
    provider = _CapturingProvider()
    battles = type(
        "DraftBattleStub", (), {"provider_for_draft": lambda self, controller: provider}
    )()
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )

    await service.agent_action(run.id, run.revision)

    assert provider.request is not None
    assert provider.request.max_output_tokens >= 512
    await database.close()


def test_runs_saved_by_retired_features_still_load() -> None:
    """`ChallengeRun` forbids extra keys, so a stale field takes the whole backend down.

    Runs written while post-battle training rewards existed carry `pending_reward` and
    `training_rewards`; loading one raised on startup and the API refused to boot.
    """
    run = _picked_run()
    payload = json.loads(run.model_dump_json())
    payload["pending_reward"] = None
    payload["training_rewards"] = [{"stage_index": 0, "stage_id": "stage-one", "option": {}}]

    restored = _deserialize_run(json.dumps(payload))

    assert restored.id == run.id
    assert restored.status is run.status
    assert not hasattr(restored, "pending_reward")


async def _attach_match(
    battles: Any, repository: ChallengeRepository, run: ChallengeRun, stage_id: str
) -> tuple[ChallengeRun, UUID]:
    """Give the run a real linked match row; `active_match_id` has a foreign key."""
    config = MatchConfig(
        players=(
            PlayerConfig(side=Side.P1, display_name="Player", agent_type=AgentType.TACTICAL_AUTO),
            PlayerConfig(side=Side.P2, display_name="Leader", agent_type=AgentType.TACTICAL_AUTO),
        )
    )
    match = await battles.create_match(config, challenge_run_id=run.id, challenge_stage_id=stage_id)
    stored = await repository.save(
        run.model_copy(update={"active_match_id": match.id}), expected_revision=run.revision
    )
    return stored, match.id


def test_downed_pokemon_are_left_out_of_the_derived_stage_team() -> None:
    run = _picked_run()
    export = "\n\n".join(
        f"{pick.candidate.species} @ Leftovers\nEVs: 4 HP\n- Tackle" for pick in run.picks
    )
    first = run.picks[0].candidate

    # Nothing down: the export is returned untouched.
    assert _without_downed(export, run) == export

    knocked = run.model_copy(update={"downed_entry_ids": (first.entry_id,)})
    reduced = _without_downed(export, knocked)
    assert first.species not in reduced
    assert len(reduced.split("\n\n")) == len(run.picks) - 1

    # A wipe must never produce an empty team; the export is kept whole instead.
    everyone = run.model_copy(
        update={"downed_entry_ids": tuple(pick.candidate.entry_id for pick in run.picks)}
    )
    assert _without_downed(export, everyone) == export


def test_fainted_species_map_back_onto_drafted_entries() -> None:
    run = _picked_run()
    first, second = run.picks[0].candidate, run.picks[1].candidate
    summary = ChallengeBattleSummary(
        match_id=uuid4(),
        player_fainted=(first.species, "Not On This Team"),
        opponent_fainted=(second.species,),
    )

    assert _knocked_out_entry_ids(run, summary) == (first.entry_id,)


@pytest.mark.asyncio
async def test_a_won_gauntlet_stage_carries_casualties_and_a_gym_heals(tmp_path: Path) -> None:
    """The Elite Four is one sitting; every Gym Leader starts from a full roster."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'gauntlet.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    base = _picked_run()
    gauntlet = base.definition.stages[0].model_copy(
        update={"id": "stage-two", "name": "Second", "full_heal_before": False}
    )
    healed = base.definition.stages[0].model_copy(
        update={"id": "stage-three", "name": "Third", "full_heal_before": True}
    )
    run = base.model_copy(
        update={
            "battle_controller": BattleControllerSnapshot(agent_type=AgentType.HUMAN),
            "definition": base.definition.model_copy(
                update={"stages": (*base.definition.stages, gauntlet, healed)}
            ),
        }
    )
    await repository.create(run)
    battles = _Battles((), BattleRepository(database))
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    stored, match_id = await _attach_match(battles, repository, run, "stage-one")
    archive = _won_archive(stored, match_id, "stage-one")

    await service.on_match_terminal(match_id, archive)
    advanced = await service.require(run.id)

    # Stage two does not heal, so whatever fainted stays out.
    assert advanced.current_stage_index == 1
    assert advanced.definition.stages[1].full_heal_before is False
    carried = advanced.downed_entry_ids

    # Winning into a stage that heals clears the list again.
    stored, second_match = await _attach_match(battles, repository, advanced, "stage-two")
    await service.on_match_terminal(second_match, _won_archive(stored, second_match, "stage-two"))
    healed_run = await service.require(run.id)
    assert healed_run.current_stage_index == 2
    assert healed_run.downed_entry_ids == ()
    assert isinstance(carried, tuple)
    await database.close()


@pytest.mark.asyncio
async def test_a_lost_stage_never_carries_casualties_into_the_retry(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'gauntlet-loss.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    base = _picked_run()
    gauntlet = base.definition.stages[0].model_copy(
        update={"id": "stage-two", "name": "Second", "full_heal_before": False}
    )
    run = base.model_copy(
        update={
            "battle_controller": BattleControllerSnapshot(agent_type=AgentType.HUMAN),
            "definition": base.definition.model_copy(
                update={"stages": (*base.definition.stages, gauntlet)}
            ),
            "downed_entry_ids": (base.picks[0].candidate.entry_id,),
        }
    )
    await repository.create(run)
    battles = _Battles((), BattleRepository(database))
    service = ChallengeService(
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, battles)
    )
    stored, match_id = await _attach_match(battles, repository, run, "stage-one")
    lost = _won_archive(stored, match_id, "stage-one").model_copy(update={"winner": Side.P2})

    await service.on_match_terminal(match_id, lost)
    retried = await service.require(run.id)

    assert retried.stage_results[-1].status == "lost"
    assert retried.current_stage_index == 0
    assert retried.downed_entry_ids == ()
    await database.close()
