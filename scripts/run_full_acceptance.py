#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

SQL_CONTENT_FIELDS = [
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact",
]
AI_SQL_CATEGORIES = [
    "AI Infra",
    "AI 应用",
    "测评技术",
    "大厂动态",
    "模型",
    "算法",
    "推理加速",
    "训练技术",
    "智能体",
    "基础竞争力",
]


class ClientResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> ClientResponse: ...

    def post(self, url: str, **kwargs: Any) -> ClientResponse: ...

    def patch(self, url: str, **kwargs: Any) -> ClientResponse: ...


@dataclass
class AcceptanceConfig:
    base_url: str = "http://127.0.0.1:8000"
    admin_username: str = "acceptance-admin"
    admin_password: str = "acceptance-password"
    invite_username: str = "acceptance-user"
    invite_password: str = "acceptance-user-password"
    workspace_prefix: str = "acceptance_intel"
    rss_bind_host: str = "127.0.0.1"
    rss_public_host: str = "127.0.0.1"
    rss_port: int = 0
    day_key: str = field(default_factory=lambda: date.today().isoformat())
    week_key: str = field(default_factory=lambda: iso_week_key(date.today()))
    setup_if_needed: bool = True
    materialize_sql_ready: bool = True
    evidence_dir: Path | None = None
    validate_sql: bool = True


@dataclass
class AcceptanceResult:
    workspace_code: str
    invited_username: str
    daily_report_id: str
    weekly_report_id: str
    report_format_code: str
    company_sql_path: Path
    daily_md_path: Path
    daily_html_path: Path
    weekly_md_path: Path
    weekly_html_path: Path
    backup_path: Path | None
    evidence_dir: Path
    pipeline_payload: dict[str, Any]
    sql_validation_stdout: str


class AcceptanceError(RuntimeError):
    pass


def main() -> int:
    args = parse_args()
    config = AcceptanceConfig(
        base_url=args.base_url.rstrip("/"),
        admin_username=args.admin_username,
        admin_password=args.admin_password,
        invite_username=args.invite_username,
        invite_password=args.invite_password,
        workspace_prefix=args.workspace_prefix,
        rss_bind_host=args.rss_bind_host or args.rss_host,
        rss_public_host=args.rss_public_host or args.rss_host,
        rss_port=args.rss_port,
        day_key=args.day_key,
        week_key=args.week_key,
        setup_if_needed=not args.no_setup,
        materialize_sql_ready=not args.no_materialize_sql_ready,
        evidence_dir=Path(args.evidence_dir).resolve() if args.evidence_dir else None,
        validate_sql=not args.no_validate_sql,
    )
    with httpx.Client(base_url=config.base_url, timeout=60.0, follow_redirects=True, trust_env=False) as client:
        result = run_acceptance(client, config)
    print(json.dumps(result_summary(result), ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the InfoWatchtower blueprint §9 full acceptance smoke flow.",
    )
    parser.add_argument("--base-url", default=os.environ.get("ACCEPTANCE_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--admin-username", default=os.environ.get("ACCEPTANCE_ADMIN_USERNAME", "acceptance-admin"))
    parser.add_argument("--admin-password", default=os.environ.get("ACCEPTANCE_ADMIN_PASSWORD", "acceptance-password"))
    parser.add_argument("--invite-username", default=os.environ.get("ACCEPTANCE_INVITE_USERNAME", "acceptance-user"))
    parser.add_argument("--invite-password", default=os.environ.get("ACCEPTANCE_INVITE_PASSWORD", "acceptance-user-password"))
    parser.add_argument("--workspace-prefix", default=os.environ.get("ACCEPTANCE_WORKSPACE_PREFIX", "acceptance_intel"))
    parser.add_argument(
        "--rss-host",
        default=os.environ.get("ACCEPTANCE_RSS_HOST", "127.0.0.1"),
        help="Compatibility shortcut used as both RSS bind host and public host.",
    )
    parser.add_argument("--rss-bind-host", default=os.environ.get("ACCEPTANCE_RSS_BIND_HOST", ""))
    parser.add_argument("--rss-public-host", default=os.environ.get("ACCEPTANCE_RSS_PUBLIC_HOST", ""))
    parser.add_argument("--rss-port", type=int, default=int(os.environ.get("ACCEPTANCE_RSS_PORT", "0")))
    parser.add_argument("--day-key", default=os.environ.get("ACCEPTANCE_DAY_KEY", date.today().isoformat()))
    parser.add_argument(
        "--week-key",
        default=os.environ.get("ACCEPTANCE_WEEK_KEY", iso_week_key(date.today())),
    )
    parser.add_argument("--evidence-dir", default=os.environ.get("ACCEPTANCE_EVIDENCE_DIR", ""))
    parser.add_argument("--no-setup", action="store_true")
    parser.add_argument("--no-materialize-sql-ready", action="store_true")
    parser.add_argument("--no-validate-sql", action="store_true")
    return parser.parse_args()


def run_acceptance(client: HttpClient, config: AcceptanceConfig) -> AcceptanceResult:
    evidence_dir = _evidence_dir(config)
    workspace_code = _unique_code(config.workspace_prefix)
    invite_username = f"{config.invite_username}-{workspace_code[-6:]}"
    report_format_code = f"weekly_exec_{workspace_code[-6:]}"
    sql_validation_stdout = ""

    with local_rss_server(
        bind_host=config.rss_bind_host,
        public_host=config.rss_public_host,
        port=config.rss_port,
        day_key=config.day_key,
    ) as rss:
        _record_json(evidence_dir / "00_health.json", expect_json(_get(client, "/healthz")))
        if config.setup_if_needed:
            _ensure_setup_account(client, config)
        login_payload = _login(client, config.admin_username, config.admin_password)
        _record_json(evidence_dir / "01_login_admin.json", login_payload)

        invite = expect_json(
            _post(
                client,
                "/api/auth/invites",
                json={
                    "email": f"{invite_username}@example.com",
                    "role_code": "viewer",
                    "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
                    "expires_in_days": 7,
                },
            ),
        )
        _record_json(evidence_dir / "02_invite.json", invite)

        invited_client = _same_kind_client(client, config.base_url)
        try:
            accepted = expect_json(
                _post(
                    invited_client,
                    f"/api/auth/invites/{invite['code']}/accept",
                    json={
                        "username": invite_username,
                        "display_name": "验收协作者",
                        "password": config.invite_password,
                    },
                ),
            )
        finally:
            close = getattr(invited_client, "close", None)
            if callable(close):
                close()
        _record_json(evidence_dir / "03_invite_accept.json", accepted)
        invited_user_id = accepted["user"]["id"]

        workspace = expect_json(
            _post(
                client,
                "/api/workspaces",
                json={
                    "code": workspace_code,
                    "name": f"全量验收工作台 {workspace_code[-6:]}",
                    "description": "蓝图 §9 自动验收工作台。",
                    "default_domain_code": "ai",
                },
            ),
        )
        _record_json(evidence_dir / "04_workspace.json", workspace)

        member = expect_json(
            _post(
                client,
                f"/api/workspaces/{workspace_code}/members",
                json={"user_id": invited_user_id, "workspace_role": "member"},
            ),
        )
        _record_json(evidence_dir / "05_workspace_member.json", member)

        shared_source = expect_json(
            _post(
                client,
                "/api/sources",
                json={
                    "workspace_code": "planning_intel",
                    "name": f"验收共享 RSS {workspace_code[-6:]}",
                    "source_type": "rss",
                    "url": rss.url("/shared.xml"),
                    "domain_code": "ai",
                    "source_weight": 1.3,
                    "daily_limit": 2,
                },
            ),
        )["source"]
        linked_shared = expect_json(
            _patch(
                client,
                f"/api/sources/{shared_source['id']}/workspace-link",
                json={
                    "workspace_code": workspace_code,
                    "enabled": True,
                    "source_weight": 1.3,
                    "daily_limit": 2,
                },
            ),
        )
        custom_source = expect_json(
            _post(
                client,
                "/api/sources",
                json={
                    "workspace_code": workspace_code,
                    "name": f"验收自建 RSS {workspace_code[-6:]}",
                    "source_type": "rss",
                    "url": rss.url("/custom.xml"),
                    "domain_code": "ai",
                    "source_weight": 1.4,
                    "daily_limit": 2,
                },
            ),
        )["source"]
        _record_json(
            evidence_dir / "06_sources.json",
            {"shared_source": shared_source, "linked_shared": linked_shared, "custom_source": custom_source},
        )

        label_policy = expect_json(
            _patch(
                client,
                f"/api/workspaces/{workspace_code}/label-policy",
                json={
                    "label_set_code": "ai_sql_categories",
                    "news_format_code": "company_sql_v1",
                    "export_category_mode": "news_primary",
                    "required_content_fields": SQL_CONTENT_FIELDS,
                    "allowed_primary_categories": AI_SQL_CATEGORIES,
                    "secondary_labels_by_primary": {
                        "AI Infra": ["GPU 集群", "推理服务"],
                        "智能体": ["企业工作流", "工具调用"],
                    },
                    "default_category": "AI Infra",
                    "fallback_category": "AI 应用",
                },
            ),
        )
        _record_json(evidence_dir / "07_label_policy.json", label_policy)

        report_format = expect_json(
            _post(
                client,
                "/api/report-formats",
                json={
                    "workspace_code": workspace_code,
                    "format_code": report_format_code,
                    "name": "验收自定义周报格式",
                    "description": "按业务板块输出摘要、要点、影响和来源。",
                    "group_by": "board",
                    "headline_enabled": True,
                    "headline_auto_top_n": 2,
                    "item_fields": ["tag_line", "bullet_points", "takeaway", "summary", "source_link"],
                    "export_targets": ["md", "html"],
                },
            ),
        )
        _record_json(evidence_dir / "08_report_format.json", report_format)

        pipeline = expect_json(
            _post(
                client,
                "/api/pipeline/daily-runs",
                json={
                    "workspace_code": workspace_code,
                    "day_key": config.day_key,
                    "source_types": ["rss"],
                    "ingestion_limit": 10,
                    "ingestion_concurrency": 2,
                    "ingestion_source_timeout_seconds": 15,
                    "ingestion_max_items_per_source": 3,
                    "recommendation_limit": 6,
                    "source_daily_limit": 3,
                    "generation_timeout_seconds": 5,
                    "create_daily_draft": True,
                    "run_ingestion": True,
                },
            ),
        )
        _record_json(evidence_dir / "09_pipeline.json", pipeline)
        if not pipeline.get("daily_report_id") or pipeline.get("selected_total", 0) < 1:
            raise AcceptanceError(f"daily pipeline did not create an accepted draft: {pipeline}")
        daily_report_id = pipeline["daily_report_id"]

        if config.materialize_sql_ready:
            materialized = materialize_daily_report_for_sql(daily_report_id)
            _record_json(evidence_dir / "10_materialize_sql_ready.json", materialized)

        published_daily = expect_json(_post(client, f"/api/daily-reports/{daily_report_id}/publish", json={}))
        _record_json(evidence_dir / "11_daily_publish.json", published_daily)

        weekly_report = expect_json(
            _post(
                client,
                "/api/weekly-reports",
                json={
                    "workspace_code": workspace_code,
                    "week_key": config.week_key,
                    "limit": 20,
                    "include_unpublished_daily": False,
                },
            ),
        )
        weekly_report_id = weekly_report["id"]
        _record_json(evidence_dir / "12_weekly_report.json", weekly_report)
        if not weekly_report.get("items"):
            raise AcceptanceError("weekly report has no items")

        published_weekly = expect_json(_post(client, f"/api/weekly-reports/{weekly_report_id}/publish", json={}))
        _record_json(evidence_dir / "13_weekly_publish.json", published_weekly)

        daily_md_path = _write_response(
            evidence_dir / "daily_report.md",
            _get(client, f"/api/daily-reports/{daily_report_id}/renditions/tech_insight_v1/export?target=md"),
        )
        daily_html_path = _write_response(
            evidence_dir / "daily_report.html",
            _get(client, f"/api/daily-reports/{daily_report_id}/renditions/tech_insight_v1/export?target=html"),
        )
        weekly_md_path = _write_response(
            evidence_dir / "weekly_report.md",
            _get(client, f"/api/weekly-reports/{weekly_report_id}/renditions/{report_format_code}/export?target=md"),
        )
        weekly_html_path = _write_response(
            evidence_dir / "weekly_report.html",
            _get(client, f"/api/weekly-reports/{weekly_report_id}/renditions/{report_format_code}/export?target=html"),
        )

        company_sql = expect_json(_post(client, f"/api/exports/company-sql/daily-reports/{daily_report_id}", json={}))
        _record_json(evidence_dir / "14_company_sql_export.json", {k: v for k, v in company_sql.items() if k != "sql_text"})
        company_sql_path = evidence_dir / "company_sql_preview.sql"
        company_sql_path.write_text(company_sql["sql_text"], encoding="utf-8")

        if config.validate_sql:
            sql_validation_stdout = validate_company_sql(company_sql_path)
            (evidence_dir / "15_company_sql_validation.txt").write_text(sql_validation_stdout, encoding="utf-8")

        backup_path = run_backup(evidence_dir)
        if backup_path is not None:
            _record_json(evidence_dir / "16_backup.json", {"backup_path": str(backup_path), "size": backup_path.stat().st_size})

    return AcceptanceResult(
        workspace_code=workspace_code,
        invited_username=invite_username,
        daily_report_id=daily_report_id,
        weekly_report_id=weekly_report_id,
        report_format_code=report_format_code,
        company_sql_path=company_sql_path,
        daily_md_path=daily_md_path,
        daily_html_path=daily_html_path,
        weekly_md_path=weekly_md_path,
        weekly_html_path=weekly_html_path,
        backup_path=backup_path,
        evidence_dir=evidence_dir,
        pipeline_payload=pipeline,
        sql_validation_stdout=sql_validation_stdout,
    )


def _ensure_setup_account(client: HttpClient, config: AcceptanceConfig) -> None:
    status_response = _get(client, "/api/setup/status")
    if status_response.status_code == 404:
        return
    status_payload = expect_json(status_response)
    if not status_payload.get("needs_setup"):
        return
    setup = expect_json(
        _post(
            client,
            "/api/setup",
            json={
                "username": config.admin_username,
                "display_name": "验收超级管理员",
                "password": config.admin_password,
            },
        ),
    )
    if "user" not in setup:
        raise AcceptanceError(f"setup did not return a user: {setup}")


def _login(client: HttpClient, username: str, password: str) -> dict[str, Any]:
    return expect_json(
        _post(
            client,
            "/api/auth/login",
            json={"username": username, "password": password},
        ),
    )


def materialize_daily_report_for_sql(daily_report_id: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.database import get_session_factory
    from app.models.reports import DailyReport, DailyReportItem

    session_factory = get_session_factory()
    if session_factory is None:
        raise AcceptanceError("DATABASE_URL is required for --materialize-sql-ready")

    with session_factory() as session:
        report = session.scalar(
            select(DailyReport).where(DailyReport.id == daily_report_id),
        )
        if report is None:
            raise AcceptanceError(f"daily report not found for materialization: {daily_report_id}")
        items = session.scalars(
            select(DailyReportItem).where(DailyReportItem.daily_report_id == daily_report_id),
        ).all()
        for index, item in enumerate(items, start=1):
            news = item.generated_news
            item.adoption_status = 2
            item.sort_order = index
            news.generation_status = "ready"
            news.generated_by = "acceptance_llm_stub"
            if news.category not in AI_SQL_CATEGORIES:
                news.category = "AI Infra"
            news.title = news.title or f"验收情报 {index}"
            news.summary = news.summary or "自动验收生成的日报摘要。"
            news.key_points = news.key_points or "模型服务；推理延迟；集群调度"
            content = dict(news.content_json or {})
            for field in SQL_CONTENT_FIELDS:
                content[field] = str(content.get(field) or _fallback_content(field, news.title))
            news.content_json = content
            insight = dict(news.insight_json or {})
            insight.setdefault("board", "infrastructure")
            insight.setdefault("bullet_points", ["推理服务架构更新", "GPU 集群调度和成本指标进入评估"])
            insight.setdefault("takeaway", "该信号适合进入周报，作为工作台验收的可导出成稿样例。")
            insight.setdefault("tag_line", ["AI Infra", "推理服务"])
            news.insight_json = insight
        session.commit()
        return {"daily_report_id": daily_report_id, "items_materialized": len(items)}


def _fallback_content(field: str, title: str) -> str:
    labels = {
        "background": "来源信息显示 AI 基础设施正在更新。",
        "effects": "可能影响模型服务成本、吞吐和部署节奏。",
        "eventSummary": title or "验收情报条目。",
        "technologyAndInnovation": "涉及推理服务、GPU 集群调度、KV cache 和性能基准。",
        "valueAndImpact": "可作为日报和周报成稿、SQL 导出链路的验收样例。",
    }
    return labels[field]


def validate_company_sql(path: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_company_sql.py"), str(path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AcceptanceError(
            "company SQL validation failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
    return result.stdout


def run_backup(evidence_dir: Path) -> Path | None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url or database_url.startswith("sqlite"):
        return None
    backup_dir = evidence_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "BACKUP_DIR": str(backup_dir),
        "BACKUP_KEEP": "3",
    }
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "backup_db.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    (evidence_dir / "16_backup_stdout.txt").write_text(result.stdout, encoding="utf-8")
    (evidence_dir / "16_backup_stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise AcceptanceError(f"backup failed: {result.stderr or result.stdout}")
    backups = sorted(backup_dir.glob("infowatchtower_*.sql.gz"))
    return backups[-1] if backups else None


@dataclass(frozen=True)
class RssServerHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread
    public_host: str
    port: int

    def url(self, path: str) -> str:
        return f"http://{self.public_host}:{self.port}{path}"


@contextlib.contextmanager
def local_rss_server(bind_host: str, public_host: str, port: int, day_key: str):
    feeds = {
        "/shared.xml": render_feed(
            title="Acceptance Shared Feed",
            day_key=day_key,
            items=[
                (
                    "shared-1",
                    "AI inference serving architecture benchmark improves GPU throughput",
                    "The model serving update describes inference latency, KV cache, GPU cluster scheduling, throughput benchmark evidence and deployment cost impact.",
                ),
                (
                    "shared-2",
                    "Enterprise agents add tool calling workflow and MCP audit controls",
                    "The agent platform release covers tool calling, MCP integration, workflow orchestration, evaluation dataset, security controls and production deployment.",
                ),
            ],
        ),
        "/custom.xml": render_feed(
            title="Acceptance Custom Feed",
            day_key=day_key,
            items=[
                (
                    "custom-1",
                    "LLM training infrastructure adds HBM cluster scheduling benchmark",
                    "The training infrastructure note covers HBM memory, distributed training, benchmark data, architecture tradeoffs, energy cost and reliability metrics.",
                ),
                (
                    "custom-2",
                    "AI application workflow rolls out assistant copilot integration",
                    "The application case explains assistant workflow, enterprise deployment, evaluation, data pipeline and measurable productivity impact.",
                ),
            ],
        ),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = feeds.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer((bind_host, port), Handler)
    actual_port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        health_host = "127.0.0.1" if bind_host == "0.0.0.0" else bind_host
        wait_for_port(health_host, actual_port)
        yield RssServerHandle(server=server, thread=thread, public_host=public_host, port=actual_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def render_feed(title: str, day_key: str, items: list[tuple[str, str, str]]) -> str:
    pub_date = f"{day_key}T08:00:00+00:00"
    item_xml = "\n".join(
        (
            "    <item>"
            f"<guid>{guid}</guid>"
            f"<title>{escape_xml(item_title)}</title>"
            f"<link>https://example.com/{guid}</link>"
            f"<pubDate>{pub_date}</pubDate>"
            f"<description>{escape_xml(description)}</description>"
            "</item>"
        )
        for guid, item_title, description in items
    )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<rss version=\"2.0\"><channel>"
        f"<title>{escape_xml(title)}</title>"
        f"<link>https://example.com/{escape_xml(title.lower().replace(' ', '-'))}</link>"
        "<description>InfoWatchtower acceptance feed</description>"
        f"{item_xml}"
        "</channel></rss>"
    )


def wait_for_port(host: str, port: int) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AcceptanceError(f"RSS server did not start on {host}:{port}")


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _same_kind_client(client: HttpClient, base_url: str) -> HttpClient:
    app = getattr(client, "app", None)
    if app is not None:
        return client.__class__(app)
    if isinstance(client, httpx.Client):
        return httpx.Client(base_url=base_url, timeout=60.0, follow_redirects=True, trust_env=False)
    raise AcceptanceError("Cannot create an isolated invite client for this HTTP client type")


def iso_week_key(value: date) -> str:
    iso_year, iso_week, _ = value.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _get(client: HttpClient, path: str, **kwargs: Any) -> ClientResponse:
    return _request(client.get(path, **kwargs), "GET", path)


def _post(client: HttpClient, path: str, **kwargs: Any) -> ClientResponse:
    return _request(client.post(path, **kwargs), "POST", path)


def _patch(client: HttpClient, path: str, **kwargs: Any) -> ClientResponse:
    return _request(client.patch(path, **kwargs), "PATCH", path)


def _request(response: ClientResponse, method: str, path: str) -> ClientResponse:
    if 200 <= response.status_code < 300:
        return response
    raise AcceptanceError(f"{method} {path} failed with {response.status_code}: {response.text}")


def expect_json(response: ClientResponse) -> Any:
    try:
        return response.json()
    except Exception as exc:
        raise AcceptanceError(f"response is not JSON: {response.text[:500]}") from exc


def _write_response(path: Path, response: ClientResponse) -> Path:
    path.write_text(response.text, encoding="utf-8")
    if path.stat().st_size == 0:
        raise AcceptanceError(f"empty export: {path}")
    return path


def _record_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _evidence_dir(config: AcceptanceConfig) -> Path:
    if config.evidence_dir is not None:
        path = config.evidence_dir
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = REPO_ROOT / "outputs" / "acceptance" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _unique_code(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    normalized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in prefix.lower())
    if not normalized or not normalized[0].isalpha():
        normalized = f"acceptance_{normalized}"
    return f"{normalized}_{suffix}"


def result_summary(result: AcceptanceResult) -> dict[str, Any]:
    return {
        "workspace_code": result.workspace_code,
        "invited_username": result.invited_username,
        "daily_report_id": result.daily_report_id,
        "weekly_report_id": result.weekly_report_id,
        "report_format_code": result.report_format_code,
        "evidence_dir": str(result.evidence_dir),
        "company_sql_path": str(result.company_sql_path),
        "daily_md_path": str(result.daily_md_path),
        "daily_html_path": str(result.daily_html_path),
        "weekly_md_path": str(result.weekly_md_path),
        "weekly_html_path": str(result.weekly_html_path),
        "backup_path": str(result.backup_path) if result.backup_path else None,
        "pipeline": result.pipeline_payload,
        "sql_validation": result.sql_validation_stdout.strip(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
