export interface RecommendationRunCreate {
  workspace_code: string;
  day_key?: string | null;
  limit: number;
  source_daily_limit: number;
  create_daily_draft: boolean;
}

export interface RecommendationRunCreateResult {
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
  source_url: string | null;
  generation_status: string;
  news_item_id: string;
  recommendation_item_id: string;
}

export interface DailyReportItemRecord {
  id: string;
  generated_news: GeneratedNewsRecord;
  adoption_status: number;
  sort_order: number;
  editor_title: string | null;
  editor_summary: string | null;
  editor_key_points: string | null;
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

export async function fetchDailyReports(workspaceCode: string): Promise<DailyReportRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<DailyReportRecord[]>(`/api/daily-reports?${params.toString()}`);
}

export async function publishDailyReport(reportId: string): Promise<DailyReportRecord> {
  return requestJson<DailyReportRecord>(`/api/daily-reports/${reportId}/publish`, {
    method: "POST"
  });
}
