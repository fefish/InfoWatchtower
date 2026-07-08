from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "frontend" / "src" / "pages"
COPY_AUDIT_CONTRACT = ROOT / "config" / "contracts" / "frontend_control_governance.json"

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


# ---------------------------------------------------------------------------
# 界面文案审计（frontend-product-design §14，契约 frontend_control_governance.json
# copy_audit_rule，断言设计见 page-specs §10.4）：用户可见文案禁止实现术语。
# ---------------------------------------------------------------------------

# 静态 title/placeholder/aria-label 属性值（绑定属性 :title 等是代码，不在扫描面内）。
_COPY_ATTR_RE = re.compile(r'(?<![:\w@-])(?:title|placeholder|aria-label)\s*=\s*"([^"]*)"')


def _load_copy_audit_rule() -> dict:
    contract = json.loads(COPY_AUDIT_CONTRACT.read_text(encoding="utf-8"))
    return contract["copy_audit_rule"]


def _vue_template_section(source: str) -> str:
    start = source.find("<template>")
    end = source.rfind("</template>")
    if start == -1 or end == -1 or end <= start:
        return ""
    return source[start:end]


def _visible_copy(template: str) -> str:
    """<template> 段的用户可见文案：正文文本 + 静态 title/placeholder/aria-label。

    注释、mustache 插值表达式（{{ item.adoption_status }} 等字段访问是代码不是
    文案）与标签本身都不属于可见文案（契约 exemptions 第 3 条）。
    """

    template = re.sub(r"<!--.*?-->", " ", template, flags=re.S)
    template = re.sub(r"\{\{.*?\}\}", " ", template, flags=re.S)
    attr_values = _COPY_ATTR_RE.findall(template)
    text = re.sub(r"<[^>]*>", "\n", template)
    return "\n".join([text, *attr_values])


def _backend_user_facing_messages(path: Path) -> list[str]:
    """后端会透传到界面的中文提示串（preflight/错误 detail）。

    company_sql_v1 导出 SQL 文件内的 "--" 注释行是契约锁死的导出产物，
    不是界面文案（契约 exemptions 第 2 条），按行首 "--" 排除。
    """

    messages = []
    for literal in re.findall(r'"((?:[^"\\]|\\.)*)"', path.read_text(encoding="utf-8")):
        if not re.search(r"[一-鿿]", literal):
            continue
        if literal.lstrip().startswith("--"):
            continue
        messages.append(literal)
    return messages


def _copy_violations(rule: dict) -> list[str]:
    banned_terms = rule["banned_terms"]
    banned_patterns = [re.compile(pattern) for pattern in rule["banned_patterns"]]
    file_markers: dict[str, list[str]] = {}
    for exemption in rule.get("exemptions", []):
        if exemption.get("file") and exemption.get("marker"):
            file_markers.setdefault(exemption["file"], []).append(exemption["marker"])

    scan_targets: list[tuple[str, str]] = []
    for scanned_path in rule["scanned_paths"]:
        for path in sorted((ROOT / scanned_path).glob("*.vue")):
            rel = path.relative_to(ROOT).as_posix()
            copy_text = _visible_copy(_vue_template_section(path.read_text(encoding="utf-8")))
            scan_targets.append((rel, copy_text))

    # 后端用户可见提示（scanned_scope；违例 #8 的所在面）。
    backend_export = ROOT / "backend" / "app" / "exports" / "company_sql.py"
    scan_targets.append(
        (
            "backend/app/exports/company_sql.py",
            "\n".join(_backend_user_facing_messages(backend_export)),
        ),
    )

    violations = []
    for rel, copy_text in scan_targets:
        for marker in file_markers.get(rel, []):
            # 豁免按契约 file+marker 白名单放行：只豁免 marker 本身的出现。
            copy_text = copy_text.replace(marker, " ")
        for term in banned_terms:
            if term in copy_text:
                violations.append(f"{rel}: banned term {term!r}")
        for pattern in banned_patterns:
            if pattern.search(copy_text):
                violations.append(f"{rel}: banned pattern {pattern.pattern!r}")
    return violations


def test_blueprint_user_copy_bans_implementation_terms():
    rule = _load_copy_audit_rule()
    violations = _copy_violations(rule)

    # known_violations 是只减不增基线：清零前只容忍契约里明确列出的文件，
    # 清零后（当前状态）收紧为全量禁止。
    tolerated_files = {
        entry.split(":", 1)[0] for entry in rule.get("known_violations", []) if isinstance(entry, str)
    }
    unexpected = [
        violation
        for violation in violations
        if violation.split(":", 1)[0] not in tolerated_files
    ]
    assert unexpected == [], "user-visible copy contains implementation terms:\n" + "\n".join(unexpected)


def test_blueprint_copy_audit_scanner_detects_seeded_violations():
    """看护扫描器本身：可见文本、静态属性与后端提示三个面都必须能命中禁用词。"""

    rule = _load_copy_audit_rule()
    template = (
        "<template>\n"
        '  <p>采信状态为 2 的条目</p>\n'
        '  <input placeholder="fallback_needs_review" :title="item.adoption_status" />\n'
        "  <span>{{ item.generation_status }}</span>\n"
        "</template>"
    )
    copy_text = _visible_copy(_vue_template_section(template))
    assert any(re.search(pattern, copy_text) for pattern in rule["banned_patterns"])
    assert "fallback_needs_review" in copy_text
    # 绑定属性与 mustache 表达式是代码，不算可见文案
    assert "adoption_status" not in copy_text
    assert "generation_status" not in copy_text
