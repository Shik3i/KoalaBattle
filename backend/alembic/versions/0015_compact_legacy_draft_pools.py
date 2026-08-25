"""Move inline draft pools out of challenge runs.

Migration 0011 gave new saves a shared, content-addressed pool table, but a
completed run is never saved again, so its ~1,200-candidate pool stayed inline.
That left 259 runs holding 206MB of pools that are near-duplicates of each other
— a third of the whole database.

It also corrects how those pools are addressed. 0011 keyed them by `catalog_hash`,
which identifies the Showdown catalog a pool was generated from, not the pool
itself: candidate objects changed as their fields did, and this archive already
contains three catalog hashes mapping to two different pools each. Keying by that
would eventually hand one run another run's pool. Pools are keyed by a hash of
their own contents from here on, and runs record which pool they use.

Every run is decoded again from what this writes and compared field by field
against what was read, before anything is dropped.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-25
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op
from koalabattle.challenges.models import ChallengeRun
from koalabattle.challenges.repository import (
    POOL_REFERENCE_KEY,
    _parse_run_payload,
    pool_content_hash,
)

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, state_json FROM challenge_runs")
    ).fetchall()

    pools: dict[str, str] = {}
    updates: list[dict[str, object]] = []
    for run_id, state_json in rows:
        try:
            run = ChallengeRun.model_validate(_parse_run_payload(state_json))
        except Exception:
            continue  # a row that cannot be loaded today is left exactly as it is
        if not run.draft_pool.candidates:
            continue

        # Normalize through the model, because that is what the repository hashes
        # when it saves. Hashing the raw JSON instead would put the same pool under
        # two different keys and quietly store it twice.
        payload = json.loads(run.model_dump_json())
        candidates = payload["draft_pool"]["candidates"]
        digest = pool_content_hash(candidates)
        pools.setdefault(digest, json.dumps({"candidates": candidates}))
        payload["draft_pool"] = {
            **payload["draft_pool"],
            "candidates": [],
            POOL_REFERENCE_KEY: digest,
        }

        # Rebuild the run the way the repository will and require the same run back.
        # Compared as `model_dump()` rather than with `==`: `recommended_move` is
        # excluded from serialization, so it never survives *any* save and would make
        # an equality check fail for reasons that have nothing to do with pools.
        restored = json.loads(json.dumps(payload))
        reference = restored["draft_pool"].pop(POOL_REFERENCE_KEY)
        restored["draft_pool"]["candidates"] = json.loads(pools[reference])["candidates"]
        if ChallengeRun.model_validate(restored).model_dump() != run.model_dump():
            raise RuntimeError(
                f"challenge run {run_id} did not survive a draft-pool round trip; "
                "aborting before any pool is dropped"
            )
        updates.append({"row_id": run_id, "state": json.dumps(payload)})

    now = datetime.now(UTC)
    for digest, payload_json in pools.items():
        connection.execute(
            sa.text(
                "INSERT INTO draft_pool_snapshots (catalog_hash, payload_json, created_at) "
                "VALUES (:hash, :payload, :created) ON CONFLICT (catalog_hash) DO NOTHING"
            ),
            {"hash": digest, "payload": payload_json, "created": now},
        )
    for start in range(0, len(updates), 200):
        connection.execute(
            sa.text("UPDATE challenge_runs SET state_json = :state WHERE id = :row_id"),
            updates[start : start + 200],
        )

    # Re-keying leaves the rows 0011 wrote under their catalog hash unreferenced.
    # Only rows no run points at are removed, and only after every run above has
    # been rewritten and verified.
    referenced = {
        json.loads(state).get("draft_pool", {}).get(POOL_REFERENCE_KEY)
        for (state,) in connection.execute(
            sa.text("SELECT state_json FROM challenge_runs")
        ).fetchall()
    }
    referenced.discard(None)
    for (digest,) in connection.execute(
        sa.text("SELECT catalog_hash FROM draft_pool_snapshots")
    ).fetchall():
        if digest not in referenced:
            connection.execute(
                sa.text("DELETE FROM draft_pool_snapshots WHERE catalog_hash = :hash"),
                {"hash": digest},
            )


def downgrade() -> None:
    """Put every pool back inline. The shared rows stay; they are still valid."""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, state_json FROM challenge_runs")
    ).fetchall()
    updates: list[dict[str, object]] = []
    for run_id, state_json in rows:
        payload = json.loads(state_json)
        pool = payload.get("draft_pool")
        if not isinstance(pool, dict):
            continue
        reference = pool.pop(POOL_REFERENCE_KEY, None)
        if not reference or pool.get("candidates"):
            continue
        stored = connection.execute(
            sa.text("SELECT payload_json FROM draft_pool_snapshots WHERE catalog_hash = :hash"),
            {"hash": reference},
        ).fetchone()
        if stored is None:
            continue
        pool["candidates"] = json.loads(stored[0])["candidates"]
        payload["draft_pool"] = pool
        updates.append({"row_id": run_id, "state": json.dumps(payload)})
    for start in range(0, len(updates), 200):
        connection.execute(
            sa.text("UPDATE challenge_runs SET state_json = :state WHERE id = :row_id"),
            updates[start : start + 200],
        )
