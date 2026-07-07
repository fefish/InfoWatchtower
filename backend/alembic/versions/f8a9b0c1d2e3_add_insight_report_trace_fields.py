"""add insight report trace fields

Revision ID: f8a9b0c1d2e3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("insights") as batch_op:
        batch_op.add_column(sa.Column("raw_item_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"))
        batch_op.add_column(sa.Column("source_report_type", sa.String(length=16), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("source_report_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source_report_item_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_insights_raw_item_id_raw_items", "raw_items", ["raw_item_id"], ["id"])
        batch_op.create_index("ix_insights_raw_item_id", ["raw_item_id"])
        batch_op.create_index("ix_insights_status", ["status"])
        batch_op.create_index("ix_insights_source_report_type", ["source_report_type"])
        batch_op.create_index("ix_insights_source_report_id", ["source_report_id"])
        batch_op.create_index("ix_insights_source_report_item_id", ["source_report_item_id"])


def downgrade() -> None:
    with op.batch_alter_table("insights") as batch_op:
        batch_op.drop_index("ix_insights_source_report_item_id")
        batch_op.drop_index("ix_insights_source_report_id")
        batch_op.drop_index("ix_insights_source_report_type")
        batch_op.drop_index("ix_insights_status")
        batch_op.drop_index("ix_insights_raw_item_id")
        batch_op.drop_constraint("fk_insights_raw_item_id_raw_items", type_="foreignkey")
        batch_op.drop_column("source_report_item_id")
        batch_op.drop_column("source_report_id")
        batch_op.drop_column("source_report_type")
        batch_op.drop_column("status")
        batch_op.drop_column("raw_item_id")
