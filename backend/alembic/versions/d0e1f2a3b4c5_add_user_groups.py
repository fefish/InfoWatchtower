"""add user groups

Revision ID: d0e1f2a3b4c5
Revises: d8e9f0a1b2c3
Create Date: 2026-07-07 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_groups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_groups_code"), "user_groups", ["code"], unique=True)

    op.create_table(
        "user_group_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["user_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_user_group_members_user"),
    )
    op.create_index(
        op.f("ix_user_group_members_group_id"),
        "user_group_members",
        ["group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_group_members_user_id"),
        "user_group_members",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_group_members_user_id"), table_name="user_group_members")
    op.drop_index(op.f("ix_user_group_members_group_id"), table_name="user_group_members")
    op.drop_table("user_group_members")
    op.drop_index(op.f("ix_user_groups_code"), table_name="user_groups")
    op.drop_table("user_groups")
