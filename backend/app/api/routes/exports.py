from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.auth.service import write_audit
from app.core.database import get_db_session
from app.exports.company_sql import (
    DailyReportGenerationNotReadyError,
    DailyReportNotFoundError,
    DailyReportNotPublishedError,
    generate_company_sql_for_daily_report,
)
from app.models.export import ExportJob
from app.models.identity import User
from app.schemas.exports import CompanySqlExportRead, ExportJobRead

router = APIRouter(prefix="/api/exports", tags=["exports"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.post("/company-sql/daily-reports/{daily_report_id}", response_model=CompanySqlExportRead)
def create_company_sql_export(
    daily_report_id: str,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> CompanySqlExportRead:
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
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[ExportJobRead]:
    jobs = session.scalars(
        select(ExportJob).order_by(ExportJob.created_at.desc()).limit(50),
    ).all()
    return [_export_job_to_read(job) for job in jobs]


@router.get("/{export_job_id}", response_model=ExportJobRead)
def get_export_job(
    export_job_id: str,
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ExportJobRead:
    job = session.get(ExportJob, export_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    return _export_job_to_read(job)


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
