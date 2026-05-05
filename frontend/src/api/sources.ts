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
  workspace_link_enabled: boolean | null;
  workspace_source_weight: number | null;
  workspace_daily_limit: number | null;
  workspace_label_set_codes: string[];
  workspace_default_label_paths: string[];
  workspace_clustering_config: Record<string, unknown>;
}

export interface LegacySeedImportResult {
  created: number;
  updated: number;
  total: number;
}

export interface SourceWorkspaceConfigUpdate {
  workspace_code: string;
  enabled: boolean;
  source_weight: number;
  daily_limit: number | null;
  label_set_codes: string[];
  default_label_paths: string[];
  clustering_config: Record<string, unknown>;
}

export interface SourceFetchResult {
  data_source_id: string;
  source_type: string;
  fetched: number;
  created: number;
  updated: number;
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

export async function fetchSources(workspaceCode?: string): Promise<DataSourceRecord[]> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<DataSourceRecord[]>(`/api/sources${params}`);
}

export async function importLegacySources(): Promise<LegacySeedImportResult> {
  return requestJson<LegacySeedImportResult>("/api/sources/import-legacy-seeds", {
    method: "POST"
  });
}

export async function fetchSource(sourceId: string): Promise<SourceFetchResult> {
  return requestJson<SourceFetchResult>(`/api/sources/${sourceId}/fetch`, {
    method: "POST"
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
