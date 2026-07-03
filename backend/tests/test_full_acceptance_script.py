from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

from tests.test_auth import make_client

ROOT = Path(__file__).resolve().parents[2]


def load_acceptance_module():
    path = ROOT / "scripts" / "run_full_acceptance.py"
    spec = importlib.util.spec_from_file_location("run_full_acceptance", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_full_acceptance_script_runs_blueprint_9_flow(monkeypatch, tmp_path):
    client, _engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    acceptance = load_acceptance_module()
    today = date.today()

    result = acceptance.run_acceptance(
        client,
        acceptance.AcceptanceConfig(
            base_url="http://testserver",
            admin_username="admin",
            admin_password="password",
            invite_username="acceptance-user",
            invite_password="acceptance-user-password",
            workspace_prefix="acceptance_test",
            day_key=today.isoformat(),
            week_key=acceptance.iso_week_key(today),
            evidence_dir=tmp_path / "acceptance-evidence",
        ),
    )

    assert result.workspace_code.startswith("acceptance_test_")
    assert result.pipeline_payload["selected_total"] >= 1
    assert result.company_sql_path.exists()
    assert result.daily_md_path.read_text(encoding="utf-8")
    assert result.daily_html_path.read_text(encoding="utf-8").lower().startswith("<!doctype html>")
    assert result.weekly_md_path.read_text(encoding="utf-8")
    assert result.weekly_html_path.read_text(encoding="utf-8").lower().startswith("<!doctype html>")
    assert "ok:" in result.sql_validation_stdout
