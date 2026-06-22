"""add legacy quality archives

Revision ID: 3c4d5e6f7081
Revises: 2b3c4d5e6f70
Create Date: 2026-06-18 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c4d5e6f7081"
down_revision: str | None = "2b3c4d5e6f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_feedback_items",
        sa.Column("legacy_system", sa.String(length=64), nullable=False),
        sa.Column("legacy_table", sa.String(length=64), nullable=False),
        sa.Column("legacy_id", sa.String(length=128), nullable=False),
        sa.Column("legacy_article_id", sa.String(length=128), nullable=True),
        sa.Column("raw_item_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_kind", sa.String(length=64), nullable=False),
        sa.Column("user_name", sa.Text(), nullable=False),
        sa.Column("feedback_type", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["raw_item_id"], ["raw_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_historical_feedback_items_legacy_identity",
        ),
    )
    op.create_index(op.f("ix_historical_feedback_items_domain_code"), "historical_feedback_items", ["domain_code"])
    op.create_index(op.f("ix_historical_feedback_items_feedback_at"), "historical_feedback_items", ["feedback_at"])
    op.create_index(
        op.f("ix_historical_feedback_items_feedback_kind"),
        "historical_feedback_items",
        ["feedback_kind"],
    )
    op.create_index(
        op.f("ix_historical_feedback_items_feedback_type"),
        "historical_feedback_items",
        ["feedback_type"],
    )
    op.create_index(op.f("ix_historical_feedback_items_global_id"), "historical_feedback_items", ["global_id"], unique=True)
    op.create_index(
        op.f("ix_historical_feedback_items_legacy_article_id"),
        "historical_feedback_items",
        ["legacy_article_id"],
    )
    op.create_index(op.f("ix_historical_feedback_items_legacy_id"), "historical_feedback_items", ["legacy_id"])
    op.create_index(
        op.f("ix_historical_feedback_items_legacy_system"),
        "historical_feedback_items",
        ["legacy_system"],
    )
    op.create_index(op.f("ix_historical_feedback_items_legacy_table"), "historical_feedback_items", ["legacy_table"])
    op.create_index(op.f("ix_historical_feedback_items_raw_item_id"), "historical_feedback_items", ["raw_item_id"])
    op.create_index(op.f("ix_historical_feedback_items_sync_policy"), "historical_feedback_items", ["sync_policy"])
    op.create_index(
        op.f("ix_historical_feedback_items_visibility_scope"),
        "historical_feedback_items",
        ["visibility_scope"],
    )
    op.create_index(
        op.f("ix_historical_feedback_items_workspace_code"),
        "historical_feedback_items",
        ["workspace_code"],
    )

    op.create_table(
        "historical_job_runs",
        sa.Column("legacy_system", sa.String(length=64), nullable=False),
        sa.Column("legacy_table", sa.String(length=64), nullable=False),
        sa.Column("legacy_id", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_sources", sa.Integer(), nullable=False),
        sa.Column("processed_sources", sa.Integer(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
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
            name="uq_historical_job_runs_legacy_identity",
        ),
    )
    op.create_index(op.f("ix_historical_job_runs_domain_code"), "historical_job_runs", ["domain_code"])
    op.create_index(op.f("ix_historical_job_runs_global_id"), "historical_job_runs", ["global_id"], unique=True)
    op.create_index(op.f("ix_historical_job_runs_job_type"), "historical_job_runs", ["job_type"])
    op.create_index(op.f("ix_historical_job_runs_legacy_id"), "historical_job_runs", ["legacy_id"])
    op.create_index(op.f("ix_historical_job_runs_legacy_system"), "historical_job_runs", ["legacy_system"])
    op.create_index(op.f("ix_historical_job_runs_legacy_table"), "historical_job_runs", ["legacy_table"])
    op.create_index(op.f("ix_historical_job_runs_started_at"), "historical_job_runs", ["started_at"])
    op.create_index(op.f("ix_historical_job_runs_status"), "historical_job_runs", ["status"])
    op.create_index(op.f("ix_historical_job_runs_sync_policy"), "historical_job_runs", ["sync_policy"])
    op.create_index(op.f("ix_historical_job_runs_visibility_scope"), "historical_job_runs", ["visibility_scope"])
    op.create_index(op.f("ix_historical_job_runs_workspace_code"), "historical_job_runs", ["workspace_code"])


def downgrade() -> None:
    op.drop_index(op.f("ix_historical_job_runs_workspace_code"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_visibility_scope"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_sync_policy"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_status"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_started_at"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_legacy_table"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_legacy_system"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_legacy_id"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_job_type"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_global_id"), table_name="historical_job_runs")
    op.drop_index(op.f("ix_historical_job_runs_domain_code"), table_name="historical_job_runs")
    op.drop_table("historical_job_runs")

    op.drop_index(op.f("ix_historical_feedback_items_workspace_code"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_visibility_scope"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_sync_policy"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_raw_item_id"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_legacy_table"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_legacy_system"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_legacy_id"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_legacy_article_id"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_global_id"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_feedback_type"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_feedback_kind"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_feedback_at"), table_name="historical_feedback_items")
    op.drop_index(op.f("ix_historical_feedback_items_domain_code"), table_name="historical_feedback_items")
    op.drop_table("historical_feedback_items")
