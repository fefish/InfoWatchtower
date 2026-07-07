"""实体大事记：发布日报自动抽取候选里程碑 + 实体/时间线 API 权限测试。"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.archive.milestones import (
    CANDIDATE_LEGACY_TABLE,
    extract_candidate_milestones_for_daily_report,
)
from app.main import create_app
from app.models import (
    DailyReport,
    DailyReportItem,
    DataSource,
    EntityMilestone,
    GeneratedNews,
    NewsItem,
    RawItem,
    TrackedEntity,
)
from tests.test_auth import make_client
from tests.test_operations_api import _create_local_user

WS = "planning_intel"


def _seed_chain(session, *, key: str, title: str, summary: str, day_key: str, adoption_status: int = 2,
                is_headline: bool = False, report: DailyReport | None = None):
    source = DataSource(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        source_type="rss",
        name=f"{key} 源",
        url=f"https://example.com/{key}.xml",
    )
    raw = RawItem(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        data_source=source,
        source_type="rss",
        source_name=source.name,
        entry_key=key,
        source_title=title,
        source_url=f"https://example.com/{key}",
        raw_content="raw payload",
        fetched_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        published_at=datetime(2026, 7, 5, 9, tzinfo=timezone.utc),
        raw_payload_json={"title": title},
    )
    news = NewsItem(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        raw_item=raw,
        data_source=source,
        source_type="rss",
        source_name=source.name,
        source_url=raw.source_url,
        canonical_url=raw.source_url,
        source_title=title,
        normalized_title=title,
        summary=summary,
        content="正文",
        published_at=datetime(2026, 7, 5, 10, tzinfo=timezone.utc),
        dedupe_key=key,
    )
    generated = GeneratedNews(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        news_item=news,
        category="智能体",
        title=title,
        summary=summary,
        source_url=raw.source_url,
        generation_status="ready",
        generated_by="minimax",
        insight_json={"board": "AI 应用"},
    )
    if report is None:
        report = DailyReport(
            workspace_code=WS,
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            day_key=day_key,
            title=f"{day_key} 日报",
            status="draft",
        )
    item = DailyReportItem(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="workspace",
        sync_policy="public_to_intranet",
        daily_report=report,
        generated_news=generated,
        adoption_status=adoption_status,
        is_headline=is_headline,
        sort_order=1,
    )
    session.add_all([source, raw, news, generated, report, item])
    return report, item, news


def _seed_entity(session, *, name: str, aliases: list[str] | None = None, legacy_system: str = "current"):
    entity = TrackedEntity(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="workspace",
        sync_policy="outbox",
        legacy_system=legacy_system,
        legacy_table="tracked_entities",
        legacy_id=f"seed:{name.lower()}",
        name=name,
        entity_type="company",
        rank="A",
        aliases_json=aliases or [],
        influence_score=80,
        notes="",
        metadata_json={},
    )
    session.add(entity)
    return entity


def test_extraction_matches_name_and_alias_and_is_idempotent(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        report, _, news = _seed_chain(
            session,
            key="extract-001",
            title="OpenAI 发布企业 Agent 平台",
            summary="OpenAI 面向企业推出 Agent 平台。",
            day_key="2026-07-05",
        )
        _seed_chain(
            session,
            key="extract-002",
            title="模型厂商动态汇总",
            summary="Anthropic 的 Fable 系列出现新的推理能力。",
            day_key="2026-07-05",
            report=report,
        )
        # 未采信条目不参与抽取
        _seed_chain(
            session,
            key="extract-003",
            title="OpenAI 相关但被剔除的条目",
            summary="不应产生候选。",
            day_key="2026-07-05",
            adoption_status=0,
            report=report,
        )
        openai = _seed_entity(session, name="OpenAI")
        anthropic = _seed_entity(session, name="Anthropic 公司", aliases=["Anthropic", "Fable"])
        _seed_entity(session, name="DeepMind")  # 未命中
        session.commit()

        created = extract_candidate_milestones_for_daily_report(session, report)
        session.commit()
        assert {m.tracked_entity_id for m in created} == {openai.id, anthropic.id}
        assert all(m.legacy_table == CANDIDATE_LEGACY_TABLE for m in created)
        assert all((m.metadata_json or {}).get("curation_status") == "candidate" for m in created)
        assert all(m.selected_for_timeline is False for m in created)

        by_entity = {m.tracked_entity_id: m for m in created}
        openai_candidate = by_entity[openai.id]
        assert openai_candidate.metadata_json["current_refs"]["news_item_id"] == news.id
        assert openai_candidate.metadata_json["current_refs"]["source_report_id"] == report.id
        assert openai_candidate.raw_item_id == news.raw_item_id
        assert "OpenAI" in openai_candidate.metadata_json["matched_terms"]
        # 别名命中（Fable 出现在摘要里）
        assert "Fable" in by_entity[anthropic.id].metadata_json["matched_terms"]

        # 幂等：重复执行不产生新候选
        again = extract_candidate_milestones_for_daily_report(session, report)
        session.commit()
        assert again == []
        count = session.query(EntityMilestone).filter(
            EntityMilestone.legacy_table == CANDIDATE_LEGACY_TABLE,
        ).count()
        assert count == 2


def test_publish_daily_report_triggers_candidate_extraction(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        report, _, _ = _seed_chain(
            session,
            key="publish-001",
            title="OpenAI 发布企业 Agent 平台",
            summary="企业 Agent 平台上线。",
            day_key="2026-07-06",
        )
        entity = _seed_entity(session, name="OpenAI")
        session.commit()
        report_id = report.id
        entity_id = entity.id

    published = client.post(f"/api/daily-reports/{report_id}/publish")
    assert published.status_code == 200

    with Session() as session:
        candidates = session.scalars(
            select(EntityMilestone).where(EntityMilestone.legacy_table == CANDIDATE_LEGACY_TABLE),
        ).all()
        assert len(candidates) == 1
        assert candidates[0].tracked_entity_id == entity_id

    # 重复发布保持幂等
    assert client.post(f"/api/daily-reports/{report_id}/publish").status_code == 200
    with Session() as session:
        count = session.query(EntityMilestone).filter(
            EntityMilestone.legacy_table == CANDIDATE_LEGACY_TABLE,
        ).count()
        assert count == 1

    timeline = client.get(f"/api/tracked-entities/{entity_id}/timeline")
    assert timeline.status_code == 200
    body = timeline.json()
    assert body["entity"]["name"] == "OpenAI"
    assert body["candidate_count"] == 1
    assert body["groups"][0]["month"] == "2026-07"
    assert body["groups"][0]["milestones"][0]["curation_status"] == "candidate"

    # 候选确认走既有 PATCH
    milestone_id = body["groups"][0]["milestones"][0]["id"]
    confirmed = client.patch(
        f"/api/entity-milestones/{milestone_id}",
        json={"curation_status": "confirmed", "selected_for_timeline": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["curation_status"] == "confirmed"
    assert confirmed.json()["selected_for_timeline"] is True


def test_tracked_entity_crud_and_manual_milestone_with_viewer_gate(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    viewer = _create_local_user(engine, "timeline-viewer", "password-123", workspace_role="viewer")

    created = client.post(
        "/api/tracked-entities",
        json={
            "workspace_code": WS,
            "name": "Moonshot",
            "entity_type": "company",
            "aliases": ["月之暗面", " Kimi ", "Kimi"],
        },
    )
    assert created.status_code == 200
    entity_payload = created.json()
    assert entity_payload["legacy_system"] == "current"
    assert entity_payload["aliases_json"] == ["月之暗面", "Kimi"]
    entity_id = entity_payload["id"]

    # 同名冲突
    assert client.post(
        "/api/tracked-entities",
        json={"workspace_code": WS, "name": "moonshot"},
    ).status_code == 409

    patched = client.patch(
        f"/api/tracked-entities/{entity_id}",
        json={"aliases": ["月之暗面", "Kimi", "Kimi 智能助手"], "notes": "重点跟踪"},
    )
    assert patched.status_code == 200
    assert "Kimi 智能助手" in patched.json()["aliases_json"]

    manual = client.post(
        "/api/entity-milestones",
        json={
            "tracked_entity_id": entity_id,
            "event_title": "Kimi 发布长上下文旗舰模型",
            "event_type": "release",
            "event_time": "2026-07-01T08:00:00Z",
            "event_brief": "人工补录的里程碑。",
            "importance_level": "high",
        },
    )
    assert manual.status_code == 200
    manual_payload = manual.json()
    assert manual_payload["curation_status"] == "confirmed"
    assert manual_payload["selected_for_timeline"] is True
    assert manual_payload["tracked_entity_id"] == entity_id

    # 有里程碑的实体不可删除
    assert client.delete(f"/api/tracked-entities/{entity_id}").status_code == 400

    # viewer 只读：能看时间线，不能增删改
    viewer_client = TestClient(create_app())
    assert viewer_client.post(
        "/api/auth/login",
        json={"username": viewer.username, "password": "password-123"},
    ).status_code == 200
    timeline = viewer_client.get(f"/api/tracked-entities/{entity_id}/timeline")
    assert timeline.status_code == 200
    assert timeline.json()["total_milestones"] == 1
    assert viewer_client.post(
        "/api/tracked-entities",
        json={"workspace_code": WS, "name": "Viewer 不可建"},
    ).status_code == 403
    assert viewer_client.patch(
        f"/api/tracked-entities/{entity_id}",
        json={"notes": "viewer 不可改"},
    ).status_code == 403
    assert viewer_client.delete(f"/api/tracked-entities/{entity_id}").status_code == 403
    assert viewer_client.post(
        "/api/entity-milestones",
        json={"tracked_entity_id": entity_id, "event_title": "viewer 不可补录"},
    ).status_code == 403

    # 空实体可删除
    empty = client.post(
        "/api/tracked-entities",
        json={"workspace_code": WS, "name": "Empty Corp"},
    )
    assert empty.status_code == 200
    assert client.delete(f"/api/tracked-entities/{empty.json()['id']}").status_code == 200

    # 导入的 legacy 实体不可改删
    Session = sessionmaker(bind=engine)
    with Session() as session:
        legacy_entity = _seed_entity(session, name="Legacy Corp", legacy_system="tech_insight_loop")
        session.commit()
        legacy_entity_id = legacy_entity.id
    assert client.patch(
        f"/api/tracked-entities/{legacy_entity_id}",
        json={"notes": "should fail"},
    ).status_code == 400
    assert client.delete(f"/api/tracked-entities/{legacy_entity_id}").status_code == 400
