import { requestJson } from "./http";
import type { EntityMilestoneDetailRecord, RequirementRecord, TopicTaskRecord } from "./operations";

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
  ingestion_max_items_per_source?: number | null;
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

export interface DailyReportBulkAdoptPayload {
  workspace_code: string;
  day_key: string;
  dedupe_group_ids: string[];
  generation_timeout_seconds?: number;
}

export interface DailyReportBulkRejectPayload {
  workspace_code: string;
  day_key: string;
  dedupe_group_ids: string[];
}

export interface DailyReportBulkAdoptResult {
  report: DailyReportRecord;
  created_total: number;
  updated_total: number;
  skipped_total: number;
  skipped_items: Array<{ dedupe_group_id: string; reason: string }>;
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
  weekly_score: number;
  final_score: number;
  heat_score: number;
  feedback_score: number;
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

export interface StrategyLoopInsightRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  news_item_id: string;
  raw_item_id: string | null;
  title: string;
  summary: string;
  insight_type: string;
  status: string;
  source_report_type: string;
  source_report_id: string | null;
  source_report_item_id: string | null;
  confidence_score: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface StrategyLoopImplicationRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  insight_id: string;
  title: string;
  description: string;
  implication_type: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ReportItemStrategyLoopPayload {
  insight_title?: string | null;
  insight_summary?: string | null;
  insight_type?: string;
  confidence_score?: number;
  implication_title?: string | null;
  implication_description?: string | null;
  implication_type?: string;
  requirement_title?: string | null;
  requirement_description?: string | null;
  requirement_priority?: string;
  requirement_status?: string;
  requirement_due_at?: string | null;
  owner_user_id?: string | null;
  source_note?: string;
  create_task?: boolean;
  task_title?: string | null;
  task_description?: string | null;
  task_status?: string;
  task_due_at?: string | null;
  task_assignee_user_id?: string | null;
  metadata_json?: Record<string, unknown>;
}

export interface ReportItemStrategyLoopResult {
  insight: StrategyLoopInsightRecord;
  implication: StrategyLoopImplicationRecord;
  requirement: RequirementRecord;
  task: TopicTaskRecord | null;
}

export interface ReportItemEntityMilestonePayload {
  entity_name: string;
  entity_type?: string;
  entity_rank?: string;
  tracked_entity_id?: string | null;
  event_title?: string | null;
  event_type?: string;
  event_time?: string | null;
  event_brief?: string | null;
  impact_brief?: string | null;
  board?: string | null;
  importance_level?: string;
  importance_score?: number;
  confidence_score?: number;
  source_note?: string;
  metadata_json?: Record<string, unknown>;
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

export async function bulkAdoptDailyReportCandidates(
  payload: DailyReportBulkAdoptPayload
): Promise<DailyReportBulkAdoptResult> {
  return requestJson<DailyReportBulkAdoptResult>("/api/daily-reports/bulk-adopt-from-candidates", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function bulkRejectDailyReportCandidates(
  payload: DailyReportBulkRejectPayload
): Promise<DailyReportBulkAdoptResult> {
  return requestJson<DailyReportBulkAdoptResult>("/api/daily-reports/bulk-reject-from-candidates", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createDailyReportItemInsight(
  itemId: string,
  payload: ReportItemStrategyLoopPayload
): Promise<ReportItemStrategyLoopResult> {
  return requestJson<ReportItemStrategyLoopResult>(`/api/daily-report-items/${itemId}/insights`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createWeeklyReportItemInsight(
  itemId: string,
  payload: ReportItemStrategyLoopPayload
): Promise<ReportItemStrategyLoopResult> {
  return requestJson<ReportItemStrategyLoopResult>(`/api/weekly-report-items/${itemId}/insights`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createDailyReportItemEntityMilestone(
  itemId: string,
  payload: ReportItemEntityMilestonePayload
): Promise<EntityMilestoneDetailRecord> {
  return requestJson<EntityMilestoneDetailRecord>(`/api/daily-report-items/${itemId}/entity-milestones`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createWeeklyReportItemEntityMilestone(
  itemId: string,
  payload: ReportItemEntityMilestonePayload
): Promise<EntityMilestoneDetailRecord> {
  return requestJson<EntityMilestoneDetailRecord>(`/api/weekly-report-items/${itemId}/entity-milestones`, {
    method: "POST",
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
