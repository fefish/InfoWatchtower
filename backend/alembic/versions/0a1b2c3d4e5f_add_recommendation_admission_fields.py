"""add recommendation admission fields

Revision ID: 0a1b2c3d4e5f
Revises: f9a0b1c2d3e4
Create Date: 2026-06-12 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recommendation_items") as batch_op:
        batch_op.add_column(sa.Column("admission_level", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("admission_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("admission_pool", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("noise_types_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("reject_reasons_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("scorer_breakdown_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("expert_routes_json", sa.JSON(), nullable=True))
        batch_op.create_index("ix_recommendation_items_admission_level", ["admission_level"])
        batch_op.create_index("ix_recommendation_items_admission_pool", ["admission_pool"])

    op.execute("UPDATE recommendation_items SET admission_level = '' WHERE admission_level IS NULL")
    op.execute("UPDATE recommendation_items SET admission_score = 0 WHERE admission_score IS NULL")
    op.execute("UPDATE recommendation_items SET admission_pool = '' WHERE admission_pool IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("recommendation_items") as batch_op:
        batch_op.drop_index("ix_recommendation_items_admission_pool")
        batch_op.drop_index("ix_recommendation_items_admission_level")
        batch_op.drop_column("expert_routes_json")
        batch_op.drop_column("scorer_breakdown_json")
        batch_op.drop_column("reject_reasons_json")
        batch_op.drop_column("noise_types_json")
        batch_op.drop_column("admission_pool")
        batch_op.drop_column("admission_score")
        batch_op.drop_column("admission_level")
