import { requestJson } from "./http";

export interface RecommendationRunCreate {
  workspace_code: string;
  day_key?: string | null;
  limit: number;
  source_daily_limit: number;
  create_daily_draft: boolean;
}

export interface ScorerPolicyPair {
  name: string;
  value: number;
}

export interface ScorerPolicyRecord {
  workspace_code: string;
  config_loaded: boolean;
  enabled: boolean;
  config_version: string;
  config_path: string;
  thresholds: Record<string, number>;
  daily_levels: string[];
  weekly_levels: string[];
  weights: ScorerPolicyPair[];
  top_topics: ScorerPolicyPair[];
  source_tiers: ScorerPolicyPair[];
  source_channels: ScorerPolicyPair[];
  noise_rule_count: number;
  direct_reject_noise_types: string[];
  formula_notes: string[];
}

export interface ScorerPreviewPayload {
  workspace_code: string;
  source_title: string;
  summary: string;
  content: string;
  source_type: string;
  source_name: string;
  source_url: string;
  source_tier: string;
  source_channel_type: string;
  source_score: number;
  source_tags: string[];
  source_secondary_tags: string[];
  board_relevance_json: Record<string, unknown>;
  freshness_score: number;
}

export interface ScorerPreviewRecord {
  workspace_code: string;
  source_title: string;
  admission_level: string;
  admission_score: number;
  admission_pool: string;
  eligible_for_daily: boolean;
  noise_types: string[];
  reject_reasons: string[];
  positive_reasons: string[];
  expert_routes: string[];
  scorer_breakdown: Record<string, unknown>;
  persistence: "not_persisted";
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
  admission_level: string;
  admission_score: number;
  admission_pool: string;
  noise_types: string[];
  reject_reasons: string[];
  scorer_breakdown: Record<string, unknown>;
  expert_routes: string[];
  source_title: string;
  source_name: string;
  source_url: string | null;
  daily_report: {
    daily_report_id: string;
    daily_report_item_id: string;
    day_key: string;
    report_status: string;
    adoption_status: number;
    generated_news_id: string;
    generation_status: string;
  } | null;
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

export async function fetchScorerPolicy(workspaceCode: string): Promise<ScorerPolicyRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<ScorerPolicyRecord>(`/api/recommendation/scorer-policy?${params.toString()}`);
}

export async function previewScorer(payload: ScorerPreviewPayload): Promise<ScorerPreviewRecord> {
  return requestJson<ScorerPreviewRecord>("/api/recommendation/scorer-preview", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
