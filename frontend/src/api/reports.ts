export interface RecommendationRunCreate {
  workspace_code: string;
  day_key?: string | null;
  limit: number;
  source_daily_limit: number;
  create_daily_draft: boolean;
  generation_timeout_seconds?: number;
}

export interface RecommendationRunCreateResult {
  daily_report_id: string | null;
  candidates_total: number;
  selected_total: number;
  generated_total: number;
}

export interface DailyPipelineRunCreate {
  workspace_code: string;
  day_key?: string | null;
  source_types: string[];
  ingestion_limit?: number | null;
  recommendation_limit: number;
  source_daily_limit: number;
  generation_timeout_seconds?: number;
  create_daily_draft: boolean;
  run_ingestion: boolean;
}

export interface DailyPipelineRunResult {
  workspace_code: string;
  day_key: string | null;
  ingestion_run_id: string | null;
  ingestion_status: string;
  raw_scanned: number;
  news_created: number;
  news_updated: number;
  raw_skipped: number;
  dedupe_groups_updated: number;
  recommendation_run_id: string;
  daily_report_id: string | null;
  candidates_total: number;
  selected_total: number;
  generated_total: number;
}

export interface GeneratedNewsRecord {
  id: string;
  category: string;
  title: string;
  summary: string;
  key_points: string;
  content_json: Record<string, unknown>;
  source_url: string | null;
  generation_status: string;
  news_item_id: string;
  recommendation_item_id: string;
}

export interface DailyReportItemRecord {
  id: string;
  generated_news: GeneratedNewsRecord;
  adoption_status: number;
  is_headline: boolean;
  sort_order: number;
  editor_title: string | null;
  editor_summary: string | null;
  editor_key_points: string | null;
  editor_content_json: Record<string, unknown> | null;
  editor_notes: string;
  reaction_count: number;
  rating_count: number;
  rating_avg: number;
  comment_count: number;
}

export interface DailyReportRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  day_key: string;
  title: string;
  summary: string;
  status: string;
  published_at: string | null;
  items: DailyReportItemRecord[];
}

export interface DailyReportItemUpdatePayload {
  adoption_status?: number;
  is_headline?: boolean;
  sort_order?: number;
  editor_title?: string;
  editor_summary?: string;
  editor_key_points?: string;
  editor_content_json?: Record<string, unknown>;
  editor_notes?: string;
}

export interface DailyReportGenerationRerunPayload {
  item_ids?: string[] | null;
  limit?: number | null;
  replace_ready?: boolean;
  generation_timeout_seconds?: number;
}

export interface DailyReportGenerationRerunResult {
  report: DailyReportRecord;
  attempted_total: number;
  ready_total: number;
  fallback_total: number;
  skipped_total: number;
}

export interface CommentRecord {
  id: string;
  user_id: string;
  body: string;
  status: string;
  parent_id: string | null;
  root_id: string | null;
  created_at: string;
}

export interface WeeklyReportItemRecord {
  id: string;
  daily_report_item_id: string | null;
  daily_day_key: string | null;
  generated_news: GeneratedNewsRecord | null;
  adoption_status: number;
  sort_order: number;
  editor_title: string | null;
  editor_summary: string | null;
  editor_content_json: Record<string, unknown> | null;
}

export interface WeeklyReportRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  week_key: string;
  title: string;
  summary: string;
  status: string;
  published_at: string | null;
  items: WeeklyReportItemRecord[];
}

export interface WeeklyReportCreatePayload {
  workspace_code: string;
  week_key: string;
  limit: number;
  include_unpublished_daily: boolean;
}

export interface WeeklyReportItemUpdatePayload {
  adoption_status?: number;
  sort_order?: number;
  editor_title?: string;
  editor_summary?: string;
  editor_content_json?: Record<string, unknown>;
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

export async function createRecommendationRun(
  payload: RecommendationRunCreate
): Promise<RecommendationRunCreateResult> {
  return requestJson<RecommendationRunCreateResult>("/api/recommendation/runs", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createDailyPipelineRun(
  payload: DailyPipelineRunCreate
): Promise<DailyPipelineRunResult> {
  return requestJson<DailyPipelineRunResult>("/api/pipeline/daily-runs", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchDailyReports(workspaceCode: string): Promise<DailyReportRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<DailyReportRecord[]>(`/api/daily-reports?${params.toString()}`);
}

export async function fetchDailyReport(reportId: string): Promise<DailyReportRecord> {
  return requestJson<DailyReportRecord>(`/api/daily-reports/${reportId}`);
}

export async function regenerateDailyReportGeneratedNews(
  reportId: string,
  payload: DailyReportGenerationRerunPayload
): Promise<DailyReportGenerationRerunResult> {
  return requestJson<DailyReportGenerationRerunResult>(
    `/api/daily-reports/${reportId}/regenerate-generated-news`,
    {
      method: "POST",
      body: JSON.stringify(payload)
    }
  );
}

export async function publishDailyReport(reportId: string): Promise<DailyReportRecord> {
  return requestJson<DailyReportRecord>(`/api/daily-reports/${reportId}/publish`, {
    method: "POST"
  });
}

export async function updateDailyReportItem(
  itemId: string,
  payload: DailyReportItemUpdatePayload
): Promise<DailyReportItemRecord> {
  return requestJson<DailyReportItemRecord>(`/api/daily-report-items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function reactToDailyReportItem(itemId: string): Promise<{ id: string; active: boolean }> {
  return requestJson<{ id: string; active: boolean }>(`/api/daily-report-items/${itemId}/reactions`, {
    method: "POST",
    body: JSON.stringify({ reaction_type: "like", active: true })
  });
}

export async function rateDailyReportItem(itemId: string, score: number): Promise<void> {
  await requestJson(`/api/daily-report-items/${itemId}/ratings`, {
    method: "POST",
    body: JSON.stringify({ dimension: "overall", score })
  });
}

export async function fetchDailyReportItemComments(itemId: string): Promise<CommentRecord[]> {
  return requestJson<CommentRecord[]>(`/api/daily-report-items/${itemId}/comments`);
}

export async function createDailyReportItemComment(
  itemId: string,
  body: string,
  parentId?: string | null
): Promise<CommentRecord> {
  return requestJson<CommentRecord>(`/api/daily-report-items/${itemId}/comments`, {
    method: "POST",
    body: JSON.stringify({ body, parent_id: parentId ?? null })
  });
}

export async function fetchWeeklyReports(workspaceCode: string): Promise<WeeklyReportRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<WeeklyReportRecord[]>(`/api/weekly-reports?${params.toString()}`);
}

export async function fetchWeeklyReport(reportId: string): Promise<WeeklyReportRecord> {
  return requestJson<WeeklyReportRecord>(`/api/weekly-reports/${reportId}`);
}

export async function createWeeklyReport(payload: WeeklyReportCreatePayload): Promise<WeeklyReportRecord> {
  return requestJson<WeeklyReportRecord>("/api/weekly-reports", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function publishWeeklyReport(reportId: string): Promise<WeeklyReportRecord> {
  return requestJson<WeeklyReportRecord>(`/api/weekly-reports/${reportId}/publish`, {
    method: "POST"
  });
}

export async function updateWeeklyReportItem(
  itemId: string,
  payload: WeeklyReportItemUpdatePayload
): Promise<WeeklyReportItemRecord> {
  return requestJson<WeeklyReportItemRecord>(`/api/weekly-report-items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}
