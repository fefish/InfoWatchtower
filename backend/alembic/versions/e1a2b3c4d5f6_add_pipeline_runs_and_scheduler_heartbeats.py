"""add pipeline runs and scheduler heartbeats

Revision ID: e1a2b3c4d5f6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a2b3c4d5f6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False),
        sa.Column("sync_policy", sa.String(length=32), nullable=False),
        sa.Column("global_id", sa.String(length=64), nullable=False),
        sa.Column("origin_instance_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("pipeline_type", sa.String(length=64), nullable=False),
        sa.Column("day_key", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("triggered_by", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", JSON_TYPE, nullable=False),
        sa.Column("summary_json", JSON_TYPE, nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("skip_reason", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_of_run_id", sa.String(length=36), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_reason", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["retry_of_run_id"], ["pipeline_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pipeline_runs_workspace_code"), "pipeline_runs", ["workspace_code"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_domain_code"), "pipeline_runs", ["domain_code"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_visibility_scope"), "pipeline_runs", ["visibility_scope"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_sync_policy"), "pipeline_runs", ["sync_policy"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_global_id"), "pipeline_runs", ["global_id"], unique=True)
    op.create_index(op.f("ix_pipeline_runs_pipeline_type"), "pipeline_runs", ["pipeline_type"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_day_key"), "pipeline_runs", ["day_key"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_status"), "pipeline_runs", ["status"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_trigger_type"), "pipeline_runs", ["trigger_type"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_error_code"), "pipeline_runs", ["error_code"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_retry_of_run_id"), "pipeline_runs", ["retry_of_run_id"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_next_retry_at"), "pipeline_runs", ["next_retry_at"], unique=False)

    op.create_table(
        "scheduler_heartbeats",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scheduler_instance", sa.String(length=128), nullable=False),
        sa.Column("job_kind", sa.String(length=64), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("last_tick_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_enqueued_job_id", sa.String(length=128), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scheduler_instance",
            "job_kind",
            "workspace_code",
            name="uq_scheduler_heartbeats_instance_kind_workspace",
        ),
    )
    op.create_index(
        op.f("ix_scheduler_heartbeats_scheduler_instance"),
        "scheduler_heartbeats",
        ["scheduler_instance"],
        unique=False,
    )
    op.create_index(op.f("ix_scheduler_heartbeats_job_kind"), "scheduler_heartbeats", ["job_kind"], unique=False)
    op.create_index(
        op.f("ix_scheduler_heartbeats_workspace_code"),
        "scheduler_heartbeats",
        ["workspace_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_scheduler_heartbeats_workspace_code"), table_name="scheduler_heartbeats")
    op.drop_index(op.f("ix_scheduler_heartbeats_job_kind"), table_name="scheduler_heartbeats")
    op.drop_index(op.f("ix_scheduler_heartbeats_scheduler_instance"), table_name="scheduler_heartbeats")
    op.drop_table("scheduler_heartbeats")
    op.drop_index(op.f("ix_pipeline_runs_next_retry_at"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_retry_of_run_id"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_error_code"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_trigger_type"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_status"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_day_key"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_pipeline_type"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_global_id"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_sync_policy"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_visibility_scope"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_domain_code"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_workspace_code"), table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
