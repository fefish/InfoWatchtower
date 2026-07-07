import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SyncRunsPage from "./SyncRunsPage.vue";
import type { SyncConflictRecord, SyncHealthRecord, SyncRunRecord } from "../api/operations";
import type { DeployMode, RuntimeCapabilities } from "../api/meta";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createSyncPullRun: vi.fn(),
  createSyncRun: vi.fn(),
  fetchSyncConflicts: vi.fn(),
  fetchSyncHealth: vi.fn(),
  fetchSyncPackageDownload: vi.fn(),
  fetchSyncRuns: vi.fn(),
  resolveSyncConflict: vi.fn(),
  retryFailedSyncInbox: vi.fn()
}));

vi.mock("../api/operations", () => ({
  createSyncPullRun: operationsApi.createSyncPullRun,
  createSyncRun: operationsApi.createSyncRun,
  fetchSyncConflicts: operationsApi.fetchSyncConflicts,
  fetchSyncHealth: operationsApi.fetchSyncHealth,
  fetchSyncPackageDownload: operationsApi.fetchSyncPackageDownload,
  fetchSyncRuns: operationsApi.fetchSyncRuns,
  resolveSyncConflict: operationsApi.resolveSyncConflict,
  retryFailedSyncInbox: operationsApi.retryFailedSyncInbox
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function syncRun(overrides: Partial<SyncRunRecord> = {}): SyncRunRecord {
  return {
    id: "run-1",
    package_id: "external-package-002_import_20260705190000000000",
    source_instance_id: "public-other",
    target_instance_id: "intranet",
    direction: "import",
    status: "completed_with_conflicts",
    counts_json: {
      conflicts: 1,
      exported: 0,
      pending_outbox: 0
    },
    started_at: "2026-07-05T09:00:00Z",
    completed_at: "2026-07-05T09:01:00Z",
    created_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function syncConflict(overrides: Partial<SyncConflictRecord> = {}): SyncConflictRecord {
  return {
    id: "conflict-1",
    sync_run_id: "run-1",
    package_id: "external-package-002_import_20260705190000000000",
    source_instance_id: "public-other",
    target_instance_id: "intranet",
    direction: "import",
    object_type: "data_sources",
    object_id: "global-source-import-001",
    local_revision: 2,
    incoming_revision: 2,
    field_name: "record",
    local_value_json: {
      name: "同步源",
      url: "https://example.com/feed.xml"
    },
    incoming_value_json: {
      name: "冲突源",
      url: "https://example.com/other.xml"
    },
    conflict_reason: "same revision has different content hash",
    status: "open",
    resolution_json: {
      reason: "same revision has different content hash"
    },
    resolved_by_user_id: null,
    resolved_by_name: null,
    resolved_at: null,
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function syncHealth(overrides: Partial<SyncHealthRecord> = {}): SyncHealthRecord {
  return {
    status: "critical",
    generated_at: "2026-07-05T09:02:00Z",
    sync_role: "consumer",
    summary: "同步存在 2 个严重告警、3 个提醒",
    thresholds: {
      warning_after_seconds: 120,
      critical_after_seconds: 360,
      pull_interval_seconds: 60
    },
    cursor_count: 2,
    missing_cursor_count: 4,
    stale_cursor_count: 0,
    failed_cursor_count: 1,
    failed_inbox_count: 2,
    failed_inbox_by_object_type: {
      raw_items: 2
    },
    failed_inbox_retry_due_count: 1,
    failed_inbox_retry_blocked_count: 0,
    failed_inbox_next_retry_at: "2026-07-05T09:05:00Z",
    failed_inbox_retry_policy: {
      enabled: true,
      base_delay_seconds: 300,
      max_delay_seconds: 3600,
      max_attempts: 5,
      limit: 50
    },
    open_conflict_count: 1,
    recent_failed_run_count: 1,
    last_run: syncRun({ package_id: "api_pull_failed_health", status: "completed_with_errors" }),
    cursors: [
      {
        object_type: "data_sources",
        cursor: "cursor-ok",
        last_pulled_at: "2026-07-05T09:01:30Z",
        last_status: "ok",
        last_error: "",
        age_seconds: 30,
        status: "ok",
        warnings: []
      },
      {
        object_type: "raw_items",
        cursor: "cursor-failed",
        last_pulled_at: "2026-07-05T08:50:00Z",
        last_status: "failed",
        last_error: "remote returned 500",
        age_seconds: 720,
        status: "critical",
        warnings: ["remote returned 500"]
      }
    ],
    alerts: [
      {
        severity: "critical",
        code: "cursor_failed_or_critical_lag",
        message: "raw_items 同步水位失败或严重滞后",
        object_type: "raw_items"
      },
      {
        severity: "warning",
        code: "missing_cursors",
        message: "4 类同步对象还没有拉取水位",
        object_type: null
      },
      {
        severity: "critical",
        code: "failed_inbox_records",
        message: "当前还有 2 条 failed sync_inbox 记录可重试",
        object_type: null
      }
    ],
    ...overrides
  };
}

function mountPage(
  options: {
    deployMode?: DeployMode;
    capabilities?: RuntimeCapabilities;
  } = {}
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  const runtime = useRuntimeStore();
  runtime.checked = true;
  runtime.deployMode = options.deployMode ?? "extranet";
  runtime.instanceId = "iw-test";
  runtime.capabilities = options.capabilities ?? {
    ingestion: true,
    sync_publisher: true,
    sync_consumer: false,
    embedding: false,
    search: true
  };

  return mount(SyncRunsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("SyncRunsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    operationsApi.fetchSyncRuns.mockResolvedValue([syncRun()]);
    operationsApi.fetchSyncConflicts.mockResolvedValue([syncConflict()]);
    operationsApi.fetchSyncHealth.mockResolvedValue(syncHealth());
    operationsApi.createSyncPullRun.mockResolvedValue(syncRun({ package_id: "pull-run-1", direction: "api_pull" }));
    operationsApi.resolveSyncConflict.mockResolvedValue(syncConflict({ status: "resolved" }));
    operationsApi.retryFailedSyncInbox.mockResolvedValue(
      syncRun({ package_id: "inbox-retry-1", direction: "inbox_retry", status: "completed" })
    );
  });

  it("shows publisher actions only when sync_publisher is enabled", async () => {
    const wrapper = mountPage({
      deployMode: "extranet",
      capabilities: {
        ingestion: true,
        sync_publisher: true,
        sync_consumer: false,
        embedding: false,
        search: true
      }
    });
    await flushPromises();

    expect(wrapper.text()).toContain("外网同步角色");
    expect(wrapper.text()).toContain("当前实例是外网发布者");
    expect(wrapper.text()).toContain("导出同步包");
    expect(wrapper.text()).not.toContain("立即拉取");
  });

  it("renders sync health waterline alerts from the backend health API", async () => {
    const wrapper = mountPage({
      deployMode: "intranet",
      capabilities: {
        ingestion: false,
        sync_publisher: false,
        sync_consumer: true,
        embedding: true,
        search: true
      }
    });
    await flushPromises();

    expect(operationsApi.fetchSyncHealth).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("同步健康");
    expect(wrapper.text()).toContain("严重");
    expect(wrapper.text()).toContain("同步存在 2 个严重告警、3 个提醒");
    expect(wrapper.text()).toContain("4 类同步对象还没有拉取水位");
    expect(wrapper.text()).toContain("raw_items");
    expect(wrapper.text()).toContain("remote returned 500");
    expect(wrapper.text()).toContain("失败 inbox");
    expect(wrapper.text()).toContain("raw_items 2");
    expect(wrapper.text()).toContain("自动重试开启：300 秒起步");
    expect(wrapper.text()).toContain("1 条已到期，等待 scheduler 自动重试");
    expect(wrapper.text()).toContain("待处理冲突");
  });

  it("shows consumer pull action and hides package export in intranet mode", async () => {
    const wrapper = mountPage({
      deployMode: "intranet",
      capabilities: {
        ingestion: false,
        sync_publisher: false,
        sync_consumer: true,
        embedding: true,
        search: true
      }
    });
    await flushPromises();

    expect(wrapper.text()).toContain("内网同步角色");
    expect(wrapper.text()).toContain("当前实例是内网消费者");
    expect(wrapper.text()).toContain("立即拉取");
    expect(wrapper.text()).not.toContain("导出同步包");

    const pullButton = wrapper.findAll("button").find((button) => button.text().includes("立即拉取"));
    expect(pullButton).toBeTruthy();
    await pullButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.createSyncPullRun).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("同步拉取已完成：pull-run-1");
  });

  it("retries failed inbox records from the health panel in consumer mode", async () => {
    operationsApi.fetchSyncHealth
      .mockResolvedValueOnce(syncHealth())
      .mockResolvedValueOnce(
        syncHealth({
          status: "ok",
          summary: "同步运行正常",
          failed_inbox_count: 0,
          failed_inbox_by_object_type: {},
          failed_inbox_retry_due_count: 0,
          failed_inbox_retry_blocked_count: 0,
          failed_inbox_next_retry_at: null,
          alerts: []
        })
      );
    const wrapper = mountPage({
      deployMode: "intranet",
      capabilities: {
        ingestion: false,
        sync_publisher: false,
        sync_consumer: true,
        embedding: true,
        search: true
      }
    });
    await flushPromises();

    const retryButton = wrapper.findAll("button").find((button) => button.text().includes("重试 failed inbox"));
    expect(retryButton).toBeTruthy();
    await retryButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.retryFailedSyncInbox).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("failed inbox 已重试：inbox-retry-1");
    expect(wrapper.text()).toContain("同步运行正常");
  });

  it("loads open sync conflicts and resolves them through the API", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchSyncConflicts).toHaveBeenCalledWith({ status: "open", limit: 50 });
    expect(wrapper.text()).toContain("同步冲突处置");
    expect(wrapper.text()).toContain("data_sources · global-source-import-001");
    expect(wrapper.text()).toContain("same revision has different content hash");
    expect(wrapper.text()).toContain("冲突源");

    const keepLocalButton = wrapper.findAll("button").find((button) => button.text().includes("保留本地"));
    expect(keepLocalButton).toBeTruthy();
    await keepLocalButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.resolveSyncConflict).toHaveBeenCalledWith("conflict-1", {
      strategy: "keep_local",
      reason: "保留本地已确认版本",
      merged_json: null
    });
    expect(wrapper.text()).toContain("同步冲突已记录处置结果");
    expect(wrapper.text()).not.toContain("data_sources · global-source-import-001");
  });

  it("resolves a sync conflict by applying incoming payload", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const useIncomingButton = wrapper.findAll("button").find((button) => button.text().includes("使用传入"));
    expect(useIncomingButton).toBeTruthy();
    await useIncomingButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.resolveSyncConflict).toHaveBeenCalledWith("conflict-1", {
      strategy: "use_incoming",
      reason: "接受外网发布者传入版本",
      merged_json: null
    });
  });

  it("submits edited JSON for manual merge on supported objects", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const textarea = wrapper.find(".manual-merge-panel textarea");
    expect(textarea.exists()).toBe(true);
    await textarea.setValue(
      JSON.stringify(
        {
          name: "人工合并源",
          url: "https://example.com/manual.xml"
        },
        null,
        2
      )
    );
    const manualMergeButton = wrapper.findAll("button").find((button) => button.text().includes("人工合并"));
    expect(manualMergeButton).toBeTruthy();
    await manualMergeButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.resolveSyncConflict).toHaveBeenCalledWith("conflict-1", {
      strategy: "manual_merge",
      reason: "按人工合并 JSON 写入新修订",
      merged_json: {
        name: "人工合并源",
        url: "https://example.com/manual.xml"
      }
    });
  });

  it("highlights a sync conflict from a notification anchor", async () => {
    routeState.query = { conflict_id: "conflict-2" };
    operationsApi.fetchSyncConflicts.mockResolvedValue([
      syncConflict(),
      syncConflict({
        id: "conflict-2",
        object_id: "global-source-import-002",
        incoming_value_json: { name: "被定位的冲突源" }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const anchored = wrapper.find(".sync-conflict-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("global-source-import-002");
    expect(anchored.text()).toContain("被定位的冲突源");
  });

  it("highlights a sync run from a search anchor", async () => {
    routeState.query = { sync_run_id: "run-2" };
    operationsApi.fetchSyncRuns.mockResolvedValue([
      syncRun(),
      syncRun({
        id: "run-2",
        package_id: "external-package-search-001",
        source_instance_id: "extranet",
        target_instance_id: "intranet",
        direction: "api_pull",
        status: "completed"
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const anchored = wrapper.find(".sync-run-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("external-package-search-001");
    expect(anchored.text()).toContain("api_pull");
  });
});
