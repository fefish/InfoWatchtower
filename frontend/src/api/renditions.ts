export interface ReportFormatRecord {
  id: string;
  workspace_code: string;
  format_code: string;
  name: string;
  description: string;
  builtin: boolean;
  locked: boolean;
  group_by: string;
  headline_enabled: boolean;
  headline_auto_top_n: number;
  item_fields: string[];
  export_targets: string[];
  enabled: boolean;
  sort_order: number;
}

export interface ReportFormatCreatePayload {
  workspace_code: string;
  format_code: string;
  name: string;
  description?: string;
  group_by: string;
  headline_enabled: boolean;
  headline_auto_top_n: number;
  item_fields: string[];
  export_targets: string[];
}

export interface ReportFormatUpdatePayload {
  name?: string;
  description?: string;
  group_by?: string;
  headline_enabled?: boolean;
  headline_auto_top_n?: number;
  item_fields?: string[];
  export_targets?: string[];
  enabled?: boolean;
}

export interface RenditionItemSnapshot {
  item_id: string;
  generated_news_id: string;
  title: string;
  summary: string;
  category: string;
  board: string;
  tag_line: string[];
  bullet_points: string[];
  takeaway: string;
  insight_source: string;
  five_fields: Record<string, string>;
  source_url: string | null;
  source_name: string;
  score: number;
  is_headline: boolean;
  generation_status: string;
}

export interface RenditionGroup {
  key: string;
  title: string;
  item_ids: string[];
}

export interface ReportRenditionRecord {
  id: string;
  report_type: string;
  report_id: string;
  format_code: string;
  status: string;
  title: string;
  summary_json: {
    period_key?: string;
    item_total?: number;
    group_distribution?: Record<string, number>;
    headline_titles?: string[];
    source_total?: number;
  };
  body_json: {
    format_code?: string;
    group_by?: string;
    item_fields?: string[];
    headlines?: string[];
    groups?: RenditionGroup[];
    items?: Record<string, RenditionItemSnapshot>;
  };
  generated_by: string;
  generated_at: string | null;
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

export async function fetchReportFormats(workspaceCode: string): Promise<ReportFormatRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<ReportFormatRecord[]>(`/api/report-formats?${params.toString()}`);
}

export async function createReportFormat(payload: ReportFormatCreatePayload): Promise<ReportFormatRecord> {
  return requestJson<ReportFormatRecord>("/api/report-formats", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateReportFormat(
  formatId: string,
  payload: ReportFormatUpdatePayload
): Promise<ReportFormatRecord> {
  return requestJson<ReportFormatRecord>(`/api/report-formats/${formatId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function deleteReportFormat(formatId: string): Promise<void> {
  const response = await fetch(`/api/report-formats/${formatId}`, {
    method: "DELETE",
    credentials: "same-origin"
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
}

export async function regenerateDailyRendition(
  reportId: string,
  formatCode: string
): Promise<ReportRenditionRecord> {
  return requestJson<ReportRenditionRecord>(
    `/api/daily-reports/${reportId}/renditions/${formatCode}/regenerate`,
    { method: "POST" }
  );
}

export function dailyRenditionExportUrl(reportId: string, formatCode: string, target: "md" | "html") {
  return `/api/daily-reports/${reportId}/renditions/${formatCode}/export?target=${target}`;
}

export function weeklyRenditionExportUrl(reportId: string, formatCode: string, target: "md" | "html") {
  return `/api/weekly-reports/${reportId}/renditions/${formatCode}/export?target=${target}`;
}
