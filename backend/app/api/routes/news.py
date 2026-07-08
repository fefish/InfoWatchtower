from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user
from app.core.database import get_db_session
from app.models.content import (
    DataSource,
    DedupeGroup,
    DedupeGroupItem,
    GeneratedNews,
    NewsItem,
    RawItem,
    RecommendationItem,
    RecommendationRun,
)
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.normalization.news import (
    NewsNormalizationRequest,
    WorkspaceNotFoundError,
    normalize_workspace_raw_items,
)
from app.schemas.news import (
    DedupeGroupDailyReportRead,
    DedupeGroupItemRead,
    DedupeGroupLineageNodeRead,
    DedupeGroupLineageRead,
    DedupeGroupRead,
    DedupeGroupRecommendationRead,
    NewsItemRead,
    NewsNormalizeCreate,
    NewsNormalizeRead,
)

router = APIRouter(prefix="/api", tags=["news"])
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.post("/news-items/normalize", response_model=NewsNormalizeRead)
def normalize_news_items(
    payload: NewsNormalizeCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> NewsNormalizeRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        result = normalize_workspace_raw_items(
            session,
            NewsNormalizationRequest(
                workspace_code=payload.workspace_code,
                source_types=payload.source_types,
                limit=payload.limit,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    session.commit()
    return NewsNormalizeRead(**result.__dict__)


@router.get("/news-items", response_model=list[NewsItemRead])
def list_news_items(
    workspace_code: str = Query(...),
    active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[NewsItemRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    statement = (
        select(NewsItem)
        .where(NewsItem.workspace_code == workspace_code)
        .order_by(NewsItem.published_at.desc(), NewsItem.created_at.desc(), NewsItem.id)
        .limit(limit)
    )
    if active is not None:
        statement = statement.where(NewsItem.active.is_(active))
    return [_news_to_read(item) for item in session.scalars(statement).all()]


@router.get("/dedupe-groups", response_model=list[DedupeGroupRead])
def list_dedupe_groups(
    workspace_code: str = Query(...),
    q: str | None = Query(default=None, max_length=128),
    recommendation_status: str = Query(default="all", pattern="^(all|recommended|selected|unrecommended)$"),
    daily_status: str = Query(default="all", pattern="^(all|adopted|candidate|rejected|not_in_report)$"),
    admission_level: str | None = Query(default=None, max_length=16),
    source_type: str | None = Query(default=None, max_length=64),
    # 候选池默认排序（recommendation_ranking.json ordering_consistency candidate_pool）：
    # 默认 score_desc（final_score 降序），其他排序仅显式选择时生效。
    sort: str = Query(
        default="score_desc",
        pattern="^(updated_desc|score_desc|score_asc|published_desc|source_count_desc)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[DedupeGroupRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    groups = session.scalars(
        select(DedupeGroup)
        .options(
            selectinload(DedupeGroup.winner_news_item)
            .selectinload(NewsItem.raw_item)
            .selectinload(RawItem.data_source),
            selectinload(DedupeGroup.items).selectinload(DedupeGroupItem.news_item),
        )
        .where(DedupeGroup.workspace_code == workspace_code)
        .order_by(DedupeGroup.updated_at.desc(), DedupeGroup.id)
        .limit(max(limit * 5, 200)),
    ).all()
    records = [_dedupe_group_to_read(session, group) for group in groups]
    records = _filter_dedupe_group_reads(
        records,
        keyword=q or "",
        recommendation_status=recommendation_status,
        daily_status=daily_status,
        admission_level=admission_level or "",
        source_type=source_type or "",
    )
    records = _sort_dedupe_group_reads(records, sort)
    return records[:limit]


def _news_to_read(item: NewsItem) -> NewsItemRead:
    return NewsItemRead(
        id=item.id,
        workspace_code=item.workspace_code,
        domain_code=item.domain_code,
        raw_item_id=item.raw_item_id,
        data_source_id=item.data_source_id,
        source_type=item.source_type,
        source_name=item.source_name,
        source_url=item.source_url,
        canonical_url=item.canonical_url,
        source_title=item.source_title,
        normalized_title=item.normalized_title,
        summary=item.summary,
        author=item.author,
        published_at=item.published_at,
        focus_id=item.focus_id,
        dedupe_key=item.dedupe_key,
        active=item.active,
        duplicate_of_id=item.duplicate_of_id,
        normalization_status=item.normalization_status,
        normalization_notes=item.normalization_notes,
    )


def _dedupe_group_to_read(session: Session, group: DedupeGroup) -> DedupeGroupRead:
    winner = group.winner_news_item
    items = sorted(group.items, key=lambda item: (not item.is_winner, -item.rank_score, item.id))
    recommendation = _recommendation_trace(session, group.winner_news_item_id)
    daily_report = _daily_report_trace(session, group.winner_news_item_id)
    return DedupeGroupRead(
        id=group.id,
        workspace_code=group.workspace_code,
        domain_code=group.domain_code,
        dedupe_key=group.dedupe_key,
        winner_news_item_id=group.winner_news_item_id,
        winner_title=winner.source_title if winner else None,
        winner_published_at=winner.published_at if winner else None,
        winner_source_type=winner.source_type if winner else None,
        item_count=group.item_count,
        status=group.status,
        items=[
            DedupeGroupItemRead(
                id=item.id,
                news_item_id=item.news_item_id,
                is_winner=item.is_winner,
                duplicate_reason=item.duplicate_reason,
                rank_score=item.rank_score,
                title=item.news_item.source_title,
                source_type=item.news_item.source_type,
                source_name=item.news_item.source_name,
                source_url=item.news_item.source_url,
            )
            for item in items
        ],
        recommendation=recommendation,
        daily_report=daily_report,
        lineage=_lineage_trace(group, winner, recommendation, daily_report),
    )


def _filter_dedupe_group_reads(
    records: list[DedupeGroupRead],
    *,
    keyword: str,
    recommendation_status: str,
    daily_status: str,
    admission_level: str,
    source_type: str,
) -> list[DedupeGroupRead]:
    keyword = keyword.strip().lower()
    admission_level = admission_level.strip().upper()
    source_type = source_type.strip()
    filtered = records
    if keyword:
        filtered = [record for record in filtered if _dedupe_group_matches_keyword(record, keyword)]
    if recommendation_status == "recommended":
        filtered = [record for record in filtered if record.recommendation is not None]
    elif recommendation_status == "selected":
        filtered = [record for record in filtered if record.recommendation is not None and record.recommendation.selected]
    elif recommendation_status == "unrecommended":
        filtered = [record for record in filtered if record.recommendation is None]
    if daily_status == "adopted":
        filtered = [record for record in filtered if record.daily_report is not None and record.daily_report.adoption_status == 2]
    elif daily_status == "candidate":
        filtered = [record for record in filtered if record.daily_report is not None and record.daily_report.adoption_status == 1]
    elif daily_status == "rejected":
        filtered = [record for record in filtered if record.daily_report is not None and record.daily_report.adoption_status == 0]
    elif daily_status == "not_in_report":
        filtered = [record for record in filtered if record.daily_report is None]
    if admission_level:
        filtered = [
            record
            for record in filtered
            if record.recommendation is not None and record.recommendation.admission_level.upper() == admission_level
        ]
    if source_type:
        filtered = [
            record
            for record in filtered
            if record.winner_source_type == source_type or any(item.source_type == source_type for item in record.items)
        ]
    return filtered


def _dedupe_group_matches_keyword(record: DedupeGroupRead, keyword: str) -> bool:
    values = [
        record.winner_title,
        record.dedupe_key,
        record.status,
        record.winner_source_type,
        record.recommendation.day_key if record.recommendation else None,
        record.recommendation.recommendation_reason if record.recommendation else None,
        record.recommendation.admission_level if record.recommendation else None,
        record.daily_report.day_key if record.daily_report else None,
        record.daily_report.category if record.daily_report else None,
    ]
    for item in record.items:
        values.extend([item.title, item.source_type, item.source_name, item.duplicate_reason])
    return keyword in " ".join(str(value) for value in values if value).lower()


def _sort_dedupe_group_reads(records: list[DedupeGroupRead], sort: str) -> list[DedupeGroupRead]:
    if sort == "score_desc":
        # ordering_consistency：final_score 降序，并列按 news_item_id 升序（稳定）。
        return sorted(
            records,
            key=lambda record: (
                -_recommendation_score(record),
                record.winner_news_item_id or "",
            ),
        )
    if sort == "score_asc":
        return sorted(records, key=lambda record: _recommendation_score(record))
    if sort == "published_desc":
        return sorted(
            records,
            key=lambda record: record.winner_published_at.timestamp() if record.winner_published_at else 0,
            reverse=True,
        )
    if sort == "source_count_desc":
        return sorted(records, key=lambda record: record.item_count, reverse=True)
    return records


def _recommendation_score(record: DedupeGroupRead) -> float:
    return record.recommendation.final_score if record.recommendation else -1.0


def _recommendation_trace(
    session: Session,
    news_item_id: str | None,
) -> DedupeGroupRecommendationRead | None:
    if not news_item_id:
        return None
    item = session.scalar(
        select(RecommendationItem)
        .join(RecommendationRun)
        .options(selectinload(RecommendationItem.run))
        .where(RecommendationItem.news_item_id == news_item_id)
        .order_by(desc(RecommendationRun.created_at), RecommendationItem.rank)
        .limit(1),
    )
    if item is None:
        return None
    day_key = (item.run.params_json or {}).get("day_key")
    return DedupeGroupRecommendationRead(
        run_id=item.run_id,
        run_key=item.run.run_key,
        day_key=str(day_key) if day_key else None,
        recommendation_item_id=item.id,
        rank=item.rank,
        selected=item.selected,
        final_score=item.final_score,
        quality_score=item.quality_score,
        topic_score=item.topic_score,
        freshness_score=item.freshness_score,
        feedback_score=item.feedback_score,
        diversity_score=item.diversity_score,
        source_score=item.source_score,
        heat_score=item.heat_score,
        recommendation_reason=item.recommendation_reason,
        admission_level=item.admission_level,
        admission_score=item.admission_score,
        admission_pool=item.admission_pool,
        noise_types=_string_list(item.noise_types_json),
        reject_reasons=_string_list(item.reject_reasons_json),
        scorer_breakdown=dict(item.scorer_breakdown_json or {}),
        expert_routes=_string_list(item.expert_routes_json),
    )


def _daily_report_trace(
    session: Session,
    news_item_id: str | None,
) -> DedupeGroupDailyReportRead | None:
    if not news_item_id:
        return None
    item = session.scalar(
        select(DailyReportItem)
        .join(GeneratedNews, GeneratedNews.id == DailyReportItem.generated_news_id)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .options(
            selectinload(DailyReportItem.daily_report),
            selectinload(DailyReportItem.generated_news),
        )
        .where(GeneratedNews.news_item_id == news_item_id)
        .order_by(desc(DailyReport.day_key), desc(DailyReportItem.created_at))
        .limit(1),
    )
    if item is None:
        return None
    return DedupeGroupDailyReportRead(
        daily_report_id=item.daily_report_id,
        daily_report_item_id=item.id,
        day_key=item.daily_report.day_key,
        report_status=item.daily_report.status,
        adoption_status=item.adoption_status,
        generated_news_id=item.generated_news_id,
        generation_status=item.generated_news.generation_status,
        category=item.generated_news.category,
    )


def _lineage_trace(
    group: DedupeGroup,
    winner: NewsItem | None,
    recommendation: DedupeGroupRecommendationRead | None,
    daily_report: DedupeGroupDailyReportRead | None,
) -> DedupeGroupLineageRead:
    nodes: list[DedupeGroupLineageNodeRead] = []
    raw_item = winner.raw_item if winner else None
    source = raw_item.data_source if raw_item else None
    if source is not None:
        nodes.append(_source_lineage_node(source))
    if raw_item is not None:
        nodes.append(_raw_lineage_node(raw_item))
    if winner is not None:
        nodes.append(_news_lineage_node(winner))
    nodes.append(_dedupe_lineage_node(group))
    if recommendation is not None:
        nodes.append(_recommendation_lineage_node(recommendation))
    if daily_report is not None:
        nodes.append(_generated_news_lineage_node(daily_report))
        nodes.append(_daily_report_lineage_node(daily_report))
    return DedupeGroupLineageRead(nodes=nodes)


def _source_lineage_node(source: DataSource) -> DedupeGroupLineageNodeRead:
    return DedupeGroupLineageNodeRead(
        object_type="data_source",
        object_id=source.id,
        label=source.name,
        status="enabled" if source.enabled else "disabled",
        review_note="确认候选来自哪个共享数据源，以及该源当前是否可抓取。",
        target_path=f"/sources/{source.id}",
        occurred_at=source.last_success_at or source.last_fetch_at or source.updated_at,
        metadata={
            "source_type": source.source_type,
            "domain_code": source.domain_code,
            "source_url": source.url or "",
            "last_error": source.last_error or "",
        },
    )


def _raw_lineage_node(raw_item: RawItem) -> DedupeGroupLineageNodeRead:
    payload = raw_item.raw_payload_json or {}
    return DedupeGroupLineageNodeRead(
        object_type="raw_item",
        object_id=raw_item.id,
        label=raw_item.source_title or raw_item.entry_key,
        status="preserved",
        review_note="确认原始信号已经完整入库；这里只展示安全摘要，完整 payload 留在后端追溯层。",
        target_path=f"/news?raw_item_id={raw_item.id}",
        occurred_at=raw_item.published_at or raw_item.fetched_at,
        metadata={
            "entry_key": raw_item.entry_key,
            "source_type": raw_item.source_type,
            "source_url": raw_item.source_url or "",
            "fetched_at": raw_item.fetched_at.isoformat() if raw_item.fetched_at else "",
            "payload_keys": sorted(str(key) for key in payload.keys())[:20],
            "raw_content_length": len(raw_item.raw_content or ""),
        },
    )


def _news_lineage_node(news_item: NewsItem) -> DedupeGroupLineageNodeRead:
    status_value = "active_winner" if news_item.active else "duplicate"
    return DedupeGroupLineageNodeRead(
        object_type="news_item",
        object_id=news_item.id,
        label=news_item.normalized_title or news_item.source_title,
        status=status_value,
        review_note="确认 raw 已标准化成候选新闻，并可检查标题归一、canonical URL 和去重 key。",
        target_path=f"/news?news_item_id={news_item.id}",
        occurred_at=news_item.published_at or news_item.created_at,
        metadata={
            "normalization_status": news_item.normalization_status,
            "dedupe_key": news_item.dedupe_key,
            "canonical_url": news_item.canonical_url or "",
            "focus_id": news_item.focus_id,
        },
    )


def _dedupe_lineage_node(group: DedupeGroup) -> DedupeGroupLineageNodeRead:
    return DedupeGroupLineageNodeRead(
        object_type="dedupe_group",
        object_id=group.id,
        label=group.dedupe_key,
        status=group.status,
        review_note="确认同一事件的重复来源已合并，当前页面只把 winner 作为推荐候选。",
        target_path=f"/news?dedupe_group_id={group.id}",
        occurred_at=group.updated_at,
        metadata={
            "item_count": group.item_count,
            "winner_news_item_id": group.winner_news_item_id or "",
        },
    )


def _recommendation_lineage_node(recommendation: DedupeGroupRecommendationRead) -> DedupeGroupLineageNodeRead:
    return DedupeGroupLineageNodeRead(
        object_type="recommendation_item",
        object_id=recommendation.recommendation_item_id,
        label=recommendation.run_key,
        status="selected" if recommendation.selected else "not_selected",
        review_note="确认候选是否进入推荐 run，以及准入层级、分数和日报池判定。",
        target_path=f"/recommendations?run_id={recommendation.run_id}&item_id={recommendation.recommendation_item_id}",
        occurred_at=None,
        metadata={
            "run_id": recommendation.run_id,
            "day_key": recommendation.day_key or "",
            "rank": recommendation.rank,
            "admission_level": recommendation.admission_level,
            "admission_pool": recommendation.admission_pool,
            "final_score": recommendation.final_score,
        },
    )


def _generated_news_lineage_node(daily_report: DedupeGroupDailyReportRead) -> DedupeGroupLineageNodeRead:
    return DedupeGroupLineageNodeRead(
        object_type="generated_news",
        object_id=daily_report.generated_news_id,
        label=daily_report.category,
        status=daily_report.generation_status,
        review_note="确认推荐候选已经生成成品新闻草稿，并查看生成状态和分类。",
        target_path=f"/daily-reports?item_id={daily_report.daily_report_item_id}",
        occurred_at=None,
        metadata={
            "category": daily_report.category,
            "daily_report_item_id": daily_report.daily_report_item_id,
        },
    )


def _daily_report_lineage_node(daily_report: DedupeGroupDailyReportRead) -> DedupeGroupLineageNodeRead:
    return DedupeGroupLineageNodeRead(
        object_type="daily_report_item",
        object_id=daily_report.daily_report_item_id,
        label=daily_report.day_key,
        status=f"adoption_status_{daily_report.adoption_status}",
        review_note="确认候选在日报采信层的最终状态；采信、候选或剔除都只写日报条目。",
        target_path=f"/daily-reports?item_id={daily_report.daily_report_item_id}",
        occurred_at=None,
        metadata={
            "daily_report_id": daily_report.daily_report_id,
            "day_key": daily_report.day_key,
            "report_status": daily_report.report_status,
            "adoption_status": daily_report.adoption_status,
        },
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
