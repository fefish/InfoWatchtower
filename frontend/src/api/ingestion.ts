export interface IngestionRunCreate {
  workspace_code: string;
  source_types: string[];
  limit: number | null;
}

export interface IngestionRunRecord {
  id: string;
  run_key: string;
  workspace_code: string;
  domain_code: string;
  run_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  source_total: number;
  source_succeeded: number;
  source_failed: number;
  items_fetched: number;
  raw_created: number;
  raw_updated: number;
  params_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
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

export async function fetchIngestionRuns(
  workspaceCode: string,
  limit = 30
): Promise<IngestionRunRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode, limit: String(limit) });
  return requestJson<IngestionRunRecord[]>(`/api/ingestion/runs?${params.toString()}`);
}

export async function createIngestionRun(payload: IngestionRunCreate): Promise<IngestionRunRecord> {
  return requestJson<IngestionRunRecord>("/api/ingestion/runs", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
