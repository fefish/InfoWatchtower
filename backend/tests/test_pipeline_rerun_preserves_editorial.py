from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.models.content import GeneratedNews
from app.models.feedback import Comment, Rating, Reaction
from app.models.identity import User
from app.models.reports import DailyReportItem
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.service import (
    PublishedDailyReportError,
    RecommendationRunRequest,
    run_daily_recommendation,
)
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace
from tests.test_recommendations import make_session

FIXED_SCORING_TIME = datetime(2026, 5, 5, 10, tzinfo=UTC)

TECHNICAL_URL = "https://example.com/inference-benchmark"
PLAIN_URL = "https://example.com/training-note"


def _run_request(limit: int = 15) -> RecommendationRunRequest:
    return RecommendationRunRequest(
        workspace_code="planning_intel",
        day_key="2026-05-05",
        limit=limit,
        source_daily_limit=2,
        create_daily_draft=True,
    )


def _seed_two_item_draft(session):
    """构造一技术强信号 + 一常规弱信号的候选池，跑出含两条条目的 draft 日报。"""
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Example Official RSS")
    add_raw_item(
        session,
        source,
        "rss:technical",
        "Inference serving architecture improves agent latency benchmark",
        TECHNICAL_URL,
        (
            "The update explains model serving architecture, inference latency, "
            "KV cache, throughput, benchmark results, and deployment tradeoffs."
        ),
    )
    add_raw_item(
        session,
        source,
        "rss:plain",
        "Training technology update",
        PLAIN_URL,
        "Training technology update body.",
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    result = run_daily_recommendation(session, _run_request(), now=FIXED_SCORING_TIME)
    assert result.daily_report is not None
    assert len(result.daily_report.items) == 2
    return result.daily_report


def _item_by_source_url(session, report_id: str, source_url: str) -> DailyReportItem:
    for item in session.scalars(
        select(DailyReportItem).where(DailyReportItem.daily_report_id == report_id),
    ).all():
        if item.generated_news.news_item.source_url == source_url:
            return item
    raise AssertionError(f"Daily report item not found for {source_url}")


def test_draft_rerun_preserves_adoption_and_editor_overrides():
    session = make_session()
    report = _seed_two_item_draft(session)
    rejected = _item_by_source_url(session, report.id, PLAIN_URL)
    rejected.adoption_status = 0
    rejected.editor_notes = "候选池批量剔除。"
    headline = _item_by_source_url(session, report.id, TECHNICAL_URL)
    headline.is_headline = True
    headline.editor_title = "编辑后的标题"
    headline.editor_content_json = {"valueAndImpact": "编辑后的价值判断"}
    headline_generated_news_id = headline.generated_news_id
    session.commit()

    run_daily_recommendation(session, _run_request(), now=FIXED_SCORING_TIME)
    session.commit()

    assert session.scalar(select(func.count(DailyReportItem.id))) == 2
    rejected_after = session.get(DailyReportItem, rejected.id)
    assert rejected_after is not None
    assert rejected_after.adoption_status == 0
    assert rejected_after.editor_notes == "候选池批量剔除。"
    headline_after = session.get(DailyReportItem, headline.id)
    assert headline_after is not None
    assert headline_after.is_headline is True
    assert headline_after.editor_title == "编辑后的标题"
    assert headline_after.editor_content_json == {"valueAndImpact": "编辑后的价值判断"}
    # 已编辑条目保持原成稿指针，编辑覆盖不会被新一轮生成顶掉基底。
    assert headline_after.generated_news_id == headline_generated_news_id


def test_draft_rerun_refreshes_unedited_items_in_place():
    session = make_session()
    report = _seed_two_item_draft(session)
    before = {
        item.id: item.generated_news_id
        for item in session.scalars(
            select(DailyReportItem).where(DailyReportItem.daily_report_id == report.id),
        ).all()
    }
    session.commit()

    run_daily_recommendation(session, _run_request(), now=FIXED_SCORING_TIME)
    session.commit()

    items_after = session.scalars(
        select(DailyReportItem).where(DailyReportItem.daily_report_id == report.id),
    ).all()
    # 未编辑条目按去重键原位复用：行不重建，只把成稿指针刷新到本次生成结果。
    assert {item.id for item in items_after} == set(before)
    assert all(item.adoption_status == 2 for item in items_after)
    assert all(item.generated_news_id != before[item.id] for item in items_after)
    assert session.scalar(select(func.count(GeneratedNews.id))) == 4


def test_draft_rerun_removes_unedited_unreferenced_item_out_of_candidates():
    session = make_session()
    report = _seed_two_item_draft(session)
    session.commit()

    run_daily_recommendation(session, _run_request(limit=1), now=FIXED_SCORING_TIME)
    session.commit()

    items = session.scalars(
        select(DailyReportItem).where(DailyReportItem.daily_report_id == report.id),
    ).all()
    assert len(items) == 1
    assert items[0].generated_news.news_item.source_url == TECHNICAL_URL


def test_draft_rerun_keeps_edited_item_even_out_of_candidates():
    session = make_session()
    report = _seed_two_item_draft(session)
    plain = _item_by_source_url(session, report.id, PLAIN_URL)
    plain.editor_title = "编辑后保留的条目"
    session.commit()

    run_daily_recommendation(session, _run_request(limit=1), now=FIXED_SCORING_TIME)
    session.commit()

    items = session.scalars(
        select(DailyReportItem).where(DailyReportItem.daily_report_id == report.id),
    ).all()
    assert len(items) == 2
    plain_after = session.get(DailyReportItem, plain.id)
    assert plain_after is not None
    assert plain_after.editor_title == "编辑后保留的条目"


def test_draft_rerun_keeps_feedback_referenced_item_without_dangling_feedback():
    session = make_session()
    report = _seed_two_item_draft(session)
    plain = _item_by_source_url(session, report.id, PLAIN_URL)
    user = User(username="editor", display_name="编辑")
    session.add(user)
    session.flush()
    session.add(Reaction(user=user, daily_report_item=plain, reaction_type="like"))
    session.add(Rating(user=user, daily_report_item=plain, score=5))
    session.add(Comment(user=user, daily_report_item=plain, body="值得进入周报"))
    session.commit()

    run_daily_recommendation(session, _run_request(limit=1), now=FIXED_SCORING_TIME)
    session.commit()

    assert session.scalar(select(func.count(DailyReportItem.id))) == 2
    plain_after = session.get(DailyReportItem, plain.id)
    assert plain_after is not None
    reaction = session.scalar(select(Reaction))
    rating = session.scalar(select(Rating))
    comment = session.scalar(select(Comment))
    assert reaction is not None and reaction.daily_report_item_id == plain.id
    assert rating is not None and rating.daily_report_item_id == plain.id
    assert comment is not None and comment.daily_report_item_id == plain.id


def test_published_daily_report_rerun_is_still_rejected():
    session = make_session()
    report = _seed_two_item_draft(session)
    report.status = "published"
    session.commit()

    with pytest.raises(PublishedDailyReportError):
        run_daily_recommendation(session, _run_request(), now=FIXED_SCORING_TIME)
