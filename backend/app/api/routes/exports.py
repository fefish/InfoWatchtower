from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin, require_sync_token
from app.auth.service import write_audit
from app.core.database import get_db_session
from app.exports.company_sql import (
    COMPANY_SQL_CONTENT_FIELDS,
    CompanySqlWorkspaceNotSupportedError,
    DailyReportGenerationNotReadyError,
    DailyReportNotFoundError,
    DailyReportNotPublishedError,
    generate_company_sql_for_daily_report,
    run_company_sql_preflight,
)
from app.models.common import utc_now
from app.models.content import NewsItem, RawItem
from app.models.export import ExportImportReceipt, ExportJob, ExportJobItem
from app.models.identity import User
from app.models.reports import DailyReport
from app.schemas.exports import (
    CompanySqlBatchExportCreate,
    CompanySqlBatchExportItemRead,
    CompanySqlBatchExportRead,
    CompanySqlExportRead,
    CompanySqlImportReceiptCreate,
    CompanySqlImportReceiptRead,
    CompanySqlPreflightRead,
    CompanySqlTraceFieldDiffRead,
    CompanySqlTraceItemRead,
    CompanySqlTraceRead,
    ExportJobRead,
)

router = APIRouter(prefix="/api/exports", tags=["exports"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)
SYNC_TOKEN = Depends(require_sync_token)
COMPANY_SQL_INLINE_PREVIEW_MAX_BYTES = 200_000
COMPANY_SQL_DOWNLOAD_CHUNK_CHARS = 32_768
COMPANY_SQL_TRACE_VALUE_PREVIEW_CHARS = 320


@router.post("/company-sql/daily-reports/{daily_report_id}/preflight", response_model=CompanySqlPreflightRead)
def preflight_company_sql_export(
    daily_report_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> CompanySqlPreflightRead:
    report = session.get(DailyReport, daily_report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Daily report not found: {daily_report_id}")
    assert_workspace_member(session, current_user, report.workspace_code, min_role="member")
    try:
        preflight = run_company_sql_preflight(session, daily_report_id)
    except DailyReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CompanySqlPreflightRead.model_validate(preflight.to_json())


@router.post("/company-sql/daily-reports/batch", response_model=CompanySqlBatchExportRead)
def create_company_sql_batch_export(
    payload: CompanySqlBatchExportCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> CompanySqlBatchExportRead:
    daily_report_ids = _unique_daily_report_ids(payload.daily_report_ids)
    if not daily_report_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="daily_report_ids cannot be empty")
    reports_by_id = {report_id: session.get(DailyReport, report_id) for report_id in daily_report_ids}
    existing_reports = [report for report in reports_by_id.values() if report is not None]
    if not existing_reports:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No daily reports found")

    workspace_code = existing_reports[0].workspace_code
    domain_code = existing_reports[0].domain_code
    for report in existing_reports:
        assert_workspace_member(session, current_user, report.workspace_code, min_role="member")
        if report.workspace_code != workspace_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Batch company SQL export only supports one workspace per request",
            )

    batch_job = ExportJob(
        workspace_code=workspace_code,
        domain_code=domain_code,
        visibility_scope=existing_reports[0].visibility_scope,
        sync_policy=existing_reports[0].sync_policy,
        export_type="company_sql_batch",
        status="running",
        requested_by_id=current_user.id,
        params_json={
            "daily_report_ids": daily_report_ids,
            "continue_on_error": payload.continue_on_error,
        },
        started_at=utc_now(),
    )
    session.add(batch_job)
    session.flush()

    items: list[CompanySqlBatchExportItemRead] = []
    stop_after_failure = False
    for report_id in daily_report_ids:
        if stop_after_failure:
            items.append(_batch_item_skipped(report_id, "Skipped because continue_on_error=false after a prior failure."))
            continue
        report = reports_by_id.get(report_id)
        if report is None:
            items.append(_batch_item_failed(report_id, None, "not_found", ["Daily report not found."]))
            stop_after_failure = not payload.continue_on_error
            continue
        item = _run_batch_export_item(session, report, batch_job, current_user)
        items.append(item)
        if item.status != "succeeded" and not payload.continue_on_error:
            stop_after_failure = True

    succeeded_count = sum(1 for item in items if item.status == "succeeded")
    failed_count = sum(1 for item in items if item.status == "failed")
    skipped_count = sum(1 for item in items if item.status == "skipped")
    total_item_count = sum(item.item_count for item in items)
    total_statement_count = sum(item.statement_count for item in items)
    total_sql_text_bytes = sum(item.sql_text_bytes for item in items)
    batch_status = "completed" if failed_count == 0 and skipped_count == 0 else "failed" if succeeded_count == 0 else "partial_success"
    batch_job.status = batch_status
    batch_job.completed_at = utc_now()
    manifest_json = {
        "schema_version": 1,
        "export_type": "company_sql_batch",
        "batch_export_job_id": batch_job.id,
        "workspace_code": workspace_code,
        "domain_code": domain_code,
        "status": batch_status,
        "requested_report_ids": daily_report_ids,
        "succeeded_count": succeeded_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "total_item_count": total_item_count,
        "total_statement_count": total_statement_count,
        "total_sql_text_bytes": total_sql_text_bytes,
        "validation_summary": {
            "rule": "Each daily report must pass company SQL preflight before an individual export job is created.",
            "passed": succeeded_count,
            "failed": failed_count,
            "skipped": skipped_count,
        },
        "items": [item.model_dump(mode="json") for item in items],
    }
    batch_job.result_json = {
        "manifest": manifest_json,
        "validation_summary": manifest_json["validation_summary"],
    }
    write_audit(
        session,
        current_user,
        "export.company_sql_batch",
        "export_job",
        batch_job.id,
        {
            "workspace_code": workspace_code,
            "daily_report_ids": daily_report_ids,
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
        },
    )
    session.commit()
    session.refresh(batch_job)
    return CompanySqlBatchExportRead(
        batch_export_job_id=batch_job.id,
        workspace_code=workspace_code,
        domain_code=domain_code,
        status=batch_status,
        total_reports=len(items),
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        total_item_count=total_item_count,
        total_statement_count=total_statement_count,
        total_sql_text_bytes=total_sql_text_bytes,
        manifest_json=manifest_json,
        items=items,
        created_at=batch_job.created_at,
        completed_at=batch_job.completed_at,
    )


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
    except CompanySqlWorkspaceNotSupportedError as exc:
        # 工作台标签策略与公司 SQL 口径不适配：明确 400 指引，不产出兼容映射 SQL。
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
    statement = (
        select(ExportJob)
        .options(selectinload(ExportJob.import_receipts).selectinload(ExportImportReceipt.recorded_by))
        .order_by(ExportJob.created_at.desc())
        .limit(50)
    )
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
    job = session.scalar(
        select(ExportJob)
        .options(selectinload(ExportJob.import_receipts).selectinload(ExportImportReceipt.recorded_by))
        .where(ExportJob.id == export_job_id),
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    assert_workspace_member(session, current_user, job.workspace_code, min_role="viewer")
    return _export_job_to_read(job)


@router.get("/{export_job_id}/download")
def download_export_job(
    export_job_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> StreamingResponse:
    job = session.get(ExportJob, export_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    assert_workspace_member(session, current_user, job.workspace_code, min_role="admin")
    if job.export_type != "company_sql":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only company_sql exports can be downloaded")
    sql_text = str((job.result_json or {}).get("sql_text") or "")
    if not sql_text:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Export SQL text is not available")
    day_key = str((job.result_json or {}).get("day_key") or "daily")
    filename = _download_filename(job, day_key)
    sql_bytes = _sql_text_size(sql_text)
    return StreamingResponse(
        _iter_sql_text(sql_text),
        media_type="text/sql; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(sql_bytes),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-InfoWatchtower-SQL-Bytes": str(sql_bytes),
            "X-InfoWatchtower-Download-Strategy": "server_streaming",
        },
    )


@router.get("/{export_job_id}/import-receipts", response_model=list[CompanySqlImportReceiptRead])
def list_export_import_receipts(
    export_job_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[CompanySqlImportReceiptRead]:
    job = session.get(ExportJob, export_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    assert_workspace_member(session, current_user, job.workspace_code, min_role="viewer")
    receipts = session.scalars(
        select(ExportImportReceipt)
        .options(selectinload(ExportImportReceipt.recorded_by))
        .where(ExportImportReceipt.export_job_id == export_job_id)
        .order_by(ExportImportReceipt.created_at.desc(), ExportImportReceipt.id.desc()),
    ).all()
    return [_import_receipt_to_read(receipt) for receipt in receipts]


@router.post("/{export_job_id}/import-receipts", response_model=CompanySqlImportReceiptRead)
def create_export_import_receipt(
    export_job_id: str,
    payload: CompanySqlImportReceiptCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> CompanySqlImportReceiptRead:
    job = session.get(ExportJob, export_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    assert_workspace_member(session, current_user, job.workspace_code, min_role="admin")
    receipt = _create_import_receipt_for_job(
        session,
        job,
        payload,
        recorded_by=current_user,
        source="manual",
    )
    session.commit()
    session.refresh(receipt)
    return _import_receipt_to_read(receipt)


@router.post(
    "/{export_job_id}/import-receipts/callback",
    response_model=CompanySqlImportReceiptRead,
    dependencies=[SYNC_TOKEN],
)
def create_export_import_receipt_callback(
    export_job_id: str,
    payload: CompanySqlImportReceiptCreate,
    session: Session = DB_SESSION,
) -> CompanySqlImportReceiptRead:
    job = session.get(ExportJob, export_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
    receipt = _create_import_receipt_for_job(
        session,
        job,
        payload,
        recorded_by=None,
        source="service_callback",
    )
    session.commit()
    session.refresh(receipt)
    return _import_receipt_to_read(receipt)


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
    inline_sql_text, truncated = _inline_sql_preview(sql_text)
    sql_text_bytes = _sql_text_size(sql_text)
    sql_text_preview_bytes = _sql_text_size(inline_sql_text)
    day_key = str(result_json.get("day_key") or "daily")
    return CompanySqlExportRead(
        export_job_id=job.id,
        daily_report_id=daily_report_id,
        workspace_code=job.workspace_code,
        domain_code=job.domain_code,
        status=job.status,
        item_count=int(result_json.get("item_count") or 0),
        statement_count=int(result_json.get("statement_count") or 0),
        sql_text=inline_sql_text,
        sql_text_bytes=sql_text_bytes,
        sql_text_preview_bytes=sql_text_preview_bytes,
        sql_text_truncated=truncated,
        download_url=f"/api/exports/{job.id}/download",
        download_filename=_download_filename(job, day_key),
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
        latest_import_receipt=_latest_import_receipt_read(job),
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _latest_import_receipt_read(job: ExportJob) -> CompanySqlImportReceiptRead | None:
    receipts = list(job.import_receipts or [])
    if not receipts:
        return None
    latest = max(receipts, key=lambda receipt: (receipt.created_at, receipt.id))
    return _import_receipt_to_read(latest)


def _import_receipt_to_read(receipt: ExportImportReceipt) -> CompanySqlImportReceiptRead:
    recorded_by = receipt.recorded_by
    return CompanySqlImportReceiptRead(
        id=receipt.id,
        export_job_id=receipt.export_job_id,
        workspace_code=receipt.workspace_code,
        domain_code=receipt.domain_code,
        target_system=receipt.target_system,
        import_status=receipt.import_status,
        imported_at=receipt.imported_at,
        imported_statement_count=receipt.imported_statement_count,
        failed_statement_count=receipt.failed_statement_count,
        failure_items=receipt.failure_items_json or [],
        notes=receipt.notes,
        recorded_by_id=receipt.recorded_by_id,
        recorded_by_name=recorded_by.display_name if recorded_by else None,
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
    )


def _create_import_receipt_for_job(
    session: Session,
    job: ExportJob,
    payload: CompanySqlImportReceiptCreate,
    *,
    recorded_by: User | None,
    source: str,
) -> ExportImportReceipt:
    if job.export_type != "company_sql":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only company_sql exports accept import receipts")
    failure_items = _normalize_import_failure_items(session, job, payload)
    failed_statement_count = max(payload.failed_statement_count, len(failure_items))
    _validate_import_receipt_counts(job, payload.import_status, payload.imported_statement_count, failed_statement_count)
    receipt = ExportImportReceipt(
        export_job_id=job.id,
        workspace_code=job.workspace_code,
        domain_code=job.domain_code,
        visibility_scope=job.visibility_scope,
        sync_policy="local_only",
        target_system=payload.target_system.strip(),
        import_status=payload.import_status,
        imported_at=payload.imported_at,
        imported_statement_count=payload.imported_statement_count,
        failed_statement_count=failed_statement_count,
        failure_items_json=failure_items,
        notes=payload.notes.strip(),
        recorded_by_id=recorded_by.id if recorded_by else None,
    )
    session.add(receipt)
    session.flush()
    write_audit(
        session,
        recorded_by,
        "export.company_sql_import_receipt",
        "export_import_receipt",
        receipt.id,
        {
            "export_job_id": job.id,
            "workspace_code": job.workspace_code,
            "target_system": receipt.target_system,
            "import_status": receipt.import_status,
            "imported_statement_count": receipt.imported_statement_count,
            "failed_statement_count": receipt.failed_statement_count,
            "source": source,
        },
    )
    return receipt


def _normalize_import_failure_items(
    session: Session,
    job: ExportJob,
    payload: CompanySqlImportReceiptCreate,
) -> list[dict[str, object]]:
    if not payload.failure_items:
        return []
    job_items = session.scalars(
        select(ExportJobItem).where(ExportJobItem.export_job_id == job.id),
    ).all()
    items_by_id = {item.id: item for item in job_items}
    items_by_sequence_table = {(item.sql_sequence, item.sql_table): item for item in job_items}
    normalized: list[dict[str, object]] = []
    for failure in payload.failure_items:
        matched_item: ExportJobItem | None = None
        if failure.export_job_item_id:
            matched_item = items_by_id.get(failure.export_job_item_id)
            if matched_item is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"export_job_item_id does not belong to this export job: {failure.export_job_item_id}",
                )
        elif failure.sql_sequence is not None and failure.sql_table:
            matched_item = items_by_sequence_table.get((failure.sql_sequence, failure.sql_table))
        sql_excerpt = failure.sql_excerpt.strip()
        if not sql_excerpt and matched_item is not None:
            sql_excerpt = matched_item.sql_text[:240].replace("\n", " ")
        normalized.append(
            {
                "export_job_item_id": matched_item.id if matched_item else failure.export_job_item_id,
                "sql_sequence": matched_item.sql_sequence if matched_item else failure.sql_sequence,
                "sql_table": matched_item.sql_table if matched_item else failure.sql_table,
                "error_code": failure.error_code.strip(),
                "error_message": failure.error_message.strip(),
                "sql_excerpt": sql_excerpt,
            },
        )
    return normalized


def _validate_import_receipt_counts(
    job: ExportJob,
    import_status: str,
    imported_statement_count: int,
    failed_statement_count: int,
) -> None:
    if import_status == "imported" and failed_statement_count > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="imported receipts cannot contain failed statements",
        )
    if import_status in {"failed", "partial"} and failed_statement_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="failed or partial receipts must include failed_statement_count or failure_items",
        )
    if import_status == "pending" and (imported_statement_count > 0 or failed_statement_count > 0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="pending receipts cannot include imported or failed statements",
        )
    statement_count = int((job.result_json or {}).get("statement_count") or 0)
    if statement_count and imported_statement_count + failed_statement_count > statement_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="import receipt statement counts exceed the export statement count",
        )


def _unique_daily_report_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        report_id = value.strip()
        if not report_id:
            continue
        if report_id in seen:
            continue
        seen.add(report_id)
        result.append(report_id)
    return result


def _batch_item_failed(
    daily_report_id: str,
    day_key: str | None,
    preflight_status: str,
    errors: list[str],
) -> CompanySqlBatchExportItemRead:
    return CompanySqlBatchExportItemRead(
        daily_report_id=daily_report_id,
        day_key=day_key,
        status="failed",
        preflight_status=preflight_status,
        export_job_id=None,
        download_url=None,
        item_count=0,
        statement_count=0,
        sql_text_bytes=0,
        warning_count=0,
        error_count=max(1, len(errors)),
        errors=errors,
    )


def _batch_item_skipped(daily_report_id: str, reason: str) -> CompanySqlBatchExportItemRead:
    return CompanySqlBatchExportItemRead(
        daily_report_id=daily_report_id,
        day_key=None,
        status="skipped",
        preflight_status="skipped",
        export_job_id=None,
        download_url=None,
        item_count=0,
        statement_count=0,
        sql_text_bytes=0,
        warning_count=0,
        error_count=0,
        errors=[reason],
    )


def _preflight_error_messages(preflight: CompanySqlPreflightRead) -> list[str]:
    messages = [issue.message for issue in preflight.errors]
    messages.extend(issue.message for item in preflight.items for issue in item.errors)
    return messages or ["Company SQL preflight failed."]


def _run_batch_export_item(
    session: Session,
    report: DailyReport,
    batch_job: ExportJob,
    current_user: User,
) -> CompanySqlBatchExportItemRead:
    try:
        preflight = CompanySqlPreflightRead.model_validate(run_company_sql_preflight(session, report.id).to_json())
        if preflight.status != "passed":
            return _batch_item_failed(
                report.id,
                report.day_key,
                preflight.status,
                _preflight_error_messages(preflight),
            )
        result = generate_company_sql_for_daily_report(
            session,
            daily_report_id=report.id,
            requested_by_id=current_user.id,
        )
    except (
        DailyReportNotFoundError,
        DailyReportNotPublishedError,
        DailyReportGenerationNotReadyError,
        CompanySqlWorkspaceNotSupportedError,
    ) as exc:
        return _batch_item_failed(report.id, report.day_key, "failed", [str(exc)])

    params_json = result.export_job.params_json or {}
    result.export_job.params_json = {**params_json, "batch_export_job_id": batch_job.id}
    result_json = result.export_job.result_json or {}
    result.export_job.result_json = {**result_json, "batch_export_job_id": batch_job.id}
    sql_text_bytes = int(result.export_job.result_json.get("sql_size_bytes") or len(result.sql_text.encode("utf-8")))
    return CompanySqlBatchExportItemRead(
        daily_report_id=report.id,
        day_key=report.day_key,
        status="succeeded",
        preflight_status=preflight.status,
        export_job_id=result.export_job.id,
        download_url=f"/api/exports/{result.export_job.id}/download",
        item_count=result.item_count,
        statement_count=result.statement_count,
        sql_text_bytes=sql_text_bytes,
        warning_count=preflight.warning_count,
        error_count=0,
        errors=[],
    )


def _safe_filename_part(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return cleaned or "export"


def _download_filename(job: ExportJob, day_key: str) -> str:
    return f"{_safe_filename_part(job.workspace_code)}_{_safe_filename_part(day_key)}_company_sql.sql"


def _sql_text_size(sql_text: str) -> int:
    return len(sql_text.encode("utf-8"))


def _inline_sql_preview(sql_text: str) -> tuple[str, bool]:
    encoded = sql_text.encode("utf-8")
    if len(encoded) <= COMPANY_SQL_INLINE_PREVIEW_MAX_BYTES:
        return sql_text, False
    preview = encoded[:COMPANY_SQL_INLINE_PREVIEW_MAX_BYTES].decode("utf-8", errors="ignore")
    return (
        preview
        + "\n\n-- SQL preview truncated by InfoWatchtower. Use the server download endpoint for the full file.\n",
        True,
    )


def _iter_sql_text(sql_text: str):
    for start in range(0, len(sql_text), COMPANY_SQL_DOWNLOAD_CHUNK_CHARS):
        yield sql_text[start : start + COMPANY_SQL_DOWNLOAD_CHUNK_CHARS].encode("utf-8")


def _has_trace_value(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _trace_text_source(
    editor_value: object,
    generated_value: object,
    *,
    editor_path: str,
    generated_path: str,
) -> str:
    if _has_trace_value(editor_value):
        return editor_path
    if _has_trace_value(generated_value):
        return generated_path
    return "missing"


def _trace_content_field_sources(item: ExportJobItem) -> dict[str, str]:
    daily_item = item.daily_report_item
    generated = item.generated_news
    editor_content = daily_item.editor_content_json if daily_item else None
    generated_content = generated.content_json if generated else None
    editor_content = editor_content if isinstance(editor_content, dict) else {}
    generated_content = generated_content if isinstance(generated_content, dict) else {}
    sources: dict[str, str] = {}
    for field in COMPANY_SQL_CONTENT_FIELDS:
        if field in editor_content and _has_trace_value(editor_content.get(field)):
            sources[field] = "daily_report_items.editor_content_json"
        elif field in generated_content and _has_trace_value(generated_content.get(field)):
            sources[field] = "generated_news.content_json"
        else:
            sources[field] = "missing"
    return sources


def _trace_editor_override_fields(item: ExportJobItem) -> list[str]:
    daily_item = item.daily_report_item
    if daily_item is None:
        return []
    override_fields: list[str] = []
    if _has_trace_value(daily_item.editor_title):
        override_fields.append("title")
    if _has_trace_value(daily_item.editor_summary):
        override_fields.append("summary")
    if _has_trace_value(daily_item.editor_key_points):
        override_fields.append("key_points")
    editor_content = daily_item.editor_content_json if isinstance(daily_item.editor_content_json, dict) else {}
    override_fields.extend(
        f"content_json.{field}"
        for field in COMPANY_SQL_CONTENT_FIELDS
        if field in editor_content and _has_trace_value(editor_content.get(field))
    )
    return override_fields


def _trace_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _trace_value_preview(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    text = _trace_value(value).strip()
    if not text:
        return "", False
    if len(text) <= COMPANY_SQL_TRACE_VALUE_PREVIEW_CHARS:
        return text, False
    return text[:COMPANY_SQL_TRACE_VALUE_PREVIEW_CHARS] + "...", True


def _trace_field_diff(
    *,
    field: str,
    label: str,
    export_source: str,
    export_value: object,
    generated_value: object | None = None,
    editor_value: object | None = None,
    raw_value: object | None = None,
) -> CompanySqlTraceFieldDiffRead:
    export_preview, export_truncated = _trace_value_preview(export_value)
    generated_preview, generated_truncated = _trace_value_preview(generated_value)
    editor_preview, editor_truncated = _trace_value_preview(editor_value)
    raw_preview, raw_truncated = _trace_value_preview(raw_value)
    return CompanySqlTraceFieldDiffRead(
        field=field,
        label=label,
        export_source=export_source,
        export_value_preview=export_preview or "",
        generated_value_preview=generated_preview,
        editor_value_preview=editor_preview,
        raw_value_preview=raw_preview,
        changed_by_editor=export_source.startswith("daily_report_items."),
        truncated=export_truncated or generated_truncated or editor_truncated or raw_truncated,
    )


def _merged_content_value(item: ExportJobItem, field: str) -> object | None:
    daily_item = item.daily_report_item
    generated = item.generated_news
    editor_content = daily_item.editor_content_json if daily_item and isinstance(daily_item.editor_content_json, dict) else {}
    generated_content = generated.content_json if generated and isinstance(generated.content_json, dict) else {}
    if field in editor_content and _has_trace_value(editor_content.get(field)):
        return editor_content.get(field)
    return generated_content.get(field)


def _trace_field_diffs(item: ExportJobItem, source_url: str) -> list[CompanySqlTraceFieldDiffRead]:
    daily_item = item.daily_report_item
    generated = item.generated_news
    news_item = item.news_item
    raw_item = news_item.raw_item if news_item else None
    if daily_item is None or generated is None:
        return []
    diffs = [
        _trace_field_diff(
            field="source_url",
            label="来源 URL",
            export_source="raw_items.source_url" if raw_item and raw_item.source_url else "news_items.source_url",
            export_value=source_url,
            generated_value=generated.source_url,
            raw_value=raw_item.source_url if raw_item else news_item.source_url if news_item else None,
        ),
        _trace_field_diff(
            field="source_title",
            label="来源标题",
            export_source="raw_items.source_title" if raw_item and raw_item.source_title else "news_items.source_title",
            export_value=(raw_item.source_title if raw_item and raw_item.source_title else news_item.source_title if news_item else ""),
            raw_value=raw_item.source_title if raw_item else news_item.source_title if news_item else None,
        ),
        _trace_field_diff(
            field="raw_content",
            label="原文内容",
            export_source="raw_items.raw_content" if raw_item and raw_item.raw_content else "news_items.content",
            export_value=(raw_item.raw_content if raw_item and raw_item.raw_content else news_item.content if news_item else ""),
            raw_value=raw_item.raw_content if raw_item else news_item.content if news_item else None,
        ),
        _trace_field_diff(
            field="title",
            label="标题",
            export_source=_trace_text_source(
                daily_item.editor_title,
                generated.title,
                editor_path="daily_report_items.editor_title",
                generated_path="generated_news.title",
            ),
            export_value=daily_item.editor_title or generated.title,
            generated_value=generated.title,
            editor_value=daily_item.editor_title,
        ),
        _trace_field_diff(
            field="summary",
            label="摘要",
            export_source=_trace_text_source(
                daily_item.editor_summary,
                generated.summary,
                editor_path="daily_report_items.editor_summary",
                generated_path="generated_news.summary",
            ),
            export_value=daily_item.editor_summary or generated.summary,
            generated_value=generated.summary,
            editor_value=daily_item.editor_summary,
        ),
        _trace_field_diff(
            field="key_points",
            label="关键点",
            export_source=_trace_text_source(
                daily_item.editor_key_points,
                generated.key_points,
                editor_path="daily_report_items.editor_key_points",
                generated_path="generated_news.key_points",
            ),
            export_value=daily_item.editor_key_points or generated.key_points,
            generated_value=generated.key_points,
            editor_value=daily_item.editor_key_points,
        ),
        _trace_field_diff(
            field="category",
            label="一级分类",
            export_source="generated_news.category",
            export_value=generated.category,
            generated_value=generated.category,
        ),
    ]
    editor_content = daily_item.editor_content_json if isinstance(daily_item.editor_content_json, dict) else {}
    generated_content = generated.content_json if isinstance(generated.content_json, dict) else {}
    for field in COMPANY_SQL_CONTENT_FIELDS:
        diffs.append(
            _trace_field_diff(
                field=f"content_json.{field}",
                label=f"正文 {field}",
                export_source=(
                    "daily_report_items.editor_content_json"
                    if field in editor_content and _has_trace_value(editor_content.get(field))
                    else "generated_news.content_json"
                ),
                export_value=_merged_content_value(item, field),
                generated_value=generated_content.get(field),
                editor_value=editor_content.get(field),
            ),
        )
    return diffs


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
    export_title = ""
    title_source = "missing"
    summary_source = "missing"
    key_points_source = "missing"
    if daily_item and generated:
        export_title = str(daily_item.editor_title or generated.title or "")
        title_source = _trace_text_source(
            daily_item.editor_title,
            generated.title,
            editor_path="daily_report_items.editor_title",
            generated_path="generated_news.title",
        )
        summary_source = _trace_text_source(
            daily_item.editor_summary,
            generated.summary,
            editor_path="daily_report_items.editor_summary",
            generated_path="generated_news.summary",
        )
        key_points_source = _trace_text_source(
            daily_item.editor_key_points,
            generated.key_points,
            editor_path="daily_report_items.editor_key_points",
            generated_path="generated_news.key_points",
        )
    return CompanySqlTraceItemRead(
        export_job_item_id=item.id,
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
        export_title=export_title,
        category=generated.category if generated else "",
        adoption_status=daily_item.adoption_status if daily_item else 0,
        sql_excerpt=sql_excerpt,
        title_source=title_source,
        summary_source=summary_source,
        key_points_source=key_points_source,
        content_field_sources=_trace_content_field_sources(item),
        editor_override_fields=_trace_editor_override_fields(item),
        field_diffs=_trace_field_diffs(item, source_url),
    )
