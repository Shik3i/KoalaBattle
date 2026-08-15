"""Add provider audit and cost metadata.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_decisions") as batch:
        batch.add_column(sa.Column("provider", sa.String(80)))
        batch.add_column(sa.Column("model", sa.String(200)))
        batch.add_column(
            sa.Column("agent_configuration_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch.add_column(
            sa.Column("prompt_schema_version", sa.String(40), nullable=False, server_default="1.0")
        )
        batch.add_column(
            sa.Column(
                "prompt_template_version", sa.String(80), nullable=False, server_default="phase1"
            )
        )
        batch.add_column(
            sa.Column(
                "information_profile",
                sa.String(40),
                nullable=False,
                server_default="standard",
            )
        )
        batch.add_column(sa.Column("usage_json", sa.Text()))
        batch.add_column(
            sa.Column("retry_attempts_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("fallback_json", sa.Text()))
        batch.add_column(sa.Column("estimated_cost", sa.Float()))
        batch.add_column(sa.Column("cost_currency", sa.String(8)))
        batch.add_column(sa.Column("pricing_version", sa.String(80)))
        batch.add_column(sa.Column("error_category", sa.String(40)))
        batch.add_column(sa.Column("error_detail", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("agent_decisions") as batch:
        for column in (
            "error_detail",
            "error_category",
            "pricing_version",
            "cost_currency",
            "estimated_cost",
            "fallback_json",
            "retry_attempts_json",
            "usage_json",
            "information_profile",
            "prompt_template_version",
            "prompt_schema_version",
            "agent_configuration_json",
            "model",
            "provider",
        ):
            batch.drop_column(column)
