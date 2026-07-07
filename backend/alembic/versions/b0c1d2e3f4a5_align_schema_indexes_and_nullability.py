"""align schema indexes and nullability

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-07-06 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b0c1d2e3f4a5"
down_revision: str | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    _replace_index("password_reset_tokens", "ix_password_reset_tokens_token_hash", ["token_hash"], unique=True)
    _replace_index("user_invites", "ix_user_invites_code", ["code"], unique=True)
    _replace_index("user_invites", "ix_user_invites_global_id", ["global_id"], unique=True)

    op.execute(sa.text("UPDATE recommendation_items SET admission_level = '' WHERE admission_level IS NULL"))
    op.execute(sa.text("UPDATE recommendation_items SET admission_score = 0 WHERE admission_score IS NULL"))
    op.execute(sa.text("UPDATE recommendation_items SET admission_pool = '' WHERE admission_pool IS NULL"))
    op.execute(sa.text("UPDATE recommendation_items SET noise_types_json = '[]' WHERE noise_types_json IS NULL"))
    op.execute(sa.text("UPDATE recommendation_items SET reject_reasons_json = '[]' WHERE reject_reasons_json IS NULL"))
    op.execute(sa.text("UPDATE recommendation_items SET scorer_breakdown_json = '{}' WHERE scorer_breakdown_json IS NULL"))
    op.execute(sa.text("UPDATE recommendation_items SET expert_routes_json = '[]' WHERE expert_routes_json IS NULL"))
    with op.batch_alter_table("recommendation_items") as batch_op:
        batch_op.alter_column("admission_level", existing_type=sa.String(length=16), nullable=False)
        batch_op.alter_column("admission_score", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("admission_pool", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column("noise_types_json", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("reject_reasons_json", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("scorer_breakdown_json", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("expert_routes_json", existing_type=sa.JSON(), nullable=False)

    _create_index_if_missing(bind, "report_formats", "ix_report_formats_domain_code", ["domain_code"])
    _create_index_if_missing(bind, "report_formats", "ix_report_formats_enabled", ["enabled"])
    _create_index_if_missing(bind, "report_formats", "ix_report_formats_global_id", ["global_id"], unique=True)
    _create_index_if_missing(bind, "report_formats", "ix_report_formats_sync_policy", ["sync_policy"])
    _create_index_if_missing(bind, "report_formats", "ix_report_formats_visibility_scope", ["visibility_scope"])
    _create_index_if_missing(bind, "report_renditions", "ix_report_renditions_domain_code", ["domain_code"])
    _create_index_if_missing(bind, "report_renditions", "ix_report_renditions_global_id", ["global_id"], unique=True)
    _create_index_if_missing(bind, "report_renditions", "ix_report_renditions_status", ["status"])
    _create_index_if_missing(bind, "report_renditions", "ix_report_renditions_sync_policy", ["sync_policy"])
    _create_index_if_missing(bind, "report_renditions", "ix_report_renditions_visibility_scope", ["visibility_scope"])

    _drop_index_if_exists(bind, "tracked_entities", "ix_tracked_entities_name")


def downgrade() -> None:
    bind = op.get_bind()

    _create_index_if_missing(bind, "tracked_entities", "ix_tracked_entities_name", ["name"])

    for table_name, index_name in (
        ("report_renditions", "ix_report_renditions_visibility_scope"),
        ("report_renditions", "ix_report_renditions_sync_policy"),
        ("report_renditions", "ix_report_renditions_status"),
        ("report_renditions", "ix_report_renditions_global_id"),
        ("report_renditions", "ix_report_renditions_domain_code"),
        ("report_formats", "ix_report_formats_visibility_scope"),
        ("report_formats", "ix_report_formats_sync_policy"),
        ("report_formats", "ix_report_formats_global_id"),
        ("report_formats", "ix_report_formats_enabled"),
        ("report_formats", "ix_report_formats_domain_code"),
    ):
        _drop_index_if_exists(bind, table_name, index_name)

    with op.batch_alter_table("recommendation_items") as batch_op:
        batch_op.alter_column("expert_routes_json", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("scorer_breakdown_json", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("reject_reasons_json", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("noise_types_json", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("admission_pool", existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column("admission_score", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("admission_level", existing_type=sa.String(length=16), nullable=True)

    _replace_index("user_invites", "ix_user_invites_global_id", ["global_id"], unique=False)
    _replace_index("user_invites", "ix_user_invites_code", ["code"], unique=False)
    _replace_index("password_reset_tokens", "ix_password_reset_tokens_token_hash", ["token_hash"], unique=False)


def _replace_index(table_name: str, index_name: str, columns: list[str], *, unique: bool) -> None:
    bind = op.get_bind()
    _drop_index_if_exists(bind, table_name, index_name)
    op.create_index(index_name, table_name, columns, unique=unique)


def _create_index_if_missing(
    bind,
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _has_index(bind, table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(bind, table_name: str, index_name: str) -> None:
    if _has_index(bind, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspect(bind).get_indexes(table_name))
