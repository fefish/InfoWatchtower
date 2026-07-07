import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DashboardPage from "./DashboardPage.vue";
import type { HealthResponse } from "../api/health";
import type { IngestionCoverageRecord } from "../api/ingestion";
import type { DedupeGroupRecord } from "../api/news";
import type { DailyReportRecord, WeeklyReportRecord } from "../api/reports";
import type { DataSourceRecord } from "../api/sources";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const healthApi = vi.hoisted(() => ({
  fetchHealth: vi.fn()
}));

const ingestionApi = vi.hoisted(() => ({
  fetchIngestionCoverage: vi.fn()
}));

const newsApi = vi.hoisted(() => ({
  fetchDedupeGroups: vi.fn()
}));

const reportsApi = vi.hoisted(() => ({
  fetchDailyReports: vi.fn(),
  fetchWeeklyReports: vi.fn()
}));

const sourcesApi = vi.hoisted(() => ({
  fetchSources: vi.fn()
}));

vi.mock("../api/health", () => ({
  fetchHealth: healthApi.fetchHealth
}));

vi.mock("../api/ingestion", () => ({
  fetchIngestionCoverage: ingestionApi.fetchIngestionCoverage
}));

vi.mock("../api/news", () => ({
  fetchDedupeGroups: newsApi.fetchDedupeGroups
}));

vi.mock("../api/reports", () => ({
  fetchDailyReports: reportsApi.fetchDailyReports,
  fetchWeeklyReports: reportsApi.fetchWeeklyReports
}));

vi.mock("../api/sources", () => ({
  fetchSources: sourcesApi.fetchSources
}));

function health(): HealthResponse {
  return {
    service: "infowatchtower",
    version: "test",
    environment: "test",
    database: { status: "ok" }
  };
}

function source(overrides: Partial<DataSourceRecord> = {}): DataSourceRecord {
  return {
    id: "source-1",
    workspace_code: "shared",
    domain_code: "ai",
    source_type: "rss",
    name: "Example RSS",
    url: "https://example.com/rss",
    enabled: true,
    default_focus_id: 1,
    backfill_days: 7,
    source_score: 80,
    last_fetch_at: "2026-07-05T08:00:00Z",
    last_success_at: "2026-07-05T08:00:00Z",
    last_error: "",
    primary_category: "AI",
    info_category: "",
    source_tags: [],
    source_secondary_tags: [],
    source_tier: "P1",
    source_channel_type: "media",
    expert_routes: [],
    inclusion_recommendation: "",
    metadata_only: false,
    needs_entry: false,
    fetch_entry_status: "",
    source_quality_notes: "",
    workspace_link_enabled: true,
    workspace_source_weight: 1,
    workspace_daily_limit: 2,
    workspace_clustering_config: {},
    ...overrides
  };
}

function coverage(overrides: Partial<IngestionCoverageRecord> = {}): IngestionCoverageRecord {
  return {
    workspace_code: "planning_intel",
    day_key: "2026-07-05",
    run_id: "run-1",
    run_key: "run-key",
    run_type: "workspace_fetch",
    run_status: "completed",
    target_range: "2026-07-05",
    recommendation_run_id: "rec-run-1",
    recommendation_run_key: "rec-key",
    daily_report_id: "daily-1",
    daily_report_status: "draft",
    funnel: {
      enabled_sources: 12,
      run_sources: 10,
      source_succeeded: 8,
      source_failed: 2,
      items_fetched: 24,
      raw_created: 18,
      raw_updated: 3,
      raw_in_target: 16,
      news_items: 14,
      dedupe_winners: 9,
      recommendation_candidates: 6,
      recommendation_selected: 4,
      generated_ready: 3,
      daily_adopted: 2
    },
    sources: [],
    ...overrides
  };
}

function candidate(overrides: Partial<DedupeGroupRecord> = {}): DedupeGroupRecord {
  return {
    id: "group-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    dedupe_key: "url:https://example.com/news",
    winner_news_item_id: "news-1",
    winner_title: "黄仁勋的物理 AI ChatGPT 时刻",
    winner_published_at: "2026-07-05T07:00:00Z",
    winner_source_type: "rss",
    item_count: 2,
    status: "active",
    items: [
      {
        id: "group-item-1",
        news_item_id: "news-1",
        is_winner: true,
        duplicate_reason: "winner",
        rank_score: 90,
        title: "黄仁勋的物理 AI ChatGPT 时刻",
        source_type: "rss",
        source_name: "机器之心",
        source_url: "https://example.com/news"
      }
    ],
    recommendation: {
      run_id: "rec-run-1",
      run_key: "rec-key",
      day_key: "2026-07-05",
      recommendation_item_id: "rec-item-1",
      rank: 1,
      selected: true,
      final_score: 96.4,
      quality_score: 90,
      topic_score: 90,
      freshness_score: 90,
      feedback_score: 0,
      diversity_score: 8,
      source_score: 8,
      heat_score: 0,
      recommendation_reason: "admission=P0",
      admission_level: "P0",
      admission_score: 96,
      admission_pool: "daily",
      noise_types: [],
      reject_reasons: [],
      scorer_breakdown: {},
      expert_routes: []
    },
    daily_report: null,
    lineage: { nodes: [] },
    ...overrides
  };
}

function dailyReport(overrides: Partial<DailyReportRecord> = {}): DailyReportRecord {
  return {
    id: "daily-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    day_key: "2026-07-04",
    title: "规划部日报",
    summary: "",
    status: "published",
    published_at: "2026-07-04T09:00:00Z",
    items: [
      {
        id: "daily-item-1",
        generated_news: {
          id: "generated-1",
          category: "模型",
          title: "模型新闻",
          summary: "",
          key_points: "",
          content_json: {},
          source_url: "https://example.com/news",
          generation_status: "ready",
          news_item_id: "news-1",
          recommendation_item_id: "rec-item-1"
        },
        adoption_status: 2,
        is_headline: true,
        sort_order: 1,
        editor_title: null,
        editor_summary: null,
        editor_key_points: null,
        editor_content_json: null,
        editor_notes: "",
        reaction_count: 0,
        rating_count: 0,
        rating_avg: 0,
        comment_count: 0
      }
    ],
    ...overrides
  };
}

function weeklyReport(overrides: Partial<WeeklyReportRecord> = {}): WeeklyReportRecord {
  return {
    id: "weekly-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    week_key: "2026-W27",
    title: "规划部周报",
    summary: "",
    status: "draft",
    published_at: null,
    items: [
      {
        id: "weekly-item-1",
        daily_report_item_id: "daily-item-1",
        daily_day_key: "2026-07-04",
        generated_news: null,
        adoption_status: 1,
        sort_order: 1,
        weekly_score: 0,
        final_score: 0,
        heat_score: 0,
        feedback_score: 0,
        editor_title: null,
        editor_summary: null,
        editor_content_json: null
      }
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
    sync_publisher: true,
    sync_consumer: true,
    embedding: true,
    search: true
  };

  return mount(DashboardPage, {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: { props: ["to"], template: "<a><slot /></a>" }
      }
    }
  });
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T02:00:00Z"));
    vi.clearAllMocks();
    healthApi.fetchHealth.mockResolvedValue(health());
    sourcesApi.fetchSources.mockResolvedValue([
      source(),
      source({
        id: "source-failed",
        name: "失败源",
        last_error: "TimeoutError: source took too long"
      }),
      source({
        id: "source-needs-entry",
        name: "待补入口源",
        workspace_link_enabled: false,
        metadata_only: true,
        needs_entry: true
      })
    ]);
    reportsApi.fetchDailyReports.mockResolvedValue([dailyReport()]);
    reportsApi.fetchWeeklyReports.mockResolvedValue([weeklyReport()]);
    newsApi.fetchDedupeGroups.mockResolvedValue([
      candidate(),
      candidate({
        id: "group-low",
        winner_title: "噪声候选",
        recommendation: {
          ...candidate().recommendation!,
          recommendation_item_id: "rec-item-low",
          admission_level: "R",
          final_score: 12
        }
      })
    ]);
    ingestionApi.fetchIngestionCoverage.mockResolvedValue(coverage());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the briefing funnel, candidates, reports and source health from real APIs", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(sourcesApi.fetchSources).toHaveBeenCalledWith("planning_intel");
    expect(reportsApi.fetchDailyReports).toHaveBeenCalledWith("planning_intel");
    expect(reportsApi.fetchWeeklyReports).toHaveBeenCalledWith("planning_intel");
    expect(newsApi.fetchDedupeGroups).toHaveBeenCalledWith("planning_intel", 40);
    expect(ingestionApi.fetchIngestionCoverage).toHaveBeenCalledWith("planning_intel", "2026-07-05");

    const text = wrapper.text();
    expect(text).toContain("2026 年 7 月 5 日");
    expect(text).toContain("系统运行正常");
    expect(text).toContain("12启用源");
    expect(text).toContain("8抓取成功");
    expect(text).toContain("今日日报 · 草稿待编审");
    expect(text).toContain("黄仁勋的物理 AI ChatGPT 时刻");
    expect(text).toContain("P0");
    expect(text).toContain("96.4 分");
    expect(text).toContain("2026-07-04");
    expect(text).toContain("模型 · 1");
    expect(text).toContain("2026-W27");
    expect(text).toContain("失败源");
    expect(text).toContain("TimeoutError");
    expect(text).toContain("1 个源待补入口");
  });

  it("shows empty states and hides ingestion actions when ingestion is disabled", async () => {
    healthApi.fetchHealth.mockRejectedValue(new Error("offline"));
    sourcesApi.fetchSources.mockResolvedValue([source({ needs_entry: true, metadata_only: true })]);
    reportsApi.fetchDailyReports.mockResolvedValue([]);
    reportsApi.fetchWeeklyReports.mockResolvedValue([]);
    newsApi.fetchDedupeGroups.mockResolvedValue([]);
    ingestionApi.fetchIngestionCoverage.mockRejectedValue(new Error("coverage unavailable"));

    const wrapper = mountPage({ canIngest: false });
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("后端未连接");
    expect(text).toContain("今天还没有候选。");
    expect(text).toContain("查看日报");
    expect(text).toContain("暂无日报");
    expect(text).toContain("暂无周报");
    expect(text).toContain("暂无日报数据");
    expect(text).not.toContain("先跑一次抓取");
    expect(text).not.toContain("抓取与覆盖");
    expect(text).not.toContain("新增信息源");
    expect(text).not.toContain("待补入口，去数据源管理处理");
    expect(text).toContain("SQL 导出");
  });

  it("keeps a visible recoverable error when a core dashboard API fails", async () => {
    sourcesApi.fetchSources.mockRejectedValue(new Error("加载数据源失败"));

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("加载数据源失败");
  });
});
