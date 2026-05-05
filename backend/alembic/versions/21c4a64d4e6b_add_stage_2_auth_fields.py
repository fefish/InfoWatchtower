"""add stage 2 auth fields

Revision ID: 21c4a64d4e6b
Revises: f65224efb871
Create Date: 2026-05-05 12:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "21c4a64d4e6b"
down_revision: str | None = "f65224efb871"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        )
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(
            "uq_users_external_identity",
            ["external_provider", "external_id"],
        )
        batch_op.alter_column("status", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_external_identity", type_="unique")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("status")
