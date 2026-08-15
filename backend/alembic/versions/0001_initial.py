"""Initial immutable battle archive schema.

Revision ID: 0001
Revises:
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("format", sa.String(80), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("winner", sa.String(2)),
        sa.Column("turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engine", sa.String(80), nullable=False),
        sa.Column("engine_version", sa.String(80)),
        sa.Column("showdown_version", sa.String(80)),
        sa.Column("poke_env_version", sa.String(40)),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("random_seed", sa.Integer()),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("raw_showdown_log", sa.Text()),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_matches_status", "matches", ["status"])
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("side", sa.String(2), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("agent_type", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(80)),
        sa.Column("model", sa.String(160)),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("team_json", sa.Text()),
        sa.UniqueConstraint("match_id", "side", name="uq_players_match_side"),
    )
    op.create_index("ix_players_match_id", "players", ["match_id"])
    op.create_table(
        "battle_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("logical_offset_ms", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.UniqueConstraint("match_id", "sequence", name="uq_battle_events_match_sequence"),
    )
    op.create_index("ix_battle_events_match_id", "battle_events", ["match_id"])
    op.create_index("ix_battle_events_event_type", "battle_events", ["event_type"])
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("side", sa.String(2), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("decision_sequence", sa.Integer(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("decision_json", sa.Text(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("legal_actions_json", sa.Text(), nullable=False),
        sa.Column("generated_prompt", sa.Text(), nullable=False),
        sa.Column("raw_response", sa.Text()),
        sa.Column("parsed_response_json", sa.Text()),
        sa.Column("selected_action", sa.String(80), nullable=False),
        sa.Column("commentary", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("provider_metadata_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.UniqueConstraint(
            "match_id",
            "side",
            "decision_sequence",
            name="uq_decisions_match_side_sequence",
        ),
    )
    op.create_index("ix_agent_decisions_match_id", "agent_decisions", ["match_id"])


def downgrade() -> None:
    op.drop_table("agent_decisions")
    op.drop_table("battle_events")
    op.drop_table("players")
    op.drop_table("matches")
