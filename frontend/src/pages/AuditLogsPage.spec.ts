import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuditLogsPage from "./AuditLogsPage.vue";
import type { AuditLogRecord } from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  fetchAuditLogs: vi.fn()
}));

vi.mock("../api/operations", () => ({
  fetchAuditLogs: operationsApi.fetchAuditLogs
}));

function auditLog(overrides: Partial<AuditLogRecord> = {}): AuditLogRecord {
  return {
    id: "audit-1",
    user_id: "user-1",
    user_name: "规划部管理员",
    workspace_code: "planning_intel",
    action: "daily_report.publish",
    object_type: "daily_report",
    object_id: "report-1",
    ip_address: "",
    user_agent: "",
    detail_json: { workspace_code: "planning_intel", day_key: "2026-07-05" },
    created_at: "2026-07-06T10:00:00Z",
    ...overrides
  };
}

function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  return mount(AuditLogsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("AuditLogsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    operationsApi.fetchAuditLogs.mockResolvedValue([auditLog()]);
  });

  it("loads audit logs scoped to the current workspace", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchAuditLogs).toHaveBeenCalledWith({ workspaceCode: "planning_intel", limit: 80 });
    expect(wrapper.text()).toContain("daily_report.publish");
    expect(wrapper.text()).toContain("planning_intel");
    expect(wrapper.text()).toContain("规划部管理员");
    expect(wrapper.text()).toContain("report-1");
    expect(wrapper.text()).toContain("2026-07-05");
  });

  it("shows an actionable empty state when no audit log exists", async () => {
    operationsApi.fetchAuditLogs.mockResolvedValue([]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("暂无审计日志");
    expect(wrapper.text()).toContain("完成登录、邀请、发布或导出后这里会记录关键操作");
  });

  it("shows a recoverable error when audit logs cannot be loaded", async () => {
    operationsApi.fetchAuditLogs.mockRejectedValue(new Error("Requires workspace admin"));

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find(".form-error").text()).toContain("Requires workspace admin");
  });
});
