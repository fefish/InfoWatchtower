from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.routes.auth import require_super_admin
from app.core.database import get_db_session
from app.pipeline.daily import DailyPipelineRequest, daily_pipeline_payload, run_daily_pipeline
from app.recommendations.service import PublishedDailyReportError
from app.schemas.pipeline import DailyPipelineRunCreate, DailyPipelineRunRead

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
SUPER_ADMIN = Depends(require_super_admin)
DB_SESSION = Depends(get_db_session)


@router.post("/daily-runs", response_model=DailyPipelineRunRead)
async def create_daily_pipeline_run(
    payload: DailyPipelineRunCreate,
    _: object = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> DailyPipelineRunRead:
    try:
        result = await run_daily_pipeline(
            session,
            DailyPipelineRequest(
                workspace_code=payload.workspace_code,
                day_key=payload.day_key,
                source_types=payload.source_types,
                ingestion_limit=payload.ingestion_limit,
                recommendation_limit=payload.recommendation_limit,
                source_daily_limit=payload.source_daily_limit,
                create_daily_draft=payload.create_daily_draft,
                run_ingestion=payload.run_ingestion,
            ),
        )
    except PublishedDailyReportError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return DailyPipelineRunRead(**daily_pipeline_payload(result))
