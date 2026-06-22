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


class CompanySqlTraceItemRead(BaseModel):
    sql_sequence: int
    sql_table: str
    status: str
    daily_report_item_id: str
    generated_news_id: str
    news_item_id: str
    raw_item_id: str | None
    data_source_id: str | None
    data_source_name: str | None
    source_type: str | None
    source_url: str | None
    source_title: str
    generated_title: str
    category: str
    adoption_status: int
    sql_excerpt: str


class CompanySqlTraceRead(BaseModel):
    export_job_id: str
    item_count: int
    statement_count: int
    trace_items: list[CompanySqlTraceItemRead]
