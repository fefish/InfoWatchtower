"""add workspace scope to audit logs

Revision ID: c0d1e2f3a4b5
Revises: b0c1d2e3f4a5
Create Date: 2026-07-06 10:24:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("workspace_code", sa.String(length=64), nullable=False, server_default="global"),
    )
    op.create_index(op.f("ix_audit_logs_workspace_code"), "audit_logs", ["workspace_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_workspace_code"), table_name="audit_logs")
    op.drop_column("audit_logs", "workspace_code")
