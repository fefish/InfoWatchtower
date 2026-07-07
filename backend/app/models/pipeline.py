from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, SyncMixin, TimestampMixin


class PipelineRun(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    """Daily pipeline run 记录（docs/backend/pipeline-jobs-design.md §3/§3.1）。

    run 级重试链字段（attempt/max_attempts/retry_of_run_id/next_retry_at/
    retry_reason）承载 §6.2 的自动重试语义：
    - attempt 首跑=1；max_attempts=schedule_policy.retry.max_attempts+1（含首跑）。
    - failed 且可重试且未达上限 → worker 写 next_retry_at，scheduler 到期重投。
    - superseded 让位 run 落 status=skipped + skip_reason=superseded。
    """

    __tablename__ = "pipeline_runs"

    pipeline_type: Mapped[str] = mapped_column(String(64), default="daily_report", index=True)
    day_key: Mapped[str] = mapped_column(String(16), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    triggered_by: Mapped[str] = mapped_column(String(64), default="")
    parameters_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    summary_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    error_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    skip_reason: Mapped[str] = mapped_column(String(64), default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    retry_of_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_runs.id"),
        nullable=True,
        index=True,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    retry_reason: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    retry_of_run: Mapped[PipelineRun | None] = relationship(remote_side="PipelineRun.id")


class SchedulerHeartbeat(IdMixin, TimestampMixin, Base):
    """调度心跳（§3.1/§8.5）：scheduler 进程写、status API 读。

    运行状态快照，可随时重建，不参与同步（sync_policy=none 语义：无 SyncMixin，
    不进 sync feed 对象清单）。workspace_code 空串表示实例级节拍行。
    """

    __tablename__ = "scheduler_heartbeats"
    __table_args__ = (
        UniqueConstraint(
            "scheduler_instance",
            "job_kind",
            "workspace_code",
            name="uq_scheduler_heartbeats_instance_kind_workspace",
        ),
    )

    scheduler_instance: Mapped[str] = mapped_column(String(128), index=True)
    job_kind: Mapped[str] = mapped_column(String(64), index=True)
    workspace_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    last_tick_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_enqueued_job_id: Mapped[str] = mapped_column(String(128), default="")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
