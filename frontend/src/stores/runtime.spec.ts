import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HttpError } from "../api/http";
import SourcesPage from "../pages/SourcesPage.vue";
import { useRuntimeStore } from "./runtime";
import { useWorkspaceStore } from "./workspace";

import type { RuntimeRecord } from "../api/meta";

const metaApi = vi.hoisted(() => ({
  fetchRuntime: vi.fn()
}));

vi.mock("../api/meta", () => ({
  fetchRuntime: metaApi.fetchRuntime
}));

const sourcesApi = vi.hoisted(() => ({
  fetchSources: vi.fn(),
  fetchSource: vi.fn(),
  createSource: vi.fn(),
  previewSourceImport: vi.fn(),
  importLegacySources: vi.fn(),
  importTechInsightLoopSources: vi.fn(),
  updateSourceDefinition: vi.fn(),
  updateSourceWorkspaceConfig: vi.fn()
}));

vi.mock("../api/sources", () => sourcesApi);

const workspacesApi = vi.hoisted(() => ({
  fetchWorkspaces: vi.fn(),
  createWorkspace: vi.fn(),
  fetchWorkspaceSections: vi.fn(),
  fetchWorkspaceLabelPolicy: vi.fn(),
  updateWorkspaceLabelPolicy: vi.fn()
}));

vi.mock("../api/workspaces", () => workspacesApi);

function runtimeRecord(overrides: Partial<RuntimeRecord> = {}): RuntimeRecord {
  return {
    deploy_mode: "intranet",
    instance_id: "intranet-01",
    capabilities: {
      ingestion: false,
      sync_publisher: false,
      sync_consumer: true,
      embedding: false,
      search: true
    },
    auth_mode: "intranet_sso",
    auth_membership_mapping: { status: "empty", default_workspaces: [], department_workspaces: [] },
    app_version: "1.0.0",
    ...overrides
  };
}

function labelPolicy() {
  return {
    workspace_code: "planning_intel",
    label_set_code: "ai_sql_categories",
    news_format_code: "company_sql_v1",
    export_category_mode: "news_primary",
    required_content_fields: [
      "background",
      "effects",
      "eventSummary",
      "technologyAndInnovation",
      "valueAndImpact"
    ],
    allowed_primary_categories: ["AI 应用", "模型"],
    secondary_labels_by_primary: {},
    default_category: "AI 应用",
    fallback_category: "AI 应用",
    tagging_stages: ["generation"]
  };
}

describe("runtime store", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setActivePinia(createPinia());
  });

  it("meta 成功时按后端能力落地并清除 metaError", async () => {
    metaApi.fetchRuntime.mockResolvedValue(runtimeRecord());
    const runtime = useRuntimeStore();

    await runtime.load();

    expect(runtime.checked).toBe(true);
    expect(runtime.metaError).toBe(false);
    expect(runtime.deployMode).toBe("intranet");
    expect(runtime.canIngest).toBe(false);
    expect(runtime.capabilities.search).toBe(true);
  });

  it("meta 失败时 fail-closed：能力全部禁用并标记 metaError", async () => {
    metaApi.fetchRuntime.mockRejectedValue(new Error("network down"));
    const runtime = useRuntimeStore();

    await runtime.load();

    expect(runtime.checked).toBe(true);
    expect(runtime.metaError).toBe(true);
    expect(runtime.metaErrorKind).toBe("unreachable");
    expect(runtime.canIngest).toBe(false);
    expect(runtime.capabilities).toEqual({
      ingestion: false,
      sync_publisher: false,
      sync_consumer: false,
      embedding: false,
      search: false
    });
  });

  it("meta 404 时诊断为 stale-backend（后端进程/镜像未随前端更新）", async () => {
    metaApi.fetchRuntime.mockRejectedValue(new HttpError("Not Found", 404));
    const runtime = useRuntimeStore();

    await runtime.load();

    expect(runtime.metaError).toBe(true);
    expect(runtime.metaErrorKind).toBe("stale-backend");
    expect(runtime.metaErrorStatus).toBe(404);
    expect(runtime.canIngest).toBe(false);
  });

  it("meta 非 404 HTTP 错误时诊断为 http-error 并携带状态码", async () => {
    metaApi.fetchRuntime.mockRejectedValue(new HttpError("boom", 500));
    const runtime = useRuntimeStore();

    await runtime.load();

    expect(runtime.metaErrorKind).toBe("http-error");
    expect(runtime.metaErrorStatus).toBe(500);
  });

  it("checked 后重复 load 不再请求 meta", async () => {
    metaApi.fetchRuntime.mockRejectedValue(new Error("network down"));
    const runtime = useRuntimeStore();

    await runtime.load();
    await runtime.load();

    expect(metaApi.fetchRuntime).toHaveBeenCalledTimes(1);
  });

  it("reload 重试成功后恢复能力并清除 metaError", async () => {
    metaApi.fetchRuntime.mockRejectedValueOnce(new Error("network down"));
    metaApi.fetchRuntime.mockResolvedValueOnce(runtimeRecord());
    const runtime = useRuntimeStore();

    await runtime.load();
    expect(runtime.metaError).toBe(true);

    await runtime.reload();

    expect(metaApi.fetchRuntime).toHaveBeenCalledTimes(2);
    expect(runtime.metaError).toBe(false);
    expect(runtime.deployMode).toBe("intranet");
    expect(runtime.capabilities.search).toBe(true);
  });

  it("meta 失败后 SourcesPage 隐藏新增/导入/抓取入口", async () => {
    metaApi.fetchRuntime.mockRejectedValue(new Error("network down"));
    sourcesApi.fetchSources.mockResolvedValue([]);
    workspacesApi.fetchWorkspaceLabelPolicy.mockResolvedValue(labelPolicy());

    const pinia = createPinia();
    setActivePinia(pinia);

    const workspace = useWorkspaceStore();
    workspace.currentCode = "planning_intel";
    workspace.options = [
      {
        code: "planning_intel",
        name: "规划部情报工作台",
        description: "",
        workspace_type: "team",
        default_domain_code: "ai",
        enabled: true
      }
    ];

    const runtime = useRuntimeStore();
    await runtime.load();
    expect(runtime.canIngest).toBe(false);

    const wrapper = mount(SourcesPage, {
      global: {
        plugins: [pinia],
        stubs: {
          RouterLink: {
            props: ["to"],
            template: "<a><slot /></a>"
          }
        }
      }
    });
    await flushPromises();

    const buttonTexts = wrapper.findAll("button").map((button) => button.text());
    expect(buttonTexts.some((text) => text.includes("新增源"))).toBe(false);
    expect(buttonTexts.some((text) => text.includes("导入数据"))).toBe(false);
    expect(buttonTexts.some((text) => text.includes("导入 Tech 源"))).toBe(false);
    expect(buttonTexts.some((text) => text.includes("抓取"))).toBe(false);
  });
});
