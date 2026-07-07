#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "contracts" / "frontend_control_governance.json"


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    errors.extend(validate_button_actions(contract))
    errors.extend(validate_router_links(contract))
    errors.extend(validate_banned_placeholder_text(contract))
    errors.extend(validate_global_controls(contract))
    if errors:
        print("frontend-control-governance: failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("frontend-control-governance: ok")
    return 0


def validate_button_actions(contract: dict[str, Any]) -> list[str]:
    markers = contract["button_action_rule"]["required_markers"]
    errors: list[str] = []
    for path in iter_vue_files(contract["button_action_rule"]["scanned_paths"]):
        content = path.read_text(encoding="utf-8")
        for attrs, line in iter_start_tags(content, "button"):
            if not any(marker in attrs for marker in markers):
                errors.append(
                    f"{relative(path)}:{line} <button> has no click handler or submit behavior"
                )
    return errors


def validate_router_links(contract: dict[str, Any]) -> list[str]:
    markers = contract["router_link_rule"]["required_markers"]
    errors: list[str] = []
    for path in iter_vue_files(contract["button_action_rule"]["scanned_paths"]):
        content = path.read_text(encoding="utf-8")
        for attrs, line in iter_start_tags(content, "RouterLink"):
            if not any(marker in attrs for marker in markers):
                errors.append(f"{relative(path)}:{line} <RouterLink> has no route target")
    return errors


def validate_banned_placeholder_text(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    banned = contract.get("banned_placeholder_text", [])
    for path in iter_vue_files(contract["button_action_rule"]["scanned_paths"]):
        content = path.read_text(encoding="utf-8")
        for text in banned:
            if text in content:
                errors.append(f"{relative(path)} contains banned placeholder text: {text}")
    return errors


def validate_global_controls(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for control in contract.get("global_controls", []):
        control_id = control["id"]
        source_path = REPO_ROOT / control["source_file"]
        if not source_path.exists():
            errors.append(f"{control_id}: missing source file {control['source_file']}")
            continue
        source_text = source_path.read_text(encoding="utf-8")
        errors.extend(missing_markers(control_id, source_path, source_text, control["required_source_markers"]))
        for key in ("api_files", "contract_files"):
            for file_name in control.get(key, []):
                file_path = REPO_ROOT / file_name
                if not file_path.exists():
                    errors.append(f"{control_id}: missing {key[:-1]} {file_name}")
        for test in control.get("test_files", []):
            test_path = REPO_ROOT / test["path"]
            if not test_path.exists():
                errors.append(f"{control_id}: missing test file {test['path']}")
                continue
            test_text = test_path.read_text(encoding="utf-8")
            errors.extend(missing_markers(control_id, test_path, test_text, test["required_markers"]))
    return errors


def missing_markers(control_id: str, path: Path, content: str, markers: list[str]) -> list[str]:
    return [
        f"{control_id}: {relative(path)} missing marker {marker!r}"
        for marker in markers
        if marker not in content
    ]


def iter_vue_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for path_name in paths:
        files.extend((REPO_ROOT / path_name).glob("*.vue"))
    return sorted(files)


def iter_start_tags(content: str, tag_name: str) -> list[tuple[str, int]]:
    tags: list[tuple[str, int]] = []
    pattern = re.compile(rf"<{re.escape(tag_name)}\b", re.IGNORECASE)
    for match in pattern.finditer(content):
        end = find_start_tag_end(content, match.end())
        if end is None:
            continue
        attrs = normalize_attrs(content[match.end() : end])
        tags.append((attrs, line_number(content, match.start())))
    return tags


def find_start_tag_end(content: str, offset: int) -> int | None:
    quote: str | None = None
    index = offset
    while index < len(content):
        char = content[index]
        if quote:
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == ">":
            return index
        index += 1
    return None


def normalize_attrs(attrs: str) -> str:
    return re.sub(r"\s+", " ", attrs.strip())


def line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
