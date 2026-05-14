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

export async function fetchExportJobs(): Promise<ExportJobRecord[]> {
  return requestJson<ExportJobRecord[]>("/api/exports");
}

export async function fetchExportJob(exportJobId: string): Promise<ExportJobRecord> {
  return requestJson<ExportJobRecord>(`/api/exports/${exportJobId}`);
}

export async function createCompanySqlExport(dailyReportId: string): Promise<CompanySqlExportRecord> {
  return requestJson<CompanySqlExportRecord>(`/api/exports/company-sql/daily-reports/${dailyReportId}`, {
    method: "POST"
  });
}
