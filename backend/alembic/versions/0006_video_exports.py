"""Add persistent video export jobs and registered media metadata.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_export_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "production_id",
            sa.String(36),
            sa.ForeignKey("productions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("matches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("backend", sa.String(30), nullable=False),
        sa.Column("preset_id", sa.String(60), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), unique=True),
        sa.Column("output_relative_path", sa.String(500), unique=True),
        sa.Column("job_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_video_export_jobs_production_id", "video_export_jobs", ["production_id"])
    op.create_index("ix_video_export_jobs_match_id", "video_export_jobs", ["match_id"])
    op.create_index("ix_video_export_jobs_backend", "video_export_jobs", ["backend"])
    op.create_index("ix_video_export_jobs_preset_id", "video_export_jobs", ["preset_id"])
    op.create_index("ix_video_export_jobs_status", "video_export_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("video_export_jobs")
