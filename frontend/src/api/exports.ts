import { requestBlob, requestJson } from "./http";

export interface CompanySqlExportRecord {
  export_job_id: string;
  daily_report_id: string;
  workspace_code: string;
  domain_code: string;
  status: string;
  item_count: number;
  statement_count: number;
  sql_text: string;
  sql_text_bytes: number;
  sql_text_preview_bytes: number;
  sql_text_truncated: boolean;
  download_url: string;
  download_filename: string;
  created_at: string;
  completed_at: string | null;
  result_json: Record<string, unknown>;
}

export interface CompanySqlBatchExportItemRecord {
  daily_report_id: string;
  day_key: string | null;
  status: string;
  preflight_status: string;
  export_job_id: string | null;
  download_url: string | null;
  item_count: number;
  statement_count: number;
  sql_text_bytes: number;
  warning_count: number;
  error_count: number;
  errors: string[];
}

export interface CompanySqlBatchExportRecord {
  batch_export_job_id: string;
  workspace_code: string;
  domain_code: string;
  status: string;
  total_reports: number;
  succeeded_count: number;
  failed_count: number;
  skipped_count: number;
  total_item_count: number;
  total_statement_count: number;
  total_sql_text_bytes: number;
  manifest_json: Record<string, unknown>;
  items: CompanySqlBatchExportItemRecord[];
  created_at: string;
  completed_at: string | null;
}

export interface ExportJobRecord {
  id: string;
  export_type: string;
  status: string;
  workspace_code: string;
  domain_code: string;
  params_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  latest_import_receipt: CompanySqlImportReceiptRecord | null;
  created_at: string;
  completed_at: string | null;
}

export interface CompanySqlImportFailureRecord {
  export_job_item_id: string | null;
  sql_sequence: number | null;
  sql_table: string | null;
  error_code: string;
  error_message: string;
  sql_excerpt: string;
}

export interface CompanySqlImportReceiptRecord {
  id: string;
  export_job_id: string;
  workspace_code: string;
  domain_code: string;
  target_system: string;
  import_status: string;
  imported_at: string | null;
  imported_statement_count: number;
  failed_statement_count: number;
  failure_items: CompanySqlImportFailureRecord[];
  notes: string;
  recorded_by_id: string | null;
  recorded_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompanySqlImportReceiptCreatePayload {
  target_system: string;
  import_status: "pending" | "imported" | "failed" | "partial";
  imported_at?: string | null;
  imported_statement_count: number;
  failed_statement_count: number;
  failure_items: Array<{
    export_job_item_id?: string | null;
    sql_sequence?: number | null;
    sql_table?: string | null;
    error_code?: string;
    error_message: string;
    sql_excerpt?: string;
  }>;
  notes: string;
}

export interface CompanySqlPreflightIssueRecord {
  level: string;
  code: string;
  message: string;
  field: string | null;
  daily_report_item_id: string | null;
}

export interface CompanySqlPreflightItemRecord {
  daily_report_item_id: string;
  generated_news_id: string;
  news_item_id: string;
  adoption_status: number;
  status: string;
  title: string;
  source_url: string | null;
  category: string | null;
  errors: CompanySqlPreflightIssueRecord[];
  warnings: CompanySqlPreflightIssueRecord[];
}

export interface CompanySqlPreflightRecord {
  daily_report_id: string;
  workspace_code: string;
  domain_code: string;
  day_key: string;
  report_status: string;
  status: string;
  eligible_count: number;
  blocked_count: number;
  skipped_count: number;
  warning_count: number;
  error_count: number;
  errors: CompanySqlPreflightIssueRecord[];
  warnings: CompanySqlPreflightIssueRecord[];
  items: CompanySqlPreflightItemRecord[];
}

export interface CompanySqlTraceItemRecord {
  export_job_item_id: string;
  sql_sequence: number;
  sql_table: string;
  status: string;
  daily_report_item_id: string;
  generated_news_id: string;
  news_item_id: string;
  raw_item_id: string | null;
  data_source_id: string | null;
  data_source_name: string | null;
  source_type: string | null;
  source_url: string | null;
  source_title: string;
  generated_title: string;
  export_title: string;
  category: string;
  adoption_status: number;
  sql_excerpt: string;
  title_source: string;
  summary_source: string;
  key_points_source: string;
  content_field_sources: Record<string, string>;
  editor_override_fields: string[];
  field_diffs: CompanySqlTraceFieldDiffRecord[];
}

export interface CompanySqlTraceFieldDiffRecord {
  field: string;
  label: string;
  export_source: string;
  export_value_preview: string;
  generated_value_preview: string | null;
  editor_value_preview: string | null;
  raw_value_preview: string | null;
  changed_by_editor: boolean;
  truncated: boolean;
}

export interface CompanySqlTraceRecord {
  export_job_id: string;
  item_count: number;
  statement_count: number;
  trace_items: CompanySqlTraceItemRecord[];
}

export async function fetchExportJobs(workspaceCode?: string): Promise<ExportJobRecord[]> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<ExportJobRecord[]>(`/api/exports${params}`);
}

export async function fetchExportJob(exportJobId: string): Promise<ExportJobRecord> {
  return requestJson<ExportJobRecord>(`/api/exports/${exportJobId}`);
}

export async function fetchCompanySqlTrace(exportJobId: string): Promise<CompanySqlTraceRecord> {
  return requestJson<CompanySqlTraceRecord>(`/api/exports/${exportJobId}/trace`);
}

export async function fetchCompanySqlImportReceipts(exportJobId: string): Promise<CompanySqlImportReceiptRecord[]> {
  return requestJson<CompanySqlImportReceiptRecord[]>(`/api/exports/${exportJobId}/import-receipts`);
}

export async function createCompanySqlImportReceipt(
  exportJobId: string,
  payload: CompanySqlImportReceiptCreatePayload
): Promise<CompanySqlImportReceiptRecord> {
  return requestJson<CompanySqlImportReceiptRecord>(`/api/exports/${exportJobId}/import-receipts`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function downloadExportJob(exportJobId: string): Promise<Blob> {
  return requestBlob(`/api/exports/${exportJobId}/download`);
}

export async function preflightCompanySqlExport(dailyReportId: string): Promise<CompanySqlPreflightRecord> {
  return requestJson<CompanySqlPreflightRecord>(`/api/exports/company-sql/daily-reports/${dailyReportId}/preflight`, {
    method: "POST"
  });
}

export async function createCompanySqlExport(dailyReportId: string): Promise<CompanySqlExportRecord> {
  return requestJson<CompanySqlExportRecord>(`/api/exports/company-sql/daily-reports/${dailyReportId}`, {
    method: "POST"
  });
}

export async function createCompanySqlBatchExport(dailyReportIds: string[]): Promise<CompanySqlBatchExportRecord> {
  return requestJson<CompanySqlBatchExportRecord>("/api/exports/company-sql/daily-reports/batch", {
    method: "POST",
    body: JSON.stringify({ daily_report_ids: dailyReportIds, continue_on_error: true })
  });
}
