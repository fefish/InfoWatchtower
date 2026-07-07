from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from app.auth.service import ExternalIdentity
from app.core.config import Settings

# JWS RS* 系列到摘要算法的映射；对称 HS* 与 none 一律拒绝（IdP 公钥验签场景）
_JWS_DIGEST_BY_ALG = {"RS256": "sha256", "RS384": "sha384", "RS512": "sha512"}
# EMSA-PKCS1-v1_5 的 DigestInfo DER 前缀（RFC 8017 §9.2）
_PKCS1_DIGEST_INFO = {
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha384": bytes.fromhex("3041300d060960864801650304020205000430"),
    "sha512": bytes.fromhex("3051300d060960864801650304020305000440"),
}


class OidcIdentity(Protocol):
    provider: str
    external_id: str
    username: str
    display_name: str
    email: str | None
    department: str | None


class OidcAdapter(Protocol):
    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Return the provider authorization URL."""

    def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        """Exchange an authorization code for a provider access token."""

    def identity(self, *, access_token: str) -> OidcIdentity:
        """Resolve the provider identity into local user fields."""


@dataclass(frozen=True)
class OidcMetadata:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str = ""


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def authorize_url(
    settings: Settings,
    *,
    state: str,
    nonce: str,
    code_verifier: str,
    redirect_uri: str,
) -> str:
    metadata = oidc_metadata(settings)
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{metadata.authorization_endpoint}?{urlencode(params)}"


def exchange_code(
    settings: Settings,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    metadata = oidc_metadata(settings)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": code_verifier,
    }
    if settings.oidc_client_secret:
        payload["client_secret"] = settings.oidc_client_secret
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        response = client.post(metadata.token_endpoint, data=payload)
        response.raise_for_status()
        tokens = response.json()
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise ValueError("OIDC token response did not include access_token")
    return tokens


def resolve_identity(
    settings: Settings,
    *,
    tokens: dict[str, Any],
    expected_nonce: str,
) -> ExternalIdentity:
    # id_token 一旦返回就必须整体校验（配置了 JWKS 则验签，否则强校验 iss/aud/exp/nonce），
    # 校验失败直接拒绝登录，不允许静默降级。
    id_token = str(tokens.get("id_token") or "")
    id_claims: dict[str, Any] = {}
    if id_token:
        id_claims = verify_id_token(settings, id_token=id_token, expected_nonce=expected_nonce)
    # userinfo 由后端带 access_token 直连 userinfo endpoint（TLS、不经浏览器中转），
    # access_token 又来自服务端直连 token endpoint 的 code+PKCE 交换，通道本身可信；
    # 标准 userinfo 响应不含 nonce claim，重放防护由上面的 id_token nonce 校验与 PKCE 承担，
    # 因此 userinfo 路径不做 nonce 比对。
    claims = _userinfo(settings, str(tokens["access_token"]))
    if not claims:
        claims = id_claims
    if not claims:
        raise ValueError("OIDC provider did not return user claims")
    # 防御性检查：个别 IdP 会把 nonce 透传进 userinfo claims，出现即比对
    if claims.get("nonce") and claims["nonce"] != expected_nonce:
        raise ValueError("OIDC nonce mismatch")

    external_id = _claim_str(claims, settings.oidc_claim_external_id)
    if not external_id:
        raise ValueError(f"OIDC claims missing configured external id claim: {settings.oidc_claim_external_id}")
    email = _claim_str(claims, settings.oidc_claim_email)
    employee_no = _claim_str(claims, settings.oidc_claim_employee_no)
    username = _claim_str(claims, settings.oidc_claim_username) or email or employee_no or external_id
    display_name = (
        _claim_str(claims, settings.oidc_claim_display_name)
        or _optional_str(claims.get("display_name"))
        or username
    )
    department = (
        _claim_str(claims, settings.oidc_claim_department)
        or _optional_str(claims.get("dept"))
        or _optional_str(claims.get("organization"))
    )
    provider = settings.oidc_provider.strip() or settings.oidc_issuer.strip() or "oidc"
    return ExternalIdentity(
        provider=provider,
        external_id=external_id,
        employee_no=employee_no,
        username=username,
        display_name=display_name,
        department=department,
        email=email,
    )


def oidc_metadata(settings: Settings) -> OidcMetadata:
    if settings.oidc_authorization_endpoint and settings.oidc_token_endpoint:
        return OidcMetadata(
            authorization_endpoint=settings.oidc_authorization_endpoint,
            token_endpoint=settings.oidc_token_endpoint,
            userinfo_endpoint=settings.oidc_userinfo_endpoint,
            jwks_uri=settings.oidc_jwks_uri,
        )
    if not settings.oidc_issuer:
        raise ValueError("OIDC_ISSUER or explicit OIDC endpoints are required")
    issuer = settings.oidc_issuer.rstrip("/")
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        response = client.get(f"{issuer}/.well-known/openid-configuration")
        response.raise_for_status()
        metadata = response.json()
    authorization_endpoint = str(metadata.get("authorization_endpoint") or "")
    token_endpoint = str(metadata.get("token_endpoint") or "")
    if not authorization_endpoint or not token_endpoint:
        raise ValueError("OIDC discovery metadata missing authorization/token endpoints")
    return OidcMetadata(
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        userinfo_endpoint=str(metadata.get("userinfo_endpoint") or ""),
        jwks_uri=settings.oidc_jwks_uri or str(metadata.get("jwks_uri") or ""),
    )


def _userinfo(settings: Settings, access_token: str) -> dict[str, Any]:
    endpoint = oidc_metadata(settings).userinfo_endpoint
    if not endpoint:
        return {}
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        response = client.get(endpoint, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, dict) else {}


def verify_id_token(
    settings: Settings,
    *,
    id_token: str,
    expected_nonce: str,
) -> dict[str, Any]:
    """校验 id_token 并返回其 claims；任何一步失败抛 ValueError。

    配置了 JWKS（OIDC_JWKS_URI 或 issuer discovery 的 jwks_uri）时先做 RS256/384/512 验签；
    没有 JWKS 时退化为强校验 claims（alg=none 拒绝 + iss/aud/exp/nonce 全查）。
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError("OIDC id_token is not a valid JWS")
    header = _decode_jwt_segment(parts[0])
    alg = str(header.get("alg") or "")
    if alg.lower() in {"", "none"}:
        raise ValueError("OIDC id_token with alg=none is rejected")
    claims = _decode_jwt_segment(parts[1])
    if not claims:
        raise ValueError("OIDC id_token payload is invalid")

    jwks_uri = settings.oidc_jwks_uri or oidc_metadata(settings).jwks_uri
    if jwks_uri:
        digest = _JWS_DIGEST_BY_ALG.get(alg)
        if digest is None:
            raise ValueError(f"OIDC id_token alg={alg} is not supported for JWKS verification")
        jwk = _match_jwk(_fetch_jwks(jwks_uri), header.get("kid"))
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        try:
            signature = _b64decode_segment(parts[2])
        except ValueError as exc:
            raise ValueError("OIDC id_token signature is not valid base64url") from exc
        if not _rsa_pkcs1_verify(jwk, signing_input, signature, digest):
            raise ValueError("OIDC id_token signature verification failed")

    _validate_id_token_claims(settings, claims, expected_nonce)
    return claims


def _validate_id_token_claims(
    settings: Settings,
    claims: dict[str, Any],
    expected_nonce: str,
) -> None:
    issuer = settings.oidc_issuer.strip().rstrip("/")
    if issuer:
        if str(claims.get("iss") or "").rstrip("/") != issuer:
            raise ValueError("OIDC id_token iss mismatch")
    aud = claims.get("aud")
    audiences = [aud] if isinstance(aud, str) else list(aud or [])
    if settings.oidc_client_id not in audiences:
        raise ValueError("OIDC id_token aud mismatch")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp <= time.time():
        raise ValueError("OIDC id_token is expired or missing exp")
    # 授权请求总是带 nonce（routes/auth.py oidc_start），id_token 必须原样带回
    if not expected_nonce or claims.get("nonce") != expected_nonce:
        raise ValueError("OIDC nonce mismatch")


def _fetch_jwks(jwks_uri: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        response = client.get(jwks_uri)
        response.raise_for_status()
        payload = response.json()
    keys = payload.get("keys") if isinstance(payload, dict) else None
    if not isinstance(keys, list):
        raise ValueError("OIDC JWKS response is missing keys")
    return [key for key in keys if isinstance(key, dict)]


def _match_jwk(keys: list[dict[str, Any]], kid: Any) -> dict[str, Any]:
    rsa_keys = [key for key in keys if key.get("kty") == "RSA"]
    if kid:
        for key in rsa_keys:
            if key.get("kid") == kid:
                return key
        raise ValueError("OIDC JWKS has no RSA key matching the id_token kid")
    if len(rsa_keys) == 1:
        return rsa_keys[0]
    raise ValueError("OIDC id_token header is missing kid and JWKS is ambiguous")


def _rsa_pkcs1_verify(
    jwk: dict[str, Any],
    message: bytes,
    signature: bytes,
    digest: str,
) -> bool:
    """RSASSA-PKCS1-v1_5 验签（RFC 8017 §8.2.2），只依赖标准库。"""
    try:
        modulus = int.from_bytes(_b64decode_segment(str(jwk.get("n") or "")), "big")
        exponent = int.from_bytes(_b64decode_segment(str(jwk.get("e") or "")), "big")
    except ValueError:
        return False
    if modulus <= 0 or exponent <= 0:
        return False
    key_len = (modulus.bit_length() + 7) // 8
    if len(signature) != key_len:
        return False
    encoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(key_len, "big")
    digest_info = _PKCS1_DIGEST_INFO[digest] + hashlib.new(digest, message).digest()
    padding_len = key_len - len(digest_info) - 3
    if padding_len < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding_len + b"\x00" + digest_info
    return hmac.compare_digest(encoded, expected)


def _b64decode_segment(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _decode_jwt_segment(segment: str) -> dict[str, Any]:
    try:
        payload = json.loads(_b64decode_segment(segment))
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _claim_str(claims: dict[str, Any], claim_name: str) -> str | None:
    claim_name = claim_name.strip()
    if not claim_name:
        return None
    value: Any = claims
    for part in claim_name.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return _optional_str(value)
