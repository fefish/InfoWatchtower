"""add workspace join codes

Revision ID: e3c4d5e6f7a8
Revises: e2b3c4d5e6a7
Create Date: 2026-07-07 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3c4d5e6f7a8"
down_revision: str | None = "e2b3c4d5e6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_join_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("global_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("default_role", sa.String(length=16), nullable=False, server_default="viewer"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_join_codes_global_id"),
        "workspace_join_codes",
        ["global_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_workspace_join_codes_workspace_id"),
        "workspace_join_codes",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_join_codes_code"),
        "workspace_join_codes",
        ["code"],
        unique=True,
    )
    op.create_index(
        op.f("ix_workspace_join_codes_status"),
        "workspace_join_codes",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_join_codes_created_by_id"),
        "workspace_join_codes",
        ["created_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workspace_join_codes_created_by_id"), table_name="workspace_join_codes")
    op.drop_index(op.f("ix_workspace_join_codes_status"), table_name="workspace_join_codes")
    op.drop_index(op.f("ix_workspace_join_codes_code"), table_name="workspace_join_codes")
    op.drop_index(op.f("ix_workspace_join_codes_workspace_id"), table_name="workspace_join_codes")
    op.drop_index(op.f("ix_workspace_join_codes_global_id"), table_name="workspace_join_codes")
    op.drop_table("workspace_join_codes")
