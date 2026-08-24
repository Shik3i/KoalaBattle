"""Drop decision audit columns that duplicated `request_json`.

`request_json` stores the whole `AgentRequest`, which already contains the game
state, the legal actions and the rendered prompt. Those three were mirrored into
their own columns as well. `state_json` and `legal_actions_json` never had a
single reader, and `generated_prompt` was byte-identical to `request_json.prompt`,
so the copies were pure overhead — roughly 380MB on a 24k-decision history.

Rebuilding this table reclaims that space but rewrites every row, so the upgrade
takes a while on a large archive. Nothing is lost: the read path now takes the
prompt from the request it already parses.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_decisions") as batch:
        batch.drop_column("state_json")
        batch.drop_column("legal_actions_json")
        batch.drop_column("generated_prompt")


def downgrade() -> None:
    # Restored as empty strings: the originals were exact copies of data that is
    # still present inside `request_json`, so nothing is actually unrecoverable.
    with op.batch_alter_table("agent_decisions") as batch:
        batch.add_column(
            sa.Column("state_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch.add_column(
            sa.Column("legal_actions_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("generated_prompt", sa.Text(), nullable=False, server_default="")
        )
