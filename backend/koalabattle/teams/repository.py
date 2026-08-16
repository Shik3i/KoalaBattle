from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from koalabattle.core.models import ProviderUsage, TeamSource
from koalabattle.models.orm import TeamBuildAuditRow, TeamSnapshotRow
from koalabattle.storage.database import Database

from .models import TeamBuildAudit, TeamSnapshot, TeamValidationResult


class TeamRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_snapshot(
        self,
        *,
        name: str,
        source: TeamSource,
        submitted_text: str,
        validation: TeamValidationResult,
        generation_audit: dict[str, object] | None = None,
    ) -> TeamSnapshot:
        if not validation.valid or not validation.normalized_export or not validation.packed_team:
            raise ValueError("only Showdown-validated teams can be persisted")
        row = TeamSnapshotRow(
            id=str(uuid4()),
            name=name,
            format=validation.format,
            source=source.value,
            submitted_text=submitted_text,
            normalized_export=validation.normalized_export,
            packed_team=validation.packed_team,
            structured_team_json=json.dumps(
                validation.structured_team, separators=(",", ":"), ensure_ascii=False
            ),
            generation_audit_json=(
                json.dumps(generation_audit, separators=(",", ":"), ensure_ascii=False)
                if generation_audit
                else None
            ),
            schema_version=validation.schema_version,
            created_at=datetime.now(UTC),
        )
        async with self.database.sessions() as session:
            session.add(row)
            await session.commit()
        return self._snapshot(row)

    async def get(self, team_id: UUID) -> TeamSnapshot | None:
        async with self.database.sessions() as session:
            row = await session.get(TeamSnapshotRow, str(team_id))
            return self._snapshot(row) if row else None

    async def list(self, limit: int = 100, offset: int = 0) -> tuple[TeamSnapshot, ...]:
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(TeamSnapshotRow)
                    .order_by(TeamSnapshotRow.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return tuple(self._snapshot(row) for row in rows)

    async def record_build_audit(self, audit: TeamBuildAudit) -> None:
        row = TeamBuildAuditRow(
            id=str(audit.id),
            participant=audit.participant,
            provider=audit.provider,
            model=audit.model,
            format=audit.format,
            prompt_profile_version=audit.prompt_profile_version,
            rendered_prompt=audit.rendered_prompt,
            raw_responses_json=json.dumps(audit.raw_responses, ensure_ascii=False),
            validation_errors_json=json.dumps(audit.validation_errors, ensure_ascii=False),
            repair_attempts=audit.repair_attempts,
            success=audit.success,
            team_snapshot_id=str(audit.team_snapshot_id) if audit.team_snapshot_id else None,
            usage_json=audit.usage.model_dump_json() if audit.usage else None,
            latency_ms=audit.latency_ms,
            schema_version=audit.schema_version,
            created_at=audit.created_at,
        )
        async with self.database.sessions() as session:
            session.add(row)
            await session.commit()

    async def get_build_audit(self, audit_id: UUID) -> TeamBuildAudit | None:
        async with self.database.sessions() as session:
            row = await session.get(TeamBuildAuditRow, str(audit_id))
            if row is None:
                return None
            return TeamBuildAudit(
                id=UUID(row.id),
                participant=row.participant,
                provider=row.provider,
                model=row.model,
                format=row.format,
                prompt_profile_version=row.prompt_profile_version,
                rendered_prompt=row.rendered_prompt,
                raw_responses=tuple(json.loads(row.raw_responses_json)),
                validation_errors=tuple(
                    tuple(items) for items in json.loads(row.validation_errors_json)
                ),
                repair_attempts=row.repair_attempts,
                success=row.success,
                team_snapshot_id=UUID(row.team_snapshot_id) if row.team_snapshot_id else None,
                usage=(
                    ProviderUsage.model_validate_json(row.usage_json) if row.usage_json else None
                ),
                latency_ms=row.latency_ms,
                created_at=row.created_at.replace(tzinfo=row.created_at.tzinfo or UTC),
            )

    @staticmethod
    def _snapshot(row: TeamSnapshotRow) -> TeamSnapshot:
        return TeamSnapshot(
            id=UUID(row.id),
            name=row.name,
            format=row.format,
            source=TeamSource(row.source),
            submitted_text=row.submitted_text,
            normalized_export=row.normalized_export,
            packed_team=row.packed_team,
            structured_team=tuple(json.loads(row.structured_team_json)),
            generation_audit=(
                json.loads(row.generation_audit_json) if row.generation_audit_json else None
            ),
            created_at=row.created_at.replace(tzinfo=row.created_at.tzinfo or UTC),
        )
