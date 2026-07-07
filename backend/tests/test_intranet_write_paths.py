"""目标态条款 4 的核心链路看护：intranet 门户身份头 + CSRF 全开下的本地写闭环。

全真组合：DEPLOY_MODE=intranet + AUTH_MODE=intranet_header + AUTH_CSRF_ENABLED=true。
链路：门户注入身份头首访自动建号（同时签发 session + csrf cookie）→ 读日报 →
写评论/点赞/评分（带 X-CSRF-Token 成功、缺 token 403）→ 写入全部留在本地库、
sync feed 面无外流通道（契约 sync_strategy：本地协作对象不同步；intranet 无
publisher 能力）。
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.core.security import CSRF_COOKIE_NAME
from app.main import create_app
from app.models.common import utc_now
from app.models.content import DataSource, GeneratedNews, NewsItem, RawItem
from app.models.feedback import Comment, Rating, Reaction
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.models.sync import SyncOutbox
from app.sync.records import SYNC_FEED_OBJECT_TYPES

INTRANET_ENV_KEYS = (
    "DATABASE_URL",
    "DEPLOY_MODE",
    "INSTANCE_ID",
    "AUTH_MODE",
    "AUTH_CSRF_ENABLED",
    "AUTH_SESSION_SECRET",
    "AUTH_AUTO_PROVISION",
    "AUTH_DEFAULT_ROLE",
    "AUTH_DEFAULT_WORKSPACE_CODES",
    "AUTH_DEPARTMENT_WORKSPACE_MAP",
    "SYNC_REMOTE_BASE_URL",
    "SYNC_REMOTE_TOKEN",
    "AUTH_BOOTSTRAP_ADMIN_USERNAME",
    "AUTH_BOOTSTRAP_ADMIN_PASSWORD",
)

# 门户网关注入的身份头（config 默认头名；中文值按网关约定 URL 编码）
EMPLOYEE_HEADERS = {
    "X-Employee-No": "E100",
    "X-Employee-Name": "%E5%86%85%E7%BD%91%E8%AF%84%E8%AE%BA%E4%BA%BA",
    "X-Department": "%E8%A7%84%E5%88%92%E9%83%A8",
    "X-Email": "e100@example.com",
}


def make_intranet_client(monkeypatch, tmp_path):
    database_path = tmp_path / "intranet_write_paths.sqlite"
    env = {
        "DATABASE_URL": f"sqlite:///{database_path}",
        "DEPLOY_MODE": "intranet",
        "AUTH_MODE": "intranet_header",
        "AUTH_CSRF_ENABLED": "true",
        "AUTH_SESSION_SECRET": "test-session-secret",
        "AUTH_AUTO_PROVISION": "true",
        "AUTH_DEFAULT_ROLE": "viewer",
        "AUTH_DEFAULT_WORKSPACE_CODES": "planning_intel:viewer",
        "SYNC_REMOTE_BASE_URL": "https://extranet.example.com",
        "SYNC_REMOTE_TOKEN": "pull-token",
    }
    for key in INTRANET_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app()), engine


def seed_published_daily_report(engine) -> str:
    """按 intranet 消费视角造一条已发布日报（源→raw→news→成稿→采信条目），返回条目 id。"""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            origin_instance_id="extranet",
            workspace_code="planning_intel",
            source_type="rss",
            name="Intranet Feed Source",
            url="https://example.com/intranet-feed.xml",
        )
        raw_item = RawItem(
            origin_instance_id="extranet",
            workspace_code="planning_intel",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="intranet-write-001",
            source_title="Intranet Write Raw",
            source_url="https://example.com/intranet/raw",
            raw_content="raw evidence",
            fetched_at=utc_now(),
        )
        news_item = NewsItem(
            origin_instance_id="extranet",
            workspace_code="planning_intel",
            raw_item=raw_item,
            data_source=source,
            source_type="rss",
            source_name=source.name,
            source_url="https://example.com/intranet/news",
            canonical_url="https://example.com/intranet/news",
            source_title="Intranet Write News",
            normalized_title="Intranet Write News",
            dedupe_key="intranet-write-news",
        )
        generated_news = GeneratedNews(
            origin_instance_id="extranet",
            workspace_code="planning_intel",
            news_item=news_item,
            category="基础竞争力",
            title="Intranet Write Generated",
            generation_status="ready",
            generated_by="llm_v1",
        )
        report = DailyReport(
            origin_instance_id="extranet",
            workspace_code="planning_intel",
            day_key="2026-07-06",
            title="Intranet Write Daily",
            status="published",
        )
        report_item = DailyReportItem(
            origin_instance_id="extranet",
            workspace_code="planning_intel",
            daily_report=report,
            generated_news=generated_news,
            adoption_status=2,
        )
        session.add_all([source, raw_item, news_item, generated_news, report, report_item])
        session.commit()
        return report_item.id


def test_intranet_header_identity_writes_with_csrf_stay_local(monkeypatch, tmp_path):
    client, engine = make_intranet_client(monkeypatch, tmp_path)
    report_item_id = seed_published_daily_report(engine)

    # 1) 门户身份头首访自动建号，并签发 session + csrf cookie
    me = client.get("/api/auth/me", headers=EMPLOYEE_HEADERS)
    assert me.status_code == 200
    me_payload = me.json()["user"]
    assert me_payload["external_provider"] == "intranet_header"
    assert me_payload["employee_no"] == "E100"
    assert me_payload["display_name"] == "内网评论人"
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token

    # 2) 读日报（默认工作台 viewer 成员即可读）
    reports = client.get(
        "/api/daily-reports",
        params={"workspace_code": "planning_intel"},
        headers=EMPLOYEE_HEADERS,
    )
    assert reports.status_code == 200
    assert [report["day_key"] for report in reports.json()] == ["2026-07-06"]

    # 3) CSRF 强校验开启：缺 X-CSRF-Token 的写操作 403
    rejected = client.post(
        f"/api/daily-report-items/{report_item_id}/comments",
        json={"body": "缺 token 的评论"},
        headers=EMPLOYEE_HEADERS,
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == {"code": "csrf_failed"}

    # 4) 带 token 的评论/点赞/评分全部成功，且归属 header 身份用户
    write_headers = {**EMPLOYEE_HEADERS, "X-CSRF-Token": csrf_token}
    comment = client.post(
        f"/api/daily-report-items/{report_item_id}/comments",
        json={"body": "内网本地评论"},
        headers=write_headers,
    )
    assert comment.status_code == 200
    reaction = client.post(
        f"/api/daily-report-items/{report_item_id}/reactions",
        json={"reaction_type": "like", "active": True},
        headers=write_headers,
    )
    assert reaction.status_code == 200
    assert reaction.json()["active"] is True
    rating = client.post(
        f"/api/daily-report-items/{report_item_id}/ratings",
        json={"dimension": "overall", "score": 5},
        headers=write_headers,
    )
    assert rating.status_code == 200
    assert rating.json()["score"] == 5

    Session = sessionmaker(bind=engine)
    with Session() as session:
        header_user = session.scalar(select(User).where(User.external_id == "E100"))
        assert header_user is not None
        assert comment.json()["user_id"] == header_user.id

        # 5) 写入落在本地库并归属 header 用户
        comment_row = session.scalar(select(Comment))
        reaction_row = session.scalar(select(Reaction))
        rating_row = session.scalar(select(Rating))
        assert comment_row is not None and comment_row.user_id == header_user.id
        assert comment_row.body == "内网本地评论"
        assert reaction_row is not None and reaction_row.user_id == header_user.id
        assert rating_row is not None and rating_row.user_id == header_user.id

        # 6) 不外流：本地协作写入不产生任何待同步 outbox 记录
        assert (session.scalar(select(func.count()).select_from(SyncOutbox)) or 0) == 0

    # 7) 本地协作对象不在 feed 对象集合内（不变式：intranet 评论只进不出）
    for object_type in ("comments", "reactions", "ratings"):
        assert object_type not in SYNC_FEED_OBJECT_TYPES

    # 8) intranet 没有 publisher 能力：feed 发布面整体关闭，写入无外流通道
    for feed_path in ("/api/sync/feed/manifest", "/api/sync/feed"):
        feed = client.get(
            feed_path,
            params={"object_type": "data_sources"},
            headers={"Authorization": "Bearer any-token"},
        )
        assert feed.status_code == 403, feed_path
        assert feed.json()["detail"] == {
            "code": "capability_disabled",
            "capability": "sync_publisher",
        }, feed_path
