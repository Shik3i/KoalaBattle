from __future__ import annotations

import pytest

from koalabattle.agents.providers import FakeProvider, ProviderError, ProviderRequest
from koalabattle.core.models import ProviderErrorCategory, ProviderKind, TeamSource
from koalabattle.storage import Database
from koalabattle.teams import TeamBuilder, TeamBuildRequest, TeamRepository
from koalabattle.teams.models import (
    MAX_TEAM_TEXT_LENGTH,
    TeamPromptContext,
    TeamValidationResult,
)
from koalabattle.teams.service import render_team_prompt
from koalabattle.teams.validator import ShowdownTeamValidator


class _AcceptingValidator:
    async def validate(self, team_text: str, format_id: str) -> TeamValidationResult:
        return TeamValidationResult(
            valid=True,
            normalized_export=team_text,
            packed_team="packed-team",
            structured_team=({"species": "Great Tusk"},),
        )


class _RepairingValidator:
    def __init__(self, valid_after: int | None) -> None:
        self.calls = 0
        self.valid_after = valid_after

    async def validate(self, team_text: str, format_id: str) -> TeamValidationResult:
        self.calls += 1
        if self.valid_after is None or self.calls < self.valid_after:
            return TeamValidationResult(valid=False, errors=("Pikachu has an illegal move.",))
        return TeamValidationResult(
            valid=True,
            normalized_export=team_text,
            packed_team="repaired-packed-team",
            structured_team=({"species": "Great Tusk"},),
        )


class _ProviderErrorThenValid(FakeProvider):
    async def generate(self, request: ProviderRequest, **kwargs):  # type: ignore[no-untyped-def]
        if request.output_schema_name == "koalabattle_team" and self.calls == 0:
            self.calls += 1
            raise ProviderError(
                ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                "temporary local provider failure",
                retryable=True,
            )
        return await super().generate(request, **kwargs)


@pytest.mark.asyncio
async def test_imported_team_snapshot_is_immutable_and_reopenable(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'teams.db'}")
    await database.create_schema()
    repository = TeamRepository(database)
    validation = TeamValidationResult(
        valid=True,
        normalized_export="Pikachu\n- Thunderbolt",
        packed_team="Pikachu||||thunderbolt",
        structured_team=({"species": "Pikachu", "moves": ["Thunderbolt"]},),
    )
    snapshot = await repository.create_snapshot(
        name="Imported fixture",
        source=TeamSource.IMPORTED,
        submitted_text="Pikachu\n- Thunderbolt",
        validation=validation,
    )
    await database.close()

    reopened = Database(f"sqlite+aiosqlite:///{tmp_path / 'teams.db'}")
    stored = await TeamRepository(reopened).get(snapshot.id)
    assert stored == snapshot
    assert stored is not None and stored.packed_team == "Pikachu||||thunderbolt"
    await reopened.close()


@pytest.mark.asyncio
async def test_fake_provider_team_build_persists_audit_without_paid_calls(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'build.db'}")
    await database.create_schema()
    repository = TeamRepository(database)
    builder = TeamBuilder(repository, _AcceptingValidator())
    audit, snapshot = await builder.build(
        TeamBuildRequest(
            name="Generated fixture",
            participant="Fake",
            provider=ProviderKind.FAKE,
            model="fake-battle-v1",
        ),
        FakeProvider(),
    )
    assert audit.success
    assert audit.team_snapshot_id == snapshot.id  # type: ignore[union-attr]
    assert audit.raw_responses
    assert await repository.get_build_audit(audit.id) == audit
    await database.close()


@pytest.mark.asyncio
async def test_team_input_rejects_size_format_and_control_characters_before_network() -> None:
    validator = ShowdownTeamValidator("http://127.0.0.1:9")
    with pytest.raises(ValueError, match="pinned Showdown registry"):
        await validator.validate("Pikachu", "not-a-real-format")
    with pytest.raises(ValueError, match="generates its own teams"):
        await validator.validate("Pikachu", "gen9randombattle")
    # Past-generation custom formats now reach the validator instead of being refused locally.
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        await validator.validate("x" * (MAX_TEAM_TEXT_LENGTH + 1), "gen1ou")
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        await validator.validate("x" * (MAX_TEAM_TEXT_LENGTH + 1), "gen9ou")
    with pytest.raises(ValueError, match="control characters"):
        await validator.validate("Pikachu\x00", "gen9ou")


@pytest.mark.asyncio
async def test_team_builder_repairs_with_exact_errors_and_aggregates_usage(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'repair.db'}")
    await database.create_schema()
    repository = TeamRepository(database)
    validator = _RepairingValidator(valid_after=2)
    provider = FakeProvider()
    audit, snapshot = await TeamBuilder(repository, validator).build(
        TeamBuildRequest(
            name="Repaired",
            participant="Fake",
            provider=ProviderKind.FAKE,
            model="fake-battle-v1",
            max_repair_attempts=2,
        ),
        provider,
    )
    assert audit.success and snapshot is not None
    assert audit.repair_attempts == 1
    assert audit.validation_errors[0] == ("Pikachu has an illegal move.",)
    assert audit.usage is not None and audit.usage.total_tokens == 1_800
    assert provider.calls == 2
    await database.close()


@pytest.mark.asyncio
async def test_team_builder_retries_transient_provider_errors_and_records_format(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'provider-retry.db'}")
    await database.create_schema()
    repository = TeamRepository(database)
    provider = _ProviderErrorThenValid()
    audit, snapshot = await TeamBuilder(repository, _AcceptingValidator()).build(
        TeamBuildRequest(
            name="Provider retry",
            participant="Fake",
            format="gen9ou",
            provider=ProviderKind.FAKE,
            model="fake-battle-v1",
        ),
        provider,
    )
    assert audit.success and snapshot is not None
    assert audit.format == "gen9ou"
    assert audit.validation_errors[0] == (
        "provider provider_unavailable: temporary local provider failure",
    )
    assert provider.calls == 2
    await database.close()


def test_gen1_team_prompt_contains_validator_checked_seed_sets() -> None:
    prompt = render_team_prompt(
        "gen1ou",
        "Gemma",
        TeamPromptContext(
            format_name="[Gen 1] OU",
            generation=1,
            has_items=False,
            has_abilities=False,
            has_natures=False,
        ),
        response="json",
    )
    assert "approved_seed_sets" in prompt
    assert '"Tauros"' in prompt
    assert '"Lovely Kiss"' in prompt
    assert "Do not invent any species or move outside that table." in prompt


@pytest.mark.asyncio
async def test_team_builder_stops_at_repair_limit_and_persists_failure(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'repair-limit.db'}")
    await database.create_schema()
    repository = TeamRepository(database)
    provider = FakeProvider()
    audit, snapshot = await TeamBuilder(repository, _RepairingValidator(None)).build(
        TeamBuildRequest(
            name="Rejected",
            participant="Fake",
            provider=ProviderKind.FAKE,
            model="fake-battle-v1",
            max_repair_attempts=1,
        ),
        provider,
    )
    assert snapshot is None and not audit.success
    assert audit.repair_attempts == 1
    assert provider.calls == 2
    assert await repository.get_build_audit(audit.id) == audit
    await database.close()
