from __future__ import annotations

import hmac
from hashlib import sha256
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode, unquote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.guest import (
    GUEST_ALLOWED_WRITE_PATHS,
    GUEST_READ_ONLY_DETAIL,
    ensure_guest_user,
    is_guest_user,
)
from app.auth.oidc import (
    authorize_url as oidc_authorize_url,
    exchange_code as oidc_exchange_code,
    resolve_identity as resolve_oidc_identity,
)
from app.auth.passwords import hash_password, verify_password
from app.auth.service import (
    ExternalIdentity,
    accept_user_invite,
    authenticate_password_user,
    create_user_invite,
    find_user_with_roles,
    generate_temporary_password,
    hash_token,
    invite_status,
    invite_to_read,
    login_failure_count,
    mark_login,
    record_login_attempt,
    resolve_header_identity,
    role_to_read,
    set_user_roles,
    user_to_read,
    write_audit,
)
from app.auth.sessions import create_session_token, verify_session_token
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.security import CSRF_COOKIE_NAME, SAFE_METHODS, peer_in_trusted_proxies
from app.models.identity import PasswordResetToken, Role, User, UserInvite
from app.models.feedback import AuditLog
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.auth import (
    AdminResetPasswordRead,
    AuthResponse,
    InviteAcceptRequest,
    InviteCreateRequest,
    InvitePublicRead,
    InviteRead,
    LoginRequest,
    PasswordChangeRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    PermissionChangeDiffRead,
    PermissionChangeRead,
    PermissionRollbackRead,
    PermissionRollbackRequest,
    PermissionRollbackResultItem,
    RoleRead,
    UpdateUserRolesRequest,
    UserPatchRequest,
    UserRead,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api", tags=["identity"])
ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
OIDC_STATE_COOKIE = "infowatchtower_oidc_state"
OIDC_VERIFIER_COOKIE = "infowatchtower_oidc_verifier"
OIDC_NONCE_COOKIE = "infowatchtower_oidc_nonce"
OIDC_NEXT_COOKIE = "infowatchtower_oidc_next"
OIDC_COOKIE_PATH = "/api/auth/oidc"
OIDC_LOGIN_ERROR_CODES = {
    "identity_resolution_failed",
    "membership_mapping_failed",
    "oidc_not_configured",
    "provider_error",
    "state_mismatch",
    "state_missing",
    "token_exchange_failed",
}
MUST_CHANGE_ALLOWED_PATHS = {
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/password/change",
}
PERMISSION_CHANGE_ACTIONS = {
    "users.roles.update",
    "workspace.member.upsert",
    "workspace.member.remove",
    "workspace.feedback_policy.update",
    "workspace.auth_membership_mapping.update",
}
FEEDBACK_POLICY_LABELS = {
    "viewer_can_react": "viewer 点赞",
    "viewer_can_rate": "viewer 评分",
    "viewer_can_comment": "viewer 评论",
    "viewer_can_edit": "viewer 编辑",
    "notify_on_comment": "评论通知",
    "notify_on_publish": "发布通知",
}


def _cookie_kwargs(settings: Settings) -> dict:
    secure = settings.auth_session_cookie_secure
    if secure is None:
        secure = settings.app_env == "production"
    return {
        "key": settings.auth_session_cookie,
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
    }


def _set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    token = create_session_token(
        user.id,
        settings.auth_session_secret,
        settings.auth_session_ttl_seconds,
        _session_version(user),
    )
    response.set_cookie(
        value=token,
        max_age=settings.auth_session_ttl_seconds,
        **_cookie_kwargs(settings),
    )
    _set_csrf_cookie(response, settings)


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(**_cookie_kwargs(settings))
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        samesite="lax",
        secure=_cookie_kwargs(settings)["secure"],
        path="/",
    )


def _set_csrf_cookie(response: Response, settings: Settings) -> None:
    if not settings.auth_csrf_effective:
        return
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=secrets.token_urlsafe(24),
        max_age=settings.auth_session_ttl_seconds,
        httponly=False,
        samesite="lax",
        secure=_cookie_kwargs(settings)["secure"],
        path="/",
    )


def _set_oidc_cookie(response: Response, settings: Settings, *, key: str, value: str) -> None:
    secure = _cookie_kwargs(settings)["secure"]
    response.set_cookie(
        key=key,
        value=value,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=secure,
        path=OIDC_COOKIE_PATH,
    )


def _clear_oidc_cookies(response: Response, settings: Settings) -> None:
    secure = _cookie_kwargs(settings)["secure"]
    for key in (OIDC_STATE_COOKIE, OIDC_VERIFIER_COOKIE, OIDC_NONCE_COOKIE, OIDC_NEXT_COOKIE):
        response.delete_cookie(key=key, samesite="lax", secure=secure, path=OIDC_COOKIE_PATH)


def _require_auth_ready(settings: Settings) -> None:
    if not settings.auth_session_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SESSION_SECRET is required",
        )
    if settings.app_env == "production" and settings.auth_session_secret.startswith("change_me"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SESSION_SECRET must be changed in production",
        )


def _require_oidc_ready(settings: Settings) -> None:
    _require_auth_ready(settings)
    if settings.auth_mode != "oidc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OIDC login is disabled for AUTH_MODE={settings.auth_mode}",
        )
    if not settings.oidc_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC_CLIENT_ID is required",
        )
    if not (
        settings.oidc_issuer
        or (settings.oidc_authorization_endpoint and settings.oidc_token_endpoint)
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC_ISSUER or explicit OIDC endpoints are required",
        )


def _header_identity(request: Request, settings: Settings) -> ExternalIdentity | None:
    # 信任边界：配置了 AUTH_TRUSTED_PROXY_CIDRS 时，身份头只信任来自受信网关
    # 直连 peer 的请求，伪造来源一律按未登录处理；未配置时沿用旧行为
    # （部署层保证网关是唯一入口，启动自检会打 warning）。
    peer_host = request.client.host if request.client else None
    if peer_in_trusted_proxies(peer_host, settings) is False:
        return None
    employee_no = request.headers.get(settings.auth_header_employee_no)
    display_name = request.headers.get(settings.auth_header_display_name)
    if not employee_no or not display_name:
        return None
    employee_no = unquote(employee_no)
    display_name = unquote(display_name)
    return ExternalIdentity(
        provider="intranet_header",
        external_id=employee_no,
        employee_no=employee_no,
        username=employee_no,
        display_name=display_name,
        department=unquote(request.headers.get(settings.auth_header_department, "")) or None,
        email=unquote(request.headers.get(settings.auth_header_email, "")) or None,
    )


def _client_ip(request: Request, settings: Settings) -> str:
    # 限流取 IP 与身份头共用同一信任判定：只有直连 peer 落在
    # AUTH_TRUSTED_PROXY_CIDRS 内才采信 X-Forwarded-For 第一跳，
    # 否则一律用直连 peer IP，防止轮换伪造头绕过登录限流。
    peer_host = (request.client.host if request.client else "") or "unknown"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for and peer_in_trusted_proxies(peer_host, settings) is True:
        return forwarded_for.split(",", 1)[0].strip()[:64] or "unknown"
    return peer_host[:64]


def _session_version(user: User) -> str:
    # 会话版本必须绑定凭据生命周期，而不是 updated_at：改密/管理员重置（password_hash
    # 变化）才吊销既有会话。绑 updated_at 时每次登录写 last_login_at 都会顶掉版本号，
    # 造成"任意一端登录、其他端全部掉线"的多端互踢。外部身份（无本地密码）用创建时间，
    # 其凭据吊销由外部 IdP 负责，本地会话仍受 exp 与 is_active 约束。
    if user.password_hash:
        return sha256(user.password_hash.encode("utf-8")).hexdigest()[:16]
    value = user.created_at or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _is_super_admin(user: User) -> bool:
    return "super_admin" in {role.code for role in user.roles}


def _oidc_redirect_uri(request: Request, settings: Settings) -> str:
    return settings.oidc_redirect_url or str(request.url_for("oidc_callback"))


def _oidc_post_login_url(settings: Settings, next_path: str | None = None) -> str:
    safe_next = _safe_relative_redirect(next_path)
    if safe_next:
        return safe_next
    return settings.oidc_post_login_redirect_url or settings.app_base_url or "/"


def _oidc_login_error_url(error_code: str) -> str:
    code = error_code if error_code in OIDC_LOGIN_ERROR_CODES else "provider_error"
    return f"/login?{urlencode({'auth_error': code})}"


def _oidc_error_redirect(settings: Settings, error_code: str) -> RedirectResponse:
    response = RedirectResponse(
        _oidc_login_error_url(error_code),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    _clear_oidc_cookies(response, settings)
    return response


def _safe_relative_redirect(value: str | None) -> str:
    if not value:
        return ""
    value = unquote(value).strip()
    # 浏览器会把 URL 中的反斜杠规范化成斜杠，"/\evil.com" 等价于 //evil.com 协议相对跳转，
    # 所以除 //、CRLF 外还要整体拒绝含反斜杠的值。
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or "\r" in value
        or "\n" in value
    ):
        return ""
    return value


def get_current_user(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    _require_auth_ready(settings)
    token = request.cookies.get(settings.auth_session_cookie)
    # 轮换语义：AUTH_SESSION_SECRETS 全列表可验签（第一个签名），换密钥不掉线
    payload = verify_session_token(token, settings.auth_session_secret_list)
    if payload:
        user = find_user_with_roles(session, payload["sub"])
        if user and user.is_active and user.status in {"active", "must_change_password"}:
            if payload.get("sv") and payload.get("sv") != _session_version(user):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
            _assert_guest_request_allowed(request, user, settings)
            if user.status == "must_change_password" and request.url.path not in MUST_CHANGE_ALLOWED_PATHS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="must_change_password",
                )
            return user

    if settings.auth_mode == "intranet_header":
        identity = _header_identity(request, settings)
        if identity is not None:
            try:
                user = resolve_header_identity(
                    session,
                    identity,
                    settings.auth_default_role,
                    settings.auth_auto_provision,
                    settings.auth_default_workspace_codes,
                    settings.auth_department_workspace_map,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
            if user is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
            mark_login(session, user, "auth.intranet_header")
            session.commit()
            session.refresh(user)
            user = find_user_with_roles(session, user.id)
            if user is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
            _set_session_cookie(response, user, settings)
            return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def _assert_guest_request_allowed(request: Request, user: User, settings: Settings) -> None:
    """游客写门禁的唯一集中点（语义见 app/auth/guest.py）。

    - 开关关闭后存量 guest 会话立即按未登录处理（401）；
    - 游客只放行安全方法与 /api/auth/logout，其余写操作一律 403，
      文案提示注册后可用（评论/点赞/订阅等无需再各自判断）。
    """
    if not is_guest_user(user):
        return
    if not settings.auth_guest_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if request.method.upper() in SAFE_METHODS:
        return
    if request.url.path in GUEST_ALLOWED_WRITE_PATHS:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=GUEST_READ_ONLY_DETAIL)


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if not _is_super_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires super_admin")
    return current_user


def require_capability(name: str):
    """能力开关 API 门（契约 capability_flags.*.gates.api），叠加在既有权限检查之外。

    用法：dependencies=[Depends(require_capability("ingestion"))]。
    """

    def _check_capability(settings: Settings = Depends(get_settings)) -> None:
        if not getattr(settings, f"capability_{name}"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "capability_disabled", "capability": name},
            )

    return _check_capability


def require_sync_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sync token")
    for candidate in settings.sync_service_token_list:
        if hmac.compare_digest(candidate, token):
            return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sync token")


def assert_workspace_member(
    session: Session,
    user: User,
    workspace_code: str,
    *,
    min_role: str = "viewer",
) -> None:
    if _is_super_admin(user):
        return
    workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code, Workspace.enabled.is_(True)))
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if is_guest_user(user):
        # 游客隐式 viewer 视角：不建 membership，仅可只读浏览 internal_public
        # 工作台（写操作已在 get_current_user 的集中门禁被 403 拦截）。
        if workspace.visibility == "internal_public" and ROLE_RANK["viewer"] >= ROLE_RANK[min_role]:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a workspace member")
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a workspace member")
    if ROLE_RANK.get(membership.workspace_role, -1) < ROLE_RANK[min_role]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient workspace role")


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    _require_auth_ready(settings)
    if settings.auth_mode == "oidc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /api/auth/oidc/start for AUTH_MODE=oidc",
        )
    if settings.auth_mode not in {"local", "public_password"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Login endpoint is disabled for AUTH_MODE={settings.auth_mode}",
        )

    ip = _client_ip(request, settings)
    if login_failure_count(session, payload.username, ip) >= 5:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts")

    user = authenticate_password_user(session, payload.username, payload.password)
    if user is None:
        record_login_attempt(session, payload.username, ip, success=False)
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    record_login_attempt(session, payload.username, ip, success=True)
    mark_login(session, user, "auth.login")
    session.commit()
    user = find_user_with_roles(session, user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    _set_session_cookie(response, user, settings)
    return AuthResponse(user=user_to_read(user))


@router.post("/guest-login", response_model=AuthResponse)
def guest_login(
    response: Response,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    """游客登录：签发共享只读 guest 会话（完整语义见 app/auth/guest.py）。

    - 仅 AUTH_GUEST_ENABLED=true 时可用（deploy_checks 限 standalone/cloud 可开）；
    - 首次调用自动创建共享 guest 本地用户（viewer 全局角色、无密码不可改密）；
    - 不写任何 workspace membership：游客按隐式 viewer 视角浏览 internal_public
      工作台的已发布内容，一切写操作 403 提示注册后可用。
    """
    _require_auth_ready(settings)
    if not settings.auth_guest_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guest login is disabled")
    try:
        user = ensure_guest_user(session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    mark_login(session, user, "auth.guest_login")
    session.commit()
    user = find_user_with_roles(session, user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    _set_session_cookie(response, user, settings)
    return AuthResponse(user=user_to_read(user))


@router.get("/oidc/start")
def oidc_start(
    request: Request,
    next_path: str | None = Query(default=None, alias="next"),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    try:
        _require_oidc_ready(settings)
    except HTTPException:
        return _oidc_error_redirect(settings, "oidc_not_configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    try:
        target = oidc_authorize_url(
            settings,
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=_oidc_redirect_uri(request, settings),
        )
    except (httpx.HTTPError, ValueError):
        return _oidc_error_redirect(settings, "oidc_not_configured")
    response = RedirectResponse(target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _set_oidc_cookie(response, settings, key=OIDC_STATE_COOKIE, value=state)
    _set_oidc_cookie(response, settings, key=OIDC_VERIFIER_COOKIE, value=code_verifier)
    _set_oidc_cookie(response, settings, key=OIDC_NONCE_COOKIE, value=nonce)
    safe_next = _safe_relative_redirect(next_path)
    if safe_next:
        _set_oidc_cookie(response, settings, key=OIDC_NEXT_COOKIE, value=safe_next)
    return response


@router.get("/oidc/callback", name="oidc_callback")
def oidc_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    try:
        _require_oidc_ready(settings)
    except HTTPException:
        return _oidc_error_redirect(settings, "oidc_not_configured")
    if error:
        return _oidc_error_redirect(settings, "provider_error")
    expected_state = request.cookies.get(OIDC_STATE_COOKIE)
    code_verifier = request.cookies.get(OIDC_VERIFIER_COOKIE)
    nonce = request.cookies.get(OIDC_NONCE_COOKIE)
    next_path = request.cookies.get(OIDC_NEXT_COOKIE)
    if not code or not state or not expected_state or not code_verifier or not nonce:
        return _oidc_error_redirect(settings, "state_missing")
    if not hmac.compare_digest(state, expected_state):
        return _oidc_error_redirect(settings, "state_mismatch")

    try:
        tokens = oidc_exchange_code(
            settings,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=_oidc_redirect_uri(request, settings),
        )
    except (httpx.HTTPError, ValueError):
        return _oidc_error_redirect(settings, "token_exchange_failed")

    try:
        identity = resolve_oidc_identity(settings, tokens=tokens, expected_nonce=nonce)
    except (httpx.HTTPError, ValueError):
        return _oidc_error_redirect(settings, "identity_resolution_failed")

    try:
        user = resolve_header_identity(
            session,
            identity,
            settings.auth_default_role,
            settings.auth_auto_provision,
            settings.auth_default_workspace_codes,
            settings.auth_department_workspace_map,
        )
    except ValueError:
        return _oidc_error_redirect(settings, "membership_mapping_failed")
    if user is None:
        return _oidc_error_redirect(settings, "identity_resolution_failed")
    mark_login(session, user, "auth.oidc")
    session.commit()
    user = find_user_with_roles(session, user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    response = RedirectResponse(_oidc_post_login_url(settings, next_path), status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _set_session_cookie(response, user, settings)
    _clear_oidc_cookies(response, settings)
    return response


@router.post("/invites", response_model=InviteRead)
def create_invite(
    payload: InviteCreateRequest,
    request: Request,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> InviteRead:
    try:
        invite = create_user_invite(
            session,
            email=payload.email,
            role_code=payload.role_code,
            workspaces=payload.workspaces,
            invited_by=current_user,
            expires_in_days=payload.expires_in_days,
            app_base_url=settings.app_base_url or str(request.base_url).rstrip("/"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    write_audit(session, current_user, "invite.create", "user_invite", invite.id, invite.model_dump(mode="json"))
    session.commit()
    return invite


@router.get("/invites", response_model=list[InviteRead])
def list_invites(
    request: Request,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[InviteRead]:
    app_base_url = settings.app_base_url or str(request.base_url).rstrip("/")
    invites = session.scalars(select(UserInvite).order_by(UserInvite.created_at.desc())).all()
    return [invite_to_read(invite, app_base_url) for invite in invites]


@router.get("/invites/{code}", response_model=InvitePublicRead)
def get_invite(
    code: str,
    session: Session = Depends(get_db_session),
) -> InvitePublicRead:
    invite = _load_invite(session, code)
    return InvitePublicRead(
        code=invite.code,
        email_hint=_email_hint(invite.email),
        role_code=invite.role_code,
        workspaces=invite_to_read(invite, "").workspaces,
        status=invite_status(invite),
        expires_at=invite.expires_at,
    )


@router.post("/invites/{code}/accept", response_model=AuthResponse)
def accept_invite(
    code: str,
    payload: InviteAcceptRequest,
    response: Response,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    invite = _load_invite(session, code)
    try:
        user = accept_user_invite(
            session,
            invite=invite,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
        )
    except RuntimeError as exc:
        if str(exc) == "username_conflict":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=f"Invite is {exc}") from exc
    write_audit(session, user, "invite.accept", "user_invite", invite.id, {"username": user.username})
    session.commit()
    user = find_user_with_roles(session, user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User not found after invite")
    _set_session_cookie(response, user, settings)
    return AuthResponse(user=user_to_read(user))


@router.post("/invites/{code}/revoke", response_model=InviteRead)
def revoke_invite(
    code: str,
    request: Request,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> InviteRead:
    invite = _load_invite(session, code)
    if invite.accepted_at is None:
        invite.revoked_at = datetime.now(timezone.utc)
    write_audit(session, current_user, "invite.revoke", "user_invite", invite.id, {"code": code})
    session.commit()
    return invite_to_read(invite, settings.app_base_url or str(request.base_url).rstrip("/"))


@router.post("/password/change", response_model=AuthResponse)
def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    if current_user.external_provider != "local":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is managed externally")
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid current password")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.status = "active"
    write_audit(session, current_user, "password.change", "user", current_user.id, {})
    session.commit()
    current_user = find_user_with_roles(session, current_user.id)
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    _set_session_cookie(response, current_user, settings)
    return AuthResponse(user=user_to_read(current_user))


@router.post("/password/forgot")
def forgot_password(
    payload: PasswordForgotRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    user = session.scalar(select(User).where(User.username == payload.username, User.is_active.is_(True)))
    if user is not None:
        write_audit(
            session,
            user,
            "password.forgot",
            "user",
            user.id,
            {"delivery": "admin_reset_required"},
        )
        session.commit()
    return {"status": "ok"}


@router.post("/password/reset")
def reset_password(
    payload: PasswordResetRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    token = session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(payload.token),
            PasswordResetToken.used_at.is_(None),
        ),
    )
    if token is None or _as_utc(token.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Reset token expired")
    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Reset token expired")
    user.password_hash = hash_password(payload.new_password)
    user.status = "active"
    token.used_at = datetime.now(timezone.utc)
    write_audit(session, user, "password.reset", "user", user.id, {})
    session.commit()
    return {"status": "ok"}


@router.post("/logout")
def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    write_audit(
        session,
        current_user,
        "auth.logout",
        "user",
        current_user.id,
        {"display_name_snapshot": current_user.display_name},
    )
    session.commit()
    _clear_session_cookie(response, settings)
    return {"status": "ok"}


@router.get("/me", response_model=AuthResponse)
def me(
    response: Response,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    _set_csrf_cookie(response, settings)
    return AuthResponse(user=user_to_read(current_user))


@admin_router.get("/users", response_model=list[UserRead])
def list_users(
    workspace_code: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[UserRead]:
    if workspace_code:
        assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    elif not _is_super_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires super_admin")
    users = session.scalars(select(User).options(selectinload(User.roles)).order_by(User.created_at)).all()
    return [user_to_read(user) for user in users]


@admin_router.get("/roles", response_model=list[RoleRead])
def list_roles(
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> list[RoleRead]:
    roles = session.scalars(select(Role).order_by(Role.code)).all()
    return [role_to_read(role) for role in roles]


@admin_router.patch("/users/{user_id}/roles", response_model=UserRead)
def update_user_roles(
    user_id: str,
    payload: UpdateUserRolesRequest,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> UserRead:
    target_user = find_user_with_roles(session, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    before = sorted(role.code for role in target_user.roles)
    try:
        set_user_roles(session, target_user, payload.role_codes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    write_audit(
        session,
        current_user,
        "users.roles.update",
        "user",
        target_user.id,
        {"before_roles": before, "after_roles": sorted(payload.role_codes)},
    )
    session.commit()
    target_user = find_user_with_roles(session, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user_to_read(target_user)


@admin_router.get("/identity/permission-changes", response_model=list[PermissionChangeRead])
def list_permission_changes(
    workspace_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> list[PermissionChangeRead]:
    logs = session.scalars(
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .where(AuditLog.action.in_(PERMISSION_CHANGE_ACTIONS))
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit * 5, 300)),
    ).all()
    changes: list[PermissionChangeRead] = []
    for log in logs:
        change = _permission_change_to_read(log)
        if workspace_code and change.scope not in {workspace_code, "global"}:
            continue
        changes.append(change)
        if len(changes) >= limit:
            break
    return changes


@admin_router.post("/identity/permission-rollbacks", response_model=PermissionRollbackRead)
def rollback_permission_changes(
    payload: PermissionRollbackRequest,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> PermissionRollbackRead:
    logs = session.scalars(
        select(AuditLog).where(AuditLog.id.in_(payload.audit_log_ids)),
    ).all()
    logs_by_id = {log.id: log for log in logs}
    results: list[PermissionRollbackResultItem] = []
    for audit_log_id in payload.audit_log_ids:
        log = logs_by_id.get(audit_log_id)
        if log is None:
            results.append(
                PermissionRollbackResultItem(
                    audit_log_id=audit_log_id,
                    status="skipped",
                    message="权限变更记录不存在",
                ),
            )
            continue
        if log.action not in PERMISSION_CHANGE_ACTIONS:
            results.append(
                PermissionRollbackResultItem(
                    audit_log_id=audit_log_id,
                    status="skipped",
                    message="该审计动作不支持权限回滚",
                ),
            )
            continue
        status_text, message = _rollback_permission_change(
            session,
            current_user=current_user,
            log=log,
            confirm_dangerous_change=payload.confirm_dangerous_change,
        )
        results.append(
            PermissionRollbackResultItem(
                audit_log_id=audit_log_id,
                status=status_text,
                message=message,
            ),
        )
    session.commit()
    return PermissionRollbackRead(results=results)


@admin_router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    user_id: str,
    payload: UserPatchRequest,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> UserRead:
    target_user = find_user_with_roles(session, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    changes: dict[str, object] = {}
    if payload.is_active is not None:
        target_user.is_active = payload.is_active
        changes["is_active"] = payload.is_active
    if payload.display_name is not None:
        target_user.display_name = payload.display_name
        changes["display_name"] = payload.display_name
    if payload.department is not None:
        target_user.department = payload.department or None
        changes["department"] = target_user.department
    if payload.email is not None:
        target_user.email = payload.email or None
        changes["email"] = target_user.email
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user fields provided")

    write_audit(session, current_user, "users.patch", "user", target_user.id, changes)
    session.commit()
    target_user = find_user_with_roles(session, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user_to_read(target_user)


@admin_router.post("/users/{user_id}/reset-password", response_model=AdminResetPasswordRead)
def admin_reset_password(
    user_id: str,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> AdminResetPasswordRead:
    target_user = find_user_with_roles(session, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target_user.external_provider != "local":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is managed externally")

    temporary_password = generate_temporary_password()
    target_user.password_hash = hash_password(temporary_password)
    target_user.status = "must_change_password"
    write_audit(session, current_user, "password.admin_reset", "user", target_user.id, {})
    session.commit()
    return AdminResetPasswordRead(temporary_password=temporary_password)


def _permission_change_to_read(log: AuditLog) -> PermissionChangeRead:
    detail = dict(log.detail_json or {})
    rollback_available = _permission_change_has_rollback_snapshot(log.action, detail)
    rollback_reason = None if rollback_available else "旧审计缺少可恢复的 before/after 快照"
    diffs = _permission_change_diffs(log.action, detail)
    title = _permission_change_title(log.action)
    scope = _permission_change_scope(log.action, detail)
    summary = _permission_change_summary(log.action, detail)
    return PermissionChangeRead(
        id=log.id,
        action=log.action,
        object_type=log.object_type,
        object_id=log.object_id,
        actor_name=log.user.display_name if log.user else None,
        created_at=log.created_at,
        scope=scope,
        title=title,
        summary=summary,
        rollback_available=rollback_available,
        rollback_reason=rollback_reason,
        diffs=diffs,
    )


def _permission_change_has_rollback_snapshot(action: str, detail: dict) -> bool:
    if action == "users.roles.update":
        return "before_roles" in detail and "after_roles" in detail
    if action in {"workspace.member.upsert", "workspace.member.remove"}:
        return "before" in detail and "after" in detail and bool(detail.get("workspace_code")) and bool(detail.get("user_id"))
    if action in {"workspace.feedback_policy.update", "workspace.auth_membership_mapping.update"}:
        return "before" in detail and "after" in detail and bool(detail.get("workspace_code"))
    return False


def _permission_change_title(action: str) -> str:
    titles = {
        "users.roles.update": "全局角色变更",
        "workspace.member.upsert": "工作台成员变更",
        "workspace.member.remove": "工作台成员移出",
        "workspace.feedback_policy.update": "Viewer 反馈策略变更",
        "workspace.auth_membership_mapping.update": "部门自动开通规则变更",
    }
    return titles.get(action, action)


def _permission_change_scope(action: str, detail: dict) -> str:
    if action == "users.roles.update":
        return "global"
    return str(detail.get("workspace_code") or "workspace")


def _permission_change_summary(action: str, detail: dict) -> str:
    if action == "users.roles.update":
        return f"全局角色 {_role_list_text(detail.get('before_roles'))} -> {_role_list_text(detail.get('after_roles'))}"
    if action in {"workspace.member.upsert", "workspace.member.remove"}:
        before = detail.get("before")
        after = detail.get("after")
        return f"{detail.get('workspace_code', '')} 成员 {detail.get('user_id', '')}: {_membership_text(before)} -> {_membership_text(after)}"
    if action == "workspace.feedback_policy.update":
        changed = [
            FEEDBACK_POLICY_LABELS.get(field, field)
            for field in sorted(set((detail.get("before") or {}).keys()) | set((detail.get("after") or {}).keys()))
            if (detail.get("before") or {}).get(field) != (detail.get("after") or {}).get(field)
        ]
        return "、".join(changed) if changed else "反馈策略无实际差异"
    if action == "workspace.auth_membership_mapping.update":
        return (
            f"部门规则 {_department_mapping_text(detail.get('before'))} -> "
            f"{_department_mapping_text(detail.get('after'))}"
        )
    return action


def _permission_change_diffs(action: str, detail: dict) -> list[PermissionChangeDiffRead]:
    if action == "users.roles.update":
        return [
            PermissionChangeDiffRead(
                field="roles",
                label="全局角色",
                before=detail.get("before_roles") or [],
                after=detail.get("after_roles") or [],
                explanation=(
                    f"该用户全局角色从 {_role_list_text(detail.get('before_roles'))} "
                    f"调整为 {_role_list_text(detail.get('after_roles'))}。"
                ),
            ),
        ]
    if action in {"workspace.member.upsert", "workspace.member.remove"}:
        before = detail.get("before")
        after = detail.get("after")
        diffs: list[PermissionChangeDiffRead] = []
        before_role = _membership_value(before, "workspace_role")
        after_role = _membership_value(after, "workspace_role")
        if before_role != after_role:
            diffs.append(
                PermissionChangeDiffRead(
                    field="workspace_role",
                    label="工作台角色",
                    before=before_role or "未加入",
                    after=after_role or "未加入",
                    explanation=f"工作台角色从 {before_role or '未加入'} 调整为 {after_role or '未加入'}。",
                ),
            )
        before_enabled = _membership_value(before, "enabled")
        after_enabled = _membership_value(after, "enabled")
        if before_enabled != after_enabled:
            diffs.append(
                PermissionChangeDiffRead(
                    field="enabled",
                    label="成员状态",
                    before=_enabled_text(before_enabled),
                    after=_enabled_text(after_enabled),
                    explanation=f"成员状态从 {_enabled_text(before_enabled)} 调整为 {_enabled_text(after_enabled)}。",
                ),
            )
        return diffs
    if action == "workspace.feedback_policy.update":
        before = dict(detail.get("before") or {})
        after = dict(detail.get("after") or {})
        diffs = []
        for field in sorted(set(before.keys()) | set(after.keys())):
            if before.get(field) == after.get(field):
                continue
            label = FEEDBACK_POLICY_LABELS.get(field, field)
            diffs.append(
                PermissionChangeDiffRead(
                    field=field,
                    label=label,
                    before=_enabled_text(before.get(field)),
                    after=_enabled_text(after.get(field)),
                    explanation=f"{label}从 {_enabled_text(before.get(field))} 调整为 {_enabled_text(after.get(field))}。",
                ),
            )
        return diffs
    if action == "workspace.auth_membership_mapping.update":
        before = detail.get("before") or {}
        after = detail.get("after") or {}
        return [
            PermissionChangeDiffRead(
                field="department_workspaces",
                label="部门自动开通规则",
                before=before,
                after=after,
                explanation=(
                    f"部门自动开通规则从 {_department_mapping_text(before)} "
                    f"调整为 {_department_mapping_text(after)}。"
                ),
            ),
        ]
    return []


def _rollback_permission_change(
    session: Session,
    *,
    current_user: User,
    log: AuditLog,
    confirm_dangerous_change: bool,
) -> tuple[str, str]:
    detail = dict(log.detail_json or {})
    if not _permission_change_has_rollback_snapshot(log.action, detail):
        return "skipped", "该变更缺少 before/after 快照，无法安全回滚"
    if log.action == "users.roles.update":
        return _rollback_user_roles(session, current_user=current_user, log=log, detail=detail)
    if log.action in {"workspace.member.upsert", "workspace.member.remove"}:
        return _rollback_workspace_membership(
            session,
            current_user=current_user,
            log=log,
            detail=detail,
            confirm_dangerous_change=confirm_dangerous_change,
        )
    if log.action == "workspace.feedback_policy.update":
        return _rollback_workspace_config(
            session,
            current_user=current_user,
            log=log,
            detail=detail,
            config_key="feedback_policy",
            label="反馈策略",
        )
    if log.action == "workspace.auth_membership_mapping.update":
        return _rollback_workspace_config(
            session,
            current_user=current_user,
            log=log,
            detail=detail,
            config_key="auth_membership_mapping",
            label="部门自动开通规则",
        )
    return "skipped", "该审计动作不支持权限回滚"


def _rollback_user_roles(
    session: Session,
    *,
    current_user: User,
    log: AuditLog,
    detail: dict,
) -> tuple[str, str]:
    target_user = find_user_with_roles(session, log.object_id)
    if target_user is None:
        return "skipped", "目标用户不存在"
    before_roles = [str(role) for role in detail.get("before_roles") or []]
    current_roles = sorted(role.code for role in target_user.roles)
    if "super_admin" in current_roles and "super_admin" not in before_roles and _active_super_admin_count(session) <= 1:
        return "skipped", "不能回滚掉最后一个 super_admin"
    set_user_roles(session, target_user, before_roles)
    write_audit(
        session,
        current_user,
        "identity.permission_rollback",
        "user",
        target_user.id,
        {
            "source_audit_log_id": log.id,
            "source_action": log.action,
            "before_rollback": {"roles": current_roles},
            "after_rollback": {"roles": before_roles},
        },
    )
    return "rolled_back", f"已恢复 {target_user.display_name} 的全局角色"


def _rollback_workspace_membership(
    session: Session,
    *,
    current_user: User,
    log: AuditLog,
    detail: dict,
    confirm_dangerous_change: bool,
) -> tuple[str, str]:
    workspace = _workspace_from_permission_detail(session, log, detail)
    if workspace is None:
        return "skipped", "工作台不存在"
    target_user_id = str(detail.get("user_id") or "")
    if not target_user_id:
        return "skipped", "缺少目标用户"
    before = detail.get("before")
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == target_user_id,
        ),
    )
    before_rollback = _membership_snapshot(membership)
    if not before or before.get("enabled") is False:
        if membership is None or not membership.enabled:
            return "skipped", "目标成员当前已经不在工作台"
        if membership.workspace_role == "owner":
            if _workspace_owner_count(session, workspace) <= 1:
                return "skipped", "不能移出最后一个 workspace owner"
            if not confirm_dangerous_change:
                return "skipped", "移出 owner 需要确认危险权限变更"
        membership.enabled = False
        after_rollback = _membership_snapshot(membership)
    else:
        target_role = str(before.get("workspace_role") or "viewer")
        target_enabled = bool(before.get("enabled", True))
        if membership is not None and membership.workspace_role == "owner" and target_role != "owner":
            if _workspace_owner_count(session, workspace) <= 1:
                return "skipped", "不能降权最后一个 workspace owner"
            if not confirm_dangerous_change:
                return "skipped", "降权 owner 需要确认危险权限变更"
        if membership is None:
            membership = WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=target_user_id,
                workspace_role=target_role,
                enabled=target_enabled,
            )
            session.add(membership)
            session.flush()
        else:
            membership.workspace_role = target_role
            membership.enabled = target_enabled
        after_rollback = _membership_snapshot(membership)
    write_audit(
        session,
        current_user,
        "identity.permission_rollback",
        "workspace",
        workspace.id,
        {
            "source_audit_log_id": log.id,
            "source_action": log.action,
            "workspace_code": workspace.code,
            "user_id": target_user_id,
            "before_rollback": before_rollback,
            "after_rollback": after_rollback,
        },
    )
    return "rolled_back", f"已恢复 {workspace.code} 的成员权限"


def _rollback_workspace_config(
    session: Session,
    *,
    current_user: User,
    log: AuditLog,
    detail: dict,
    config_key: str,
    label: str,
) -> tuple[str, str]:
    workspace = _workspace_from_permission_detail(session, log, detail)
    if workspace is None:
        return "skipped", "工作台不存在"
    config = dict(workspace.config_json or {})
    before_rollback = dict(config.get(config_key) or {})
    restore_value = dict(detail.get("before") or {})
    if restore_value:
        config[config_key] = restore_value
    else:
        config.pop(config_key, None)
    workspace.config_json = config
    write_audit(
        session,
        current_user,
        "identity.permission_rollback",
        "workspace",
        workspace.id,
        {
            "source_audit_log_id": log.id,
            "source_action": log.action,
            "workspace_code": workspace.code,
            "config_key": config_key,
            "before_rollback": before_rollback,
            "after_rollback": restore_value,
        },
    )
    return "rolled_back", f"已恢复 {workspace.code} 的{label}"


def _workspace_from_permission_detail(session: Session, log: AuditLog, detail: dict) -> Workspace | None:
    workspace_code = str(detail.get("workspace_code") or "")
    if workspace_code:
        workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
        if workspace is not None:
            return workspace
    if log.object_type == "workspace":
        return session.get(Workspace, log.object_id)
    return None


def _membership_snapshot(membership: WorkspaceMembership | None) -> dict | None:
    if membership is None:
        return None
    return {"workspace_role": membership.workspace_role, "enabled": membership.enabled}


def _membership_value(value: object, field: str):
    if not isinstance(value, dict):
        return None
    return value.get(field)


def _membership_text(value: object) -> str:
    if not isinstance(value, dict):
        return "未加入"
    role = value.get("workspace_role") or "viewer"
    enabled = bool(value.get("enabled", False))
    return f"{role} / {_enabled_text(enabled)}"


def _role_list_text(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "无"
    return "、".join(str(item) for item in value)


def _enabled_text(value: object) -> str:
    if value is None:
        return "未设置"
    return "开启" if bool(value) else "关闭"


def _department_mapping_text(value: object) -> str:
    if not isinstance(value, dict):
        return "空"
    rows = value.get("department_workspaces") or []
    if not rows:
        return "空"
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parts.append(f"{row.get('department', '')}:{row.get('workspace_role', 'viewer')}")
    return "、".join(parts) if parts else "空"


def _active_super_admin_count(session: Session) -> int:
    value = session.scalar(
        select(func.count(User.id))
        .join(User.roles)
        .where(User.is_active.is_(True), Role.code == "super_admin"),
    )
    return int(value or 0)


def _workspace_owner_count(session: Session, workspace: Workspace) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.workspace_role == "owner",
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    return int(value or 0)


def _load_invite(session: Session, code: str) -> UserInvite:
    invite = session.scalar(select(UserInvite).where(UserInvite.code == code))
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    return invite


def _email_hint(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    name, domain = email.split("@", 1)
    prefix = name[:2] if len(name) > 2 else name[:1]
    return f"{prefix}***@{domain}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
