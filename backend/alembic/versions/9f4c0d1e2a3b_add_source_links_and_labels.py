"""add source links and labels

Revision ID: 9f4c0d1e2a3b
Revises: 7b8d2a91f4c3
Create Date: 2026-05-05 15:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "9f4c0d1e2a3b"
down_revision: str | None = "7b8d2a91f4c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workspace_source_links",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source_weight", sa.Float(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=True),
        sa.Column("config_json", json_type, nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "data_source_id", name="uq_workspace_source_link"),
    )
    op.create_index(
        op.f("ix_workspace_source_links_data_source_id"),
        "workspace_source_links",
        ["data_source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_source_links_domain_code"),
        "workspace_source_links",
        ["domain_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_source_links_enabled"),
        "workspace_source_links",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_source_links_workspace_id"),
        "workspace_source_links",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "label_sets",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("target_types", json_type, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_json", json_type, nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False),
        sa.Column("sync_policy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_code", "domain_code", "code", name="uq_label_sets_scope_code"),
    )
    op.create_index(op.f("ix_label_sets_code"), "label_sets", ["code"], unique=False)
    op.create_index(op.f("ix_label_sets_domain_code"), "label_sets", ["domain_code"], unique=False)
    op.create_index(op.f("ix_label_sets_enabled"), "label_sets", ["enabled"], unique=False)
    op.create_index(op.f("ix_label_sets_scope_type"), "label_sets", ["scope_type"], unique=False)
    op.create_index(op.f("ix_label_sets_sync_policy"), "label_sets", ["sync_policy"], unique=False)
    op.create_index(
        op.f("ix_label_sets_visibility_scope"),
        "label_sets",
        ["visibility_scope"],
        unique=False,
    )
    op.create_index(op.f("ix_label_sets_workspace_code"), "label_sets", ["workspace_code"], unique=False)

    op.create_table(
        "labels",
        sa.Column("label_set_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["label_set_id"], ["label_sets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label_set_id", "code", name="uq_labels_set_code"),
    )
    op.create_index(op.f("ix_labels_code"), "labels", ["code"], unique=False)
    op.create_index(op.f("ix_labels_enabled"), "labels", ["enabled"], unique=False)
    op.create_index(op.f("ix_labels_label_set_id"), "labels", ["label_set_id"], unique=False)
    op.create_index(op.f("ix_labels_name"), "labels", ["name"], unique=False)

    op.create_table(
        "content_labels",
        sa.Column("label_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("assignment_source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False),
        sa.Column("sync_policy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["label_id"], ["labels.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label_id", "target_type", "target_id", name="uq_content_labels_target"),
    )
    op.create_index(op.f("ix_content_labels_assignment_source"), "content_labels", ["assignment_source"], unique=False)
    op.create_index(op.f("ix_content_labels_domain_code"), "content_labels", ["domain_code"], unique=False)
    op.create_index(op.f("ix_content_labels_label_id"), "content_labels", ["label_id"], unique=False)
    op.create_index(op.f("ix_content_labels_sync_policy"), "content_labels", ["sync_policy"], unique=False)
    op.create_index(op.f("ix_content_labels_target_id"), "content_labels", ["target_id"], unique=False)
    op.create_index(op.f("ix_content_labels_target_type"), "content_labels", ["target_type"], unique=False)
    op.create_index(
        op.f("ix_content_labels_visibility_scope"),
        "content_labels",
        ["visibility_scope"],
        unique=False,
    )
    op.create_index(op.f("ix_content_labels_workspace_code"), "content_labels", ["workspace_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_content_labels_workspace_code"), table_name="content_labels")
    op.drop_index(op.f("ix_content_labels_visibility_scope"), table_name="content_labels")
    op.drop_index(op.f("ix_content_labels_target_type"), table_name="content_labels")
    op.drop_index(op.f("ix_content_labels_target_id"), table_name="content_labels")
    op.drop_index(op.f("ix_content_labels_sync_policy"), table_name="content_labels")
    op.drop_index(op.f("ix_content_labels_label_id"), table_name="content_labels")
    op.drop_index(op.f("ix_content_labels_domain_code"), table_name="content_labels")
    op.drop_index(op.f("ix_content_labels_assignment_source"), table_name="content_labels")
    op.drop_table("content_labels")
    op.drop_index(op.f("ix_labels_name"), table_name="labels")
    op.drop_index(op.f("ix_labels_label_set_id"), table_name="labels")
    op.drop_index(op.f("ix_labels_enabled"), table_name="labels")
    op.drop_index(op.f("ix_labels_code"), table_name="labels")
    op.drop_table("labels")
    op.drop_index(op.f("ix_label_sets_workspace_code"), table_name="label_sets")
    op.drop_index(op.f("ix_label_sets_visibility_scope"), table_name="label_sets")
    op.drop_index(op.f("ix_label_sets_sync_policy"), table_name="label_sets")
    op.drop_index(op.f("ix_label_sets_scope_type"), table_name="label_sets")
    op.drop_index(op.f("ix_label_sets_enabled"), table_name="label_sets")
    op.drop_index(op.f("ix_label_sets_domain_code"), table_name="label_sets")
    op.drop_index(op.f("ix_label_sets_code"), table_name="label_sets")
    op.drop_table("label_sets")
    op.drop_index(op.f("ix_workspace_source_links_workspace_id"), table_name="workspace_source_links")
    op.drop_index(op.f("ix_workspace_source_links_enabled"), table_name="workspace_source_links")
    op.drop_index(op.f("ix_workspace_source_links_domain_code"), table_name="workspace_source_links")
    op.drop_index(op.f("ix_workspace_source_links_data_source_id"), table_name="workspace_source_links")
    op.drop_table("workspace_source_links")
