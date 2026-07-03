export interface CompanySqlExportRecord {
  export_job_id: string;
  daily_report_id: string;
  workspace_code: string;
  domain_code: string;
  status: string;
  item_count: number;
  statement_count: number;
  sql_text: string;
  created_at: string;
  completed_at: string | null;
  result_json: Record<string, unknown>;
}

export interface ExportJobRecord {
  id: string;
  export_type: string;
  status: string;
  workspace_code: string;
  domain_code: string;
  params_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

export interface CompanySqlTraceItemRecord {
  sql_sequence: number;
  sql_table: string;
  status: string;
  daily_report_item_id: string;
  generated_news_id: string;
  news_item_id: string;
  raw_item_id: string | null;
  data_source_id: string | null;
  data_source_name: string | null;
  source_type: string | null;
  source_url: string | null;
  source_title: string;
  generated_title: string;
  category: string;
  adoption_status: number;
  sql_excerpt: string;
}

export interface CompanySqlTraceRecord {
  export_job_id: string;
  item_count: number;
  statement_count: number;
  trace_items: CompanySqlTraceItemRecord[];
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

export async function fetchExportJobs(workspaceCode?: string): Promise<ExportJobRecord[]> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<ExportJobRecord[]>(`/api/exports${params}`);
}

export async function fetchExportJob(exportJobId: string): Promise<ExportJobRecord> {
  return requestJson<ExportJobRecord>(`/api/exports/${exportJobId}`);
}

export async function fetchCompanySqlTrace(exportJobId: string): Promise<CompanySqlTraceRecord> {
  return requestJson<CompanySqlTraceRecord>(`/api/exports/${exportJobId}/trace`);
}

export async function createCompanySqlExport(dailyReportId: string): Promise<CompanySqlExportRecord> {
  return requestJson<CompanySqlExportRecord>(`/api/exports/company-sql/daily-reports/${dailyReportId}`, {
    method: "POST"
  });
}
