"""scope dedupe groups by workspace

Revision ID: d7e8f9a0b1c2
Revises: c6e7f8a9b0c1
Create Date: 2026-05-06 09:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_dedupe_groups_dedupe_key"), table_name="dedupe_groups")
    op.create_index(op.f("ix_dedupe_groups_dedupe_key"), "dedupe_groups", ["dedupe_key"], unique=False)
    with op.batch_alter_table("dedupe_groups") as batch_op:
        batch_op.create_unique_constraint(
            "uq_dedupe_groups_workspace_key",
            ["workspace_code", "dedupe_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("dedupe_groups") as batch_op:
        batch_op.drop_constraint("uq_dedupe_groups_workspace_key", type_="unique")
    op.drop_index(op.f("ix_dedupe_groups_dedupe_key"), table_name="dedupe_groups")
    op.create_index(op.f("ix_dedupe_groups_dedupe_key"), "dedupe_groups", ["dedupe_key"], unique=True)
