"""add generation template columns and daily usage ledger

WP3-B/WP3-C（docs/backend/report-renditions-design.md §10、
docs/backend/generation-provider-design.md §3.2）：
- report_formats.generation_template(+_source)：模板规范形 + 上传原文；
- generated_news.template_extras_json：按 format_code 分桶的增量字段产出；
- generation_daily_usage：工作台每日模型调用计数（daily_generation_budget 口径）。

依赖说明：down_revision 固定为 WP3-A 的 e1a2b3c4d5f6（编写本文件时该迁移
尚未落地；sqlite 测试走 Base.metadata.create_all 不受影响，postgres 升级
需等 WP3-A 迁移合入后按链执行）。

Revision ID: e2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-07-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2b3c4d5e6a7"
down_revision: str | None = "e1a2b3c4d5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "report_formats",
        sa.Column("generation_template", sa.JSON(), nullable=True),
    )
    op.add_column(
        "report_formats",
        sa.Column("generation_template_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "generated_news",
        sa.Column("template_extras_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "generation_daily_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("day_key", sa.String(length=10), nullable=False),
        sa.Column("calls_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_code", "day_key", name="uq_generation_daily_usage_ws_day"),
    )
    op.create_index(
        "ix_generation_daily_usage_workspace_code",
        "generation_daily_usage",
        ["workspace_code"],
    )
    op.create_index(
        "ix_generation_daily_usage_day_key",
        "generation_daily_usage",
        ["day_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_daily_usage_day_key", table_name="generation_daily_usage")
    op.drop_index(
        "ix_generation_daily_usage_workspace_code",
        table_name="generation_daily_usage",
    )
    op.drop_table("generation_daily_usage")
    op.drop_column("generated_news", "template_extras_json")
    op.drop_column("report_formats", "generation_template_source")
    op.drop_column("report_formats", "generation_template")
