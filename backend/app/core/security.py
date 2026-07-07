from __future__ import annotations

import hmac
import ipaddress
from functools import lru_cache

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings

CSRF_COOKIE_NAME = "infowatchtower_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_EXEMPT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/password/forgot",
    "/api/auth/password/reset",
    "/api/setup",
    "/api/sync/feed",
    "/healthz",
)
CSRF_EXEMPT_EXPORT_CALLBACK_SUFFIX = "/import-receipts/callback"
# 邀请链接只豁免匿名 accept（受邀人尚无会话拿不到 CSRF cookie）；
# 同前缀下的 revoke 是 super_admin 会话鉴权写操作，必须走 double-submit 校验。
CSRF_EXEMPT_INVITE_PREFIX = "/api/auth/invites/"
CSRF_EXEMPT_INVITE_SUFFIX = "/accept"


@lru_cache(maxsize=16)
def trusted_proxy_networks(cidrs: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """解析 AUTH_TRUSTED_PROXY_CIDRS（逗号分隔），非法 CIDR 抛 ValueError（启动自检兜底）。"""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in cidrs.split(","):
        item = item.strip()
        if not item:
            continue
        networks.append(ipaddress.ip_network(item, strict=False))
    return tuple(networks)


def peer_in_trusted_proxies(client_host: str | None, settings: Settings) -> bool | None:
    """判定直连 peer 是否为受信代理（信任边界的单一判定点，身份头与限流取 IP 共用）。

    - 未配置 AUTH_TRUSTED_PROXY_CIDRS 时返回 None，调用方各自沿用兼容行为；
    - 配置后按 request.client.host 是否落在 CIDR 白名单内返回 True/False，
      解析失败（含非法 CIDR、非 IP peer）一律按不受信处理（fail-closed）。
    """
    cidrs = settings.auth_trusted_proxy_cidrs.strip()
    if not cidrs:
        return None
    try:
        networks = trusted_proxy_networks(cidrs)
    except ValueError:
        return False
    if not client_host:
        return False
    try:
        address = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    return any(address in network for network in networks)


class SecurityHeadersAndCsrfMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._should_check_csrf(request):
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
            header_token = request.headers.get(CSRF_HEADER_NAME, "")
            if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
                return self._csrf_rejected_response()

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = f"frame-ancestors {self.settings.embed_frame_ancestors}"
        return response

    def _should_check_csrf(self, request: Request) -> bool:
        if not self.settings.auth_csrf_effective:
            return False
        if request.method.upper() in SAFE_METHODS:
            return False
        path = request.url.path
        if path.startswith("/api/exports/") and path.endswith(CSRF_EXEMPT_EXPORT_CALLBACK_SUFFIX):
            return False
        if path.startswith(CSRF_EXEMPT_INVITE_PREFIX) and path.endswith(CSRF_EXEMPT_INVITE_SUFFIX):
            return False
        return not any(path.startswith(prefix) for prefix in CSRF_EXEMPT_PREFIXES)

    def _csrf_rejected_response(self) -> JSONResponse:
        response = JSONResponse(
            status_code=403,
            content={"detail": {"code": "csrf_failed"}},
        )
        response.headers["Content-Security-Policy"] = f"frame-ancestors {self.settings.embed_frame_ancestors}"
        return response
