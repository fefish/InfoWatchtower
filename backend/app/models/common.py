from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

JsonDict = dict[str, Any]
JsonList = list[Any]
JsonValue = JsonDict | JsonList
JsonColumn = JSON().with_variant(JSONB, "postgresql")


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class SyncMixin:
    global_id: Mapped[str] = mapped_column(String(64), default=new_id, unique=True, index=True)
    origin_instance_id: Mapped[str] = mapped_column(String(64), default="local")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(128), default="")


class ScopeMixin:
    domain_code: Mapped[str] = mapped_column(String(64), default="ai", index=True)
    visibility_scope: Mapped[str] = mapped_column(String(32), default="public", index=True)
    sync_policy: Mapped[str] = mapped_column(String(32), default="public_to_intranet", index=True)
