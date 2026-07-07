"""发布日报时自动抽取实体大事记候选（Archive / Knowledge 持续沉淀，设计见
docs/backend/archive-knowledge-design.md §6）。

规则：
- 只扫描已发布日报中 adoption_status = 2（已采信）的条目。
- 标题/摘要命中 tracked_entities 的名称或别名（大小写不敏感的包含匹配）即产生候选。
- 候选写入 entity_milestones，curation_status = candidate，selected_for_timeline = False，
  等待 workspace admin 在 /entity-milestones 页确认或驳回。
- 幂等：同一 (tracked_entity, news_item) 只产生一条候选；人工已从报告条目登记过
  同一实体+素材的事件时也不再重复生成。
- 只写 tracked_entities/entity_milestones 归档层：不触碰 raw/news/report 主链，
  不进入推荐或公司 SQL。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.content import GeneratedNews, NewsItem
from app.models.legacy import EntityMilestone, TrackedEntity
from app.models.reports import DailyReport, DailyReportItem

ADOPTED_STATUS = 2
CANDIDATE_LEGACY_TABLE = "published_report_candidate_milestones"
CANDIDATE_EVENT_TYPE = "report_mention"


def candidate_legacy_id(tracked_entity_id: str, news_item_id: str) -> str:
    """entity+news 幂等键（entity_milestones legacy 唯一约束的 legacy_id）。"""

    return f"{tracked_entity_id}:{news_item_id}"


def entity_matched_terms(entity: TrackedEntity, text: str) -> list[str]:
    """返回实体名称/别名中命中 text 的词（大小写不敏感包含匹配）。"""

    haystack = (text or "").lower()
    if not haystack:
        return []
    terms: list[str] = []
    candidates = [entity.name, *[alias for alias in (entity.aliases_json or []) if isinstance(alias, str)]]
    for term in candidates:
        cleaned = (term or "").strip()
        if cleaned and cleaned.lower() in haystack and cleaned not in terms:
            terms.append(cleaned)
    return terms


def _existing_entity_news_pairs(session: Session, workspace_code: str) -> set[tuple[str, str]]:
    """已存在的 (tracked_entity_id, news_item_id) 组合，用于幂等去重。

    覆盖两条来路：本模块自动抽取的候选（legacy_id 即幂等键），以及
    人工从日报/周报条目登记的事件（news_item_id 记录在 metadata current_refs）。
    """

    pairs: set[tuple[str, str]] = set()
    milestones = session.scalars(
        select(EntityMilestone).where(
            EntityMilestone.workspace_code == workspace_code,
            EntityMilestone.legacy_system == "current",
        ),
    ).all()
    for milestone in milestones:
        refs = (milestone.metadata_json or {}).get("current_refs")
        news_item_id = refs.get("news_item_id") if isinstance(refs, dict) else None
        if isinstance(news_item_id, str) and news_item_id:
            pairs.add((milestone.tracked_entity_id, news_item_id))
    return pairs


def _generated_news_board(generated_news: GeneratedNews) -> str:
    insight_json = generated_news.insight_json or {}
    board = insight_json.get("board") if isinstance(insight_json, dict) else None
    return str(board or generated_news.category or "")


def _load_adopted_items(session: Session, report: DailyReport) -> list[DailyReportItem]:
    return list(
        session.scalars(
            select(DailyReportItem)
            .options(
                selectinload(DailyReportItem.generated_news)
                .selectinload(GeneratedNews.news_item)
                .selectinload(NewsItem.raw_item),
            )
            .where(
                DailyReportItem.daily_report_id == report.id,
                DailyReportItem.adoption_status == ADOPTED_STATUS,
            )
            .order_by(DailyReportItem.sort_order, DailyReportItem.created_at),
        ).all(),
    )


def extract_candidate_milestones_for_daily_report(
    session: Session,
    report: DailyReport,
) -> list[EntityMilestone]:
    """扫描已采信条目并为命中的 tracked_entities 生成 candidate 里程碑。

    只 flush 不 commit，由调用方（发布事务）统一提交。返回本次新建的候选列表。
    """

    entities = session.scalars(
        select(TrackedEntity).where(TrackedEntity.workspace_code == report.workspace_code),
    ).all()
    if not entities:
        return []

    existing_pairs = _existing_entity_news_pairs(session, report.workspace_code)
    created: list[EntityMilestone] = []

    for item in _load_adopted_items(session, report):
        generated_news = item.generated_news
        news_item = generated_news.news_item if generated_news else None
        if generated_news is None or news_item is None:
            continue
        title = (item.editor_title or generated_news.title or "").strip()
        summary = (item.editor_summary or generated_news.summary or "").strip()
        text = f"{title}\n{summary}"
        for entity in entities:
            matched_terms = entity_matched_terms(entity, text)
            if not matched_terms:
                continue
            pair = (entity.id, news_item.id)
            if pair in existing_pairs:
                continue
            existing_pairs.add(pair)
            created.append(
                _build_candidate_milestone(
                    report=report,
                    item=item,
                    entity=entity,
                    generated_news=generated_news,
                    news_item=news_item,
                    title=title,
                    summary=summary,
                    matched_terms=matched_terms,
                ),
            )

    if created:
        session.add_all(created)
        session.flush()
    return created


def _build_candidate_milestone(
    *,
    report: DailyReport,
    item: DailyReportItem,
    entity: TrackedEntity,
    generated_news: GeneratedNews,
    news_item: NewsItem,
    title: str,
    summary: str,
    matched_terms: list[str],
) -> EntityMilestone:
    raw_item = news_item.raw_item
    brief = summary or title
    event_time = (
        news_item.published_at
        or (raw_item.published_at if raw_item else None)
        or report.published_at
        or report.created_at
    )
    source_url = generated_news.source_url or news_item.source_url or (raw_item.source_url if raw_item else None)
    source_name = news_item.source_name or (raw_item.source_name if raw_item else "")
    return EntityMilestone(
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        legacy_system="current",
        legacy_table=CANDIDATE_LEGACY_TABLE,
        legacy_id=candidate_legacy_id(entity.id, news_item.id),
        tracked_entity_id=entity.id,
        legacy_entity_id=entity.legacy_id,
        raw_item_id=news_item.raw_item_id,
        event_time=event_time,
        event_type=CANDIDATE_EVENT_TYPE,
        title=title or "未命名情报",
        event_content=brief,
        impact="",
        event_brief=brief,
        impact_brief="",
        timeline_brief=brief,
        source_url=source_url,
        source_name=source_name,
        board=_generated_news_board(generated_news),
        selected_for_timeline=False,
        confidence_score=0.6,
        importance_score=75.0 if item.is_headline else 55.0,
        importance_level="high" if item.is_headline else "medium",
        event_dedupe_key=candidate_legacy_id(entity.id, news_item.id),
        metadata_json={
            "curation_status": "candidate",
            "created_from": "daily_report_publish_auto_extract",
            "matched_terms": matched_terms,
            "current_refs": {
                "source_report_type": "daily",
                "source_report_id": report.id,
                "source_report_item_id": item.id,
                "daily_report_item_id": item.id,
                "day_key": report.day_key,
                "generated_news_id": generated_news.id,
                "news_item_id": news_item.id,
                "raw_item_id": news_item.raw_item_id,
                "data_source_id": news_item.data_source_id,
            },
        },
    )
