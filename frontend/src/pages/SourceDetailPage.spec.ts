import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SourceDetailPage from "./SourceDetailPage.vue";
import type { SourceDetailRecord } from "../api/sources";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const sourcesApi = vi.hoisted(() => ({
  fetchSource: vi.fn(),
  fetchSourceDetail: vi.fn(),
  updateSourceWorkspaceConfig: vi.fn()
}));

const routerState = vi.hoisted(() => ({
  params: { id: "source-1" },
  push: vi.fn()
}));

vi.mock("../api/sources", () => ({
  fetchSource: sourcesApi.fetchSource,
  fetchSourceDetail: sourcesApi.fetchSourceDetail,
  updateSourceWorkspaceConfig: sourcesApi.updateSourceWorkspaceConfig
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: routerState.params }),
  useRouter: () => ({ push: routerState.push })
}));

function sourceDetail(overrides: Partial<SourceDetailRecord> = {}): SourceDetailRecord {
  return {
    source: {
      id: "source-1",
      workspace_code: "shared",
      domain_code: "ai",
      source_type: "rss",
      name: "详情测试 RSS",
      url: "https://example.com/feed.xml",
      enabled: true,
      default_focus_id: 1,
      backfill_days: 7,
      source_score: 8.5,
      last_fetch_at: "2026-07-05T08:00:00Z",
      last_success_at: "2026-07-05T08:00:00Z",
      last_error: "",
      primary_category: "AI",
      info_category: "技术",
      source_tags: ["模型"],
      source_secondary_tags: [],
      source_tier: "P0",
      source_channel_type: "RSS",
      expert_routes: ["模型工程"],
      inclusion_recommendation: "keep",
      metadata_only: false,
      needs_entry: false,
      fetch_entry_status: "ready",
      source_quality_notes: "",
      workspace_link_enabled: true,
      workspace_source_weight: 1,
      workspace_daily_limit: null,
      workspace_clustering_config: {}
    },
    raw_count: 2,
    news_count: 1,
    recent_raw_items: [
      {
        id: "raw-1",
        source_title: "最近 raw 标题",
        source_url: "https://example.com/news",
        raw_content_excerpt: "最近 raw 摘要",
        fetched_at: "2026-07-05T08:00:00Z",
        published_at: "2026-07-05T07:00:00Z"
      }
    ],
    recent_runs: [
      {
        run_id: "run-1",
        run_key: "detail-run",
        run_type: "workspace_fetch",
        status: "failed",
        completed_at: "2026-07-05T08:05:00Z",
        fetched: 0,
        created: 0,
        updated: 0,
        error: "TimeoutError"
      }
    ],
    error_logs: [
      {
        run_id: "run-1",
        run_key: "detail-run",
        run_type: "workspace_fetch",
        status: "failed",
        completed_at: "2026-07-05T08:05:00Z",
        fetched: 0,
        created: 0,
        updated: 0,
        error: "TimeoutError"
      }
    ],
    raw_trend: [
      { day_key: "2026-07-04", raw_count: 1 },
      { day_key: "2026-07-05", raw_count: 2 }
    ],
    ...overrides
  };
}

function mountPage(options: { canIngest?: boolean } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  const runtime = useRuntimeStore();
  runtime.checked = true;
  runtime.capabilities = {
    ingestion: options.canIngest ?? true,
    sync_publisher: false,
    sync_consumer: false,
    embedding: false,
    search: true
  };
  return mount(SourceDetailPage, {
    global: {
      plugins: [pinia]
    }
  });
}

function buttonByText(wrapper: ReturnType<typeof mount>, label: string) {
  const button = wrapper.findAll("button").find((item) => item.text().includes(label));
  if (!button) {
    throw new Error(`Button not found: ${label}`);
  }
  return button;
}

describe("SourceDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routerState.params = { id: "source-1" };
    sourcesApi.fetchSourceDetail.mockResolvedValue(sourceDetail());
    sourcesApi.fetchSource.mockResolvedValue({ data_source_id: "source-1", source_type: "rss", fetched: 1, created: 1, updated: 0 });
    sourcesApi.updateSourceWorkspaceConfig.mockResolvedValue(sourceDetail().source);
  });

  it("loads safe source detail with raw samples, trend and error logs", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(sourcesApi.fetchSourceDetail).toHaveBeenCalledWith("source-1", "planning_intel");
    expect(wrapper.text()).toContain("详情测试 RSS");
    expect(wrapper.text()).toContain("Raw 累计");
    expect(wrapper.text()).toContain("News 累计");
    expect(wrapper.text()).toContain("最近 raw 标题");
    expect(wrapper.text()).toContain("TimeoutError");
    expect(wrapper.text()).not.toContain("raw_payload_json");
  });

  it("fetches the current source through the workspace-scoped API", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "抓取").trigger("click");
    await flushPromises();

    expect(sourcesApi.fetchSource).toHaveBeenCalledWith("source-1", "planning_intel");
    expect(wrapper.text()).toContain("抓取完成");
  });

  it("hides fetch actions in read-only deployment mode", async () => {
    const wrapper = mountPage({ canIngest: false });
    await flushPromises();

    expect(wrapper.text()).not.toContain("抓取中");
    expect(wrapper.findAll("button").some((button) => button.text().includes("抓取"))).toBe(false);
  });

  it("shows a recoverable error state when the source cannot be loaded", async () => {
    sourcesApi.fetchSourceDetail.mockRejectedValue(new Error("Data source not found"));
    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("Data source not found");
    expect(wrapper.text()).toContain("没有找到这个数据源");
  });
});
