"""add sync cursors and feed support

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_cursors",
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("cursor", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("last_pulled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("object_type"),
    )

    # intranet 侧联动同步的成稿没有本地推荐链（docs/deployment/deployment-topology.md §3.4）
    with op.batch_alter_table("generated_news") as batch_op:
        batch_op.alter_column(
            "recommendation_item_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("generated_news") as batch_op:
        batch_op.alter_column(
            "recommendation_item_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
    op.drop_table("sync_cursors")
