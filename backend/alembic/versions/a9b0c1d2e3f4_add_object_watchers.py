"""add object watchers

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-07-06 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: str | None = "f8a9b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_watchers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_code",
            "object_type",
            "object_id",
            name="uq_object_watchers_user_object",
        ),
    )
    op.create_index(op.f("ix_object_watchers_active"), "object_watchers", ["active"], unique=False)
    op.create_index(op.f("ix_object_watchers_object_id"), "object_watchers", ["object_id"], unique=False)
    op.create_index(op.f("ix_object_watchers_object_type"), "object_watchers", ["object_type"], unique=False)
    op.create_index(op.f("ix_object_watchers_user_id"), "object_watchers", ["user_id"], unique=False)
    op.create_index(op.f("ix_object_watchers_workspace_code"), "object_watchers", ["workspace_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_object_watchers_workspace_code"), table_name="object_watchers")
    op.drop_index(op.f("ix_object_watchers_user_id"), table_name="object_watchers")
    op.drop_index(op.f("ix_object_watchers_object_type"), table_name="object_watchers")
    op.drop_index(op.f("ix_object_watchers_object_id"), table_name="object_watchers")
    op.drop_index(op.f("ix_object_watchers_active"), table_name="object_watchers")
    op.drop_table("object_watchers")
