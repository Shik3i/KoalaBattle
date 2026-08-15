"""Add versioned agent context and immutable custom-team audit.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_decisions") as batch:
        batch.add_column(sa.Column("knowledge_json", sa.Text()))
        batch.add_column(sa.Column("context_json", sa.Text()))
        batch.add_column(sa.Column("context_metrics_json", sa.Text()))
        batch.add_column(sa.Column("prompt_profile_id", sa.String(80)))
        batch.add_column(sa.Column("prompt_profile_version", sa.String(40)))
        batch.add_column(sa.Column("context_schema_version", sa.String(40)))
        batch.add_column(sa.Column("knowledge_schema_version", sa.String(40)))
        batch.add_column(sa.Column("history_policy_version", sa.String(80)))
        batch.add_column(sa.Column("memory_policy", sa.String(40)))
        batch.add_column(sa.Column("memory_policy_version", sa.String(40)))
        batch.add_column(sa.Column("strategy_memory_before", sa.String(400)))
        batch.add_column(sa.Column("strategy_memory_after", sa.String(400)))
        batch.create_index(
            "ix_agent_decisions_match_side_turn",
            ["match_id", "side", "turn"],
        )

    with op.batch_alter_table("matches") as batch:
        batch.create_index("ix_matches_status_created_at", ["status", "created_at"])

    op.create_table(
        "team_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("format", sa.String(40), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("submitted_text", sa.Text(), nullable=False),
        sa.Column("normalized_export", sa.Text(), nullable=False),
        sa.Column("packed_team", sa.Text(), nullable=False),
        sa.Column("structured_team_json", sa.Text(), nullable=False),
        sa.Column("generation_audit_json", sa.Text()),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_team_snapshots_name", "team_snapshots", ["name"])
    op.create_index("ix_team_snapshots_format", "team_snapshots", ["format"])
    op.create_index("ix_team_snapshots_source", "team_snapshots", ["source"])

    op.create_table(
        "team_build_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("participant", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("format", sa.String(40), nullable=False),
        sa.Column("prompt_profile_version", sa.String(80), nullable=False),
        sa.Column("rendered_prompt", sa.Text(), nullable=False),
        sa.Column("raw_responses_json", sa.Text(), nullable=False),
        sa.Column("validation_errors_json", sa.Text(), nullable=False),
        sa.Column("repair_attempts", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column(
            "team_snapshot_id",
            sa.String(36),
            sa.ForeignKey("team_snapshots.id", ondelete="SET NULL"),
        ),
        sa.Column("usage_json", sa.Text()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_team_build_audits_provider", "team_build_audits", ["provider"])
    op.create_index(
        "ix_team_build_audits_team_snapshot_id", "team_build_audits", ["team_snapshot_id"]
    )


def downgrade() -> None:
    op.drop_table("team_build_audits")
    op.drop_table("team_snapshots")
    with op.batch_alter_table("matches") as batch:
        batch.drop_index("ix_matches_status_created_at")
    with op.batch_alter_table("agent_decisions") as batch:
        batch.drop_index("ix_agent_decisions_match_side_turn")
        for column in (
            "strategy_memory_after",
            "strategy_memory_before",
            "memory_policy_version",
            "memory_policy",
            "history_policy_version",
            "knowledge_schema_version",
            "context_schema_version",
            "prompt_profile_version",
            "prompt_profile_id",
            "context_metrics_json",
            "context_json",
            "knowledge_json",
        ):
            batch.drop_column(column)
