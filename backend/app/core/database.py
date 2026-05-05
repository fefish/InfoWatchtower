from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine | None:
    settings = get_settings()
    if not settings.database_url:
        return None
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session_factory() -> sessionmaker | None:
    engine = get_engine()
    if engine is None:
        return None
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db_session():
    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for database-backed API routes.")

    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def check_database() -> dict[str, Any]:
    engine = get_engine()
    if engine is None:
        return {"status": "not_configured"}

    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        return {"status": "ok"}
    except SQLAlchemyError as exc:
        return {"status": "error", "error_type": exc.__class__.__name__}
