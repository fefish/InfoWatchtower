"""add label hierarchy

Revision ID: b1a2c3d4e5f6
Revises: 9f4c0d1e2a3b
Create Date: 2026-05-05 16:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "b1a2c3d4e5f6"
down_revision: str | None = "9f4c0d1e2a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("labels") as batch_op:
        batch_op.add_column(sa.Column("parent_label_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("label_level", sa.Integer(), server_default="1", nullable=False))
        batch_op.create_foreign_key(
            "fk_labels_parent_label_id_labels",
            "labels",
            ["parent_label_id"],
            ["id"],
        )
    op.create_index(op.f("ix_labels_label_level"), "labels", ["label_level"], unique=False)
    with op.batch_alter_table("labels") as batch_op:
        batch_op.alter_column("label_level", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_labels_label_level"), table_name="labels")
    with op.batch_alter_table("labels") as batch_op:
        batch_op.drop_constraint("fk_labels_parent_label_id_labels", type_="foreignkey")
        batch_op.drop_column("label_level")
        batch_op.drop_column("parent_label_id")
