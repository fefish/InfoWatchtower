"""credential_ref 解析机制（契约：config/contracts/source_fields.json——
credential_ref 是唯一的凭据指针，密钥本体不进 Git、不进 fetch_config、不进同步 payload）。

支持两种 scheme：
- ``env:VAR_NAME``        —— 读取环境变量值；
- ``file:/absolute/path`` —— 读取文件首行（去首尾空白），适配 docker/k8s secret 挂载。

错误语义：非法 / 缺失一律返回 None 并记 WARNING，不抛异常——与 adapter 既有的
auth_token_env 缺失行为一致（按"无凭据"匿名继续请求；真正需要凭据的上游会以
401/403 让 run 层把该源记为失败）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def resolve_credential(ref: str | None) -> str | None:
    """解析 credential_ref；成功返回密钥文本，非法/缺失返回 None 并记 WARNING。"""
    text = str(ref or "").strip()
    if not text:
        return None
    scheme, sep, value = text.partition(":")
    scheme = scheme.strip().lower()
    value = value.strip()
    if not sep or not value:
        logger.warning(
            "credential_ref %r is malformed; expected env:VAR_NAME or file:/absolute/path; "
            "continuing without credential",
            text,
        )
        return None
    if scheme == "env":
        secret = os.environ.get(value, "").strip()
        if not secret:
            logger.warning(
                "credential_ref env:%s points to an unset or empty environment variable; "
                "continuing without credential",
                value,
            )
            return None
        return secret
    if scheme == "file":
        path = Path(value)
        if not path.is_absolute():
            logger.warning(
                "credential_ref %r must use an absolute file path; continuing without credential",
                text,
            )
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "credential_ref %r could not be read (%s); continuing without credential",
                text,
                exc,
            )
            return None
        lines = content.splitlines()
        secret = lines[0].strip() if lines else ""
        if not secret:
            logger.warning(
                "credential_ref %r resolved to an empty first line; continuing without credential",
                text,
            )
            return None
        return secret
    logger.warning(
        "credential_ref %r uses unknown scheme %r (supported: env, file); "
        "continuing without credential",
        text,
        scheme,
    )
    return None


def resolve_source_token(data_source: Any, config: dict[str, Any]) -> str:
    """按推荐顺序解析数据源级 Bearer token：

    1. data_sources.credential_ref（推荐：env:/file: 指针，密钥不落库不进同步 payload）；
    2. fetch_config.auth_token_env（过渡兼容：环境变量间接引用）；
    3. fetch_config.auth_token（过渡兼容：仅限本地/测试，密钥禁止写进 Git 与配置导出）。

    任一级解析为空则回退下一级；全部为空返回 ""，抓取按无凭据匿名请求继续。
    """
    ref = str(getattr(data_source, "credential_ref", "") or "").strip()
    if ref:
        secret = resolve_credential(ref)
        if secret:
            return secret
    env_name = str(config.get("auth_token_env") or "").strip()
    if env_name:
        token = os.environ.get(env_name, "").strip()
        if token:
            return token
    return str(config.get("auth_token") or "").strip()
