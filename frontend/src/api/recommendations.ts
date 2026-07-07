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

// ---------------------------------------------------------------------------
// 反馈回哺（WP4-G，feedback-heat-scoring §16.2；契约 feedback_workflow.api）
// ---------------------------------------------------------------------------

export interface FeedbackRollupMetrics {
  precision_at_6?: number | null;
  precision_at_12?: number | null;
  rerank_uplift?: number | null;
  source_coverage?: number | null;
  topic_entropy?: number | null;
  normalized_adopt_rate?: number | null;
  edit_rate?: number | null;
  drift_flag?: boolean;
  signal_counts?: Record<string, number>;
  low_data_sources?: { id: string; name: string }[];
  [key: string]: unknown;
}

export interface FeedbackRollupRecord {
  id: string;
  workspace_code: string;
  period_type: "weekly" | "monthly";
  period_key: string;
  window_start: string | null;
  window_end: string | null;
  status: string;
  proposal_status: string;
  metrics: FeedbackRollupMetrics;
  computed_at: string | null;
}

export interface FeedbackRollupSourceEntry {
  data_source_id: string;
  name: string;
  recommended_count: number;
  adopted_count: number;
  rejected_count: number;
  normalized_adopt_rate: number;
  reject_rate: number;
  suggestion: string;
}

export interface FeedbackRollupDetailRecord extends FeedbackRollupRecord {
  source_breakdown: {
    window?: string;
    sources?: FeedbackRollupSourceEntry[];
    stale_source_suggestions?: { id: string; name: string; suggestion: string; reason: string }[];
  };
  topic_breakdown: Record<string, unknown>;
  sample_refs: Record<string, unknown>;
}

export interface FeedbackRollupListResult {
  items: FeedbackRollupRecord[];
  total: number;
}

export interface RubricChangeSummaryEntry {
  op: string;
  target_code: string;
  from: unknown;
  to: unknown;
  rationale: string;
}

export interface RubricRevisionProposalRecord {
  id: string;
  workspace_code: string;
  rollup_id: string;
  rollup_period_key: string;
  base_rubric_version: number;
  prompt_version: string;
  proposed_rubric: Record<string, unknown>;
  change_summary: RubricChangeSummaryEntry[];
  sample_refs: { adopted?: string[]; rejected?: string[] };
  status: string;
  review_comment: string;
  reviewed_at: string | null;
  compile_fingerprint: string;
  created_at: string | null;
}

export interface WorkspaceRecommendationPolicyRecord {
  workspace_code: string;
  policy: {
    rubric_version: number;
    rubric_status: string;
    feedback_workflow: {
      weekly_rollup_enabled: boolean;
      monthly_review_enabled: boolean;
      proposal_generation_enabled: boolean;
      exploration_epsilon: number;
    };
    [key: string]: unknown;
  };
  resolved: Record<string, unknown>;
}

export async function fetchWorkspaceRecommendationPolicy(
  workspaceCode: string
): Promise<WorkspaceRecommendationPolicyRecord> {
  return requestJson<WorkspaceRecommendationPolicyRecord>(
    `/api/workspaces/${workspaceCode}/recommendation-policy`
  );
}

export async function fetchFeedbackRollups(
  workspaceCode: string,
  periodType: "weekly" | "monthly",
  limit = 8
): Promise<FeedbackRollupListResult> {
  const params = new URLSearchParams({ period_type: periodType, limit: String(limit) });
  return requestJson<FeedbackRollupListResult>(
    `/api/workspaces/${workspaceCode}/feedback-rollups?${params.toString()}`
  );
}

export async function fetchFeedbackRollupDetail(
  workspaceCode: string,
  rollupId: string
): Promise<FeedbackRollupDetailRecord> {
  return requestJson<FeedbackRollupDetailRecord>(
    `/api/workspaces/${workspaceCode}/feedback-rollups/${rollupId}`
  );
}

export async function runFeedbackRollup(
  workspaceCode: string,
  payload: { period_type: "weekly" | "monthly"; period_key?: string }
): Promise<FeedbackRollupDetailRecord> {
  return requestJson<FeedbackRollupDetailRecord>(
    `/api/workspaces/${workspaceCode}/feedback-rollups/run`,
    {
      method: "POST",
      body: JSON.stringify(payload)
    }
  );
}

export async function fetchRubricRevisionProposals(
  workspaceCode: string,
  status = "pending_review"
): Promise<{ items: RubricRevisionProposalRecord[] }> {
  const params = new URLSearchParams({ status });
  return requestJson<{ items: RubricRevisionProposalRecord[] }>(
    `/api/workspaces/${workspaceCode}/rubric-revision-proposals?${params.toString()}`
  );
}

export async function reviewRubricRevisionProposal(
  workspaceCode: string,
  proposalId: string,
  payload: { action: "accept" | "reject"; comment: string }
): Promise<RubricRevisionProposalRecord> {
  return requestJson<RubricRevisionProposalRecord>(
    `/api/workspaces/${workspaceCode}/rubric-revision-proposals/${proposalId}/review`,
    {
      method: "POST",
      body: JSON.stringify(payload)
    }
  );
}
