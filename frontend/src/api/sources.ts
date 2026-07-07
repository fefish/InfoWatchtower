import { requestJson } from "./http";

export interface DataSourceRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  source_type: string;
  name: string;
  url: string | null;
  enabled: boolean;
  default_focus_id: number;
  backfill_days: number;
  source_score: number;
  last_fetch_at: string | null;
  last_success_at: string | null;
  last_error: string;
  primary_category: string;
  info_category: string;
  source_tags: string[];
  source_secondary_tags: string[];
  source_tier: string;
  source_channel_type: string;
  expert_routes: string[];
  inclusion_recommendation: string;
  metadata_only: boolean;
  needs_entry: boolean;
  fetch_entry_status: string;
  source_quality_notes: string;
  workspace_link_enabled: boolean | null;
  workspace_source_weight: number | null;
  workspace_daily_limit: number | null;
  workspace_clustering_config: Record<string, unknown>;
}

export interface SourceRecentRawRecord {
  id: string;
  source_title: string;
  source_url: string | null;
  raw_content_excerpt: string;
  fetched_at: string;
  published_at: string | null;
}

export interface SourceRunSummaryRecord {
  run_id: string;
  run_key: string;
  run_type: string;
  status: string;
  completed_at: string | null;
  fetched: number;
  created: number;
  updated: number;
  error: string;
}

export interface SourceTrendPointRecord {
  day_key: string;
  raw_count: number;
}

export interface SourceDetailRecord {
  source: DataSourceRecord;
  raw_count: number;
  news_count: number;
  recent_raw_items: SourceRecentRawRecord[];
  recent_runs: SourceRunSummaryRecord[];
  error_logs: SourceRunSummaryRecord[];
  raw_trend: SourceTrendPointRecord[];
}

export interface LegacySeedImportResult {
  created: number;
  updated: number;
  total: number;
}

export interface TechInsightLoopImportResult {
  created: number;
  updated: number;
  total: number;
  fetchable: number;
  metadata_only: number;
}

export interface SourceImportPreviewSample {
  name: string;
  source_type: string;
  url: string | null;
}

export interface SourceImportPreview {
  catalog: string;
  total: number;
  would_create: number;
  would_update: number;
  samples: SourceImportPreviewSample[];
}

export interface SourceWorkspaceConfigUpdate {
  workspace_code: string;
  enabled: boolean;
  source_weight: number;
  daily_limit: number | null;
}

export interface SourceFetchResult {
  data_source_id: string;
  source_type: string;
  fetched: number;
  created: number;
  updated: number;
}

export interface SourceCreatePayload {
  workspace_code: string;
  name: string;
  source_type: string;
  url: string;
  domain_code?: string;
  backfill_days?: number;
  source_weight?: number;
  daily_limit?: number | null;
  reuse_existing?: boolean;
}

export interface SourceCreateResult {
  source: DataSourceRecord;
  created: boolean;
}

export interface SourceDefinitionUpdatePayload {
  name?: string;
  url?: string;
  enabled?: boolean;
  backfill_days?: number;
}

export async function fetchSources(workspaceCode?: string): Promise<DataSourceRecord[]> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<DataSourceRecord[]>(`/api/sources${params}`);
}

export async function fetchSourceDetail(sourceId: string, workspaceCode?: string): Promise<SourceDetailRecord> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<SourceDetailRecord>(`/api/sources/${sourceId}${params}`);
}

export async function previewSourceImport(catalog: "legacy" | "tech"): Promise<SourceImportPreview> {
  const params = new URLSearchParams({ catalog });
  return requestJson<SourceImportPreview>(`/api/sources/import-preview?${params.toString()}`);
}

export async function importLegacySources(): Promise<LegacySeedImportResult> {
  return requestJson<LegacySeedImportResult>("/api/sources/import-legacy-seeds", {
    method: "POST"
  });
}

export async function importTechInsightLoopSources(): Promise<TechInsightLoopImportResult> {
  return requestJson<TechInsightLoopImportResult>("/api/sources/import-tech-insight-loop", {
    method: "POST"
  });
}

export async function fetchSource(sourceId: string, workspaceCode?: string): Promise<SourceFetchResult> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<SourceFetchResult>(`/api/sources/${sourceId}/fetch${params}`, {
    method: "POST"
  });
}

export async function createSource(payload: SourceCreatePayload): Promise<SourceCreateResult> {
  return requestJson<SourceCreateResult>("/api/sources", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateSourceDefinition(
  sourceId: string,
  payload: SourceDefinitionUpdatePayload,
  workspaceCode?: string
): Promise<DataSourceRecord> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<DataSourceRecord>(`/api/sources/${sourceId}${params}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function updateSourceWorkspaceConfig(
  sourceId: string,
  payload: SourceWorkspaceConfigUpdate
): Promise<DataSourceRecord> {
  return requestJson<DataSourceRecord>(`/api/sources/${sourceId}/workspace-link`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}
