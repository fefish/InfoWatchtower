from __future__ import annotations

import gzip
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_backup_db_script_writes_gzip_and_rotates(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pg_dump = bin_dir / "pg_dump"
    pg_dump.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' '-- fake dump'\n"
        "printf 'select 1; -- %s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    pg_dump.chmod(0o755)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "infowatchtower_20000101T000000Z.sql.gz").write_bytes(gzip.compress(b"old"))

    result = subprocess.run(
        [str(ROOT / "scripts" / "backup_db.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DATABASE_URL": "postgresql+psycopg://example",
            "BACKUP_DIR": str(backup_dir),
            "BACKUP_KEEP": "1",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    backups = sorted(backup_dir.glob("infowatchtower_*.sql.gz"))
    assert len(backups) == 1
    assert backups[0].name != "infowatchtower_20000101T000000Z.sql.gz"
    with gzip.open(backups[0], "rt", encoding="utf-8") as handle:
        content = handle.read()
    assert "-- fake dump" in content
    assert "postgresql://example" in content
    assert "postgresql+psycopg://example" not in content


def test_restore_db_script_streams_backup_to_psql(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    restored_sql = tmp_path / "restored.sql"
    psql_args = tmp_path / "psql.args"
    psql = bin_dir / "psql"
    psql.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" > {shlex.quote(str(psql_args))}\n"
        f"cat > {shlex.quote(str(restored_sql))}\n",
        encoding="utf-8",
    )
    psql.chmod(0o755)
    backup = tmp_path / "backup.sql.gz"
    backup.write_bytes(gzip.compress(b"select 42;\n"))

    result = subprocess.run(
        [str(ROOT / "scripts" / "restore_db.sh"), str(backup)],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DATABASE_URL": "postgresql+psycopg://example",
            "RESTORE_CONFIRM": "yes",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert restored_sql.read_text(encoding="utf-8") == "select 42;\n"
    assert psql_args.read_text(encoding="utf-8").strip() == "postgresql://example"
    assert "Restore completed" in result.stdout


def test_deploy_scripts_have_valid_bash_syntax():
    for script in ("deploy/install.sh", "deploy/upgrade.sh", "scripts/backup_db.sh", "scripts/restore_db.sh"):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / script)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
