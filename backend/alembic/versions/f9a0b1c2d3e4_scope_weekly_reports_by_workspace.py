"""scope weekly reports by workspace

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-05-14 16:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch_op:
        batch_op.drop_constraint("uq_weekly_reports_domain_week", type_="unique")
        batch_op.create_unique_constraint(
            "uq_weekly_reports_workspace_domain_week",
            ["workspace_code", "domain_code", "week_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch_op:
        batch_op.drop_constraint("uq_weekly_reports_workspace_domain_week", type_="unique")
        batch_op.create_unique_constraint(
            "uq_weekly_reports_domain_week",
            ["domain_code", "week_key"],
        )
