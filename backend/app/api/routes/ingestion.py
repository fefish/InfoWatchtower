from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.database import get_db_session
from app.ingestion.runs import (
    WorkspaceIngestionRequest,
    WorkspaceNotFoundError,
    run_workspace_ingestion,
)
from app.models.content import IngestionRun
from app.models.identity import User
from app.schemas.ingestion import IngestionRunCreate, IngestionRunRead

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.post("/runs", response_model=IngestionRunRead)
async def create_ingestion_run(
    payload: IngestionRunCreate,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> IngestionRunRead:
    try:
        run = await run_workspace_ingestion(
            session,
            WorkspaceIngestionRequest(
                workspace_code=payload.workspace_code,
                source_types=payload.source_types,
                limit=payload.limit,
                concurrency=payload.concurrency,
                source_timeout_seconds=payload.source_timeout_seconds,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    session.commit()
    session.refresh(run)
    return _run_to_read(run)


@router.get("/runs", response_model=list[IngestionRunRead])
def list_ingestion_runs(
    workspace_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[IngestionRunRead]:
    statement = select(IngestionRun).order_by(IngestionRun.created_at.desc())
    if workspace_code:
        statement = statement.where(IngestionRun.workspace_code == workspace_code)
    runs = session.scalars(statement.limit(limit)).all()
    return [_run_to_read(run) for run in runs]


@router.get("/runs/{run_id}", response_model=IngestionRunRead)
def get_ingestion_run(
    run_id: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> IngestionRunRead:
    run = session.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found")
    return _run_to_read(run)


def _run_to_read(run: IngestionRun) -> IngestionRunRead:
    return IngestionRunRead(
        id=run.id,
        run_key=run.run_key,
        workspace_code=run.workspace_code,
        domain_code=run.domain_code,
        run_type=run.run_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        source_total=run.source_total,
        source_succeeded=run.source_succeeded,
        source_failed=run.source_failed,
        items_fetched=run.items_fetched,
        raw_created=run.raw_created,
        raw_updated=run.raw_updated,
        params_json=run.params_json or {},
        summary_json=run.summary_json or {},
    )
