"""scope daily reports by workspace

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-05-06 11:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("daily_reports") as batch_op:
        batch_op.drop_constraint("uq_daily_reports_domain_day", type_="unique")
        batch_op.create_unique_constraint(
            "uq_daily_reports_workspace_domain_day",
            ["workspace_code", "domain_code", "day_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("daily_reports") as batch_op:
        batch_op.drop_constraint("uq_daily_reports_workspace_domain_day", type_="unique")
        batch_op.create_unique_constraint(
            "uq_daily_reports_domain_day",
            ["domain_code", "day_key"],
        )
