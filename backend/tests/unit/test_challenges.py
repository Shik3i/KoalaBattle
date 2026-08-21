from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from koalabattle.agents.providers.fake import FakeProvider
from koalabattle.challenges.domain import (
    feasible_candidates,
    generate_offer,
    minimum_completion_cost,
)
from koalabattle.challenges.models import (
    BattleControllerSnapshot,
    ChallengeDefinition,
    ChallengeRun,
    ChallengeSource,
    ChallengeStage,
    ChallengeStatus,
    CreateChallengeRun,
    DraftCandidate,
    DraftControllerKind,
    DraftControllerSnapshot,
    DraftPick,
    DraftRules,
    EvSpread,
    PricingCatalogSnapshot,
    TrainingRules,
)
from koalabattle.challenges.pricing import DraftPriceStore, parse_catalog
from koalabattle.challenges.repository import ChallengeRepository
from koalabattle.challenges.service import (
    ChallengeService,
    _with_level,
    _with_zero_ev_confirmation,
    redact_challenge_match,
)
from koalabattle.challenges.species import ShowdownSpeciesCatalog
from koalabattle.core.models import (
    AgentConfiguration,
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


def _candidate(index: int, points: int = 1) -> DraftCandidate:
    return DraftCandidate(
        entry_id=f"mon{index}",
        species=f"Mon {index}",
        showdown_id=f"mon{index}",
        base_species_id=f"mon{index}",
        national_dex_number=index,
        introduction_generation=1,
        types=("Normal",),
        points=points,
    )


def _run(
    *,
    candidates: tuple[DraftCandidate, ...] | None = None,
    draft_rules: DraftRules | None = None,
    status: ChallengeStatus = ChallengeStatus.DRAFTING,
) -> ChallengeRun:
    now = datetime.now(UTC)
    definition = ChallengeDefinition(
        id="fixture",
        version="1",
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
        draft_rules=draft_rules or DraftRules(roster_size=3, starting_credits=6, choice_count=3),
        training_rules=TrainingRules(global_ev_budget=1200),
        stages=(
            ChallengeStage(
                id="stage-one",
                name="Fixture Leader",
                title="Test Stage",
                theme="Deterministic",
                level=50,
                opponent_team="Mon 9\n- Tackle",
            ),
        ),
    )
    return ChallengeRun(
        id=uuid4(),
        name="Fixture run",
        definition=definition,
        status=status,
        seed=987654,
        pricing=PricingCatalogSnapshot(
            schema_version="1.0",
            parser_version="1.0",
            board_name="Synthetic board",
            context="sv-natdex",
            imported_at=now,
            source_sha256="a" * 64,
            catalog_hash="b" * 64,
            parsed_entries=8,
            candidates=candidates or tuple(_candidate(index) for index in range(1, 9)),
        ),
        draft_controller=DraftControllerSnapshot(kind=DraftControllerKind.HUMAN),
        battle_controller=BattleControllerSnapshot(agent_type=AgentType.HUMAN),
        opponent_controller=BattleControllerSnapshot(agent_type=AgentType.RANDOM),
        credits_remaining=definition.draft_rules.starting_credits,
        rerolls_remaining=definition.draft_rules.rerolls,
        created_at=now,
        updated_at=now,
    )


def test_seeded_generation_type_offer_is_reproducible() -> None:
    run = _run()
    first = generate_offer(run)
    second = generate_offer(run)
    assert first == second
    assert first.generation == 1 and first.type == "Normal"
    assert len(first.options) == 3


def test_budget_dead_end_candidate_is_removed_before_offer() -> None:
    candidates = (_candidate(1, 4), _candidate(2), _candidate(3), _candidate(4), _candidate(5))
    run = _run(
        candidates=candidates,
        draft_rules=DraftRules(roster_size=3, starting_credits=5, choice_count=3),
    )
    assert "mon1" not in {item.entry_id for item in feasible_candidates(run)}
    assert "mon1" not in {item.entry_id for item in generate_offer(run).options}


def test_exhausted_pool_falls_back_to_one_persisted_budget_safe_choice() -> None:
    candidates = (_candidate(1, 2), _candidate(2, 2), _candidate(3, 2))
    run = _run(candidates=candidates)
    picks = tuple(
        DraftPick(
            round=index,
            offer_fingerprint="c" * 64,
            candidate=candidate,
            selected_by=DraftControllerKind.HUMAN,
        )
        for index, candidate in enumerate(candidates[:2], start=1)
    )
    run = run.model_copy(update={"picks": picks, "credits_remaining": 2})

    offer = generate_offer(run)

    assert [item.entry_id for item in offer.options] == ["mon3"]
    assert minimum_completion_cost(run) == 2


@pytest.mark.asyncio
async def test_offer_and_reroll_survive_repository_restart_without_rerolling(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'challenge.db'}"
    database = Database(database_url)
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _run()
    run = run.model_copy(update={"current_offer": generate_offer(run)})
    await repository.create(run)
    service = ChallengeService(
        repository,
        DraftPriceStore(tmp_path / "prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, None),
    )
    rerolled = await service.reroll(
        run.id,
        run.current_offer.fingerprint,
        run.revision,  # type: ignore[union-attr]
    )
    with pytest.raises(ValueError, match="stale challenge revision"):
        await service.reroll(
            run.id,
            rerolled.current_offer.fingerprint,  # type: ignore[union-attr]
            run.revision,
        )
    await database.close()

    reopened = Database(database_url)
    persisted = await ChallengeRepository(reopened).get(run.id)
    assert persisted is not None
    assert persisted.current_offer == rerolled.current_offer
    assert persisted.current_offer != run.current_offer
    assert persisted.rerolls_remaining == run.rerolls_remaining - 1
    await reopened.close()


@pytest.mark.asyncio
async def test_failed_agent_draft_can_be_taken_over_without_accepting_late_agent_work(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'takeover.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _run().model_copy(
        update={
            "draft_controller": DraftControllerSnapshot(
                kind=DraftControllerKind.AGENT,
                provider=ProviderKind.FAKE,
                model="fake-battle-v1",
            )
        }
    )
    run = run.model_copy(update={"current_offer": generate_offer(run)})
    await repository.create(run)
    service = ChallengeService(
        repository,
        DraftPriceStore(tmp_path / "prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, None),
    )

    taken_over = await service.take_over_draft(run.id, run.revision)
    assert taken_over.draft_controller.kind is DraftControllerKind.HUMAN
    assert taken_over.draft_controller_history == (run.draft_controller,)
    with pytest.raises(ValueError, match="stale challenge revision"):
        await service.pick(
            run.id,
            run.current_offer.options[0].entry_id,  # type: ignore[union-attr]
            run.current_offer.fingerprint,  # type: ignore[union-attr]
            run.revision,
            selected_by=DraftControllerKind.AGENT,
        )
    picked = await service.pick(
        run.id,
        taken_over.current_offer.options[0].entry_id,  # type: ignore[union-attr]
        taken_over.current_offer.fingerprint,  # type: ignore[union-attr]
        taken_over.revision,
    )
    assert picked.picks[-1].selected_by is DraftControllerKind.HUMAN
    await database.close()


@pytest.mark.asyncio
async def test_agent_draft_provider_failure_keeps_the_exact_offer_retryable(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'agent-failure.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _run().model_copy(
        update={
            "draft_controller": DraftControllerSnapshot(
                kind=DraftControllerKind.AGENT,
                provider=ProviderKind.FAKE,
                model="fake-battle-v1",
                configuration=AgentConfiguration(max_retries=0, fake_scenario="provider_error"),
            )
        }
    )
    run = run.model_copy(update={"current_offer": generate_offer(run)})
    await repository.create(run)
    provider = FakeProvider("provider_error")
    battles = type(
        "DraftBattleStub",
        (),
        {"provider_for_draft": lambda self, controller: provider},
    )()
    service = ChallengeService(
        repository,
        DraftPriceStore(tmp_path / "prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, battles),
    )

    with pytest.raises(ValueError, match="deterministic fake provider failure"):
        await service.agent_action(run.id, run.revision)

    restored = await repository.get(run.id)
    assert restored is not None
    assert restored.revision == run.revision
    assert restored.current_offer == run.current_offer
    await database.close()


@pytest.mark.asyncio
async def test_existing_run_remains_readable_without_local_pricing_catalog(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'snapshot.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _run()
    run = run.model_copy(update={"current_offer": generate_offer(run)})
    await repository.create(run)
    service = ChallengeService(
        repository,
        DraftPriceStore(tmp_path / "missing-prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, None),
    )

    status = await service.pricing_status()
    restored = await service.get(run.id)

    assert not status.ready and not status.available
    assert restored.run.pricing.catalog_hash == run.pricing.catalog_hash
    assert restored.run.current_offer == run.current_offer
    await database.close()


@pytest.mark.asyncio
async def test_new_run_is_blocked_when_pricing_source_cannot_be_verified(tmp_path: Path) -> None:
    source = b"Pokemon,SV NatDex\n" + b"".join(
        f"Mon {index},{index}\n".encode() for index in range(1, 7)
    )
    store = DraftPriceStore(tmp_path / "prices")
    store.save(
        parse_catalog(
            source,
            "source.csv",
            board_name="Fixture",
            context="sv-natdex",
            price_column="SV NatDex",
        )
    )
    service = ChallengeService(
        cast(Any, None),
        store,
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, None),
    )
    payload = CreateChallengeRun(
        seed=1,
        draft_controller=DraftControllerSnapshot(kind=DraftControllerKind.HUMAN),
        battle_controller=BattleControllerSnapshot(agent_type=AgentType.HUMAN),
        opponent_controller=BattleControllerSnapshot(agent_type=AgentType.RANDOM),
    )

    with pytest.raises(ValueError, match="draft pricing verification failed"):
        await service.create(payload)


@pytest.mark.asyncio
async def test_training_budget_and_per_pokemon_limits_are_enforced(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'training.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _run(status=ChallengeStatus.TRAINING)
    picks = tuple(
        DraftPick(
            round=index,
            offer_fingerprint="c" * 64,
            candidate=candidate,
            selected_by=DraftControllerKind.HUMAN,
        )
        for index, candidate in enumerate(run.pricing.candidates[:3], start=1)
    )
    run = run.model_copy(update={"picks": picks})
    await repository.create(run)
    service = ChallengeService(
        repository,
        DraftPriceStore(tmp_path / "prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, None),
    )
    allocations = {candidate.entry_id: EvSpread(hp=200) for candidate in run.pricing.candidates[:3]}
    saved = await service.save_training(run.id, allocations, run.revision)
    assert saved.status is ChallengeStatus.TEAM_REVIEW
    assert sum(item.total for item in saved.ev_allocations.values()) == 600
    await database.close()


class _Teams:
    def __init__(self) -> None:
        self.created: TeamSnapshot | None = None

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
        return self.created


class _Validator:
    def __init__(self, structured: tuple[dict[str, object], ...]) -> None:
        self.structured = structured

    async def validate(self, team_text: str, format_id: str) -> TeamValidationResult:
        return TeamValidationResult(
            format=format_id,
            valid=True,
            normalized_export=team_text,
            packed_team="packed",
            structured_team=self.structured,
        )


class _Battles:
    def __init__(self, structured: tuple[dict[str, object], ...]) -> None:
        self.teams = _Teams()
        self.team_validator = _Validator(structured)
        self.cancelled: list[UUID] = []

    async def cancel_match(self, match_id: UUID) -> None:
        self.cancelled.append(match_id)


@pytest.mark.asyncio
async def test_final_team_must_match_roster_and_training_then_locks_snapshot(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'team.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _run(status=ChallengeStatus.TEAM_REVIEW)
    candidates = run.pricing.candidates[:3]
    allocations = {
        candidate.entry_id: EvSpread(hp=0 if index == 0 else 200)
        for index, candidate in enumerate(candidates)
    }
    picks = tuple(
        DraftPick(
            round=index,
            offer_fingerprint="c" * 64,
            candidate=candidate,
            selected_by=DraftControllerKind.HUMAN,
        )
        for index, candidate in enumerate(candidates, start=1)
    )
    run = run.model_copy(update={"picks": picks, "ev_allocations": allocations})
    await repository.create(run)
    structured = tuple(
        {"species": item.species, "evs": {"hp": 1 if index == 0 else 200}}
        for index, item in enumerate(candidates)
    )
    battles = _Battles(structured)
    service = ChallengeService(
        repository,
        DraftPriceStore(tmp_path / "prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, battles),
    )
    finalized = await service.finalize_team(run.id, "synthetic legal export", run.revision)
    assert finalized.status is ChallengeStatus.READY
    assert finalized.team_snapshot_id == battles.teams.created.id  # type: ignore[union-attr]
    await database.close()


@pytest.mark.asyncio
async def test_normal_match_link_and_stage_completion_are_durable(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'progress.db'}")
    await database.create_schema()
    challenges = ChallengeRepository(database)
    battles = BattleRepository(database)
    match_id = uuid4()
    run = _run(status=ChallengeStatus.BATTLE_QUEUED)
    await challenges.create(run)
    config = MatchConfig(
        players=(
            PlayerConfig(side=Side.P1, display_name="Player", agent_type=AgentType.RANDOM),
            PlayerConfig(side=Side.P2, display_name="Leader", agent_type=AgentType.RANDOM),
        )
    )
    await battles.create_match(
        match_id,
        config,
        engine="test",
        engine_version="1",
        showdown_version="pinned",
        poke_env_version="0.15.0",
        challenge_run_id=run.id,
        challenge_stage_id="stage-one",
    )
    linked = await battles.get_match(match_id)
    assert linked is not None
    assert linked.challenge_run_id == run.id and linked.challenge_stage_id == "stage-one"
    run = await challenges.save(
        run.model_copy(update={"active_match_id": match_id}), expected_revision=run.revision
    )
    await battles.set_status(match_id, MatchStatus.QUEUED)
    await battles.set_status(match_id, MatchStatus.STARTING)
    service = ChallengeService(
        challenges,
        DraftPriceStore(tmp_path / "prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, type("BattleStub", (), {"repository": battles})()),
    )
    active = await service.get(run.id)
    assert active.run.status is ChallengeStatus.BATTLING
    run = await challenges.get(run.id)
    assert run is not None
    completed = linked.model_copy(
        update={"status": MatchStatus.COMPLETED, "winner": Side.P1, "turns": 12}
    )
    await service.on_match_terminal(match_id, completed)
    await service.on_match_terminal(match_id, completed)
    progressed = await challenges.get(run.id)
    assert progressed is not None and progressed.status is ChallengeStatus.COMPLETED
    assert progressed.stage_results[0].match_id == match_id
    assert progressed.stage_results[0].turns == 12
    assert len(progressed.stage_results) == 1
    assert service.view(progressed).statistics.total_battles == 1
    assert service.view(progressed).run.definition.stages[0].opponent_team == "[private stage team]"
    await database.close()


@pytest.mark.asyncio
async def test_failed_stage_remains_retryable_and_run_cancellation_stops_active_match(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'terminal.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    battle_repository = BattleRepository(database)
    battles = _Battles(())
    service = ChallengeService(
        repository,
        DraftPriceStore(tmp_path / "prices"),
        ShowdownSpeciesCatalog("http://127.0.0.1:9"),
        cast(Any, battles),
    )
    config = MatchConfig(
        players=(
            PlayerConfig(side=Side.P1, display_name="Player", agent_type=AgentType.RANDOM),
            PlayerConfig(side=Side.P2, display_name="Leader", agent_type=AgentType.RANDOM),
        )
    )

    failed_match_id = uuid4()
    failed_run = _run(status=ChallengeStatus.BATTLE_QUEUED)
    await repository.create(failed_run)
    await battle_repository.create_match(
        failed_match_id,
        config,
        engine="test",
        engine_version="1",
        showdown_version="pinned",
        poke_env_version="0.15.0",
        challenge_run_id=failed_run.id,
        challenge_stage_id="stage-one",
    )
    failed_run = await repository.save(
        failed_run.model_copy(
            update={"status": ChallengeStatus.BATTLING, "active_match_id": failed_match_id}
        ),
        expected_revision=failed_run.revision,
    )
    now = datetime.now(UTC)
    archive = MatchArchive(
        id=failed_match_id,
        created_at=now,
        updated_at=now,
        status=MatchStatus.FAILED,
        config=config,
        engine="test",
        error="synthetic engine failure",
        challenge_run_id=failed_run.id,
        challenge_stage_id="stage-one",
    )
    await service.on_match_terminal(failed_match_id, archive)
    retryable = await repository.get(failed_run.id)
    assert retryable is not None
    assert retryable.status is ChallengeStatus.STAGE_RESULT
    assert retryable.current_stage_index == 0
    assert retryable.active_match_id is None
    assert retryable.stage_results[-1].status == "failed"
    assert retryable.error == "synthetic engine failure"

    active_match_id = uuid4()
    active_run = _run(status=ChallengeStatus.BATTLE_QUEUED)
    await repository.create(active_run)
    await battle_repository.create_match(
        active_match_id,
        config,
        engine="test",
        engine_version="1",
        showdown_version="pinned",
        poke_env_version="0.15.0",
        challenge_run_id=active_run.id,
        challenge_stage_id="stage-one",
    )
    active_run = await repository.save(
        active_run.model_copy(
            update={"status": ChallengeStatus.BATTLING, "active_match_id": active_match_id}
        ),
        expected_revision=active_run.revision,
    )
    cancelled = await service.cancel(active_run.id, active_run.revision)
    assert cancelled.status is ChallengeStatus.CANCELLED
    assert cancelled.active_match_id is None
    assert battles.cancelled == [active_match_id]
    await database.close()


def test_level_normalization_replaces_or_inserts_without_mutating_source() -> None:
    source = "Mon One\nLevel: 37\nEVs: 252 Atk / 4 SpD / 252 Spe\n- Tackle\n\nMon Two\n- Splash"
    derived = _with_level(source, 85)
    assert derived.count("Level: 85") == 2
    assert "Level: 37" not in derived
    assert "EVs: 252 Atk / 5 SpD / 252 Spe" in derived
    assert "EVs: 1 HP" in derived
    assert source.startswith("Mon One\nLevel: 37")


def test_level_100_never_adds_the_showdown_low_level_confirmation_marker() -> None:
    source = "Mon One\nEVs: 252 Atk / 4 SpD / 252 Spe\n- Tackle"
    assert _with_level(source, 100) == (
        "Mon One\nLevel: 100\nEVs: 252 Atk / 4 SpD / 252 Spe\n- Tackle"
    )


def test_zero_ev_confirmation_is_derived_without_mutating_source() -> None:
    source = "Mon One\nAbility: Sturdy\n- Tackle\n\nMon Two\nEVs: 0 HP\n- Splash"
    derived = _with_zero_ev_confirmation(source)
    assert derived.count("EVs: 1 HP") == 2
    assert "EVs:" not in source.split("\n\n")[0]


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
