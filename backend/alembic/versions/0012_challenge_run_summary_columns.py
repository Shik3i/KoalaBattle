"""Denormalize challenge run summary fields into columns.

The run list only needs ~10 fields per row, but four of them lived solely inside
`state_json`. Reading them meant loading and fully validating every run's state
(hundreds of KB each), which made `GET /api/challenges` take seconds. Copy them
into columns once here so the list query can ignore `state_json` entirely.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-24
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("challenge_runs") as batch:
        batch.add_column(
            sa.Column("definition_name", sa.String(120), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("difficulty", sa.String(20), nullable=False, server_default="normal")
        )
        batch.add_column(sa.Column("stage_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("stages_cleared", sa.Integer(), nullable=False, server_default="0")
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, state_json FROM challenge_runs")
    ).fetchall()
    for run_id, state_json in rows:
        try:
            payload = json.loads(state_json)
        except (TypeError, ValueError):
            # A row we cannot parse keeps the column defaults; the list stays
            # renderable and `get()` still reports the real problem on open.
            continue
        definition = payload.get("definition") or {}
        stage_results = payload.get("stage_results") or []
        connection.execute(
            sa.text(
                "UPDATE challenge_runs SET definition_name = :name, difficulty = :difficulty, "
                "stage_count = :stage_count, stages_cleared = :stages_cleared WHERE id = :id"
            ),
            {
                "name": str(definition.get("name") or "")[:120],
                "difficulty": str(payload.get("difficulty") or "normal")[:20],
                "stage_count": len(definition.get("stages") or []),
                "stages_cleared": sum(
                    1
                    for item in stage_results
                    if isinstance(item, dict) and item.get("status") == "won"
                ),
                "id": run_id,
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("challenge_runs") as batch:
        batch.drop_column("stages_cleared")
        batch.drop_column("stage_count")
        batch.drop_column("difficulty")
        batch.drop_column("definition_name")
