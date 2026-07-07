from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CompanySqlExportRead(BaseModel):
    export_job_id: str
    daily_report_id: str
    workspace_code: str
    domain_code: str
    status: str
    item_count: int
    statement_count: int
    sql_text: str
    sql_text_bytes: int
    sql_text_preview_bytes: int
    sql_text_truncated: bool
    download_url: str
    download_filename: str
    created_at: datetime
    completed_at: datetime | None
    result_json: dict[str, Any]


class CompanySqlBatchExportCreate(BaseModel):
    daily_report_ids: list[str] = Field(min_length=1, max_length=31)
    continue_on_error: bool = True


class CompanySqlBatchExportItemRead(BaseModel):
    daily_report_id: str
    day_key: str | None
    status: str
    preflight_status: str
    export_job_id: str | None
    download_url: str | None
    item_count: int
    statement_count: int
    sql_text_bytes: int
    warning_count: int
    error_count: int
    errors: list[str]


class CompanySqlBatchExportRead(BaseModel):
    batch_export_job_id: str
    workspace_code: str
    domain_code: str
    status: str
    total_reports: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    total_item_count: int
    total_statement_count: int
    total_sql_text_bytes: int
    manifest_json: dict[str, Any]
    items: list[CompanySqlBatchExportItemRead]
    created_at: datetime
    completed_at: datetime | None


class CompanySqlPreflightIssueRead(BaseModel):
    level: str
    code: str
    message: str
    field: str | None = None
    daily_report_item_id: str | None = None


class CompanySqlPreflightItemRead(BaseModel):
    daily_report_item_id: str
    generated_news_id: str
    news_item_id: str
    adoption_status: int
    status: str
    title: str
    source_url: str | None
    category: str | None
    errors: list[CompanySqlPreflightIssueRead]
    warnings: list[CompanySqlPreflightIssueRead]


class CompanySqlPreflightRead(BaseModel):
    daily_report_id: str
    workspace_code: str
    domain_code: str
    day_key: str
    report_status: str
    status: str
    eligible_count: int
    blocked_count: int
    skipped_count: int
    warning_count: int
    error_count: int
    errors: list[CompanySqlPreflightIssueRead]
    warnings: list[CompanySqlPreflightIssueRead]
    items: list[CompanySqlPreflightItemRead]


CompanySqlImportStatus = Literal["pending", "imported", "failed", "partial"]


class CompanySqlImportFailureCreate(BaseModel):
    export_job_item_id: str | None = None
    sql_sequence: int | None = Field(default=None, ge=1)
    sql_table: str | None = None
    error_code: str = ""
    error_message: str = Field(min_length=1, max_length=2000)
    sql_excerpt: str = ""


class CompanySqlImportReceiptCreate(BaseModel):
    target_system: str = Field(default="company_intranet", min_length=1, max_length=128)
    import_status: CompanySqlImportStatus
    imported_at: datetime | None = None
    imported_statement_count: int = Field(default=0, ge=0)
    failed_statement_count: int = Field(default=0, ge=0)
    failure_items: list[CompanySqlImportFailureCreate] = Field(default_factory=list, max_length=200)
    notes: str = Field(default="", max_length=4000)


class CompanySqlImportFailureRead(BaseModel):
    export_job_item_id: str | None
    sql_sequence: int | None
    sql_table: str | None
    error_code: str
    error_message: str
    sql_excerpt: str


class CompanySqlImportReceiptRead(BaseModel):
    id: str
    export_job_id: str
    workspace_code: str
    domain_code: str
    target_system: str
    import_status: str
    imported_at: datetime | None
    imported_statement_count: int
    failed_statement_count: int
    failure_items: list[CompanySqlImportFailureRead]
    notes: str
    recorded_by_id: str | None
    recorded_by_name: str | None
    created_at: datetime
    updated_at: datetime


class ExportJobRead(BaseModel):
    id: str
    export_type: str
    status: str
    workspace_code: str
    domain_code: str
    params_json: dict[str, Any]
    result_json: dict[str, Any]
    latest_import_receipt: CompanySqlImportReceiptRead | None = None
    created_at: datetime
    completed_at: datetime | None


class CompanySqlTraceFieldDiffRead(BaseModel):
    field: str
    label: str
    export_source: str
    export_value_preview: str
    generated_value_preview: str | None
    editor_value_preview: str | None
    raw_value_preview: str | None
    changed_by_editor: bool
    truncated: bool


class CompanySqlTraceItemRead(BaseModel):
    export_job_item_id: str
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
    export_title: str
    category: str
    adoption_status: int
    sql_excerpt: str
    title_source: str
    summary_source: str
    key_points_source: str
    content_field_sources: dict[str, str]
    editor_override_fields: list[str]
    field_diffs: list[CompanySqlTraceFieldDiffRead]


class CompanySqlTraceRead(BaseModel):
    export_job_id: str
    item_count: int
    statement_count: int
    trace_items: list[CompanySqlTraceItemRead]
