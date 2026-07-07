import { requestBlob, requestJson } from "./http";

export interface RequirementSourceLinkRecord {
  id: string;
  link_type: string;
  note: string;
  insight_id: string | null;
  daily_report_item_id: string | null;
  weekly_report_item_id: string | null;
  entity_milestone_id: string | null;
  historical_report_id: string | null;
  historical_feedback_item_id: string | null;
  news_item_id: string | null;
  raw_item_id: string | null;
  source_object_type: string;
  source_title: string;
  source_url: string | null;
  data_source_name: string | null;
  created_at: string;
}

export interface RequirementRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  title: string;
  description: string;
  priority: string;
  status: string;
  due_at: string | null;
  owner_user_id: string | null;
  owner_name: string | null;
  source_count: number;
  source_links: RequirementSourceLinkRecord[];
  task_count: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface InsightRecord {
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
  source_title: string;
  source_url: string | null;
  data_source_name: string | null;
  implication_count: number;
  confidence_score: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface InsightCreatePayload {
  workspace_code: string;
  domain_code?: string;
  news_item_id: string;
  raw_item_id?: string | null;
  title: string;
  summary?: string;
  insight_type?: string;
  status?: string;
  source_report_type?: string;
  source_report_id?: string | null;
  source_report_item_id?: string | null;
  confidence_score?: number;
}

export interface InsightUpdatePayload {
  title?: string;
  summary?: string;
  insight_type?: string;
  status?: string;
  confidence_score?: number;
}

export interface StrategicImplicationRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  insight_id: string;
  insight_title: string | null;
  title: string;
  description: string;
  implication_type: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface StrategicImplicationCreatePayload {
  insight_id: string;
  title: string;
  description?: string;
  implication_type?: string;
}

export interface StrategicImplicationUpdatePayload {
  title?: string;
  description?: string;
  implication_type?: string;
}

export interface RequirementCreatePayload {
  workspace_code: string;
  domain_code?: string;
  title: string;
  description?: string;
  priority?: string;
  status?: string;
  due_at?: string | null;
  owner_user_id?: string | null;
  source_daily_report_item_id?: string | null;
  source_weekly_report_item_id?: string | null;
  source_entity_milestone_id?: string | null;
  source_historical_report_id?: string | null;
  source_historical_feedback_item_id?: string | null;
  source_news_item_id?: string | null;
  source_raw_item_id?: string | null;
  source_insight_id?: string | null;
  source_note?: string;
}

export interface RequirementUpdatePayload {
  title?: string;
  description?: string;
  priority?: string;
  status?: string;
  due_at?: string | null;
  owner_user_id?: string | null;
  metadata_json?: Record<string, unknown> | null;
}

export interface TopicTaskRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  requirement_id: string | null;
  requirement_title: string | null;
  title: string;
  description: string;
  status: string;
  due_at: string | null;
  is_overdue: boolean;
  blocked_reason: string;
  assignee_user_id: string | null;
  assignee_name: string | null;
  requirement_source_count: number;
  requirement_source_links: RequirementSourceLinkRecord[];
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TopicTaskCreatePayload {
  workspace_code: string;
  domain_code?: string;
  requirement_id?: string | null;
  title: string;
  description?: string;
  status?: string;
  due_at?: string | null;
  assignee_user_id?: string | null;
}

export interface TopicTaskUpdatePayload {
  requirement_id?: string | null;
  title?: string;
  description?: string;
  status?: string;
  due_at?: string | null;
  assignee_user_id?: string | null;
  metadata_json?: Record<string, unknown> | null;
}

export interface TopicTaskBatchUpdatePayload {
  workspace_code: string;
  task_ids: string[];
  status?: string | null;
  blocked_reason?: string | null;
}

export interface TopicTaskBatchUpdateResult {
  updated_count: number;
  tasks: TopicTaskRecord[];
}

export interface TopicTaskFilters {
  status?: string;
  assigneeUserId?: string;
  assignedToMe?: boolean;
  due?: "overdue" | "due_today";
}

export interface SyncRunRecord {
  id: string;
  package_id: string;
  source_instance_id: string;
  target_instance_id: string;
  direction: string;
  status: string;
  counts_json: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export type SyncHealthStatus = "ok" | "warning" | "critical" | "inactive";

export interface SyncHealthAlertRecord {
  severity: "warning" | "critical";
  code: string;
  message: string;
  object_type: string | null;
}

export interface SyncCursorHealthRecord {
  object_type: string;
  cursor: string;
  last_pulled_at: string | null;
  last_status: string;
  last_error: string;
  age_seconds: number | null;
  status: SyncHealthStatus;
  warnings: string[];
}

export interface SyncHealthRecord {
  status: SyncHealthStatus;
  generated_at: string;
  sync_role: string;
  summary: string;
  thresholds: {
    warning_after_seconds: number;
    critical_after_seconds: number;
    pull_interval_seconds: number;
  };
  cursor_count: number;
  missing_cursor_count: number;
  stale_cursor_count: number;
  failed_cursor_count: number;
  failed_inbox_count: number;
  failed_inbox_by_object_type: Record<string, number>;
  failed_inbox_retry_due_count: number;
  failed_inbox_retry_blocked_count: number;
  failed_inbox_next_retry_at: string | null;
  failed_inbox_retry_policy: {
    enabled?: boolean;
    base_delay_seconds?: number;
    max_delay_seconds?: number;
    max_attempts?: number;
    limit?: number;
    [key: string]: unknown;
  };
  open_conflict_count: number;
  recent_failed_run_count: number;
  last_run: SyncRunRecord | null;
  cursors: SyncCursorHealthRecord[];
  alerts: SyncHealthAlertRecord[];
}

export interface SyncPackageExportRecord {
  sync_run: SyncRunRecord;
  package_manifest: Record<string, unknown>;
  records: Record<string, unknown>[];
}

export interface SyncConflictRecord {
  id: string;
  sync_run_id: string;
  package_id: string | null;
  source_instance_id: string | null;
  target_instance_id: string | null;
  direction: string | null;
  object_type: string;
  object_id: string;
  local_revision: number;
  incoming_revision: number;
  field_name: string;
  local_value_json: Record<string, unknown>;
  incoming_value_json: Record<string, unknown>;
  conflict_reason: string;
  status: string;
  resolution_json: Record<string, unknown>;
  resolved_by_user_id: string | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export type SyncConflictResolveStrategy =
  | "keep_local"
  | "ignored"
  | "retry_after_dependency"
  | "use_incoming"
  | "manual_merge";

export interface SyncConflictResolvePayload {
  strategy: SyncConflictResolveStrategy;
  reason?: string;
  merged_json?: Record<string, unknown> | null;
}

export interface SyncConflictFilters {
  status?: "open" | "resolved" | "ignored" | "retry_after_dependency" | "all";
  objectType?: string;
  syncRunId?: string;
  limit?: number;
}

export interface AuditLogRecord {
  id: string;
  user_id: string | null;
  user_name: string | null;
  workspace_code: string;
  action: string;
  object_type: string;
  object_id: string;
  ip_address: string;
  user_agent: string;
  detail_json: Record<string, unknown>;
  created_at: string;
}

export interface HistoricalReportSummaryRecord {
  workspace_code: string;
  total: number;
  by_report_type: Record<string, number>;
  by_status: Record<string, number>;
  unresolved_report_count: number;
  unresolved_ref_count: number;
  earliest_period_start_at: string | null;
  latest_period_start_at: string | null;
}

export interface HistoricalReportListItem {
  id: string;
  workspace_code: string;
  domain_code: string;
  legacy_system: string;
  legacy_id: string;
  report_type: string;
  title: string;
  status: string;
  period_start_at: string | null;
  period_end_at: string | null;
  resolved_ref_count: number;
  unresolved_ref_count: number;
  content_excerpt: string;
  created_at: string;
  updated_at: string;
}

export interface HistoricalReportDetailRecord extends HistoricalReportListItem {
  content: string;
  source_refs_json: Record<string, unknown>;
  metadata_json: Record<string, unknown>;
}

export interface LegacyImportMetricRecord {
  key: string;
  label: string;
  expected: number;
  actual: number;
  missing: number;
  coverage_rate: number;
  status: string;
}

export interface LegacyImportRefStatsRecord {
  total: number;
  resolved: number;
  unresolved: number;
}

export interface LegacyImportSummaryRecord {
  workspace_code: string;
  generated_at: string;
  expected_counts: Record<string, number>;
  metrics: LegacyImportMetricRecord[];
  report_refs: LegacyImportRefStatsRecord;
  milestone_article_refs: LegacyImportRefStatsRecord;
  milestone_report_refs: LegacyImportRefStatsRecord;
  feedback_article_refs: LegacyImportRefStatsRecord;
  total_unresolved_refs: number;
  gap_item_count: number;
}

export interface LegacyImportGapItemRecord {
  kind: string;
  id: string;
  legacy_id: string;
  title: string;
  ref_type: string;
  unresolved_refs: unknown[];
  unresolved_count: number;
  detail_path: string;
  context: Record<string, unknown>;
}

export interface EntityTimelineSummaryRecord {
  workspace_code: string;
  total_entities: number;
  total_milestones: number;
  selected_milestones: number;
  unresolved_milestone_count: number;
  unresolved_ref_count: number;
  by_entity_type: Record<string, number>;
  by_event_type: Record<string, number>;
  by_importance_level: Record<string, number>;
  earliest_event_time: string | null;
  latest_event_time: string | null;
}

export interface TrackedEntityListItem {
  id: string;
  workspace_code: string;
  domain_code: string;
  legacy_system: string;
  legacy_id: string;
  name: string;
  entity_type: string;
  rank: string;
  aliases_json: unknown[];
  influence_score: number;
  milestone_count: number;
  latest_event_time: string | null;
  created_at: string;
  updated_at: string;
}

export interface EntityMilestoneListItem {
  id: string;
  workspace_code: string;
  domain_code: string;
  legacy_system: string;
  legacy_id: string;
  tracked_entity_id: string;
  entity_name: string;
  entity_type: string;
  legacy_article_id: string | null;
  legacy_report_id: string | null;
  raw_item_id: string | null;
  historical_report_id: string | null;
  event_time: string | null;
  event_type: string;
  title: string;
  timeline_brief: string;
  source_url: string | null;
  source_name: string;
  board: string;
  selected_for_timeline: boolean;
  curation_status: string;
  importance_score: number;
  importance_level: string;
  article_ref_resolved: boolean | null;
  report_ref_resolved: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface EntityMilestoneDetailRecord extends EntityMilestoneListItem {
  event_content: string;
  impact: string;
  event_brief: string;
  impact_brief: string;
  confidence_score: number;
  event_dedupe_key: string;
  legacy_refs: Record<string, unknown>;
  metadata_json: Record<string, unknown>;
}

export interface TrackedEntityCreatePayload {
  workspace_code: string;
  domain_code?: string;
  name: string;
  entity_type?: string;
  rank?: string;
  aliases?: string[];
  notes?: string;
  influence_score?: number;
}

export interface TrackedEntityUpdatePayload {
  name?: string;
  entity_type?: string;
  rank?: string;
  aliases?: string[];
  notes?: string;
  influence_score?: number;
}

export interface EntityMilestoneManualCreatePayload {
  tracked_entity_id: string;
  event_title: string;
  event_type?: string;
  event_time?: string | null;
  event_brief?: string;
  impact_brief?: string;
  source_url?: string | null;
  source_name?: string;
  board?: string;
  importance_level?: string;
  importance_score?: number;
  confidence_score?: number;
  news_item_id?: string | null;
  note?: string;
}

export interface EntityTimelineMonthGroupRecord {
  month: string;
  milestone_count: number;
  candidate_count: number;
  milestones: EntityMilestoneListItem[];
}

export interface TrackedEntityTimelineRecord {
  entity: TrackedEntityListItem;
  total_milestones: number;
  candidate_count: number;
  confirmed_count: number;
  groups: EntityTimelineMonthGroupRecord[];
}

export interface ReportArchiveSourceStat {
  name: string;
  count: number;
}

export interface ReportArchiveListItem {
  id: string;
  origin: "published" | "legacy";
  report_type: string;
  workspace_code: string;
  title: string;
  date_key: string;
  month: string;
  status: string;
  published_at: string | null;
  item_count: number;
  adopted_count: number;
  headline_count: number;
  adoption_rate: number;
  top_sources: ReportArchiveSourceStat[];
  detail_kind: "daily_report" | "weekly_report" | "historical_report";
  detail_id: string;
  content_excerpt: string;
}

export interface ReportArchiveMonthBucket {
  month: string;
  count: number;
}

export interface ReportArchiveSummaryRecord {
  workspace_code: string;
  total: number;
  published_daily: number;
  published_weekly: number;
  legacy_reports: number;
  total_items: number;
  total_adopted: number;
  average_adoption_rate: number;
  months: ReportArchiveMonthBucket[];
  latest_published_at: string | null;
}

export interface ReportArchiveFilters {
  workspaceCode?: string;
  month?: string;
  reportType?: string;
  origin?: string;
  query?: string;
  limit?: number;
}

export interface EntityMilestoneUpdatePayload {
  event_title?: string | null;
  event_type?: string | null;
  event_time?: string | null;
  event_brief?: string | null;
  event_content?: string | null;
  impact_brief?: string | null;
  impact?: string | null;
  timeline_brief?: string | null;
  source_url?: string | null;
  source_name?: string | null;
  board?: string | null;
  selected_for_timeline?: boolean | null;
  importance_level?: string | null;
  importance_score?: number | null;
  confidence_score?: number | null;
  curation_status?: string | null;
  curation_note?: string | null;
  metadata_json?: Record<string, unknown> | null;
}

export interface QualityArchiveSummaryRecord {
  workspace_code: string;
  total_feedback: number;
  total_quality_feedback: number;
  total_job_runs: number;
  unresolved_feedback_count: number;
  unresolved_feedback_ref_count: number;
  total_job_failures: number;
  by_feedback_type: Record<string, number>;
  by_quality_reason: Record<string, number>;
  by_job_type: Record<string, number>;
  by_job_status: Record<string, number>;
  latest_feedback_at: string | null;
  latest_job_started_at: string | null;
}

export interface HistoricalFeedbackItemRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  legacy_system: string;
  legacy_table: string;
  legacy_id: string;
  legacy_article_id: string | null;
  raw_item_id: string | null;
  feedback_kind: string;
  user_name: string;
  feedback_type: string;
  reason: string;
  comment: string;
  feedback_at: string | null;
  article_ref_resolved: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface HistoricalJobRunRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  legacy_system: string;
  legacy_table: string;
  legacy_id: string;
  job_type: string;
  status: string;
  message: string;
  started_at: string | null;
  ended_at: string | null;
  total_sources: number;
  processed_sources: number;
  inserted_count: number;
  failed_count: number;
  details_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TrackedEntityFilters {
  workspaceCode?: string;
  entityType?: string;
  rank?: string;
  query?: string;
  limit?: number;
}

export interface EntityMilestoneFilters {
  workspaceCode?: string;
  trackedEntityId?: string;
  entityType?: string;
  eventType?: string;
  importanceLevel?: string;
  board?: string;
  startDate?: string;
  endDate?: string;
  query?: string;
  hasUnresolvedRefs?: boolean | null;
  limit?: number;
}

export interface HistoricalReportFilters {
  workspaceCode?: string;
  reportType?: string;
  status?: string;
  startDate?: string;
  endDate?: string;
  query?: string;
  hasUnresolvedRefs?: boolean | null;
  limit?: number;
}

export interface LegacyImportGapFilters {
  workspaceCode?: string;
  kind?: "all" | "historical_reports" | "entity_milestones" | "historical_feedback";
  limit?: number;
}

export interface HistoricalFeedbackFilters {
  workspaceCode?: string;
  feedbackKind?: string;
  feedbackType?: string;
  query?: string;
  hasUnresolvedRefs?: boolean | null;
  limit?: number;
}

export interface HistoricalJobRunFilters {
  workspaceCode?: string;
  jobType?: string;
  status?: string;
  query?: string;
  limit?: number;
}

function requireWorkspaceCode(workspaceCode: string | undefined): string {
  if (!workspaceCode) {
    throw new Error("workspace_code is required");
  }
  return workspaceCode;
}

export async function fetchRequirements(workspaceCode: string): Promise<RequirementRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<RequirementRecord[]>(`/api/requirements?${params.toString()}`);
}

export async function fetchInsights(
  workspaceCode: string,
  filters: { status?: string; q?: string } = {}
): Promise<InsightRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.q) {
    params.set("q", filters.q);
  }
  return requestJson<InsightRecord[]>(`/api/insights?${params.toString()}`);
}

export async function createInsight(payload: InsightCreatePayload): Promise<InsightRecord> {
  return requestJson<InsightRecord>("/api/insights", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateInsight(id: string, payload: InsightUpdatePayload): Promise<InsightRecord> {
  return requestJson<InsightRecord>(`/api/insights/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function fetchStrategicImplications(
  workspaceCode: string,
  insightId?: string
): Promise<StrategicImplicationRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  if (insightId) {
    params.set("insight_id", insightId);
  }
  return requestJson<StrategicImplicationRecord[]>(`/api/strategic-implications?${params.toString()}`);
}

export async function createStrategicImplication(
  payload: StrategicImplicationCreatePayload
): Promise<StrategicImplicationRecord> {
  return requestJson<StrategicImplicationRecord>("/api/strategic-implications", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateStrategicImplication(
  id: string,
  payload: StrategicImplicationUpdatePayload
): Promise<StrategicImplicationRecord> {
  return requestJson<StrategicImplicationRecord>(`/api/strategic-implications/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function createRequirement(payload: RequirementCreatePayload): Promise<RequirementRecord> {
  return requestJson<RequirementRecord>("/api/requirements", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateRequirement(
  id: string,
  payload: RequirementUpdatePayload
): Promise<RequirementRecord> {
  return requestJson<RequirementRecord>(`/api/requirements/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function fetchTopicTasks(
  workspaceCode: string,
  filters: TopicTaskFilters = {}
): Promise<TopicTaskRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.assigneeUserId) {
    params.set("assignee_user_id", filters.assigneeUserId);
  }
  if (filters.assignedToMe) {
    params.set("assigned_to_me", "true");
  }
  if (filters.due) {
    params.set("due", filters.due);
  }
  return requestJson<TopicTaskRecord[]>(`/api/topic-tasks?${params.toString()}`);
}

export async function fetchTopicTask(id: string): Promise<TopicTaskRecord> {
  return requestJson<TopicTaskRecord>(`/api/topic-tasks/${id}`);
}

export async function createTopicTask(payload: TopicTaskCreatePayload): Promise<TopicTaskRecord> {
  return requestJson<TopicTaskRecord>("/api/topic-tasks", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateTopicTask(id: string, payload: TopicTaskUpdatePayload): Promise<TopicTaskRecord> {
  return requestJson<TopicTaskRecord>(`/api/topic-tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function batchUpdateTopicTasks(payload: TopicTaskBatchUpdatePayload): Promise<TopicTaskBatchUpdateResult> {
  return requestJson<TopicTaskBatchUpdateResult>("/api/topic-tasks/batch", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchSyncRuns(): Promise<SyncRunRecord[]> {
  return requestJson<SyncRunRecord[]>("/api/sync-runs");
}

export async function fetchSyncHealth(): Promise<SyncHealthRecord> {
  return requestJson<SyncHealthRecord>("/api/sync/health");
}

export async function createSyncRun(): Promise<SyncRunRecord> {
  const result = await requestJson<SyncPackageExportRecord>("/api/sync/packages/export", {
    method: "POST",
    body: JSON.stringify({ source_instance_id: "public", target_instance_id: "intranet", direction: "public_to_intranet" })
  });
  return result.sync_run;
}

export async function createSyncPullRun(): Promise<SyncRunRecord> {
  return requestJson<SyncRunRecord>("/api/sync/pull-runs", {
    method: "POST"
  });
}

export async function retryFailedSyncInbox(): Promise<SyncRunRecord> {
  return requestJson<SyncRunRecord>("/api/sync/inbox/retry-failed", {
    method: "POST"
  });
}

export async function fetchSyncPackageDownload(packageId: string): Promise<Blob> {
  return requestBlob(`/api/sync/packages/${encodeURIComponent(packageId)}/download`);
}

export async function fetchSyncConflicts(filters: SyncConflictFilters = {}): Promise<SyncConflictRecord[]> {
  const params = new URLSearchParams({
    status: filters.status ?? "open",
    limit: String(filters.limit ?? 50)
  });
  if (filters.objectType) params.set("object_type", filters.objectType);
  if (filters.syncRunId) params.set("sync_run_id", filters.syncRunId);
  return requestJson<SyncConflictRecord[]>(`/api/sync/conflicts?${params.toString()}`);
}

export async function resolveSyncConflict(
  id: string,
  payload: SyncConflictResolvePayload
): Promise<SyncConflictRecord> {
  return requestJson<SyncConflictRecord>(`/api/sync/conflicts/${id}/resolve`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export interface AuditLogFilters {
  workspaceCode?: string;
  action?: string;
  objectType?: string;
  limit?: number;
}

export async function fetchAuditLogs(filters: AuditLogFilters = {}): Promise<AuditLogRecord[]> {
  const params = new URLSearchParams();
  if (filters.workspaceCode) {
    params.set("workspace_code", filters.workspaceCode);
  }
  if (filters.action) {
    params.set("action", filters.action);
  }
  if (filters.objectType) {
    params.set("object_type", filters.objectType);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return requestJson<AuditLogRecord[]>(query ? `/api/audit-logs?${query}` : "/api/audit-logs");
}

export async function fetchHistoricalReportSummary(workspaceCode: string): Promise<HistoricalReportSummaryRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<HistoricalReportSummaryRecord>(`/api/historical-reports/summary?${params.toString()}`);
}

export async function fetchHistoricalReports(
  filters: HistoricalReportFilters = {}
): Promise<HistoricalReportListItem[]> {
  const params = new URLSearchParams({
    workspace_code: requireWorkspaceCode(filters.workspaceCode),
    limit: String(filters.limit ?? 80)
  });
  if (filters.reportType) params.set("report_type", filters.reportType);
  if (filters.status) params.set("status", filters.status);
  if (filters.startDate) params.set("start_date", filters.startDate);
  if (filters.endDate) params.set("end_date", filters.endDate);
  if (filters.query) params.set("q", filters.query);
  if (filters.hasUnresolvedRefs !== undefined && filters.hasUnresolvedRefs !== null) {
    params.set("has_unresolved_refs", String(filters.hasUnresolvedRefs));
  }
  return requestJson<HistoricalReportListItem[]>(`/api/historical-reports?${params.toString()}`);
}

export async function fetchHistoricalReportDetail(id: string): Promise<HistoricalReportDetailRecord> {
  return requestJson<HistoricalReportDetailRecord>(`/api/historical-reports/${id}`);
}

export async function fetchLegacyImportSummary(workspaceCode: string): Promise<LegacyImportSummaryRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<LegacyImportSummaryRecord>(`/api/legacy-import/summary?${params.toString()}`);
}

export async function fetchLegacyImportGaps(
  filters: LegacyImportGapFilters = {}
): Promise<LegacyImportGapItemRecord[]> {
  const params = new URLSearchParams({
    workspace_code: requireWorkspaceCode(filters.workspaceCode),
    kind: filters.kind ?? "all",
    limit: String(filters.limit ?? 20)
  });
  return requestJson<LegacyImportGapItemRecord[]>(`/api/legacy-import/gaps?${params.toString()}`);
}

export async function fetchEntityTimelineSummary(workspaceCode: string): Promise<EntityTimelineSummaryRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<EntityTimelineSummaryRecord>(`/api/entity-timeline/summary?${params.toString()}`);
}

export async function fetchTrackedEntities(
  filters: TrackedEntityFilters = {}
): Promise<TrackedEntityListItem[]> {
  const params = new URLSearchParams({
    workspace_code: requireWorkspaceCode(filters.workspaceCode),
    limit: String(filters.limit ?? 120)
  });
  if (filters.entityType) params.set("entity_type", filters.entityType);
  if (filters.rank) params.set("rank", filters.rank);
  if (filters.query) params.set("q", filters.query);
  return requestJson<TrackedEntityListItem[]>(`/api/tracked-entities?${params.toString()}`);
}

export async function fetchEntityMilestones(
  filters: EntityMilestoneFilters = {}
): Promise<EntityMilestoneListItem[]> {
  const params = new URLSearchParams({
    workspace_code: requireWorkspaceCode(filters.workspaceCode),
    limit: String(filters.limit ?? 120)
  });
  if (filters.trackedEntityId) params.set("tracked_entity_id", filters.trackedEntityId);
  if (filters.entityType) params.set("entity_type", filters.entityType);
  if (filters.eventType) params.set("event_type", filters.eventType);
  if (filters.importanceLevel) params.set("importance_level", filters.importanceLevel);
  if (filters.board) params.set("board", filters.board);
  if (filters.startDate) params.set("start_date", filters.startDate);
  if (filters.endDate) params.set("end_date", filters.endDate);
  if (filters.query) params.set("q", filters.query);
  if (filters.hasUnresolvedRefs !== undefined && filters.hasUnresolvedRefs !== null) {
    params.set("has_unresolved_refs", String(filters.hasUnresolvedRefs));
  }
  return requestJson<EntityMilestoneListItem[]>(`/api/entity-milestones?${params.toString()}`);
}

export async function fetchEntityMilestoneDetail(id: string): Promise<EntityMilestoneDetailRecord> {
  return requestJson<EntityMilestoneDetailRecord>(`/api/entity-milestones/${id}`);
}

export async function createTrackedEntity(payload: TrackedEntityCreatePayload): Promise<TrackedEntityListItem> {
  return requestJson<TrackedEntityListItem>("/api/tracked-entities", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateTrackedEntity(
  id: string,
  payload: TrackedEntityUpdatePayload
): Promise<TrackedEntityListItem> {
  return requestJson<TrackedEntityListItem>(`/api/tracked-entities/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function deleteTrackedEntity(id: string): Promise<{ status: string; id: string }> {
  return requestJson<{ status: string; id: string }>(`/api/tracked-entities/${id}`, {
    method: "DELETE"
  });
}

export async function fetchTrackedEntityTimeline(id: string): Promise<TrackedEntityTimelineRecord> {
  return requestJson<TrackedEntityTimelineRecord>(`/api/tracked-entities/${id}/timeline`);
}

export async function createEntityMilestone(
  payload: EntityMilestoneManualCreatePayload
): Promise<EntityMilestoneDetailRecord> {
  return requestJson<EntityMilestoneDetailRecord>("/api/entity-milestones", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchReportArchive(filters: ReportArchiveFilters = {}): Promise<ReportArchiveListItem[]> {
  const params = new URLSearchParams({
    workspace_code: requireWorkspaceCode(filters.workspaceCode),
    limit: String(filters.limit ?? 60)
  });
  if (filters.month) params.set("month", filters.month);
  if (filters.reportType) params.set("report_type", filters.reportType);
  if (filters.origin) params.set("origin", filters.origin);
  if (filters.query) params.set("q", filters.query);
  return requestJson<ReportArchiveListItem[]>(`/api/report-archive?${params.toString()}`);
}

export async function fetchReportArchiveSummary(workspaceCode: string): Promise<ReportArchiveSummaryRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<ReportArchiveSummaryRecord>(`/api/report-archive/summary?${params.toString()}`);
}

export async function updateEntityMilestone(
  id: string,
  payload: EntityMilestoneUpdatePayload
): Promise<EntityMilestoneDetailRecord> {
  return requestJson<EntityMilestoneDetailRecord>(`/api/entity-milestones/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function fetchQualityArchiveSummary(workspaceCode: string): Promise<QualityArchiveSummaryRecord> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<QualityArchiveSummaryRecord>(`/api/quality-archive/summary?${params.toString()}`);
}

export async function fetchHistoricalFeedbackItems(
  filters: HistoricalFeedbackFilters = {}
): Promise<HistoricalFeedbackItemRecord[]> {
  const params = new URLSearchParams({
    workspace_code: requireWorkspaceCode(filters.workspaceCode),
    limit: String(filters.limit ?? 80)
  });
  if (filters.feedbackKind) params.set("feedback_kind", filters.feedbackKind);
  if (filters.feedbackType) params.set("feedback_type", filters.feedbackType);
  if (filters.query) params.set("q", filters.query);
  if (filters.hasUnresolvedRefs !== undefined && filters.hasUnresolvedRefs !== null) {
    params.set("has_unresolved_refs", String(filters.hasUnresolvedRefs));
  }
  return requestJson<HistoricalFeedbackItemRecord[]>(`/api/historical-feedback-items?${params.toString()}`);
}

export async function fetchHistoricalJobRuns(
  filters: HistoricalJobRunFilters = {}
): Promise<HistoricalJobRunRecord[]> {
  const params = new URLSearchParams({
    workspace_code: requireWorkspaceCode(filters.workspaceCode),
    limit: String(filters.limit ?? 80)
  });
  if (filters.jobType) params.set("job_type", filters.jobType);
  if (filters.status) params.set("status", filters.status);
  if (filters.query) params.set("q", filters.query);
  return requestJson<HistoricalJobRunRecord[]>(`/api/historical-job-runs?${params.toString()}`);
}
