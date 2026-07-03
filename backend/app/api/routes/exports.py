from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.auth.service import write_audit
from app.core.database import get_db_session
from app.exports.company_sql import (
    DailyReportGenerationNotReadyError,
    DailyReportNotFoundError,
    DailyReportNotPublishedError,
    generate_company_sql_for_daily_report,
)
from app.models.content import NewsItem, RawItem
from app.models.export import ExportJob, ExportJobItem
from app.models.identity import User
from app.models.reports import DailyReport
from app.schemas.exports import (
    CompanySqlExportRead,
    CompanySqlTraceItemRead,
    CompanySqlTraceRead,
    ExportJobRead,
)

router = APIRouter(prefix="/api/exports", tags=["exports"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.post("/company-sql/daily-reports/{daily_report_id}", response_model=CompanySqlExportRead)
def create_company_sql_export(
    daily_report_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> CompanySqlExportRead:
    report = session.get(DailyReport, daily_report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Daily report not found: {daily_report_id}")
    assert_workspace_member(session, current_user, report.workspace_code, min_role="member")
    try:
        result = generate_company_sql_for_daily_report(
            session,
            daily_report_id=daily_report_id,
            requested_by_id=current_user.id,
        )
    except DailyReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DailyReportNotPublishedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DailyReportGenerationNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    write_audit(
        session,
        current_user,
        "export.company_sql",
        "export_job",
        result.export_job.id,
        {
            "daily_report_id": daily_report_id,
            "item_count": result.item_count,
            "statement_count": result.statement_count,
        },
    )
    session.commit()
    session.refresh(result.export_job)
    return _company_sql_export_to_read(
        result.export_job,
        daily_report_id=daily_report_id,
        sql_text=result.sql_text,
    )


@router.get("", response_model=list[ExportJobRead])
def list_export_jobs(
    workspace_code: str | None = Query(default=None),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[ExportJobRead]:
    if workspace_code:
        assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    else:
        require_super_admin(current_user)
    statement = select(ExportJob).order_by(ExportJob.created_at.desc()).limit(50)
    if workspace_code:
        statement = statement.where(ExportJob.workspace_code == workspace_code)
    jobs = session.scalars(statement).all()
    return [_export_job_to_read(job) for job in jobs]


@router.get("/{export_job_id}", response_model=ExportJobRead)
def get_export_job(
    export_job_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ExportJobRead:
    job = session.get(ExportJob, export_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    assert_workspace_member(session, current_user, job.workspace_code, min_role="viewer")
    return _export_job_to_read(job)


@router.get("/{export_job_id}/trace", response_model=CompanySqlTraceRead)
def get_export_job_trace(
    export_job_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> CompanySqlTraceRead:
    job = session.get(ExportJob, export_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    assert_workspace_member(session, current_user, job.workspace_code, min_role="viewer")
    items = session.scalars(
        select(ExportJobItem)
        .options(
            selectinload(ExportJobItem.daily_report_item),
            selectinload(ExportJobItem.generated_news),
            selectinload(ExportJobItem.news_item).selectinload(NewsItem.raw_item).selectinload(RawItem.data_source),
        )
        .where(ExportJobItem.export_job_id == export_job_id)
        .order_by(ExportJobItem.sql_sequence, ExportJobItem.id),
    ).all()
    return CompanySqlTraceRead(
        export_job_id=job.id,
        item_count=int((job.result_json or {}).get("item_count") or 0),
        statement_count=len(items),
        trace_items=[_export_job_item_to_trace(item) for item in items],
    )


def _company_sql_export_to_read(
    job: ExportJob,
    daily_report_id: str,
    sql_text: str,
) -> CompanySqlExportRead:
    result_json = job.result_json or {}
    return CompanySqlExportRead(
        export_job_id=job.id,
        daily_report_id=daily_report_id,
        workspace_code=job.workspace_code,
        domain_code=job.domain_code,
        status=job.status,
        item_count=int(result_json.get("item_count") or 0),
        statement_count=int(result_json.get("statement_count") or 0),
        sql_text=sql_text,
        created_at=job.created_at,
        completed_at=job.completed_at,
        result_json=result_json,
    )


def _export_job_to_read(job: ExportJob) -> ExportJobRead:
    return ExportJobRead(
        id=job.id,
        export_type=job.export_type,
        status=job.status,
        workspace_code=job.workspace_code,
        domain_code=job.domain_code,
        params_json=job.params_json or {},
        result_json=job.result_json or {},
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _export_job_item_to_trace(item: ExportJobItem) -> CompanySqlTraceItemRead:
    news_item = item.news_item
    raw_item = news_item.raw_item if news_item else None
    data_source = raw_item.data_source if raw_item else None
    source_url = ""
    if raw_item and raw_item.source_url:
        source_url = raw_item.source_url
    elif news_item and news_item.source_url:
        source_url = news_item.source_url
    daily_item = item.daily_report_item
    generated = item.generated_news
    sql_excerpt = item.sql_text[:240].replace("\n", " ")
    return CompanySqlTraceItemRead(
        sql_sequence=item.sql_sequence,
        sql_table=item.sql_table,
        status=item.status,
        daily_report_item_id=item.daily_report_item_id,
        generated_news_id=item.generated_news_id,
        news_item_id=item.news_item_id,
        raw_item_id=raw_item.id if raw_item else None,
        data_source_id=data_source.id if data_source else None,
        data_source_name=data_source.name if data_source else None,
        source_type=news_item.source_type if news_item else None,
        source_url=source_url or None,
        source_title=(raw_item.source_title if raw_item else news_item.source_title if news_item else ""),
        generated_title=generated.title if generated else "",
        category=generated.category if generated else "",
        adoption_status=daily_item.adoption_status if daily_item else 0,
        sql_excerpt=sql_excerpt,
    )
