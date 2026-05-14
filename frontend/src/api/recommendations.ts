export interface RecommendationRunCreate {
  workspace_code: string;
  day_key?: string | null;
  limit: number;
  source_daily_limit: number;
  create_daily_draft: boolean;
}

export interface RecommendationItemRecord {
  id: string;
  news_item_id: string;
  dedupe_group_id: string;
  rank: number;
  quality_score: number;
  topic_score: number;
  freshness_score: number;
  feedback_score: number;
  diversity_score: number;
  source_score: number;
  heat_score: number;
  final_score: number;
  selected: boolean;
  recommendation_reason: string;
  source_title: string;
  source_name: string;
  source_url: string | null;
}

export interface RecommendationRunRecord {
  id: string;
  run_key: string;
  workspace_code: string;
  domain_code: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  params_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
  items: RecommendationItemRecord[];
}

export interface RecommendationRunCreateResult {
  run: RecommendationRunRecord;
  daily_report_id: string | null;
  candidates_total: number;
  selected_total: number;
  generated_total: number;
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

export async function fetchRecommendationRuns(
  workspaceCode: string,
  limit = 30
): Promise<RecommendationRunRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode, limit: String(limit) });
  return requestJson<RecommendationRunRecord[]>(`/api/recommendation/runs?${params.toString()}`);
}

export async function fetchRecommendationRun(runId: string): Promise<RecommendationRunRecord> {
  return requestJson<RecommendationRunRecord>(`/api/recommendation/runs/${runId}`);
}

export async function createRecommendationRun(
  payload: RecommendationRunCreate
): Promise<RecommendationRunCreateResult> {
  return requestJson<RecommendationRunCreateResult>("/api/recommendation/runs", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
