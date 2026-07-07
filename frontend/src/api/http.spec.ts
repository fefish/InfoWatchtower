import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiUrl, readCsrfToken, requestJson, requestRaw } from "./http";

const CSRF_COOKIE_NAME = "infowatchtower_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    blob: async () => new Blob([JSON.stringify(body)])
  } as unknown as Response;
}

function setCsrfCookie(value: string) {
  document.cookie = `${CSRF_COOKIE_NAME}=${value}; path=/`;
}

function clearCsrfCookie() {
  document.cookie = `${CSRF_COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

const fetchMock = vi.fn();

function lastFetchCall() {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) {
    throw new Error("fetch was not called");
  }
  return { url: call[0] as string, init: (call[1] ?? {}) as RequestInit };
}

function lastHeaders(): Record<string, string> {
  return (lastFetchCall().init.headers ?? {}) as Record<string, string>;
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(jsonResponse({}));
  vi.stubGlobal("fetch", fetchMock);
  clearCsrfCookie();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  clearCsrfCookie();
});

describe("apiUrl", () => {
  it("BASE_URL 为 / 时保持路径不变", () => {
    expect(apiUrl("/api/meta/runtime")).toBe("/api/meta/runtime");
  });

  it("BASE_URL 为子路径（如 /watchtower/）时拼接前缀", () => {
    vi.stubEnv("BASE_URL", "/watchtower/");
    expect(apiUrl("/api/meta/runtime")).toBe("/watchtower/api/meta/runtime");
    expect(apiUrl("/healthz")).toBe("/watchtower/healthz");
  });

  it("非绝对路径（如完整 URL）原样返回", () => {
    vi.stubEnv("BASE_URL", "/watchtower/");
    expect(apiUrl("https://example.com/feed.xml")).toBe("https://example.com/feed.xml");
  });
});

describe("readCsrfToken", () => {
  it("cookie 缺失时返回空串", () => {
    expect(readCsrfToken()).toBe("");
  });

  it("读取 infowatchtower_csrf cookie 并做 URL 解码", () => {
    setCsrfCookie(encodeURIComponent("token=with=equals"));
    expect(readCsrfToken()).toBe("token=with=equals");
  });
});

describe("requestRaw 的 CSRF 双提交", () => {
  it.each(["POST", "PUT", "PATCH", "DELETE"])("unsafe 方法 %s 自动附 X-CSRF-Token 头", async (method) => {
    setCsrfCookie("token-123");
    await requestRaw("/api/example", { method });
    expect(lastHeaders()[CSRF_HEADER_NAME]).toBe("token-123");
  });

  it("GET 不附 CSRF 头", async () => {
    setCsrfCookie("token-123");
    await requestRaw("/api/example");
    expect(lastHeaders()[CSRF_HEADER_NAME]).toBeUndefined();
  });

  it("cookie 缺失时 unsafe 方法也不附空头", async () => {
    await requestRaw("/api/example", { method: "POST" });
    expect(lastHeaders()[CSRF_HEADER_NAME]).toBeUndefined();
  });

  it("调用方显式传入的 CSRF 头不被覆盖", async () => {
    setCsrfCookie("token-123");
    await requestRaw("/api/example", {
      method: "POST",
      headers: { [CSRF_HEADER_NAME]: "explicit-token" }
    });
    expect(lastHeaders()[CSRF_HEADER_NAME]).toBe("explicit-token");
  });

  it("默认附 same-origin cookie 与 JSON Content-Type", async () => {
    await requestRaw("/api/example", { method: "POST" });
    const { init } = lastFetchCall();
    expect(init.credentials).toBe("same-origin");
    expect(lastHeaders()["Content-Type"]).toBe("application/json");
  });

  it("BASE_URL 为 /watchtower/ 时请求 URL 带前缀", async () => {
    vi.stubEnv("BASE_URL", "/watchtower/");
    await requestRaw("/api/example", { method: "POST" });
    expect(lastFetchCall().url).toBe("/watchtower/api/example");
  });
});

describe("requestJson", () => {
  it("!ok 时抛出后端 detail", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "csrf_failed" }, 403));
    await expect(requestJson("/api/example", { method: "POST" })).rejects.toThrow("csrf_failed");
  });

  it("!ok 且 body 无 detail 时抛 HTTP 状态码", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));
    await expect(requestJson("/api/example")).rejects.toThrow("HTTP 500");
  });

  it("ok 时返回解析后的 JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ value: 1 }));
    await expect(requestJson<{ value: number }>("/api/example")).resolves.toEqual({ value: 1 });
  });
});

describe("api 模块统一走 http client", () => {
  it("除 http.ts 与 health.ts 探活外，src/api 下不允许出现裸 fetch(", () => {
    const apiModules = import.meta.glob("./*.ts", {
      query: "?raw",
      import: "default",
      eager: true
    }) as Record<string, string>;
    const exempt = new Set(["./http.ts", "./health.ts"]);
    const offenders = Object.entries(apiModules)
      .filter(([file]) => !file.endsWith(".spec.ts") && !exempt.has(file))
      .filter(([, content]) => /(?<![\w$.])fetch\(/.test(content))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });
});
