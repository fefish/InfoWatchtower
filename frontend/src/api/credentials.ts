/**
 * Provider 预设目录与 LLM 凭据 CRUD API（generation-provider-design §4/§8/§9，WP4-B 供给）。
 *
 * 安全不变式：key 是 write-only——只出现在 create/update 请求体里；任何响应只含
 * masked 视图（`key_masked = "****" + 后 4 位`），前端状态在提交后立即清空明文。
 */
import { requestJson } from "./http";

/** 目录条目与 config/contracts/llm_providers.json catalog 逐字段一致。 */
export interface ProviderCatalogEntry {
  code: string;
  name: string;
  default_base_url: string | null;
  auth_header: string;
  key_required: boolean;
  common_models: string[];
  notes: string;
  sort_order: number;
}

export interface ProviderCatalogResponse {
  catalog: ProviderCatalogEntry[];
}

/** 登录即可读：目录只是 UI 预填数据，不是安全边界（base_url 可改、模型可自定义）。 */
export async function fetchGenerationProviders(): Promise<ProviderCatalogResponse> {
  return requestJson<ProviderCatalogResponse>("/api/generation/providers");
}

export interface LlmCredentialRecord {
  id: string;
  provider: string;
  base_url: string;
  base_url_host: string;
  label: string;
  key_masked: string;
  enabled: boolean;
  disabled_at: string | null;
  created_at: string;
  updated_at: string;
}

/** super_admin / editor_admin；列表永只含 masked 视图。 */
export async function listLlmCredentials(): Promise<LlmCredentialRecord[]> {
  return requestJson<LlmCredentialRecord[]>("/api/generation/credentials");
}

export interface LlmCredentialCreatePayload {
  provider: string;
  /** 缺省取目录默认；custom 必填。 */
  base_url?: string | null;
  /** write-only；ollama/custom 等 key_required=false 的 provider 允许留空。 */
  api_key?: string | null;
  label?: string | null;
}

/** 仅 super_admin；审计 generation.credential.create（detail 无明文）。 */
export async function createLlmCredential(
  payload: LlmCredentialCreatePayload
): Promise<LlmCredentialRecord> {
  return requestJson<LlmCredentialRecord>("/api/generation/credentials", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export interface LlmCredentialUpdatePayload {
  label?: string;
  base_url?: string;
  enabled?: boolean;
  /** 传新值即整体替换重加密。 */
  api_key?: string;
}

/** 仅 super_admin；审计 generation.credential.update。 */
export async function updateLlmCredential(
  credentialId: string,
  payload: LlmCredentialUpdatePayload
): Promise<LlmCredentialRecord> {
  return requestJson<LlmCredentialRecord>(`/api/generation/credentials/${credentialId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

/** 仅 super_admin；软删（enabled=false），被引用的工作台按 credential_missing 降级。 */
export async function disableLlmCredential(credentialId: string): Promise<LlmCredentialRecord> {
  return requestJson<LlmCredentialRecord>(`/api/generation/credentials/${credentialId}`, {
    method: "DELETE"
  });
}
