"""add sync inbox retry state

Revision ID: c6d7e8f9a0b1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-06 15:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.common import JsonColumn

revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_inbox",
        sa.Column("record_json", JsonColumn, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "sync_inbox",
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "sync_inbox",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_inbox",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_inbox", "last_attempt_at")
    op.drop_column("sync_inbox", "attempt_count")
    op.drop_column("sync_inbox", "error_message")
    op.drop_column("sync_inbox", "record_json")
