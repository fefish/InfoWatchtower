"""add recommendation rerank fields, rubric compiles and feedback priors

WP4-A（docs/backend/recommendation-scoring-design.md §9.1/§10、
docs/backend/feedback-heat-scoring.md §10）单迁移：
- generation_daily_usage + purpose 列，unique 约束改 (workspace_code, day_key,
  purpose)，存量行回填 purpose='generation'（三桶配额互不挤占）;
- recommendation_items 六个精排解释列（coarse_score 回填 = final_score）;
- 新表 recommendation_rubric_compiles / source_score_snapshots /
  rubric_topic_priors / news_item_embeddings（后者仅 L2 启用时写入，留位）。

Revision ID: f1a2b3c4d5e6
Revises: e3c4d5e6f7a8
Create Date: 2026-07-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- generation_daily_usage：purpose 三桶（batch 模式兼容 sqlite 约束重建） ---
    with op.batch_alter_table("generation_daily_usage") as batch:
        batch.add_column(
            sa.Column(
                "purpose",
                sa.String(length=24),
                nullable=False,
                server_default="generation",
            ),
        )
        batch.drop_constraint("uq_generation_daily_usage_ws_day", type_="unique")
        batch.create_unique_constraint(
            "uq_generation_daily_usage_ws_day_purpose",
            ["workspace_code", "day_key", "purpose"],
        )
    op.execute("UPDATE generation_daily_usage SET purpose = 'generation' WHERE purpose IS NULL")
    op.create_index(
        "ix_generation_daily_usage_purpose",
        "generation_daily_usage",
        ["purpose"],
    )

    # --- recommendation_items：精排可解释列（coarse_score 回填 = final_score） ---
    op.add_column(
        "recommendation_items",
        sa.Column("coarse_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "recommendation_items",
        sa.Column("llm_relevance_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "recommendation_items",
        sa.Column(
            "llm_rerank_status",
            sa.String(length=24),
            nullable=False,
            server_default="not_run",
        ),
    )
    op.add_column(
        "recommendation_items",
        sa.Column("llm_rerank_reason", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "recommendation_items",
        sa.Column("rubric_hits_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "recommendation_items",
        sa.Column("rubric_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE recommendation_items SET coarse_score = final_score")

    # --- recommendation_rubric_compiles ---
    op.create_table(
        "recommendation_rubric_compiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("guidance_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rubric_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "prompt_version",
            sa.String(length=32),
            nullable=False,
            server_default="compile_prompt_v1",
        ),
        sa.Column("model_called", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_code",
            "fingerprint",
            name="uq_recommendation_rubric_compiles_ws_fp",
        ),
    )
    op.create_index(
        "ix_recommendation_rubric_compiles_workspace_code",
        "recommendation_rubric_compiles",
        ["workspace_code"],
    )
    op.create_index(
        "ix_recommendation_rubric_compiles_fingerprint",
        "recommendation_rubric_compiles",
        ["fingerprint"],
    )

    # --- source_score_snapshots ---
    op.create_table(
        "source_score_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column(
            "data_source_id",
            sa.String(length=36),
            sa.ForeignKey("data_sources.id"),
            nullable=False,
        ),
        sa.Column("window", sa.String(length=16), nullable=False, server_default="14d"),
        sa.Column("recommended_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("adopted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("adopt_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reject_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("like_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_prior_delta", sa.Float(), nullable=False, server_default="0"),
        sa.Column("day_key", sa.String(length=10), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_code",
            "data_source_id",
            "window",
            "day_key",
            name="uq_source_score_snapshots_ws_src_window_day",
        ),
    )
    op.create_index(
        "ix_source_score_snapshots_workspace_code",
        "source_score_snapshots",
        ["workspace_code"],
    )
    op.create_index(
        "ix_source_score_snapshots_data_source_id",
        "source_score_snapshots",
        ["data_source_id"],
    )
    op.create_index(
        "ix_source_score_snapshots_day_key",
        "source_score_snapshots",
        ["day_key"],
    )

    # --- rubric_topic_priors ---
    op.create_table(
        "rubric_topic_priors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_code", sa.String(length=64), nullable=False),
        sa.Column("rubric_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("topic_code", sa.String(length=32), nullable=False),
        sa.Column("pos_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("neg_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("effective_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("day_key", sa.String(length=10), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_code",
            "rubric_version",
            "topic_code",
            "day_key",
            name="uq_rubric_topic_priors_ws_ver_topic_day",
        ),
    )
    op.create_index(
        "ix_rubric_topic_priors_workspace_code",
        "rubric_topic_priors",
        ["workspace_code"],
    )
    op.create_index(
        "ix_rubric_topic_priors_rubric_version",
        "rubric_topic_priors",
        ["rubric_version"],
    )
    op.create_index(
        "ix_rubric_topic_priors_topic_code",
        "rubric_topic_priors",
        ["topic_code"],
    )
    op.create_index(
        "ix_rubric_topic_priors_day_key",
        "rubric_topic_priors",
        ["day_key"],
    )

    # --- news_item_embeddings（L2 留位，默认不写入） ---
    op.create_table(
        "news_item_embeddings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "news_item_id",
            sa.String(length=36),
            sa.ForeignKey("news_items.id"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vector_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("news_item_id", "model", name="uq_news_item_embeddings_item_model"),
    )
    op.create_index(
        "ix_news_item_embeddings_news_item_id",
        "news_item_embeddings",
        ["news_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_item_embeddings_news_item_id", table_name="news_item_embeddings")
    op.drop_table("news_item_embeddings")
    op.drop_index("ix_rubric_topic_priors_day_key", table_name="rubric_topic_priors")
    op.drop_index("ix_rubric_topic_priors_topic_code", table_name="rubric_topic_priors")
    op.drop_index("ix_rubric_topic_priors_rubric_version", table_name="rubric_topic_priors")
    op.drop_index("ix_rubric_topic_priors_workspace_code", table_name="rubric_topic_priors")
    op.drop_table("rubric_topic_priors")
    op.drop_index("ix_source_score_snapshots_day_key", table_name="source_score_snapshots")
    op.drop_index("ix_source_score_snapshots_data_source_id", table_name="source_score_snapshots")
    op.drop_index("ix_source_score_snapshots_workspace_code", table_name="source_score_snapshots")
    op.drop_table("source_score_snapshots")
    op.drop_index(
        "ix_recommendation_rubric_compiles_fingerprint",
        table_name="recommendation_rubric_compiles",
    )
    op.drop_index(
        "ix_recommendation_rubric_compiles_workspace_code",
        table_name="recommendation_rubric_compiles",
    )
    op.drop_table("recommendation_rubric_compiles")
    op.drop_column("recommendation_items", "rubric_version")
    op.drop_column("recommendation_items", "rubric_hits_json")
    op.drop_column("recommendation_items", "llm_rerank_reason")
    op.drop_column("recommendation_items", "llm_rerank_status")
    op.drop_column("recommendation_items", "llm_relevance_score")
    op.drop_column("recommendation_items", "coarse_score")
    op.drop_index("ix_generation_daily_usage_purpose", table_name="generation_daily_usage")
    with op.batch_alter_table("generation_daily_usage") as batch:
        batch.drop_constraint("uq_generation_daily_usage_ws_day_purpose", type_="unique")
        batch.create_unique_constraint(
            "uq_generation_daily_usage_ws_day",
            ["workspace_code", "day_key"],
        )
        batch.drop_column("purpose")
