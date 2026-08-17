"""Add production styles, saved style presets and the brand asset library.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing productions keep working: an empty style JSON resolves to the built-in
    # Koala Broadcast defaults when the timeline is read back.
    op.add_column(
        "productions",
        sa.Column(
            "style_id", sa.String(60), nullable=False, server_default="koala-broadcast"
        ),
    )
    op.add_column(
        "productions", sa.Column("style_json", sa.Text(), nullable=False, server_default="{}")
    )
    op.add_column("productions", sa.Column("title", sa.String(90), nullable=True))
    op.create_table(
        "brand_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, index=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("media_type", sa.String(60), nullable=False),
        sa.Column("relative_path", sa.String(160), nullable=False, unique=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "style_presets",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("style_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("style_presets")
    op.drop_table("brand_assets")
    op.drop_column("productions", "title")
    op.drop_column("productions", "style_json")
    op.drop_column("productions", "style_id")
