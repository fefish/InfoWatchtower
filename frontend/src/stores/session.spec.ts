import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Router } from "vue-router";

import type { SessionUser } from "../api/auth";
import { onUnauthorized, requestJson } from "../api/http";
import { installUnauthorizedRedirect, useSessionStore } from "./session";

vi.mock("../api/auth", () => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  changePassword: vi.fn()
}));

function fakeRouter(path: string, fullPath = path): Router {
  return {
    currentRoute: { value: { path, fullPath } },
    push: vi.fn()
  } as unknown as Router;
}

function sessionUser(): SessionUser {
  return {
    id: "user-1",
    external_provider: "local",
    external_id: "admin",
    employee_no: null,
    username: "admin",
    display_name: "管理员",
    department: null,
    email: null,
    status: "active",
    is_active: true,
    roles: ["super_admin"]
  };
}

const fetchMock = vi.fn();

function unauthorizedResponse() {
  return {
    ok: false,
    status: 401,
    json: async () => ({ detail: "unauthenticated" })
  } as unknown as Response;
}

beforeEach(() => {
  setActivePinia(createPinia());
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(unauthorizedResponse());
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  onUnauthorized(null);
});

describe("installUnauthorizedRedirect（全局 401 联动装配）", () => {
  it("运行中业务 API 401：清空 session 并跳 /login?redirect=当前路由", async () => {
    const router = fakeRouter("/sources", "/sources?tab=policy");
    const session = useSessionStore();
    session.user = sessionUser();
    session.checked = true;

    installUnauthorizedRedirect(router);
    await expect(requestJson("/api/sources")).rejects.toThrow("unauthenticated");

    expect(session.user).toBeNull();
    expect(session.checked).toBe(true);
    expect(router.push).toHaveBeenCalledWith({
      path: "/login",
      query: { redirect: "/sources?tab=policy" }
    });
  });

  it("已在 /login 时收到 401 不重复跳转", async () => {
    const router = fakeRouter("/login");
    installUnauthorizedRedirect(router);

    await expect(requestJson("/api/sources")).rejects.toThrow("unauthenticated");

    expect(router.push).not.toHaveBeenCalled();
  });

  it("匿名可达的邀请页收到 401 不跳转（守卫自行兜底）", async () => {
    const router = fakeRouter("/invite/abc123");
    installUnauthorizedRedirect(router);

    await expect(requestJson("/api/sources")).rejects.toThrow("unauthenticated");

    expect(router.push).not.toHaveBeenCalled();
  });

  it("登录请求本身 401（密码错误）不清 session 也不跳转", async () => {
    const router = fakeRouter("/login");
    const session = useSessionStore();
    session.user = sessionUser();

    installUnauthorizedRedirect(router);
    await expect(requestJson("/api/auth/login", { method: "POST" })).rejects.toThrow("unauthenticated");

    expect(session.user).not.toBeNull();
    expect(router.push).not.toHaveBeenCalled();
  });
});
