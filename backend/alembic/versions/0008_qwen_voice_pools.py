"""Add local Qwen voice metadata and deterministic voice pools.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voice_presets", sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]")
    )
    op.add_column("voice_presets", sa.Column("reference_audio_path", sa.String(260)))
    op.add_column("voice_presets", sa.Column("reference_text", sa.String(1000)))
    op.add_column(
        "voice_presets",
        sa.Column("x_vector_only_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "voice_pools",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(400), nullable=False, server_default=""),
        sa.Column("voice_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("voice_pools")
    op.drop_column("voice_presets", "x_vector_only_mode")
    op.drop_column("voice_presets", "reference_text")
    op.drop_column("voice_presets", "reference_audio_path")
    op.drop_column("voice_presets", "tags_json")
