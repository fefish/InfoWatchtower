"""add workspace visibility

Revision ID: d8e9f0a1b2c3
Revises: c6d7e8f9a0b1
Create Date: 2026-07-07 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("visibility", sa.String(length=32), nullable=False, server_default="private"),
    )
    op.create_index(op.f("ix_workspaces_visibility"), "workspaces", ["visibility"], unique=False)
    # 种子口径：planning_intel 默认对登录用户开放发现/订阅（internal_public），
    # 之后可由 owner/admin 在 PATCH /api/workspaces/{code}/visibility 改回 private。
    op.execute("UPDATE workspaces SET visibility = 'internal_public' WHERE code = 'planning_intel'")


def downgrade() -> None:
    op.drop_index(op.f("ix_workspaces_visibility"), table_name="workspaces")
    op.drop_column("workspaces", "visibility")
