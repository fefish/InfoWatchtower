"""落库凭据加密 at rest（generation-provider-design §9.3，WP4-B）。

- 算法：`cryptography` Fernet（AES128-CBC + HMAC-SHA256，自带时间戳与完整性校验）。
- 密钥派生：不新增 env。Fernet key = HKDF-SHA256(
  ikm=AUTH_SESSION_SECRET(utf-8)，salt="infowatchtower/llm-credentials/v1"，
  info="fernet-key"，length=32) 后 urlsafe-base64。salt/info 固定串保证该
  Fernet key 与 session 签名用途分离。
- 轮换：`AUTH_SESSION_SECRETS` 轮换列表（首个=当前签名 secret，
  Settings.auth_session_secret_list）逐个派生，组成 MultiFernet——加密永远用
  第一个，解密按序尝试全部；`decrypt` 返回 stale 标记，命中旧 key 的行由调用方
  用新 key 重加密（幂等）。
- 丢弃旧 secret（不走轮换列表）的行为定义：解密失败返回 None——调用方按
  「未配置 key」降级（key_source=credential_missing），不崩溃、不删行、
  不回落 env；审计 generation.credential.decrypt_failed（无明文）。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import Settings

CREDENTIALS_HKDF_SALT = b"infowatchtower/llm-credentials/v1"
CREDENTIALS_HKDF_INFO = b"fernet-key"


def derive_fernet_key(secret: str) -> bytes:
    """HKDF-SHA256 派生 32 字节并 urlsafe-base64（Fernet key 形态）。"""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=CREDENTIALS_HKDF_SALT,
        info=CREDENTIALS_HKDF_INFO,
    )
    return base64.urlsafe_b64encode(hkdf.derive(secret.encode("utf-8")))


@dataclass(frozen=True)
class DecryptedCredential:
    """解密结果：plaintext=None 即解密失败（credential_missing 语义）。

    stale=True 表示密文由轮换列表中的旧 secret 加密，调用方应立刻用当前
    secret 重加密回写（MultiFernet 轮换语义，幂等）。
    """

    plaintext: str | None
    stale: bool


class CredentialCipher:
    """MultiFernet 语义：加密用首个 secret 派生 key，解密按序尝试全部。"""

    def __init__(self, secrets: list[str]):
        self._fernets = [Fernet(derive_fernet_key(secret)) for secret in secrets if secret]

    @property
    def available(self) -> bool:
        return bool(self._fernets)

    def encrypt(self, plaintext: str) -> str:
        if not self._fernets:
            raise RuntimeError(
                "credential encryption requires AUTH_SESSION_SECRET "
                "(deploy checks refuse startup without it)",
            )
        return self._fernets[0].encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> DecryptedCredential:
        # 空串是合法密文位（ollama 等免 key 凭据允许空 key），直接回空明文。
        if token == "":
            return DecryptedCredential(plaintext="", stale=False)
        data = token.encode("ascii", errors="ignore")
        for index, fernet in enumerate(self._fernets):
            try:
                plaintext = fernet.decrypt(data).decode("utf-8")
            except InvalidToken:
                continue
            return DecryptedCredential(plaintext=plaintext, stale=index > 0)
        return DecryptedCredential(plaintext=None, stale=False)


@lru_cache(maxsize=8)
def _cipher_for_secrets(secrets: tuple[str, ...]) -> CredentialCipher:
    # HKDF 派生只做一次（同一轮换列表进程内复用）；派生密钥仅驻内存、不落盘。
    return CredentialCipher(list(secrets))


def credential_cipher(settings: Settings) -> CredentialCipher:
    """按当前 settings 的轮换列表构造 cipher（首个签名 secret 加密，全部解密）。"""
    return _cipher_for_secrets(tuple(settings.auth_session_secret_list))
