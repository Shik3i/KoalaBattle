from __future__ import annotations

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
    BattleControllerSnapshot,
    ChallengeDefinition,
    ChallengeRun,
    ChallengeSource,
    ChallengeStage,
    ChallengeStatus,
    DraftCandidate,
    DraftControllerKind,
    DraftControllerSnapshot,
    DraftHistoryEntry,
    DraftPick,
    DraftPoolSnapshot,
    DraftRules,
    EvSpread,
    PokemonAbility,
    TrainingRules,
)
from koalabattle.challenges.repository import (
    LEGACY_NOTICE,
    ChallengeRepository,
    _deserialize_run,
)
from koalabattle.challenges.service import (
    ChallengeService,
    _team_scaffold,
    _with_level,
    _with_zero_ev_confirmation,
    redact_challenge_match,
)
from koalabattle.challenges.species import ShowdownSpeciesCatalog, SpeciesMetadata
from koalabattle.core.models import (
    AgentType,
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


def _candidate(
    index: int,
    *,
    base_species_id: str | None = None,
    types: tuple[str, ...] = ("Normal",),
    abilities: tuple[PokemonAbility, ...] | None = None,
    generation: int = 1,
) -> DraftCandidate:
    return DraftCandidate(
        entry_id=f"mon{index}",
        species=f"Mon {index}",
        showdown_id=f"mon{index}",
        base_species_id=base_species_id or f"mon{index}",
        national_dex_number=index,
        introduction_generation=generation,
        types=types,
        base_stat_total=300 + index,
        abilities=_abilities(index) if abilities is None else abilities,
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
    assert rerolled.draft_history[-1].outcome == "rerolled"
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
            (1, 1, "Water"), (2, 1, "Water"), (3, 1, "Water"),
            (4, 1, "Fire"), (5, 1, "Fire"), (6, 1, "Fire"),
            (7, 2, "Water"), (8, 2, "Water"), (9, 2, "Water"),
            (10, 2, "Fire"), (11, 2, "Fire"), (12, 2, "Fire"),
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
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
    )
    original = run.current_offer
    assert original is not None

    type_rerolled = await service.reroll(
        run.id, original.fingerprint, run.revision, kind="type"
    )
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
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
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
    assert run.status is ChallengeStatus.TRAINING
    assert len(run.picks) == 3
    assert run.ability_selections == {
        pick.candidate.entry_id: pick.candidate.abilities[0].id for pick in run.picks
    }
    assert set(run.ev_allocations) == {pick.candidate.entry_id for pick in run.picks}
    assert all(spread.total == 508 for spread in run.ev_allocations.values())
    trained = await service.save_training(run.id, run.ev_allocations, run.revision)
    assert trained.status is ChallengeStatus.TEAM_REVIEW
    assert sum(spread.total for spread in trained.ev_allocations.values()) == 1524
    public = service.view(run)
    assert {item.entry_id for item in public.run.draft_pool.candidates} == {
        candidate.entry_id for history in run.draft_history for candidate in history.offer.options
    }
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
        repository, ShowdownSpeciesCatalog("http://127.0.0.1:9"), cast(Any, None)
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
        update={"recommended_move": "Thunderbolt", "required_item": "Magnet"}
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

    async def validate(self, team_text: str, format_id: str) -> TeamValidationResult:
        self.submitted = team_text
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
    await database.close()


class _CapturingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request: ProviderRequest | None = None

    async def generate(self, request: ProviderRequest, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.request = request
        return await super().generate(request, **kwargs)


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
