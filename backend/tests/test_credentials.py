"""credential_ref 解析机制（app/core/credentials.py）。

契约口径：credential_ref 是唯一的凭据指针（env:VAR / file:/absolute/path），
非法/缺失返回 None 并记 WARNING（不抛），抓取层按"无凭据"匿名继续。
"""

import logging

import pytest

from app.core.credentials import resolve_credential, resolve_source_token
from app.models.content import DataSource


# ---- env: scheme ----


def test_env_scheme_resolves_environment_variable(monkeypatch):
    monkeypatch.setenv("IW_TEST_TOKEN", "  secret-from-env  ")

    assert resolve_credential("env:IW_TEST_TOKEN") == "secret-from-env"


def test_env_scheme_missing_variable_returns_none_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("IW_TEST_MISSING_TOKEN", raising=False)

    with caplog.at_level(logging.WARNING, logger="app.core.credentials"):
        assert resolve_credential("env:IW_TEST_MISSING_TOKEN") is None
    assert "IW_TEST_MISSING_TOKEN" in caplog.text


# ---- file: scheme ----


def test_file_scheme_reads_first_line_stripped(tmp_path):
    secret_file = tmp_path / "token.txt"
    secret_file.write_text("  secret-from-file \n# second line is ignored\n", encoding="utf-8")

    assert resolve_credential(f"file:{secret_file}") == "secret-from-file"


def test_file_scheme_missing_file_returns_none_with_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.credentials"):
        assert resolve_credential(f"file:{tmp_path / 'absent.txt'}") is None
    assert "continuing without credential" in caplog.text


def test_file_scheme_rejects_relative_path(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.credentials"):
        assert resolve_credential("file:relative/token.txt") is None
    assert "absolute" in caplog.text


def test_file_scheme_empty_first_line_returns_none(tmp_path, caplog):
    secret_file = tmp_path / "empty.txt"
    secret_file.write_text("   \n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.core.credentials"):
        assert resolve_credential(f"file:{secret_file}") is None


# ---- 非法输入 ----


@pytest.mark.parametrize(
    "ref",
    ["vault://feed-secret", "no-scheme-token", "env:", "file:", "unknown:whatever"],
)
def test_malformed_or_unknown_scheme_returns_none_with_warning(ref, caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.credentials"):
        assert resolve_credential(ref) is None
    assert caplog.records, ref


def test_blank_ref_returns_none_without_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.credentials"):
        assert resolve_credential(None) is None
        assert resolve_credential("   ") is None
    assert not caplog.records


# ---- resolve_source_token：credential_ref → auth_token_env → auth_token ----


def make_source(credential_ref: str | None = None) -> DataSource:
    return DataSource(source_type="internal", name="内部源", credential_ref=credential_ref)


def test_source_token_prefers_credential_ref(monkeypatch):
    monkeypatch.setenv("IW_REF_TOKEN", "ref-token")
    monkeypatch.setenv("IW_ENV_TOKEN", "env-token")

    token = resolve_source_token(
        make_source("env:IW_REF_TOKEN"),
        {"auth_token_env": "IW_ENV_TOKEN", "auth_token": "inline-token"},
    )

    assert token == "ref-token"


def test_source_token_falls_back_to_auth_token_env_then_auth_token(monkeypatch):
    monkeypatch.delenv("IW_REF_TOKEN", raising=False)
    monkeypatch.setenv("IW_ENV_TOKEN", "env-token")

    # credential_ref 解析失败（env 未设置）→ auth_token_env
    token = resolve_source_token(
        make_source("env:IW_REF_TOKEN"),
        {"auth_token_env": "IW_ENV_TOKEN", "auth_token": "inline-token"},
    )
    assert token == "env-token"

    # auth_token_env 也为空 → auth_token
    monkeypatch.delenv("IW_ENV_TOKEN", raising=False)
    token = resolve_source_token(
        make_source("env:IW_REF_TOKEN"),
        {"auth_token_env": "IW_ENV_TOKEN", "auth_token": "inline-token"},
    )
    assert token == "inline-token"


def test_source_token_returns_empty_when_nothing_configured():
    assert resolve_source_token(make_source(), {}) == ""
