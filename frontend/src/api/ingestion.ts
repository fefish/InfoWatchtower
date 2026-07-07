import { requestJson } from "./http";

export interface IngestionRunCreate {
  workspace_code: string;
  source_types: string[];
  limit: number | null;
  concurrency?: number;
  source_timeout_seconds?: number;
}

export interface IngestionRetryFailedCreate {
  concurrency?: number;
  source_timeout_seconds?: number;
  max_items_per_source?: number | null;
}

export interface HistoricalBackfillCreate {
  workspace_code: string;
  target_day_start: string;
  target_day_end: string;
  source_types: string[];
  limit: number | null;
  include_undated: boolean;
  concurrency?: number;
  source_timeout_seconds?: number;
  backfill_mode?: string;
  source_scope?: string;
  retry_policy?: string;
  manual_items?: Record<string, unknown>[];
}

export interface ManualImportPreviewCreate {
  workspace_code: string;
  source_types: string[];
  default_data_source_id?: string;
  input_text: string;
  input_format?: "auto" | "csv" | "sql";
  filename?: string;
}

export interface ManualImportPreviewError {
  row_number: number;
  code: string;
  message: string;
  raw_text: string;
}

export interface ManualImportPreviewRecord {
  workspace_code: string;
  input_format: string;
  filename: string;
  total_rows: number;
  accepted_count: number;
  rejected_count: number;
  accepted_items: Record<string, unknown>[];
  errors: ManualImportPreviewError[];
  error_report_csv: string;
}

export interface IngestionSourceSummary {
  data_source_id?: string;
  name?: string;
  source_type?: string;
  status?: string;
  error?: string;
  fetched?: number;
  created?: number;
  updated?: number;
  in_target_range?: number;
  out_of_target_range?: number;
  missing_published_at?: number;
}

export interface IngestionRunRecord {
  id: string;
  run_key: string;
  workspace_code: string;
  domain_code: string;
  run_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  source_total: number;
  source_succeeded: number;
  source_failed: number;
  items_fetched: number;
  raw_created: number;
  raw_updated: number;
  params_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
}

export interface IngestionCoverageFunnel {
  enabled_sources: number;
  run_sources: number;
  source_succeeded: number;
  source_failed: number;
  items_fetched: number;
  raw_created: number;
  raw_updated: number;
  raw_in_target: number;
  news_items: number;
  dedupe_winners: number;
  recommendation_candidates: number;
  recommendation_selected: number;
  generated_ready: number;
  daily_adopted: number;
}

export interface IngestionCoverageSource {
  data_source_id: string;
  name: string;
  source_type: string;
  run_status: string;
  error: string;
  run_fetched: number;
  run_created: number;
  run_updated: number;
  in_target_range: number;
  out_of_target_range: number;
  missing_published_at: number;
  raw_in_target: number;
  news_items: number;
  dedupe_winners: number;
  recommendation_candidates: number;
  recommendation_selected: number;
  generated_ready: number;
  daily_adopted: number;
}

export interface IngestionCoverageRecord {
  workspace_code: string;
  day_key: string;
  run_id: string | null;
  run_key: string | null;
  run_type: string | null;
  run_status: string | null;
  target_range: string;
  recommendation_run_id: string | null;
  recommendation_run_key: string | null;
  daily_report_id: string | null;
  daily_report_status: string | null;
  funnel: IngestionCoverageFunnel;
  sources: IngestionCoverageSource[];
}

export interface IngestionCoverageTrendPoint {
  day_key: string;
  run_count: number;
  latest_run_id: string | null;
  latest_run_key: string | null;
  latest_run_status: string | null;
  source_total: number;
  source_succeeded: number;
  source_failed: number;
  source_skipped_unimplemented: number;
  items_fetched: number;
  raw_created: number;
  raw_updated: number;
  success_rate: number;
}

export interface IngestionCoverageFailureTrend {
  data_source_id: string;
  name: string;
  source_type: string;
  failure_count: number;
  last_error: string;
  last_run_id: string;
  last_run_key: string;
  last_failed_at: string | null;
}

export interface IngestionCoverageTrendsRecord {
  workspace_code: string;
  days: number;
  generated_at: string;
  total_runs: number;
  total_source_failed: number;
  total_raw_created: number;
  average_success_rate: number;
  points: IngestionCoverageTrendPoint[];
  top_failed_sources: IngestionCoverageFailureTrend[];
}

export interface IngestionFailedSourceRetryRun {
  run_id: string;
  run_key: string;
  run_type: string;
  status: string;
  failed_source_count: number;
  attempt_count: number;
  last_attempt_at: string | null;
  next_retry_at: string | null;
  blocked: boolean;
  due: boolean;
  latest_retry_run_id: string | null;
  latest_retry_run_key: string | null;
  latest_retry_status: string | null;
}

export interface IngestionFailedSourceRetrySummaryRecord {
  workspace_code: string;
  generated_at: string;
  policy: {
    enabled?: boolean;
    base_delay_seconds?: number;
    max_delay_seconds?: number;
    max_attempts?: number;
    limit?: number;
  };
  due_count: number;
  blocked_count: number;
  next_retry_at: string | null;
  runs: IngestionFailedSourceRetryRun[];
}

export async function fetchIngestionRuns(
  workspaceCode: string,
  limit = 30
): Promise<IngestionRunRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode, limit: String(limit) });
  return requestJson<IngestionRunRecord[]>(`/api/ingestion/runs?${params.toString()}`);
}

export async function createIngestionRun(payload: IngestionRunCreate): Promise<IngestionRunRecord> {
  return requestJson<IngestionRunRecord>("/api/ingestion/runs", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchIngestionRun(runId: string): Promise<IngestionRunRecord> {
  return requestJson<IngestionRunRecord>(`/api/ingestion/runs/${runId}`);
}

export async function retryFailedIngestionRun(
  runId: string,
  payload: IngestionRetryFailedCreate = {}
): Promise<IngestionRunRecord> {
  return requestJson<IngestionRunRecord>(`/api/ingestion/runs/${runId}/retry-failed-sources`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export interface SchedulerConfigRecord {
  enabled: boolean;
  daily_time: string;
  timezone: string;
  interval_seconds: number;
  workspace_code: string;
  source_types: string;
  limit: number | null;
  max_items_per_source: number | null;
  job_mode: string;
  day_offset_days: number;
  failed_source_auto_retry_enabled: boolean;
  failed_source_retry_base_seconds: number;
  failed_source_retry_max_attempts: number;
  failed_source_retry_limit: number;
  config_hint: string;
}

export async function fetchSchedulerConfig(): Promise<SchedulerConfigRecord> {
  return requestJson<SchedulerConfigRecord>("/api/ingestion/scheduler");
}

export async function fetchIngestionCoverage(
  workspaceCode: string,
  dayKey: string,
  runId?: string
): Promise<IngestionCoverageRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode, day_key: dayKey });
  if (runId) {
    params.set("run_id", runId);
  }
  return requestJson<IngestionCoverageRecord>(`/api/ingestion/coverage?${params.toString()}`);
}

export async function fetchIngestionCoverageTrends(
  workspaceCode: string,
  days = 14
): Promise<IngestionCoverageTrendsRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode, days: String(days) });
  return requestJson<IngestionCoverageTrendsRecord>(`/api/ingestion/coverage/trends?${params.toString()}`);
}

export async function fetchFailedSourceRetrySummary(
  workspaceCode: string
): Promise<IngestionFailedSourceRetrySummaryRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<IngestionFailedSourceRetrySummaryRecord>(
    `/api/ingestion/failed-source-retry-summary?${params.toString()}`
  );
}

export async function createHistoricalBackfillRun(
  payload: HistoricalBackfillCreate
): Promise<IngestionRunRecord> {
  return requestJson<IngestionRunRecord>("/api/ingestion/backfill-runs", {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      backfill_mode: payload.backfill_mode ?? "rss_window",
      source_scope: payload.source_scope ?? "source_type",
      retry_policy: payload.retry_policy ?? "manual_run_no_retry"
    })
  });
}

export async function previewManualImport(payload: ManualImportPreviewCreate): Promise<ManualImportPreviewRecord> {
  return requestJson<ManualImportPreviewRecord>("/api/ingestion/manual-import-preview", {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      input_format: payload.input_format ?? "auto",
      filename: payload.filename ?? ""
    })
  });
}
