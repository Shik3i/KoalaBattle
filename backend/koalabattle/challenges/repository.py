from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from koalabattle.models.orm import ChallengeRunRow, DraftPoolSnapshotRow
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
    # A pre-fix automatic-progression failure could persist Showdown's complete
    # multi-Pokemon validation response beyond the public model's 1000-char bound.
    # Keep the saved audit readable without allowing one bad row to block startup.
    if isinstance(cleaned.get("error"), str):
        cleaned["error"] = cleaned["error"][:1000]
    return cleaned


def _parse_run_payload(state_json: str) -> dict[str, Any]:
    payload = _without_retired_fields(json.loads(state_json))
    if payload.get("schema_version") != "1.0":
        return payload

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
    return payload


async def _store_draft_pool(session: AsyncSession, run: ChallengeRun) -> dict[str, Any]:
    """Persist the run's draft pool once per distinct `catalog_hash`, and return the
    run's JSON-mode payload with `draft_pool.candidates` stripped for storage.

    The pool is immutable content addressed by that hash, so a repeat save for the
    same pool (every pick, reroll, and stage transition in a run) is a no-op insert
    instead of re-writing potentially ~1,200 candidates every time.
    """
    pool = run.draft_pool
    if pool.candidates:
        stmt = (
            sqlite_insert(DraftPoolSnapshotRow)
            .values(
                catalog_hash=pool.catalog_hash,
                payload_json=pool.model_dump_json(),
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["catalog_hash"])
        )
        await session.execute(stmt)
    payload = json.loads(run.model_dump_json())
    payload["draft_pool"] = {**payload["draft_pool"], "candidates": []}
    return payload


def _deserialize_run(state_json: str) -> ChallengeRun:
    """Parse a run payload that still carries its draft pool inline (never went
    through `_store_draft_pool`'s stripping) — the legacy-migration branch of
    `_parse_run_payload` always does, and so does any hand-built test payload."""
    return ChallengeRun.model_validate(_parse_run_payload(state_json))


async def _hydrate_draft_pool(
    session: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    """Reverse of `_store_draft_pool`: fill `draft_pool.candidates` back in from the
    content-addressed store. A no-op for legacy payloads that still carry candidates
    inline (see `_parse_run_payload`'s pre-2.0 migration branch)."""
    pool = payload.get("draft_pool")
    catalog_hash = pool.get("catalog_hash") if isinstance(pool, dict) else None
    if not isinstance(pool, dict) or pool.get("candidates") or not catalog_hash:
        return payload
    row = await session.get(DraftPoolSnapshotRow, catalog_hash)
    if row is None:
        # Should never happen — every stored run's pool is written before the run
        # itself. Leave `candidates` empty rather than crash; downstream Pydantic
        # validation surfaces this loudly if the pool is actually required to be
        # non-empty, which is a more debuggable failure than a repository crash.
        return payload
    stored_pool = json.loads(row.payload_json)
    payload["draft_pool"] = {**pool, "candidates": stored_pool.get("candidates", [])}
    return payload


class ChallengeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock(self, run_id: UUID) -> asyncio.Lock:
        return self._locks[str(run_id)]

    async def create(self, run: ChallengeRun) -> ChallengeRun:
        async with self.database.sessions() as session:
            payload = await _store_draft_pool(session, run)
            row = ChallengeRunRow(
                id=str(run.id),
                definition_id=run.definition.id,
                definition_version=run.definition.version,
                name=run.name,
                status=run.status.value,
                revision=run.revision,
                current_stage_index=run.current_stage_index,
                active_match_id=str(run.active_match_id) if run.active_match_id else None,
                state_json=json.dumps(payload),
                schema_version=run.schema_version,
                created_at=run.created_at,
                updated_at=run.updated_at,
                completed_at=run.completed_at,
            )
            session.add(row)
            await session.commit()
        return run

    async def get(self, run_id: UUID) -> ChallengeRun | None:
        async with self.database.sessions() as session:
            row = await session.get(ChallengeRunRow, str(run_id))
            if row is None:
                return None
            payload = await _hydrate_draft_pool(session, _parse_run_payload(row.state_json))
            return ChallengeRun.model_validate(payload)

    async def save(self, run: ChallengeRun, *, expected_revision: int) -> ChallengeRun:
        stored = run.model_copy(
            update={"revision": expected_revision + 1, "updated_at": datetime.now(UTC)}
        )
        async with self.database.sessions() as session:
            payload = await _store_draft_pool(session, stored)
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
                    state_json=json.dumps(payload),
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
                # Summaries never read draft_pool.candidates, so skip rehydrating it —
                # avoids pulling the (potentially ~1,200-candidate) pool payload per run.
                run = ChallengeRun.model_validate(_parse_run_payload(row.state_json))
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
