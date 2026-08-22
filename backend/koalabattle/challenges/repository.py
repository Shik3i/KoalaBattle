from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update

from koalabattle.models.orm import ChallengeRunRow
from koalabattle.storage import Database

from .models import ChallengeRun, ChallengeRunSummary

LEGACY_NOTICE = (
    "This development-era run uses draft-rules-v1 with Draft Credits and cannot be resumed. "
    "Start a new draft-rules-v2 Challenge; the legacy run remains listed for auditability."
)


def _without_legacy_points(candidate: dict[str, object]) -> dict[str, object]:
    cleaned = dict(candidate)
    cleaned.pop("points", None)
    cleaned.setdefault("abilities", [])
    return cleaned


#: Fields written by retired features. `ChallengeRun` forbids extra keys, so a saved run
#: carrying one of these would fail to load and take the whole backend down with it.
RETIRED_RUN_FIELDS = ("pending_reward", "training_rewards")


def _without_retired_fields(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    cleaned: dict[str, Any] = dict(payload)
    for field in RETIRED_RUN_FIELDS:
        cleaned.pop(field, None)
    return cleaned


def _deserialize_run(state_json: str) -> ChallengeRun:
    payload = _without_retired_fields(json.loads(state_json))
    if payload.get("schema_version") != "1.0":
        return ChallengeRun.model_validate(payload)

    definition = dict(payload["definition"])
    draft_rules = dict(definition["draft_rules"])
    draft_rules.pop("starting_credits", None)
    definition["draft_rules"] = draft_rules
    pricing = dict(payload.pop("pricing"))
    candidates = tuple(
        _without_legacy_points(dict(candidate)) for candidate in pricing.get("candidates", [])
    )
    picks = []
    for original in payload.get("picks", []):
        pick = dict(original)
        pick["candidate"] = _without_legacy_points(dict(pick["candidate"]))
        picks.append(pick)
    payload.pop("credits_remaining", None)
    payload.update(
        {
            "schema_version": "2.0",
            "draft_rules_version": "draft-rules-v1-incompatible",
            "definition": definition,
            "status": "abandoned",
            "draft_pool": {
                "schema_version": "legacy-1.0",
                "showdown_version": "legacy-unknown",
                "format": definition["format"],
                "format_generation": 9,
                "abilities_supported": True,
                "catalog_hash": pricing["catalog_hash"],
                "candidates": candidates,
            },
            "current_offer": None,
            "draft_history": [],
            "consumed_species_ids": [],
            "picks": picks,
            "ability_selections": {},
            "active_match_id": None,
            "compatibility_notice": LEGACY_NOTICE,
            "error": LEGACY_NOTICE,
        }
    )
    return ChallengeRun.model_validate(payload)


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
            return _deserialize_run(row.state_json) if row else None

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

    async def delete(self, run_id: UUID) -> bool:
        async with self.database.sessions() as session:
            row = await session.get(ChallengeRunRow, str(run_id))
            if row is None:
                return False
            await session.execute(
                delete(ChallengeRunRow).where(ChallengeRunRow.id == str(run_id))
            )
            await session.commit()
            return True

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
                run = _deserialize_run(row.state_json)
                result.append(
                    ChallengeRunSummary(
                        id=run.id,
                        name=run.name,
                        definition_name=run.definition.name,
                        definition_version=run.definition.version,
                        status=run.status,
                        difficulty=run.difficulty,
                        current_stage_index=run.current_stage_index,
                        stage_count=len(run.definition.stages),
                        stages_cleared=sum(item.status == "won" for item in run.stage_results),
                        created_at=run.created_at,
                        updated_at=run.updated_at,
                    )
                )
            return tuple(result)
