export interface HealthResponse {
  service: string;
  version: string;
  environment: string;
  database: {
    status: string;
    error_type?: string;
  };
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch("/healthz");
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return response.json() as Promise<HealthResponse>;
}
