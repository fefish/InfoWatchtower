"""add llm provider credentials

Revision ID: f2b3c4d5e6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-08 10:00:00.000000

llm_provider_credentials（generation-provider-design §9.2，决策变更
D-2026-07-08-KEY）：instance 级凭据表，key 只存 Fernet 密文。新增表一张、
无既有表变更；不回填任何数据（env 配置不自动导入 DB，避免密钥在未经用户
确认下改变存放位置）。down_revision 固定指向 WP4-A 的 f1a2b3c4d5e6
（generation_daily_usage purpose 分桶迁移，实施计划 §18 冲突提示约定）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2b3c4d5e6a7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("global_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("key_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("key_last4", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("label", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_global_id"),
        "llm_provider_credentials",
        ["global_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_provider"),
        "llm_provider_credentials",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_enabled"),
        "llm_provider_credentials",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_created_by_id"),
        "llm_provider_credentials",
        ["created_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_llm_provider_credentials_created_by_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_enabled"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_provider"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_global_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_table("llm_provider_credentials")
