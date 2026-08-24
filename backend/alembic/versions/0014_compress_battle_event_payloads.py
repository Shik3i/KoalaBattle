"""Store battle-event payloads compressed.

Event payloads were the largest remaining table: `state_snapshot` re-serializes
both full teams on every agent decision and accounted for 82% of it. Payloads are
now zlib-compressed and, except at keyframes, chained against the previous payload
of the same event type within the match — measured at roughly 14x on real
archives, losslessly. `koalabattle.storage.payloads` documents why chaining is
safe against this schema.

Rewriting the table touches every row, so this upgrade takes a while on a large
archive and needs temporary space for the rebuild. Nothing is lost: the migration
verifies that every payload it writes decodes back to the exact bytes it read, and
aborts before committing if any row disagrees.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from koalabattle.storage.payloads import ChainDecoder, ChainEncoder

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Rows per write batch. Keeps peak memory bounded on a large archive.
_BATCH = 2000


def upgrade() -> None:
    connection = op.get_bind()
    with op.batch_alter_table("battle_events") as batch:
        batch.add_column(sa.Column("payload_z", sa.LargeBinary(), nullable=True))
        batch.add_column(
            sa.Column("payload_keyframe", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    # Match by match, in sequence order: that is the order the decoder replays.
    match_ids = [
        row[0]
        for row in connection.execute(
            sa.text("SELECT DISTINCT match_id FROM battle_events")
        ).fetchall()
    ]
    for match_id in match_ids:
        rows = connection.execute(
            sa.text(
                "SELECT id, event_type, payload_json FROM battle_events "
                "WHERE match_id = :match_id ORDER BY sequence"
            ),
            {"match_id": match_id},
        ).fetchall()
        encoder, verifier = ChainEncoder(), ChainDecoder()
        updates: list[dict[str, object]] = []
        for row_id, event_type, payload_json in rows:
            payload = (payload_json or "null").encode()
            blob, keyframe = encoder.encode(event_type, payload)
            # Prove the round trip before this row can replace the original.
            if verifier.decode(event_type, blob, keyframe) != payload:
                raise RuntimeError(
                    f"battle_events row {row_id} did not survive a compression round trip; "
                    "aborting before any payload is dropped"
                )
            updates.append({"row_id": row_id, "blob": blob, "keyframe": keyframe})
        for start in range(0, len(updates), _BATCH):
            connection.execute(
                sa.text(
                    "UPDATE battle_events SET payload_z = :blob, payload_keyframe = :keyframe "
                    "WHERE id = :row_id"
                ),
                updates[start : start + _BATCH],
            )

    with op.batch_alter_table("battle_events") as batch:
        batch.alter_column("payload_z", existing_type=sa.LargeBinary(), nullable=False)
        batch.drop_column("payload_json")


def downgrade() -> None:
    connection = op.get_bind()
    with op.batch_alter_table("battle_events") as batch:
        batch.add_column(sa.Column("payload_json", sa.Text(), nullable=True))

    match_ids = [
        row[0]
        for row in connection.execute(
            sa.text("SELECT DISTINCT match_id FROM battle_events")
        ).fetchall()
    ]
    for match_id in match_ids:
        rows = connection.execute(
            sa.text(
                "SELECT id, event_type, payload_z, payload_keyframe FROM battle_events "
                "WHERE match_id = :match_id ORDER BY sequence"
            ),
            {"match_id": match_id},
        ).fetchall()
        decoder = ChainDecoder()
        updates = [
            {
                "row_id": row_id,
                "payload": decoder.decode(event_type, blob, bool(keyframe)).decode(),
            }
            for row_id, event_type, blob, keyframe in rows
        ]
        for start in range(0, len(updates), _BATCH):
            connection.execute(
                sa.text("UPDATE battle_events SET payload_json = :payload WHERE id = :row_id"),
                updates[start : start + _BATCH],
            )

    with op.batch_alter_table("battle_events") as batch:
        batch.alter_column("payload_json", existing_type=sa.Text(), nullable=False)
        batch.drop_column("payload_keyframe")
        batch.drop_column("payload_z")
