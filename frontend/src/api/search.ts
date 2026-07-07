import { requestJson } from "./http";

export interface SearchResultRecord {
  object_type: string;
  object_id: string;
  title: string;
  summary: string;
  matched_fields: string[];
  highlight: string;
  route: string;
  score: number;
  updated_at: string | null;
}

export interface SearchResponse {
  query: string;
  workspace_code: string;
  results: SearchResultRecord[];
  next_cursor: string | null;
}

export async function searchWorkspace(
  workspaceCode: string,
  query: string,
  types?: string[],
  limit = 10
): Promise<SearchResponse> {
  const params = new URLSearchParams({
    workspace_code: workspaceCode,
    q: query,
    limit: String(limit)
  });
  if (types && types.length > 0) {
    params.set("types", types.join(","));
  }
  return requestJson<SearchResponse>(`/api/search?${params.toString()}`);
}
