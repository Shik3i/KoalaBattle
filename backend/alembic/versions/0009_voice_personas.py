"""Add explicit voice mode and fictional persona metadata to voice presets.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voice_presets",
        sa.Column("voice_mode", sa.String(30), nullable=False, server_default="system"),
    )
    op.add_column("voice_presets", sa.Column("persona_id", sa.String(80)))
    op.add_column("voice_presets", sa.Column("delivery_profile", sa.String(60)))
    op.add_column("voice_presets", sa.Column("disclosure_label", sa.String(180)))


def downgrade() -> None:
    op.drop_column("voice_presets", "disclosure_label")
    op.drop_column("voice_presets", "delivery_profile")
    op.drop_column("voice_presets", "persona_id")
    op.drop_column("voice_presets", "voice_mode")
