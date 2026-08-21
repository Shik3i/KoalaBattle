"""Add persistent Draft Challenge runs and normal-match ownership links.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "challenge_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("definition_id", sa.String(60), nullable=False),
        sa.Column("definition_version", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_stage_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_match_id", sa.String(36)),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["active_match_id"], ["matches.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_challenge_runs_definition_id", "challenge_runs", ["definition_id"])
    op.create_index("ix_challenge_runs_name", "challenge_runs", ["name"])
    op.create_index("ix_challenge_runs_status", "challenge_runs", ["status"])
    op.create_index("ix_challenge_runs_active_match_id", "challenge_runs", ["active_match_id"])
    with op.batch_alter_table("matches") as batch:
        batch.add_column(sa.Column("challenge_run_id", sa.String(36)))
        batch.add_column(sa.Column("challenge_stage_id", sa.String(60)))
        batch.create_foreign_key(
            "fk_matches_challenge_run_id",
            "challenge_runs",
            ["challenge_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_matches_challenge_run_id", ["challenge_run_id"])
        batch.create_index("ix_matches_challenge_stage_id", ["challenge_stage_id"])


def downgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.drop_index("ix_matches_challenge_stage_id")
        batch.drop_index("ix_matches_challenge_run_id")
        batch.drop_constraint("fk_matches_challenge_run_id", type_="foreignkey")
        batch.drop_column("challenge_stage_id")
        batch.drop_column("challenge_run_id")
    op.drop_table("challenge_runs")
