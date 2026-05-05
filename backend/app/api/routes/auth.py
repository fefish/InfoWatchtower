from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.service import (
    ExternalIdentity,
    authenticate_password_user,
    find_user_with_roles,
    mark_login,
    resolve_header_identity,
    role_to_read,
    set_user_roles,
    user_to_read,
    write_audit,
)
from app.auth.sessions import create_session_token, verify_session_token
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.models.identity import Role, User
from app.schemas.auth import AuthResponse, LoginRequest, RoleRead, UpdateUserRolesRequest, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api", tags=["identity"])


def _cookie_kwargs(settings: Settings) -> dict:
    return {
        "key": settings.auth_session_cookie,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.app_env == "production",
        "path": "/",
    }


def _set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    token = create_session_token(
        user.id,
        settings.auth_session_secret,
        settings.auth_session_ttl_seconds,
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
        if user and user.is_active and user.status == "active":
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
    if "super_admin" not in {role.code for role in current_user.roles}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires super_admin")
    return current_user


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    response: Response,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    _require_auth_ready(settings)
    if settings.auth_mode not in {"local", "public_password"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Login endpoint is disabled for AUTH_MODE={settings.auth_mode}",
        )

    user = authenticate_password_user(session, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    mark_login(session, user, "auth.login")
    session.commit()
    user = find_user_with_roles(session, user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    _set_session_cookie(response, user, settings)
    return AuthResponse(user=user_to_read(user))


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
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> list[UserRead]:
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
