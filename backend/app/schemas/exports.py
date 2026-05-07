from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CompanySqlExportRead(BaseModel):
    export_job_id: str
    daily_report_id: str
    workspace_code: str
    domain_code: str
    status: str
    item_count: int
    statement_count: int
    sql_text: str
    created_at: datetime
    completed_at: datetime | None
    result_json: dict[str, Any]


class ExportJobRead(BaseModel):
    id: str
    export_type: str
    status: str
    workspace_code: str
    domain_code: str
    params_json: dict[str, Any]
    result_json: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
