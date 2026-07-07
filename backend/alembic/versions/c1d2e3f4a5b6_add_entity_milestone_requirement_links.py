"""add entity milestone requirement links

Revision ID: c1d2e3f4a5b6
Revises: c0d1e2f3a4b5
Create Date: 2026-07-06 12:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.add_column(sa.Column("entity_milestone_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_req_src_links_entity_milestone_id",
            "entity_milestones",
            ["entity_milestone_id"],
            ["id"],
        )
        batch_op.create_index("ix_requirement_source_links_entity_milestone_id", ["entity_milestone_id"])


def downgrade() -> None:
    with op.batch_alter_table("requirement_source_links") as batch_op:
        batch_op.drop_index("ix_requirement_source_links_entity_milestone_id")
        batch_op.drop_constraint(
            "fk_req_src_links_entity_milestone_id",
            type_="foreignkey",
        )
        batch_op.drop_column("entity_milestone_id")
