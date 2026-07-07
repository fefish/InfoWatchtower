"""add historical feedback requirement links

Revision ID: c4d5e6f7a8b9
Revises: c2d3e4f5a6b7
Create Date: 2026-07-06 13:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.add_column(sa.Column("historical_feedback_item_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_requirement_source_links_historical_feedback_item_id_historical_feedback_items",
            "historical_feedback_items",
            ["historical_feedback_item_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_requirement_source_links_historical_feedback_item_id",
            ["historical_feedback_item_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.drop_index("ix_requirement_source_links_historical_feedback_item_id")
        batch_op.drop_constraint(
            "fk_requirement_source_links_historical_feedback_item_id_historical_feedback_items",
            type_="foreignkey",
        )
        batch_op.drop_column("historical_feedback_item_id")
