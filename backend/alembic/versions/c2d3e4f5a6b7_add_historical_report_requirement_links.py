"""add historical report requirement links

Revision ID: c2d3e4f5a6b7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-06 12:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.add_column(sa.Column("historical_report_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_requirement_source_links_historical_report_id_historical_reports",
            "historical_reports",
            ["historical_report_id"],
            ["id"],
        )
        batch_op.create_index("ix_requirement_source_links_historical_report_id", ["historical_report_id"])


def downgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.drop_index("ix_requirement_source_links_historical_report_id")
        batch_op.drop_constraint(
            "fk_requirement_source_links_historical_report_id_historical_reports",
            type_="foreignkey",
        )
        batch_op.drop_column("historical_report_id")
