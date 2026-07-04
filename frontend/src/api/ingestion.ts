export interface IngestionRunCreate {
  workspace_code: string;
  source_types: string[];
  limit: number | null;
  concurrency?: number;
  source_timeout_seconds?: number;
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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
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
