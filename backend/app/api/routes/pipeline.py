from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.routes.auth import assert_workspace_member, get_current_user, require_capability
from app.core.database import get_db_session
from app.models.identity import User
from app.pipeline.daily import DailyPipelineRequest, daily_pipeline_payload, run_daily_pipeline
from app.recommendations.service import PublishedDailyReportError
from app.schemas.pipeline import DailyPipelineRunCreate, DailyPipelineRunRead

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)
# 含采集阶段，intranet 形态整条本地管线关闭（消费远端成稿）
INGESTION_CAPABILITY = Depends(require_capability("ingestion"))


@router.post("/daily-runs", response_model=DailyPipelineRunRead, dependencies=[INGESTION_CAPABILITY])
async def create_daily_pipeline_run(
    payload: DailyPipelineRunCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyPipelineRunRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        result = await run_daily_pipeline(
            session,
            DailyPipelineRequest(
                workspace_code=payload.workspace_code,
                day_key=payload.day_key,
                source_types=payload.source_types,
                ingestion_limit=payload.ingestion_limit,
                ingestion_concurrency=payload.ingestion_concurrency,
                ingestion_source_timeout_seconds=payload.ingestion_source_timeout_seconds,
                ingestion_max_items_per_source=payload.ingestion_max_items_per_source,
                recommendation_limit=payload.recommendation_limit,
                source_daily_limit=payload.source_daily_limit,
                generation_timeout_seconds=payload.generation_timeout_seconds,
                create_daily_draft=payload.create_daily_draft,
                run_ingestion=payload.run_ingestion,
            ),
        )
    except PublishedDailyReportError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return DailyPipelineRunRead(**daily_pipeline_payload(result))
