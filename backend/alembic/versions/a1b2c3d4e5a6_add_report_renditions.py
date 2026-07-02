"""add report renditions, formats, insight fields and headline flag

Revision ID: a1b2c3d4e5a6
Revises: 3c4d5e6f7081
Create Date: 2026-07-02 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5a6"
down_revision: str | None = "3c4d5e6f7081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generated_news",
        sa.Column("insight_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "daily_report_items",
        sa.Column("is_headline", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_daily_report_items_is_headline",
        "daily_report_items",
        ["is_headline"],
    )

    op.create_table(
        "report_formats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_code", sa.String(length=64), nullable=False, index=True),
        sa.Column("domain_code", sa.String(length=64), nullable=False, server_default="ai"),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False, server_default="public"),
        sa.Column("sync_policy", sa.String(length=32), nullable=False, server_default="public_to_intranet"),
        sa.Column("global_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("origin_instance_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("format_code", sa.String(length=64), nullable=False, index=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("group_by", sa.String(length=32), nullable=False, server_default="category"),
        sa.Column("headline_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("headline_auto_top_n", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("item_fields", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("export_targets", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_code", "format_code", name="uq_report_formats_workspace_code"),
    )

    op.create_table(
        "report_renditions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_code", sa.String(length=64), nullable=False, index=True),
        sa.Column("domain_code", sa.String(length=64), nullable=False, server_default="ai"),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False, server_default="public"),
        sa.Column("sync_policy", sa.String(length=32), nullable=False, server_default="public_to_intranet"),
        sa.Column("global_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("origin_instance_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("report_type", sa.String(length=16), nullable=False, index=True),
        sa.Column("report_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("format_code", sa.String(length=64), nullable=False, index=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("body_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("generated_by", sa.String(length=64), nullable=False, server_default="rule_projection_v1"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "report_type",
            "report_id",
            "format_code",
            name="uq_report_renditions_report_format",
        ),
    )


def downgrade() -> None:
    op.drop_table("report_renditions")
    op.drop_table("report_formats")
    op.drop_index("ix_daily_report_items_is_headline", table_name="daily_report_items")
    op.drop_column("daily_report_items", "is_headline")
    op.drop_column("generated_news", "insight_json")
