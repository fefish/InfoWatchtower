"""add requirement report item links

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-06 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.add_column(sa.Column("daily_report_item_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("weekly_report_item_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_req_src_links_daily_report_item_id",
            "daily_report_items",
            ["daily_report_item_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_req_src_links_weekly_report_item_id",
            "weekly_report_items",
            ["weekly_report_item_id"],
            ["id"],
        )
        batch_op.create_index("ix_requirement_source_links_daily_report_item_id", ["daily_report_item_id"])
        batch_op.create_index("ix_requirement_source_links_weekly_report_item_id", ["weekly_report_item_id"])


def downgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.drop_index("ix_requirement_source_links_weekly_report_item_id")
        batch_op.drop_index("ix_requirement_source_links_daily_report_item_id")
        batch_op.drop_constraint(
            "fk_req_src_links_weekly_report_item_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_req_src_links_daily_report_item_id",
            type_="foreignkey",
        )
        batch_op.drop_column("weekly_report_item_id")
        batch_op.drop_column("daily_report_item_id")
