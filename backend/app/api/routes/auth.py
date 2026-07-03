from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

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
from app.models.identity import PasswordResetToken, Role, User, UserInvite
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
    RoleRead,
    UpdateUserRolesRequest,
    UserPatchRequest,
    UserRead,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api", tags=["identity"])
ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
MUST_CHANGE_ALLOWED_PATHS = {
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/password/change",
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


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(**_cookie_kwargs(settings))


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


def _header_identity(request: Request, settings: Settings) -> ExternalIdentity | None:
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


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:64] or "unknown"
    return (request.client.host if request.client else "unknown")[:64]


def _session_version(user: User) -> str:
    value = user.updated_at or user.created_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _is_super_admin(user: User) -> bool:
    return "super_admin" in {role.code for role in user.roles}


def get_current_user(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    _require_auth_ready(settings)
    token = request.cookies.get(settings.auth_session_cookie)
    payload = verify_session_token(token, settings.auth_session_secret)
    if payload:
        user = find_user_with_roles(session, payload["sub"])
        if user and user.is_active and user.status in {"active", "must_change_password"}:
            if payload.get("sv") and payload.get("sv") != _session_version(user):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
            if user.status == "must_change_password" and request.url.path not in MUST_CHANGE_ALLOWED_PATHS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="must_change_password",
                )
            return user

    if settings.auth_mode == "intranet_header":
        identity = _header_identity(request, settings)
        if identity is not None:
            user = resolve_header_identity(
                session,
                identity,
                settings.auth_default_role,
                settings.auth_auto_provision,
            )
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


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if not _is_super_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires super_admin")
    return current_user


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
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="AUTH_MODE=oidc requires an OIDC adapter configuration",
        )
    if settings.auth_mode not in {"local", "public_password"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Login endpoint is disabled for AUTH_MODE={settings.auth_mode}",
        )

    ip = _client_ip(request)
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
def me(current_user: User = Depends(get_current_user)) -> AuthResponse:
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
