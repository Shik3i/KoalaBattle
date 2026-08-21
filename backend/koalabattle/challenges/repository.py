from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from koalabattle.models.orm import ChallengeRunRow
from koalabattle.storage import Database

from .models import ChallengeRun, ChallengeRunSummary


class ChallengeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock(self, run_id: UUID) -> asyncio.Lock:
        return self._locks[str(run_id)]

    async def create(self, run: ChallengeRun) -> ChallengeRun:
        row = ChallengeRunRow(
            id=str(run.id),
            definition_id=run.definition.id,
            definition_version=run.definition.version,
            name=run.name,
            status=run.status.value,
            revision=run.revision,
            current_stage_index=run.current_stage_index,
            active_match_id=str(run.active_match_id) if run.active_match_id else None,
            state_json=run.model_dump_json(),
            schema_version=run.schema_version,
            created_at=run.created_at,
            updated_at=run.updated_at,
            completed_at=run.completed_at,
        )
        async with self.database.sessions() as session:
            session.add(row)
            await session.commit()
        return run

    async def get(self, run_id: UUID) -> ChallengeRun | None:
        async with self.database.sessions() as session:
            row = await session.get(ChallengeRunRow, str(run_id))
            return ChallengeRun.model_validate_json(row.state_json) if row else None

    async def save(self, run: ChallengeRun, *, expected_revision: int) -> ChallengeRun:
        stored = run.model_copy(
            update={"revision": expected_revision + 1, "updated_at": datetime.now(UTC)}
        )
        async with self.database.sessions() as session:
            result = await session.execute(
                update(ChallengeRunRow)
                .where(
                    ChallengeRunRow.id == str(run.id),
                    ChallengeRunRow.revision == expected_revision,
                )
                .values(
                    name=stored.name,
                    status=stored.status.value,
                    revision=stored.revision,
                    current_stage_index=stored.current_stage_index,
                    active_match_id=(
                        str(stored.active_match_id) if stored.active_match_id else None
                    ),
                    state_json=stored.model_dump_json(),
                    updated_at=stored.updated_at,
                    completed_at=stored.completed_at,
                )
                .returning(ChallengeRunRow.id)
            )
            if result.scalar_one_or_none() is None:
                row = await session.get(ChallengeRunRow, str(run.id))
                if row is None:
                    raise KeyError(str(run.id))
                raise ValueError(
                    f"stale challenge revision: expected {expected_revision}, "
                    f"current {row.revision}"
                )
            await session.commit()
            return stored

    async def list(self, *, limit: int = 100, offset: int = 0) -> tuple[ChallengeRunSummary, ...]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(ChallengeRunRow)
                    .order_by(ChallengeRunRow.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
            result: list[ChallengeRunSummary] = []
            for row in rows:
                run = ChallengeRun.model_validate_json(row.state_json)
                result.append(
                    ChallengeRunSummary(
                        id=run.id,
                        name=run.name,
                        definition_name=run.definition.name,
                        definition_version=run.definition.version,
                        status=run.status,
                        current_stage_index=run.current_stage_index,
                        stage_count=len(run.definition.stages),
                        stages_cleared=sum(item.status == "won" for item in run.stage_results),
                        created_at=run.created_at,
                        updated_at=run.updated_at,
                    )
                )
            return tuple(result)
