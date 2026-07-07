import { requestJson } from "./http";

export interface NewsItemRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  raw_item_id: string;
  data_source_id: string;
  source_type: string;
  source_name: string;
  source_url: string | null;
  canonical_url: string | null;
  source_title: string;
  normalized_title: string;
  summary: string;
  author: string;
  published_at: string | null;
  focus_id: number;
  dedupe_key: string;
  active: boolean;
  duplicate_of_id: string | null;
  normalization_status: string;
  normalization_notes: string;
}

export interface DedupeGroupItemRecord {
  id: string;
  news_item_id: string;
  is_winner: boolean;
  duplicate_reason: string;
  rank_score: number;
  title: string;
  source_type: string;
  source_name: string;
  source_url: string | null;
}

export interface DedupeGroupRecommendationRecord {
  run_id: string;
  run_key: string;
  day_key: string | null;
  recommendation_item_id: string;
  rank: number;
  selected: boolean;
  final_score: number;
  quality_score: number;
  topic_score: number;
  freshness_score: number;
  feedback_score: number;
  diversity_score: number;
  source_score: number;
  heat_score: number;
  recommendation_reason: string;
  admission_level: string;
  admission_score: number;
  admission_pool: string;
  noise_types: string[];
  reject_reasons: string[];
  scorer_breakdown: Record<string, unknown>;
  expert_routes: string[];
}

export interface DedupeGroupDailyReportRecord {
  daily_report_id: string;
  daily_report_item_id: string;
  day_key: string;
  report_status: string;
  adoption_status: number;
  generated_news_id: string;
  generation_status: string;
  category: string;
}

export interface DedupeGroupLineageNodeRecord {
  object_type: string;
  object_id: string | null;
  label: string;
  status: string;
  review_note: string;
  target_path: string | null;
  occurred_at: string | null;
  metadata: Record<string, unknown>;
}

export interface DedupeGroupLineageRecord {
  nodes: DedupeGroupLineageNodeRecord[];
}

export interface DedupeGroupRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  dedupe_key: string;
  winner_news_item_id: string | null;
  winner_title: string | null;
  winner_published_at: string | null;
  winner_source_type: string | null;
  item_count: number;
  status: string;
  items: DedupeGroupItemRecord[];
  recommendation: DedupeGroupRecommendationRecord | null;
  daily_report: DedupeGroupDailyReportRecord | null;
  lineage: DedupeGroupLineageRecord;
}

export interface NewsNormalizeResult {
  workspace_code: string;
  raw_scanned: number;
  news_created: number;
  news_updated: number;
  raw_skipped: number;
  dedupe_groups_updated: number;
  winners: number;
  losers: number;
}

export async function fetchDedupeGroups(
  workspaceCode: string,
  limit = 80,
  filters: {
    q?: string;
    recommendationStatus?: string;
    dailyStatus?: string;
    admissionLevel?: string;
    sourceType?: string;
    sort?: string;
  } = {}
): Promise<DedupeGroupRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode, limit: String(limit) });
  if (filters.q) {
    params.set("q", filters.q);
  }
  if (filters.recommendationStatus && filters.recommendationStatus !== "all") {
    params.set("recommendation_status", filters.recommendationStatus);
  }
  if (filters.dailyStatus && filters.dailyStatus !== "all") {
    params.set("daily_status", filters.dailyStatus);
  }
  if (filters.admissionLevel) {
    params.set("admission_level", filters.admissionLevel);
  }
  if (filters.sourceType) {
    params.set("source_type", filters.sourceType);
  }
  if (filters.sort) {
    params.set("sort", filters.sort);
  }
  return requestJson<DedupeGroupRecord[]>(`/api/dedupe-groups?${params.toString()}`);
}

export async function fetchNewsItems(
  workspaceCode: string,
  active: boolean | null = null,
  limit = 80
): Promise<NewsItemRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode, limit: String(limit) });
  if (active !== null) {
    params.set("active", String(active));
  }
  return requestJson<NewsItemRecord[]>(`/api/news-items?${params.toString()}`);
}

export async function normalizeNewsItems(
  workspaceCode: string,
  sourceTypes: string[] = [],
  limit: number | null = null
): Promise<NewsNormalizeResult> {
  return requestJson<NewsNormalizeResult>("/api/news-items/normalize", {
    method: "POST",
    body: JSON.stringify({
      workspace_code: workspaceCode,
      source_types: sourceTypes,
      limit
    })
  });
}
