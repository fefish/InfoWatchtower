"""add feedback rollups and rubric revision proposals

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6a7
Create Date: 2026-07-08 12:00:00.000000

WP4-G 反馈回哺工作流（feedback-heat-scoring §16.1，契约
recommendation_ranking.json `feedback_workflow.data_model_deltas`）：
单迁移新增 feedback_rollups + rubric_revision_proposals 两表，均无 SyncMixin、
永不进同步 feed 与公司 SQL 导出。无既有表变更、不回填任何数据；
generation_daily_usage.purpose 的新枚举 feedback_rollup 由 String 列直接容纳，
无迁移。down_revision 固定指向定稿日 e/f 链 head f2b3c4d5e6a7。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3c4d5e6f7a8"
down_revision: str | None = "f2b3c4d5e6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_rollups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("period_type", sa.String(length=16), nullable=False),
        sa.Column("period_key", sa.String(length=16), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="succeeded"),
        sa.Column("proposal_status", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("source_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("topic_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("sample_refs_json", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_code",
            "period_type",
            "period_key",
            name="uq_feedback_rollups_ws_period",
        ),
    )
    op.create_index(
        op.f("ix_feedback_rollups_workspace_code"),
        "feedback_rollups",
        ["workspace_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_rollups_period_type"),
        "feedback_rollups",
        ["period_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_rollups_period_key"),
        "feedback_rollups",
        ["period_key"],
        unique=False,
    )

    op.create_table(
        "rubric_revision_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("rollup_id", sa.String(length=36), nullable=False),
        sa.Column("base_rubric_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "prompt_version",
            sa.String(length=32),
            nullable=False,
            server_default="revision_prompt_v1",
        ),
        sa.Column("proposed_rubric_json", sa.JSON(), nullable=False),
        sa.Column("change_summary_json", sa.JSON(), nullable=False),
        sa.Column("sample_refs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending_review"),
        sa.Column("review_comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compile_fingerprint", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rollup_id"], ["feedback_rollups.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rubric_revision_proposals_workspace_code"),
        "rubric_revision_proposals",
        ["workspace_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rubric_revision_proposals_rollup_id"),
        "rubric_revision_proposals",
        ["rollup_id"],
        unique=False,
    )
    op.create_index(
        "ix_rubric_revision_proposals_ws_status",
        "rubric_revision_proposals",
        ["workspace_code", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rubric_revision_proposals_ws_status",
        table_name="rubric_revision_proposals",
    )
    op.drop_index(
        op.f("ix_rubric_revision_proposals_rollup_id"),
        table_name="rubric_revision_proposals",
    )
    op.drop_index(
        op.f("ix_rubric_revision_proposals_workspace_code"),
        table_name="rubric_revision_proposals",
    )
    op.drop_table("rubric_revision_proposals")
    op.drop_index(op.f("ix_feedback_rollups_period_key"), table_name="feedback_rollups")
    op.drop_index(op.f("ix_feedback_rollups_period_type"), table_name="feedback_rollups")
    op.drop_index(op.f("ix_feedback_rollups_workspace_code"), table_name="feedback_rollups")
    op.drop_table("feedback_rollups")
