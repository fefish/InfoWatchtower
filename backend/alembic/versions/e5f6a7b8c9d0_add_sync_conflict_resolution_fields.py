"""add sync conflict resolution fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-05 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sync_conflicts") as batch_op:
        batch_op.add_column(sa.Column("conflict_reason", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("resolved_by_user_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_sync_conflicts_resolved_by_user_id_users",
            "users",
            ["resolved_by_user_id"],
            ["id"],
        )
        batch_op.create_index("ix_sync_conflicts_resolved_by_user_id", ["resolved_by_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("sync_conflicts") as batch_op:
        batch_op.drop_index("ix_sync_conflicts_resolved_by_user_id")
        batch_op.drop_constraint("fk_sync_conflicts_resolved_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("resolved_by_user_id")
        batch_op.drop_column("conflict_reason")
