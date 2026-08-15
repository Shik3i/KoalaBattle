"""Add multi-match orchestration and generic tournament persistence.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("engine", sa.String(80), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("presentation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tournament_presets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tournaments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("format", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("best_of", sa.Integer(), nullable=False),
        sa.Column("max_concurrent_matches", sa.Integer(), nullable=False),
        sa.Column("maximum_total_cost", sa.Float()),
        sa.Column("max_draw_replays", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("manual_scheduling", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("match_template_json", sa.Text(), nullable=False),
        sa.Column("presentation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("scoring_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("current_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winner_participant_id", sa.String(36)),
        sa.Column("error", sa.Text()),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tournaments_name", "tournaments", ["name"])
    op.create_index("ix_tournaments_format", "tournaments", ["format"])
    op.create_index("ix_tournaments_status", "tournaments", ["status"])
    op.create_table(
        "tournament_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.String(36),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("agent_snapshot_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.UniqueConstraint(
            "tournament_id", "seed", name="uq_tournament_participant_seed"
        ),
    )
    op.create_index(
        "ix_tournament_participants_tournament_id",
        "tournament_participants",
        ["tournament_id"],
    )
    op.create_table(
        "tournament_series",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.String(36),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("bracket_position", sa.Integer(), nullable=False),
        sa.Column("queue_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("participant_a_id", sa.String(36)),
        sa.Column("participant_b_id", sa.String(36)),
        sa.Column("dependency_a_id", sa.String(36)),
        sa.Column("dependency_b_id", sa.String(36)),
        sa.Column("best_of", sa.Integer(), nullable=False),
        sa.Column("wins_a", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wins_b", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("draws", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("games_played", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_games", sa.Integer(), nullable=False),
        sa.Column("winner_participant_id", sa.String(36)),
        sa.Column("result_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dependency_a_id"], ["tournament_series.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["dependency_b_id"], ["tournament_series.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tournament_id",
            "round_number",
            "bracket_position",
            name="uq_series_bracket_slot",
        ),
    )
    op.create_index(
        "ix_tournament_series_tournament_id", "tournament_series", ["tournament_id"]
    )
    op.create_index("ix_tournament_series_queue_order", "tournament_series", ["queue_order"])
    op.create_index("ix_tournament_series_status", "tournament_series", ["status"])

    with op.batch_alter_table("matches") as batch:
        batch.add_column(sa.Column("tournament_id", sa.String(36)))
        batch.add_column(sa.Column("series_id", sa.String(36)))
        batch.add_column(sa.Column("queue_position", sa.Integer()))
        batch.create_foreign_key(
            "fk_matches_tournament_id",
            "tournaments",
            ["tournament_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_matches_series_id", "tournament_series", ["series_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_matches_tournament_id", ["tournament_id"])
        batch.create_index("ix_matches_series_id", ["series_id"])
        batch.create_index("ix_matches_queue_position", ["queue_position"])


def downgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.drop_index("ix_matches_queue_position")
        batch.drop_index("ix_matches_series_id")
        batch.drop_index("ix_matches_tournament_id")
        batch.drop_constraint("fk_matches_series_id", type_="foreignkey")
        batch.drop_constraint("fk_matches_tournament_id", type_="foreignkey")
        batch.drop_column("queue_position")
        batch.drop_column("series_id")
        batch.drop_column("tournament_id")
    op.drop_table("tournament_series")
    op.drop_table("tournament_participants")
    op.drop_table("tournaments")
    op.drop_table("tournament_presets")
    op.drop_table("match_templates")
