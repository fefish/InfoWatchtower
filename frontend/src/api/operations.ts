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
  task_count: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RequirementCreatePayload {
  workspace_code: string;
  domain_code?: string;
  title: string;
  description?: string;
  priority?: string;
  status?: string;
  due_at?: string | null;
}

export interface RequirementUpdatePayload {
  title?: string;
  description?: string;
  priority?: string;
  status?: string;
  due_at?: string | null;
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
  assignee_user_id: string | null;
  assignee_name: string | null;
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
}

export interface TopicTaskUpdatePayload {
  requirement_id?: string | null;
  title?: string;
  description?: string;
  status?: string;
  due_at?: string | null;
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

export interface SyncPackageExportRecord {
  sync_run: SyncRunRecord;
  package_manifest: Record<string, unknown>;
  records: Record<string, unknown>[];
}

export interface AuditLogRecord {
  id: string;
  user_id: string | null;
  user_name: string | null;
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

export async function fetchTopicTasks(workspaceCode: string): Promise<TopicTaskRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<TopicTaskRecord[]>(`/api/topic-tasks?${params.toString()}`);
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

export async function fetchSyncRuns(): Promise<SyncRunRecord[]> {
  return requestJson<SyncRunRecord[]>("/api/sync-runs");
}

export async function createSyncRun(): Promise<SyncRunRecord> {
  const result = await requestJson<SyncPackageExportRecord>("/api/sync/packages/export", {
    method: "POST",
    body: JSON.stringify({ source_instance_id: "public", target_instance_id: "intranet", direction: "public_to_intranet" })
  });
  return result.sync_run;
}

export async function fetchSyncPackageDownload(packageId: string): Promise<Blob> {
  const response = await fetch(`/api/sync/packages/${encodeURIComponent(packageId)}/download`, {
    credentials: "same-origin"
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return response.blob();
}

export async function fetchAuditLogs(): Promise<AuditLogRecord[]> {
  return requestJson<AuditLogRecord[]>("/api/audit-logs");
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
