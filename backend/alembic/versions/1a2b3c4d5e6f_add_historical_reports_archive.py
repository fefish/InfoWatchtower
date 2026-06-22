"""add historical reports archive

Revision ID: 1a2b3c4d5e6f
Revises: 0a1b2c3d4e5f
Create Date: 2026-06-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: str | None = "0a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_reports",
        sa.Column("legacy_system", sa.String(length=64), nullable=False),
        sa.Column("legacy_table", sa.String(length=64), nullable=False),
        sa.Column("legacy_id", sa.String(length=128), nullable=False),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("period_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False),
        sa.Column("sync_policy", sa.String(length=32), nullable=False),
        sa.Column("global_id", sa.String(length=64), nullable=False),
        sa.Column("origin_instance_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_historical_reports_legacy_identity",
        ),
    )
    op.create_index(op.f("ix_historical_reports_domain_code"), "historical_reports", ["domain_code"])
    op.create_index(op.f("ix_historical_reports_global_id"), "historical_reports", ["global_id"], unique=True)
    op.create_index(op.f("ix_historical_reports_legacy_id"), "historical_reports", ["legacy_id"])
    op.create_index(op.f("ix_historical_reports_legacy_system"), "historical_reports", ["legacy_system"])
    op.create_index(op.f("ix_historical_reports_legacy_table"), "historical_reports", ["legacy_table"])
    op.create_index(op.f("ix_historical_reports_report_type"), "historical_reports", ["report_type"])
    op.create_index(op.f("ix_historical_reports_status"), "historical_reports", ["status"])
    op.create_index(op.f("ix_historical_reports_sync_policy"), "historical_reports", ["sync_policy"])
    op.create_index(op.f("ix_historical_reports_visibility_scope"), "historical_reports", ["visibility_scope"])
    op.create_index(op.f("ix_historical_reports_workspace_code"), "historical_reports", ["workspace_code"])


def downgrade() -> None:
    op.drop_index(op.f("ix_historical_reports_workspace_code"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_visibility_scope"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_sync_policy"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_status"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_report_type"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_legacy_table"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_legacy_system"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_legacy_id"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_global_id"), table_name="historical_reports")
    op.drop_index(op.f("ix_historical_reports_domain_code"), table_name="historical_reports")
    op.drop_table("historical_reports")
