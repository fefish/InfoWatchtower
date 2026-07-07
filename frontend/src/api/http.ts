/**
 * 统一 HTTP client（docs/deployment/deployment-topology.md §4.3）。
 * 所有 api 模块必须经由本模块请求：
 * - same-origin cookie + JSON + !ok 抛 Error(detail)，行为对齐原各模块私有 requestJson；
 * - unsafe 方法（POST/PUT/PATCH/DELETE）自动读取 infowatchtower_csrf cookie 附 X-CSRF-Token 头
 *   （双提交 CSRF，配合后端 AUTH_CSRF_ENABLED）；
 * - API 前缀统一从 import.meta.env.BASE_URL 拼接，支撑子路径部署（如 /watchtower/）。
 */

const CSRF_COOKIE_NAME = "infowatchtower_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function readCsrfToken(): string {
  if (typeof document === "undefined") {
    return "";
  }
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === CSRF_COOKIE_NAME) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return "";
}

export function apiUrl(path: string): string {
  if (!path.startsWith("/")) {
    return path;
  }
  const base = import.meta.env.BASE_URL ?? "/";
  const trimmedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${trimmedBase}${path}`;
}

function buildInit(init?: RequestInit): RequestInit {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string> | undefined) ?? {})
  };
  if (UNSAFE_METHODS.has(method)) {
    const token = readCsrfToken();
    if (token && !headers[CSRF_HEADER_NAME]) {
      headers[CSRF_HEADER_NAME] = token;
    }
  }
  return {
    credentials: "same-origin",
    ...init,
    headers
  };
}

async function raiseForStatus(response: Response): Promise<void> {
  if (response.ok) {
    return;
  }
  const body: { detail?: unknown } = await response.json().catch(() => ({}));
  const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
  throw new Error(detail);
}

/** 底层入口：仅拼 base 前缀 + 附 cookie/CSRF，不检查状态码（logout 等特殊流程用）。 */
export async function requestRaw(path: string, init?: RequestInit): Promise<Response> {
  return fetch(apiUrl(path), buildInit(init));
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await requestRaw(path, init);
  await raiseForStatus(response);
  return response.json() as Promise<T>;
}

export async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await requestRaw(path, init);
  await raiseForStatus(response);
}

export async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await requestRaw(path, init);
  await raiseForStatus(response);
  return response.blob();
}
