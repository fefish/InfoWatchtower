"""add tracked entities and milestones

Revision ID: 2b3c4d5e6f70
Revises: 1a2b3c4d5e6f
Create Date: 2026-06-18 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2b3c4d5e6f70"
down_revision: str | None = "1a2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tracked_entities",
        sa.Column("legacy_system", sa.String(length=64), nullable=False),
        sa.Column("legacy_table", sa.String(length=64), nullable=False),
        sa.Column("legacy_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("rank", sa.String(length=32), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("influence_score", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
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
            name="uq_tracked_entities_legacy_identity",
        ),
    )
    op.create_index(op.f("ix_tracked_entities_domain_code"), "tracked_entities", ["domain_code"])
    op.create_index(op.f("ix_tracked_entities_entity_type"), "tracked_entities", ["entity_type"])
    op.create_index(op.f("ix_tracked_entities_global_id"), "tracked_entities", ["global_id"], unique=True)
    op.create_index(op.f("ix_tracked_entities_influence_score"), "tracked_entities", ["influence_score"])
    op.create_index(op.f("ix_tracked_entities_legacy_id"), "tracked_entities", ["legacy_id"])
    op.create_index(op.f("ix_tracked_entities_legacy_system"), "tracked_entities", ["legacy_system"])
    op.create_index(op.f("ix_tracked_entities_legacy_table"), "tracked_entities", ["legacy_table"])
    op.create_index(op.f("ix_tracked_entities_name"), "tracked_entities", ["name"])
    op.create_index(op.f("ix_tracked_entities_rank"), "tracked_entities", ["rank"])
    op.create_index(op.f("ix_tracked_entities_sync_policy"), "tracked_entities", ["sync_policy"])
    op.create_index(op.f("ix_tracked_entities_visibility_scope"), "tracked_entities", ["visibility_scope"])
    op.create_index(op.f("ix_tracked_entities_workspace_code"), "tracked_entities", ["workspace_code"])

    op.create_table(
        "entity_milestones",
        sa.Column("legacy_system", sa.String(length=64), nullable=False),
        sa.Column("legacy_table", sa.String(length=64), nullable=False),
        sa.Column("legacy_id", sa.String(length=128), nullable=False),
        sa.Column("tracked_entity_id", sa.String(length=36), nullable=False),
        sa.Column("legacy_entity_id", sa.String(length=128), nullable=False),
        sa.Column("legacy_article_id", sa.String(length=128), nullable=True),
        sa.Column("legacy_report_id", sa.String(length=128), nullable=True),
        sa.Column("raw_item_id", sa.String(length=36), nullable=True),
        sa.Column("historical_report_id", sa.String(length=36), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("event_content", sa.Text(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("event_brief", sa.Text(), nullable=False),
        sa.Column("impact_brief", sa.Text(), nullable=False),
        sa.Column("timeline_brief", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("board", sa.String(length=128), nullable=False),
        sa.Column("selected_for_timeline", sa.Boolean(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("importance_level", sa.String(length=32), nullable=False),
        sa.Column("event_dedupe_key", sa.String(length=256), nullable=False),
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
        sa.ForeignKeyConstraint(["historical_report_id"], ["historical_reports.id"]),
        sa.ForeignKeyConstraint(["raw_item_id"], ["raw_items.id"]),
        sa.ForeignKeyConstraint(["tracked_entity_id"], ["tracked_entities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_entity_milestones_legacy_identity",
        ),
    )
    op.create_index(op.f("ix_entity_milestones_board"), "entity_milestones", ["board"])
    op.create_index(op.f("ix_entity_milestones_domain_code"), "entity_milestones", ["domain_code"])
    op.create_index(op.f("ix_entity_milestones_event_dedupe_key"), "entity_milestones", ["event_dedupe_key"])
    op.create_index(op.f("ix_entity_milestones_event_time"), "entity_milestones", ["event_time"])
    op.create_index(op.f("ix_entity_milestones_event_type"), "entity_milestones", ["event_type"])
    op.create_index(op.f("ix_entity_milestones_global_id"), "entity_milestones", ["global_id"], unique=True)
    op.create_index(
        op.f("ix_entity_milestones_historical_report_id"),
        "entity_milestones",
        ["historical_report_id"],
    )
    op.create_index(op.f("ix_entity_milestones_importance_level"), "entity_milestones", ["importance_level"])
    op.create_index(op.f("ix_entity_milestones_importance_score"), "entity_milestones", ["importance_score"])
    op.create_index(op.f("ix_entity_milestones_legacy_article_id"), "entity_milestones", ["legacy_article_id"])
    op.create_index(op.f("ix_entity_milestones_legacy_entity_id"), "entity_milestones", ["legacy_entity_id"])
    op.create_index(op.f("ix_entity_milestones_legacy_id"), "entity_milestones", ["legacy_id"])
    op.create_index(op.f("ix_entity_milestones_legacy_report_id"), "entity_milestones", ["legacy_report_id"])
    op.create_index(op.f("ix_entity_milestones_legacy_system"), "entity_milestones", ["legacy_system"])
    op.create_index(op.f("ix_entity_milestones_legacy_table"), "entity_milestones", ["legacy_table"])
    op.create_index(op.f("ix_entity_milestones_raw_item_id"), "entity_milestones", ["raw_item_id"])
    op.create_index(
        op.f("ix_entity_milestones_selected_for_timeline"),
        "entity_milestones",
        ["selected_for_timeline"],
    )
    op.create_index(op.f("ix_entity_milestones_sync_policy"), "entity_milestones", ["sync_policy"])
    op.create_index(op.f("ix_entity_milestones_tracked_entity_id"), "entity_milestones", ["tracked_entity_id"])
    op.create_index(op.f("ix_entity_milestones_visibility_scope"), "entity_milestones", ["visibility_scope"])
    op.create_index(op.f("ix_entity_milestones_workspace_code"), "entity_milestones", ["workspace_code"])


def downgrade() -> None:
    op.drop_index(op.f("ix_entity_milestones_workspace_code"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_visibility_scope"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_tracked_entity_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_sync_policy"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_selected_for_timeline"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_raw_item_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_legacy_table"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_legacy_system"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_legacy_report_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_legacy_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_legacy_entity_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_legacy_article_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_importance_score"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_importance_level"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_historical_report_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_global_id"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_event_type"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_event_time"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_event_dedupe_key"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_domain_code"), table_name="entity_milestones")
    op.drop_index(op.f("ix_entity_milestones_board"), table_name="entity_milestones")
    op.drop_table("entity_milestones")

    op.drop_index(op.f("ix_tracked_entities_workspace_code"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_visibility_scope"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_sync_policy"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_rank"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_name"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_legacy_table"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_legacy_system"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_legacy_id"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_influence_score"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_global_id"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_entity_type"), table_name="tracked_entities")
    op.drop_index(op.f("ix_tracked_entities_domain_code"), table_name="tracked_entities")
    op.drop_table("tracked_entities")
