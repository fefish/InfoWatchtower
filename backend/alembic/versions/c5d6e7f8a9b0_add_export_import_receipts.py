"""add export import receipts

Revision ID: c5d6e7f8a9b0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-06 14:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.common import JsonColumn

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_import_receipts",
        sa.Column("export_job_id", sa.String(length=36), nullable=False),
        sa.Column("target_system", sa.String(length=128), nullable=False),
        sa.Column("import_status", sa.String(length=32), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_statement_count", sa.Integer(), nullable=False),
        sa.Column("failed_statement_count", sa.Integer(), nullable=False),
        sa.Column("failure_items_json", JsonColumn, nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("recorded_by_id", sa.String(length=36), nullable=True),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False),
        sa.Column("sync_policy", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["export_job_id"], ["export_jobs.id"]),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_export_import_receipts_domain_code"), "export_import_receipts", ["domain_code"])
    op.create_index(op.f("ix_export_import_receipts_export_job_id"), "export_import_receipts", ["export_job_id"])
    op.create_index(op.f("ix_export_import_receipts_import_status"), "export_import_receipts", ["import_status"])
    op.create_index(op.f("ix_export_import_receipts_recorded_by_id"), "export_import_receipts", ["recorded_by_id"])
    op.create_index(op.f("ix_export_import_receipts_sync_policy"), "export_import_receipts", ["sync_policy"])
    op.create_index(op.f("ix_export_import_receipts_target_system"), "export_import_receipts", ["target_system"])
    op.create_index(op.f("ix_export_import_receipts_visibility_scope"), "export_import_receipts", ["visibility_scope"])
    op.create_index(op.f("ix_export_import_receipts_workspace_code"), "export_import_receipts", ["workspace_code"])


def downgrade() -> None:
    op.drop_index(op.f("ix_export_import_receipts_workspace_code"), table_name="export_import_receipts")
    op.drop_index(op.f("ix_export_import_receipts_visibility_scope"), table_name="export_import_receipts")
    op.drop_index(op.f("ix_export_import_receipts_target_system"), table_name="export_import_receipts")
    op.drop_index(op.f("ix_export_import_receipts_sync_policy"), table_name="export_import_receipts")
    op.drop_index(op.f("ix_export_import_receipts_recorded_by_id"), table_name="export_import_receipts")
    op.drop_index(op.f("ix_export_import_receipts_import_status"), table_name="export_import_receipts")
    op.drop_index(op.f("ix_export_import_receipts_export_job_id"), table_name="export_import_receipts")
    op.drop_index(op.f("ix_export_import_receipts_domain_code"), table_name="export_import_receipts")
    op.drop_table("export_import_receipts")
