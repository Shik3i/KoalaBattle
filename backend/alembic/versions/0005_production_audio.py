"""Add production timelines, voice presets, and speech cache metadata.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_presets",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("voice", sa.String(120), nullable=False),
        sa.Column("model", sa.String(160)),
        sa.Column("language", sa.String(20)),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("instructions", sa.String(500)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_voice_presets_provider", "voice_presets", ["provider"])
    op.create_table(
        "productions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(60), nullable=False),
        sa.Column("profile_version", sa.String(20), nullable=False),
        sa.Column("timeline_version", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("director_state", sa.String(40), nullable=False),
        sa.Column("timeline_json", sa.Text(), nullable=False),
        sa.Column("voice_assignments_json", sa.Text(), nullable=False),
        sa.Column("overrides_json", sa.Text(), nullable=False),
        sa.Column("authoritative_client_id", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_productions_match_id", "productions", ["match_id"])
    op.create_index("ix_productions_profile_id", "productions", ["profile_id"])
    op.create_index("ix_productions_status", "productions", ["status"])
    op.create_table(
        "speech_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("voice", sa.String(120), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.String(260), nullable=False, unique=True),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_speech_cache_provider", "speech_cache", ["provider"])


def downgrade() -> None:
    op.drop_table("speech_cache")
    op.drop_table("productions")
    op.drop_table("voice_presets")
