"""add ingestion runs

Revision ID: c6e7f8a9b0c1
Revises: b1a2c3d4e5f6
Create Date: 2026-05-05 21:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "c6e7f8a9b0c1"
down_revision: str | None = "b1a2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("run_key", sa.String(length=128), nullable=False),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_total", sa.Integer(), nullable=False),
        sa.Column("source_succeeded", sa.Integer(), nullable=False),
        sa.Column("source_failed", sa.Integer(), nullable=False),
        sa.Column("items_fetched", sa.Integer(), nullable=False),
        sa.Column("raw_created", sa.Integer(), nullable=False),
        sa.Column("raw_updated", sa.Integer(), nullable=False),
        sa.Column("params_json", json_type, nullable=False),
        sa.Column("summary_json", json_type, nullable=False),
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
    )
    op.create_index(op.f("ix_ingestion_runs_domain_code"), "ingestion_runs", ["domain_code"], unique=False)
    op.create_index(op.f("ix_ingestion_runs_global_id"), "ingestion_runs", ["global_id"], unique=True)
    op.create_index(op.f("ix_ingestion_runs_run_key"), "ingestion_runs", ["run_key"], unique=True)
    op.create_index(op.f("ix_ingestion_runs_run_type"), "ingestion_runs", ["run_type"], unique=False)
    op.create_index(op.f("ix_ingestion_runs_status"), "ingestion_runs", ["status"], unique=False)
    op.create_index(op.f("ix_ingestion_runs_sync_policy"), "ingestion_runs", ["sync_policy"], unique=False)
    op.create_index(
        op.f("ix_ingestion_runs_visibility_scope"),
        "ingestion_runs",
        ["visibility_scope"],
        unique=False,
    )
    op.create_index(op.f("ix_ingestion_runs_workspace_code"), "ingestion_runs", ["workspace_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_runs_workspace_code"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_visibility_scope"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_sync_policy"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_status"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_run_type"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_run_key"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_global_id"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_domain_code"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
