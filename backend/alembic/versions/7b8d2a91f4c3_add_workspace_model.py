"""add workspace model

Revision ID: 7b8d2a91f4c3
Revises: 21c4a64d4e6b
Create Date: 2026-05-05 13:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text

from sqlalchemy.dialects import postgresql

revision: str = "7b8d2a91f4c3"
down_revision: str | None = "21c4a64d4e6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPED_TABLES = [
    "daily_report_items",
    "daily_reports",
    "data_sources",
    "dedupe_groups",
    "export_jobs",
    "generated_news",
    "insights",
    "news_items",
    "raw_items",
    "recommendation_items",
    "recommendation_runs",
    "requirements",
    "strategic_implications",
    "sync_outbox",
    "topic_tasks",
    "weekly_report_items",
    "weekly_reports",
]


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("workspace_type", sa.String(length=64), nullable=False),
        sa.Column("default_domain_code", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("global_id", sa.String(length=64), nullable=False),
        sa.Column("origin_instance_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workspaces_code"), "workspaces", ["code"], unique=True)
    op.create_index(op.f("ix_workspaces_enabled"), "workspaces", ["enabled"], unique=False)
    op.create_index(op.f("ix_workspaces_global_id"), "workspaces", ["global_id"], unique=True)
    op.create_index(
        op.f("ix_workspaces_workspace_type"),
        "workspaces",
        ["workspace_type"],
        unique=False,
    )
    op.create_table(
        "workspace_sections",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("section_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("section_type", sa.String(length=64), nullable=False),
        sa.Column("route_path", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "section_key", name="uq_workspace_sections_key"),
    )
    op.create_index(
        op.f("ix_workspace_sections_enabled"),
        "workspace_sections",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_sections_section_key"),
        "workspace_sections",
        ["section_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_sections_section_type"),
        "workspace_sections",
        ["section_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_sections_workspace_id"),
        "workspace_sections",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_role", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership_user"),
    )
    op.create_index(
        op.f("ix_workspace_memberships_enabled"),
        "workspace_memberships",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_memberships_user_id"),
        "workspace_memberships",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_memberships_workspace_id"),
        "workspace_memberships",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_memberships_workspace_role"),
        "workspace_memberships",
        ["workspace_role"],
        unique=False,
    )

    for table_name in SCOPED_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "workspace_code",
                    sa.String(length=64),
                    server_default="planning_intel",
                    nullable=False,
                ),
            )
        op.create_index(
            op.f(f"ix_{table_name}_workspace_code"),
            table_name,
            ["workspace_code"],
            unique=False,
        )
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("workspace_code", server_default=None)


def downgrade() -> None:
    for table_name in reversed(SCOPED_TABLES):
        op.drop_index(op.f(f"ix_{table_name}_workspace_code"), table_name=table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("workspace_code")

    op.drop_index(op.f("ix_workspace_memberships_workspace_role"), table_name="workspace_memberships")
    op.drop_index(op.f("ix_workspace_memberships_workspace_id"), table_name="workspace_memberships")
    op.drop_index(op.f("ix_workspace_memberships_user_id"), table_name="workspace_memberships")
    op.drop_index(op.f("ix_workspace_memberships_enabled"), table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_index(op.f("ix_workspace_sections_workspace_id"), table_name="workspace_sections")
    op.drop_index(op.f("ix_workspace_sections_section_type"), table_name="workspace_sections")
    op.drop_index(op.f("ix_workspace_sections_section_key"), table_name="workspace_sections")
    op.drop_index(op.f("ix_workspace_sections_enabled"), table_name="workspace_sections")
    op.drop_table("workspace_sections")
    op.drop_index(op.f("ix_workspaces_workspace_type"), table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_global_id"), table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_enabled"), table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_code"), table_name="workspaces")
    op.drop_table("workspaces")
