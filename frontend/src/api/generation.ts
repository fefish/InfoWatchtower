/**
 * 生成 provider 工作台策略与连通性自检 API（generation-provider-design §4/§5，WP3-B 供给）。
 *
 * 安全不变式：任何响应字段不含 key 明文——resolved 只有 key_configured /
 * key_source 状态位与 base_url_host；「生成模型」卡只显示"已配置/未配置"。
 */
import { requestJson } from "./http";

export interface GenerationPolicyRecord {
  /** null=跟随实例 env 链；否则引用 llm_provider_credentials 的一行（R2） */
  credential_id: string | null;
  model: string | null;
  temperature: number | null;
  max_tokens: number | null;
  timeout_seconds: number | null;
  daily_generation_budget: number | null;
  fallback_behavior: string;
}

export interface GenerationResolvedRecord {
  provider: string;
  model: string;
  base_url_host: string;
  enabled: boolean;
  key_configured: boolean;
  // credential | credential_ref | env | credential_missing | ""（未配置）
  key_source: string;
  credential_id: string | null;
  credential_label: string | null;
}

/** 「生成模型」卡凭据下拉项（workspace admin+ 才返回；viewer 为 null）。 */
export interface CredentialOptionRecord {
  id: string;
  label: string;
  provider: string;
  base_url_host: string;
  key_masked: string;
}

export interface WorkspaceGenerationPolicyRecord {
  workspace_code: string;
  policy: GenerationPolicyRecord;
  resolved: GenerationResolvedRecord;
  credential_options: CredentialOptionRecord[] | null;
}

/** PATCH 为增量语义：只发送用户改动的字段，未发送字段保持原值。 */
export type WorkspaceGenerationPolicyUpdate = Partial<GenerationPolicyRecord>;

export async function fetchWorkspaceGenerationPolicy(
  workspaceCode: string
): Promise<WorkspaceGenerationPolicyRecord> {
  return requestJson<WorkspaceGenerationPolicyRecord>(`/api/workspaces/${workspaceCode}/generation-policy`);
}

export async function updateWorkspaceGenerationPolicy(
  workspaceCode: string,
  payload: WorkspaceGenerationPolicyUpdate
): Promise<WorkspaceGenerationPolicyRecord> {
  return requestJson<WorkspaceGenerationPolicyRecord>(`/api/workspaces/${workspaceCode}/generation-policy`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export interface GenerationPingRecord {
  // ok | error（错误分类在 error_code：key_missing / dns_or_connect_failed /
  // auth_failed / timeout / http_{status} / bad_response）
  status: string;
  provider: string;
  model: string;
  base_url_host: string;
  key_configured: boolean;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
}

/** 仅 super_admin/editor_admin；最小探针外呼，写审计 generation.ping。
 * R2：credentialId 与 workspaceCode 同给时后端以 credential_id 优先（保存后立即试连）。 */
export async function pingGeneration(
  workspaceCode?: string,
  credentialId?: string
): Promise<GenerationPingRecord> {
  const body: Record<string, string> = {};
  if (workspaceCode) {
    body.workspace_code = workspaceCode;
  }
  if (credentialId) {
    body.credential_id = credentialId;
  }
  return requestJson<GenerationPingRecord>("/api/generation/ping", {
    method: "POST",
    body: JSON.stringify(body)
  });
}
