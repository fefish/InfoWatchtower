from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.auth import _session_version
from app.auth.service import create_initial_super_admin, setup_needed, user_to_read
from app.auth.sessions import create_session_token
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.schemas.setup import SetupCreateRead, SetupCreateRequest, SetupStatusRead

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatusRead)
def get_setup_status(session: Session = Depends(get_db_session)) -> SetupStatusRead:
    return SetupStatusRead(needs_setup=setup_needed(session))


@router.post("", response_model=SetupCreateRead)
def create_setup_admin(
    payload: SetupCreateRequest,
    response: Response,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SetupCreateRead:
    if payload.password == payload.username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password cannot match username")
    try:
        user = create_initial_super_admin(
            session,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
        )
        session.commit()
    except RuntimeError as exc:
        if str(exc) == "setup_already_completed":
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Setup already completed") from exc
        raise
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc

    token = create_session_token(
        user.id,
        settings.auth_session_secret,
        ttl_seconds=settings.auth_session_ttl_seconds,
        session_version=_session_version(user),
    )
    response.set_cookie(
        settings.auth_session_cookie,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth_session_ttl_seconds,
    )
    return SetupCreateRead(user=user_to_read(user))
