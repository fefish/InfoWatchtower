"""add activity events and notifications

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-05 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("target_object_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("target_object_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("sync_policy", sa.String(length=32), nullable=False, server_default="local_only"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_activity_events_actor_user_id"), "activity_events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_activity_events_event_type"), "activity_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_activity_events_object_id"), "activity_events", ["object_id"], unique=False)
    op.create_index(op.f("ix_activity_events_object_type"), "activity_events", ["object_type"], unique=False)
    op.create_index(op.f("ix_activity_events_sync_policy"), "activity_events", ["sync_policy"], unique=False)
    op.create_index(op.f("ix_activity_events_target_object_id"), "activity_events", ["target_object_id"], unique=False)
    op.create_index(op.f("ix_activity_events_target_object_type"), "activity_events", ["target_object_type"], unique=False)
    op.create_index(op.f("ix_activity_events_workspace_code"), "activity_events", ["workspace_code"], unique=False)
    op.create_index(op.f("ix_activity_events_domain_code"), "activity_events", ["domain_code"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("activity_event_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unread"),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="normal"),
        sa.Column("delivery_channel", sa.String(length=32), nullable=False, server_default="in_app"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["activity_event_id"], ["activity_events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_activity_event_id"), "notifications", ["activity_event_id"], unique=False)
    op.create_index(op.f("ix_notifications_priority"), "notifications", ["priority"], unique=False)
    op.create_index(op.f("ix_notifications_status"), "notifications", ["status"], unique=False)
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index(op.f("ix_notifications_workspace_code"), "notifications", ["workspace_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_workspace_code"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_status"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_priority"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_activity_event_id"), table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_activity_events_domain_code"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_workspace_code"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_target_object_type"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_target_object_id"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_sync_policy"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_object_type"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_object_id"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_event_type"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_actor_user_id"), table_name="activity_events")
    op.drop_table("activity_events")
