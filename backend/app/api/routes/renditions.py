from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.database import get_db_session
from app.models.identity import User
from app.models.reports import ReportFormat, ReportRendition
from app.models.workspace import Workspace
from app.reports.renditions import (
    build_daily_rendition,
    build_weekly_rendition,
    ensure_report_formats,
    load_daily_report_for_rendition,
    load_weekly_report,
    render_markdown,
)
from app.reports.rendition_html import render_html
from app.schemas.renditions import (
    REPORT_FORMAT_EXPORT_TARGETS,
    REPORT_FORMAT_GROUP_BY,
    REPORT_FORMAT_ITEM_FIELDS,
    ReportFormatCreate,
    ReportFormatRead,
    ReportFormatUpdate,
    ReportRenditionRead,
)

router = APIRouter(prefix="/api", tags=["renditions"])


@router.get("/report-formats", response_model=list[ReportFormatRead])
def list_report_formats(
    workspace_code: str = Query(...),
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[ReportFormatRead]:
    _require_workspace(session, workspace_code)
    ensure_report_formats(session, workspace_code)
    session.commit()
    formats = session.scalars(
        select(ReportFormat)
        .where(ReportFormat.workspace_code == workspace_code)
        .order_by(ReportFormat.sort_order, ReportFormat.format_code),
    ).all()
    return [_format_to_read(fmt) for fmt in formats]


@router.post("/report-formats", response_model=ReportFormatRead, status_code=status.HTTP_201_CREATED)
def create_report_format(
    payload: ReportFormatCreate,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> ReportFormatRead:
    _require_workspace(session, payload.workspace_code)
    _validate_format_options(payload.group_by, payload.item_fields, payload.export_targets)
    existing = session.scalar(
        select(ReportFormat).where(
            ReportFormat.workspace_code == payload.workspace_code,
            ReportFormat.format_code == payload.format_code,
        ),
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report format already exists: {payload.format_code}",
        )
    max_sort = max(
        (
            fmt.sort_order
            for fmt in session.scalars(
                select(ReportFormat).where(ReportFormat.workspace_code == payload.workspace_code),
            ).all()
        ),
        default=0,
    )
    fmt = ReportFormat(
        workspace_code=payload.workspace_code,
        format_code=payload.format_code,
        name=payload.name.strip(),
        description=payload.description.strip(),
        builtin=False,
        locked=False,
        group_by=payload.group_by,
        headline_enabled=payload.headline_enabled,
        headline_auto_top_n=payload.headline_auto_top_n,
        item_fields={"fields": payload.item_fields},
        export_targets={"targets": payload.export_targets},
        enabled=True,
        sort_order=max_sort + 10,
    )
    session.add(fmt)
    session.commit()
    session.refresh(fmt)
    return _format_to_read(fmt)


@router.patch("/report-formats/{format_id}", response_model=ReportFormatRead)
def update_report_format(
    format_id: str,
    payload: ReportFormatUpdate,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> ReportFormatRead:
    fmt = session.get(ReportFormat, format_id)
    if fmt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report format not found")

    if fmt.locked:
        # locked 内置格式（公司 SQL 口径）只允许启停
        if payload.enabled is None or any(
            value is not None
            for value in (
                payload.name,
                payload.description,
                payload.group_by,
                payload.headline_enabled,
                payload.headline_auto_top_n,
                payload.item_fields,
                payload.export_targets,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Locked builtin format only allows enabled toggle",
            )
        fmt.enabled = payload.enabled
        session.commit()
        session.refresh(fmt)
        return _format_to_read(fmt)

    _validate_format_options(
        payload.group_by or fmt.group_by,
        payload.item_fields if payload.item_fields is not None else list((fmt.item_fields or {}).get("fields") or []),
        payload.export_targets
        if payload.export_targets is not None
        else list((fmt.export_targets or {}).get("targets") or []),
    )
    if payload.name is not None:
        fmt.name = payload.name.strip()
    if payload.description is not None:
        fmt.description = payload.description.strip()
    if payload.group_by is not None:
        fmt.group_by = payload.group_by
    if payload.headline_enabled is not None:
        fmt.headline_enabled = payload.headline_enabled
    if payload.headline_auto_top_n is not None:
        fmt.headline_auto_top_n = payload.headline_auto_top_n
    if payload.item_fields is not None:
        fmt.item_fields = {"fields": payload.item_fields}
    if payload.export_targets is not None:
        fmt.export_targets = {"targets": payload.export_targets}
    if payload.enabled is not None:
        fmt.enabled = payload.enabled
    session.commit()
    session.refresh(fmt)
    return _format_to_read(fmt)


@router.delete("/report-formats/{format_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report_format(
    format_id: str,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> Response:
    fmt = session.get(ReportFormat, format_id)
    if fmt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report format not found")
    if fmt.builtin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Builtin formats cannot be deleted")
    session.query(ReportRendition).filter(ReportRendition.format_code == fmt.format_code).delete()
    session.delete(fmt)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/daily-reports/{report_id}/renditions", response_model=list[ReportRenditionRead])
def list_daily_renditions(
    report_id: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[ReportRenditionRead]:
    report = load_daily_report_for_rendition(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")
    renditions = session.scalars(
        select(ReportRendition).where(
            ReportRendition.report_type == "daily",
            ReportRendition.report_id == report_id,
        ),
    ).all()
    return [_rendition_to_read(rendition) for rendition in renditions]


@router.post(
    "/daily-reports/{report_id}/renditions/{format_code}/regenerate",
    response_model=ReportRenditionRead,
)
def regenerate_daily_rendition(
    report_id: str,
    format_code: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ReportRenditionRead:
    report = load_daily_report_for_rendition(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")
    fmt = _get_enabled_format(session, report.workspace_code, format_code)
    workspace_name = _workspace_name(session, report.workspace_code)
    rendition = build_daily_rendition(session, report, fmt, workspace_name)
    session.commit()
    session.refresh(rendition)
    return _rendition_to_read(rendition)


@router.get("/daily-reports/{report_id}/renditions/{format_code}/export")
def export_daily_rendition(
    report_id: str,
    format_code: str,
    target: str = Query(default="md"),
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    if target not in REPORT_FORMAT_EXPORT_TARGETS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target must be md or html")
    report = load_daily_report_for_rendition(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")
    fmt = _get_enabled_format(session, report.workspace_code, format_code)
    allowed_targets = list((fmt.export_targets or {}).get("targets") or [])
    if target not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Format {format_code} does not export {target}",
        )
    workspace_name = _workspace_name(session, report.workspace_code)
    rendition = build_daily_rendition(session, report, fmt, workspace_name)
    session.commit()

    filename = f"{rendition.title.replace(' ', '-')}.{target}"
    if target == "md":
        content = render_markdown(rendition)
        media_type = "text/markdown; charset=utf-8"
    else:
        content = render_html(rendition)
        media_type = "text/html; charset=utf-8"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_rfc5987(filename)}"},
    )


@router.post(
    "/weekly-reports/{report_id}/renditions/{format_code}/regenerate",
    response_model=ReportRenditionRead,
)
def regenerate_weekly_rendition(
    report_id: str,
    format_code: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ReportRenditionRead:
    report = load_weekly_report(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly report not found")
    fmt = _get_enabled_format(session, report.workspace_code, format_code)
    workspace_name = _workspace_name(session, report.workspace_code)
    rendition = build_weekly_rendition(session, report, fmt, workspace_name)
    session.commit()
    session.refresh(rendition)
    return _rendition_to_read(rendition)


@router.get("/weekly-reports/{report_id}/renditions/{format_code}/export")
def export_weekly_rendition(
    report_id: str,
    format_code: str,
    target: str = Query(default="md"),
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    if target not in REPORT_FORMAT_EXPORT_TARGETS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target must be md or html")
    report = load_weekly_report(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly report not found")
    fmt = _get_enabled_format(session, report.workspace_code, format_code)
    allowed_targets = list((fmt.export_targets or {}).get("targets") or [])
    if target not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Format {format_code} does not export {target}",
        )
    workspace_name = _workspace_name(session, report.workspace_code)
    rendition = build_weekly_rendition(session, report, fmt, workspace_name)
    session.commit()

    filename = f"{rendition.title.replace(' ', '-')}.{target}"
    if target == "md":
        content = render_markdown(rendition)
        media_type = "text/markdown; charset=utf-8"
    else:
        content = render_html(rendition)
        media_type = "text/html; charset=utf-8"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_rfc5987(filename)}"},
    )


def _rfc5987(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _require_workspace(session: Session, workspace_code: str) -> Workspace:
    workspace = session.scalar(
        select(Workspace).where(Workspace.code == workspace_code, Workspace.enabled.is_(True)),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


def _workspace_name(session: Session, workspace_code: str) -> str:
    workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
    return workspace.name if workspace else workspace_code


def _get_enabled_format(session: Session, workspace_code: str, format_code: str) -> ReportFormat:
    ensure_report_formats(session, workspace_code)
    fmt = session.scalar(
        select(ReportFormat).where(
            ReportFormat.workspace_code == workspace_code,
            ReportFormat.format_code == format_code,
            ReportFormat.enabled.is_(True),
        ),
    )
    if fmt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report format not found or disabled")
    return fmt


def _validate_format_options(group_by: str, item_fields: list[str], export_targets: list[str]) -> None:
    if group_by not in REPORT_FORMAT_GROUP_BY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"group_by must be one of: {', '.join(REPORT_FORMAT_GROUP_BY)}",
        )
    invalid_fields = [field for field in item_fields if field not in REPORT_FORMAT_ITEM_FIELDS]
    if invalid_fields or not item_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"item_fields must be non-empty subset of: {', '.join(REPORT_FORMAT_ITEM_FIELDS)}",
        )
    invalid_targets = [target for target in export_targets if target not in REPORT_FORMAT_EXPORT_TARGETS]
    if invalid_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"export_targets must be subset of: {', '.join(REPORT_FORMAT_EXPORT_TARGETS)}",
        )


def _format_to_read(fmt: ReportFormat) -> ReportFormatRead:
    return ReportFormatRead(
        id=fmt.id,
        workspace_code=fmt.workspace_code,
        format_code=fmt.format_code,
        name=fmt.name,
        description=fmt.description,
        builtin=fmt.builtin,
        locked=fmt.locked,
        group_by=fmt.group_by,
        headline_enabled=fmt.headline_enabled,
        headline_auto_top_n=fmt.headline_auto_top_n,
        item_fields=list((fmt.item_fields or {}).get("fields") or []),
        export_targets=list((fmt.export_targets or {}).get("targets") or []),
        enabled=fmt.enabled,
        sort_order=fmt.sort_order,
    )


def _rendition_to_read(rendition: ReportRendition) -> ReportRenditionRead:
    return ReportRenditionRead(
        id=rendition.id,
        report_type=rendition.report_type,
        report_id=rendition.report_id,
        format_code=rendition.format_code,
        status=rendition.status,
        title=rendition.title,
        summary_json=rendition.summary_json or {},
        body_json=rendition.body_json or {},
        generated_by=rendition.generated_by,
        generated_at=rendition.generated_at,
    )
