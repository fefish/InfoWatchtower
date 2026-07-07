#!/usr/bin/env python3
"""Validate InfoWatchtower documentation layering rules."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"

ALLOWED_DOCS_ROOT_FILES = {
    "README.md",
    "00-system-design.md",
}

REQUIRED_DOC_DIRS = {
    "architecture",
    "product",
    "backend",
    "deployment",
    "implementation",
    "reference",
}

REQUIRED_DOC_FILES = {
    "README.md",
    "00-system-design.md",
    "architecture/README.md",
    "architecture/design-governance.md",
    "architecture/capability-map.md",
    "architecture/software-design-description.md",
    "architecture/strategic-intelligence-platform.md",
    "architecture/target-state-spec.md",
    "product/README.md",
    "product/frontend-product-design.md",
    "product/page-specs/frontend-page-specs.md",
    "backend/README.md",
    "backend/archive-knowledge-design.md",
    "backend/audit-ops-observability-design.md",
    "backend/backend-module-design.md",
    "backend/identity-access-design.md",
    "backend/collaboration-notification-design.md",
    "backend/contract-test-governance-design.md",
    "backend/data-format-mapping.md",
    "backend/data-ingestion-flow-storage-design.md",
    "backend/data-lineage-and-storage.md",
    "backend/export-compliance-design.md",
    "backend/extension-governance-design.md",
    "backend/extension-points.md",
    "backend/extension-recipes.md",
    "backend/feedback-heat-scoring.md",
    "backend/ingestion-adapter-dedup-spec.md",
    "backend/pipeline-jobs-design.md",
    "backend/recommendation-scoring-design.md",
    "backend/report-renditions-design.md",
    "backend/reports-editorial-design.md",
    "backend/security-secrets-privacy-design.md",
    "backend/workspace-configuration-design.md",
    "backend/search-design.md",
    "backend/strategy-loop-design.md",
    "backend/sync-conflict-distribution-design.md",
    "backend/tech-insight-loop-fusion-plan.md",
    "backend/workspace-module-model.md",
    "deployment/README.md",
    "deployment/auth-security-roadmap.md",
    "deployment/auth-unified-login.md",
    "deployment/deployment-topology.md",
    "deployment/deployment-ops.md",
    "deployment/development-quickstart.md",
    "deployment/multi-environment-sync.md",
    "implementation/README.md",
    "implementation/01-implementation-plan.md",
    "implementation/api-and-ui-implementation.md",
    "implementation/implementation-handoff.md",
    "implementation/technical-debt-and-refactor-log.md",
    "reference/README.md",
    "reference/ai-collaboration-engineering-case.md",
    "reference/data-examples.md",
    "reference/legacy-system-spec.md",
    "reference/system-blueprint.md",
}

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "outputs",
    "references",
}

TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
    "",
}

DOC_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_./-])(docs/[A-Za-z0-9_./-]+\.md)")


def main() -> int:
    issues: list[str] = []
    issues.extend(_validate_docs_root())
    issues.extend(_validate_required_docs())
    issues.extend(_validate_indexed_docs())
    issues.extend(_validate_doc_references())

    if issues:
        for issue in issues:
            print(f"docs-governance: {issue}", file=sys.stderr)
        return 1

    print("docs-governance: ok")
    return 0


def _validate_docs_root() -> list[str]:
    issues: list[str] = []
    if not DOCS_ROOT.exists():
        return ["docs/ directory is missing"]

    root_files = {path.name for path in DOCS_ROOT.iterdir() if path.is_file()}
    unexpected = sorted(root_files - ALLOWED_DOCS_ROOT_FILES)
    if unexpected:
        issues.append(
            "docs/ root may only contain README.md and 00-system-design.md; "
            f"unexpected files: {', '.join(unexpected)}"
        )

    missing = sorted(ALLOWED_DOCS_ROOT_FILES - root_files)
    if missing:
        issues.append(f"docs/ root is missing required files: {', '.join(missing)}")

    root_dirs = {path.name for path in DOCS_ROOT.iterdir() if path.is_dir()}
    missing_dirs = sorted(REQUIRED_DOC_DIRS - root_dirs)
    if missing_dirs:
        issues.append(f"docs/ is missing required directories: {', '.join(missing_dirs)}")
    return issues


def _validate_required_docs() -> list[str]:
    issues: list[str] = []
    for relative_path in sorted(REQUIRED_DOC_FILES):
        if not (DOCS_ROOT / relative_path).is_file():
            issues.append(f"required document is missing: docs/{relative_path}")
    return issues


def _validate_indexed_docs() -> list[str]:
    issues: list[str] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        if path == DOCS_ROOT / "README.md":
            continue

        relative_to_docs = path.relative_to(DOCS_ROOT).as_posix()
        index_start = path.parent.parent if path.name == "README.md" else path.parent
        index_path = _nearest_index(index_start)
        if index_path is None:
            issues.append(f"document has no parent README index: docs/{relative_to_docs}")
            continue

        index_text = _read_text(index_path)
        if index_text is None:
            issues.append(f"cannot read parent README index for docs/{relative_to_docs}")
            continue

        relative_to_index = path.relative_to(index_path.parent).as_posix()
        if relative_to_index not in index_text and relative_to_docs not in index_text:
            index_display = index_path.relative_to(REPO_ROOT).as_posix()
            issues.append(
                f"document is not indexed by {index_display}: docs/{relative_to_docs}"
            )
    return issues


def _nearest_index(directory: Path) -> Path | None:
    current = directory
    while current == DOCS_ROOT or DOCS_ROOT in current.parents:
        candidate = current / "README.md"
        if candidate.is_file():
            return candidate
        if current == DOCS_ROOT:
            break
        current = current.parent
    return None


def _validate_doc_references() -> list[str]:
    issues: list[str] = []
    for path in _iter_text_files(REPO_ROOT):
        text = _read_text(path)
        if text is None:
            continue
        for match in DOC_PATH_PATTERN.finditer(text):
            doc_path = match.group(1)
            if "..." in doc_path:
                continue
            if not (REPO_ROOT / doc_path).is_file():
                line_number = text.count("\n", 0, match.start()) + 1
                display_path = path.relative_to(REPO_ROOT)
                issues.append(f"{display_path}:{line_number} references missing {doc_path}")
    return issues


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        yield path


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
