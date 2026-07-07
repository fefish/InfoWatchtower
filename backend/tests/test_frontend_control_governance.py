from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_control_governance_script_passes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_frontend_controls.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "frontend-control-governance: ok" in result.stdout
