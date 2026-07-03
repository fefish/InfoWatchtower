from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "frontend" / "src" / "pages"

WORKSPACE_PAGE_FILES = [
    "AuditLogsPage.vue",
    "DashboardPage.vue",
    "DailyReportsPage.vue",
    "EntityMilestonesPage.vue",
    "ExportsPage.vue",
    "HistoricalReportsPage.vue",
    "IngestionRunsPage.vue",
    "NewsPage.vue",
    "QualityArchivePage.vue",
    "RecommendationsPage.vue",
    "RequirementsPage.vue",
    "SourceDetailPage.vue",
    "SourcesPage.vue",
    "SyncRunsPage.vue",
    "TopicTasksPage.vue",
    "UsersPage.vue",
    "WeeklyReportsPage.vue",
]


def test_blueprint_workspace_pages_reload_on_workspace_switch():
    missing = []
    for filename in WORKSPACE_PAGE_FILES:
        content = (PAGES / filename).read_text(encoding="utf-8")
        if "workspace.currentCode" not in content or "watch(" not in content:
            missing.append(filename)
    assert missing == []


def test_blueprint_empty_states_explain_next_action():
    too_bare = []
    for path in sorted(PAGES.glob("*.vue")):
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if 'class="empty-state"' in stripped and ("暂无" in stripped or "没有找到" in stripped):
                if "，" not in stripped and "请" not in stripped and "先" not in stripped:
                    too_bare.append(f"{path.name}: {stripped}")
    assert too_bare == []
