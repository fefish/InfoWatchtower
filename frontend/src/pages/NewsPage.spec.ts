import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NewsPage from "./NewsPage.vue";
import type { DedupeGroupRecord, NewsItemRecord } from "../api/news";
import { useWorkspaceStore } from "../stores/workspace";

const newsApi = vi.hoisted(() => ({
  fetchDedupeGroups: vi.fn(),
  fetchNewsItems: vi.fn(),
  normalizeNewsItems: vi.fn()
}));

const reportsApi = vi.hoisted(() => ({
  bulkAdoptDailyReportCandidates: vi.fn(),
  bulkRejectDailyReportCandidates: vi.fn()
}));

const watchersApi = vi.hoisted(() => ({
  fetchObjectWatcher: vi.fn(),
  updateObjectWatcher: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/news", () => ({
  fetchDedupeGroups: newsApi.fetchDedupeGroups,
  fetchNewsItems: newsApi.fetchNewsItems,
  normalizeNewsItems: newsApi.normalizeNewsItems
}));

vi.mock("../api/reports", () => ({
  bulkAdoptDailyReportCandidates: reportsApi.bulkAdoptDailyReportCandidates,
  bulkRejectDailyReportCandidates: reportsApi.bulkRejectDailyReportCandidates
}));

vi.mock("../api/watchers", () => watchersApi);

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function newsItem(overrides: Partial<NewsItemRecord> = {}): NewsItemRecord {
  return {
    id: "news-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    raw_item_id: "raw-1",
    data_source_id: "source-1",
    source_type: "rss",
    source_name: "Example RSS",
    source_url: "https://example.com/news",
    canonical_url: "https://example.com/news",
    source_title: "Agent 工程新闻",
    normalized_title: "Agent 工程新闻",
    summary: "摘要",
    author: "",
    published_at: "2026-07-05T09:00:00Z",
    focus_id: 1,
    dedupe_key: "agent-news",
    active: true,
    duplicate_of_id: null,
    normalization_status: "normalized",
    normalization_notes: "",
    ...overrides
  };
}

function group(overrides: Partial<DedupeGroupRecord> = {}): DedupeGroupRecord {
  return {
    id: "group-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    dedupe_key: "agent-news",
    winner_news_item_id: "news-1",
    winner_title: "Agent 工程新闻",
    winner_published_at: "2026-07-05T09:00:00Z",
    winner_source_type: "rss",
    item_count: 1,
    status: "active",
    items: [
      {
        id: "group-item-1",
        news_item_id: "news-1",
        is_winner: true,
        duplicate_reason: "winner",
        rank_score: 1,
        title: "Agent 工程新闻",
        source_type: "rss",
        source_name: "Example RSS",
        source_url: "https://example.com/news"
      }
    ],
    recommendation: null,
    daily_report: null,
    lineage: {
      nodes: [
        {
          object_type: "data_source",
          object_id: "source-1",
          label: "Example RSS",
          status: "enabled",
          review_note: "确认候选来自哪个共享数据源。",
          target_path: "/sources/source-1",
          occurred_at: "2026-07-05T09:00:00Z",
          metadata: { source_type: "rss", domain_code: "ai" }
        },
        {
          object_type: "raw_item",
          object_id: "raw-1",
          label: "Agent 工程新闻",
          status: "preserved",
          review_note: "确认原始信号已经完整入库。",
          target_path: "/news?raw_item_id=raw-1",
          occurred_at: "2026-07-05T09:00:00Z",
          metadata: { payload_keys: ["title", "link"], raw_content_length: 2 }
        },
        {
          object_type: "news_item",
          object_id: "news-1",
          label: "Agent 工程新闻",
          status: "active_winner",
          review_note: "确认 raw 已标准化成候选新闻。",
          target_path: "/news?news_item_id=news-1",
          occurred_at: "2026-07-05T09:00:00Z",
          metadata: { normalization_status: "normalized", dedupe_key: "agent-news" }
        },
        {
          object_type: "dedupe_group",
          object_id: "group-1",
          label: "agent-news",
          status: "active",
          review_note: "确认同一事件的重复来源已合并。",
          target_path: "/news?dedupe_group_id=group-1",
          occurred_at: "2026-07-05T09:00:00Z",
          metadata: { item_count: 1, winner_news_item_id: "news-1" }
        }
      ]
    },
    ...overrides
  };
}

function mountPage(workspaceRole = "member") {
  const pinia = createPinia();
  setActivePinia(pinia);
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  workspace.options = [
    {
      code: "planning_intel",
      name: "规划部情报工作台",
      description: "",
      workspace_type: "department",
      default_domain_code: "ai",
      enabled: true,
      current_user_workspace_role: workspaceRole
    }
  ];
  return mount(NewsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("NewsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    newsApi.fetchDedupeGroups.mockResolvedValue([group()]);
    newsApi.fetchNewsItems.mockResolvedValue([newsItem()]);
    newsApi.normalizeNewsItems.mockResolvedValue({
      workspace_code: "planning_intel",
      raw_scanned: 0,
      news_created: 0,
      news_updated: 0,
      raw_skipped: 0,
      dedupe_groups_updated: 0,
      winners: 0,
      losers: 0
    });
    reportsApi.bulkAdoptDailyReportCandidates.mockResolvedValue({
      report: {
        id: "report-1",
        workspace_code: "planning_intel",
        domain_code: "ai",
        day_key: "2026-07-05",
        title: "日报",
        summary: "",
        status: "draft",
        published_at: null,
        items: []
      },
      created_total: 1,
      updated_total: 0,
      skipped_total: 0,
      skipped_items: []
    });
    reportsApi.bulkRejectDailyReportCandidates.mockResolvedValue({
      report: {
        id: "report-1",
        workspace_code: "planning_intel",
        domain_code: "ai",
        day_key: "2026-07-05",
        title: "日报",
        summary: "",
        status: "draft",
        published_at: null,
        items: []
      },
      created_total: 1,
      updated_total: 0,
      skipped_total: 0,
      skipped_items: []
    });
    watchersApi.fetchObjectWatcher.mockResolvedValue({
      object_type: "dedupe_group",
      object_id: "group-1",
      workspace_code: "planning_intel",
      watching: false,
      watcher_count: 0
    });
    watchersApi.updateObjectWatcher.mockResolvedValue({
      object_type: "dedupe_group",
      object_id: "group-1",
      workspace_code: "planning_intel",
      watching: true,
      watcher_count: 1
    });
  });

  it("highlights a candidate group from a search news_item route", async () => {
    routeState.query = { news_item_id: "news-2" };
    newsApi.fetchDedupeGroups.mockResolvedValue([
      group(),
      group({
        id: "group-2",
        dedupe_key: "search-hit",
        winner_news_item_id: "news-2",
        winner_title: "搜索命中的候选新闻",
        items: [
          {
            id: "group-item-2",
            news_item_id: "news-2",
            is_winner: true,
            duplicate_reason: "winner",
            rank_score: 1,
            title: "搜索命中的候选新闻",
            source_type: "rss",
            source_name: "Search RSS",
            source_url: "https://example.com/search-hit"
          }
        ]
      })
    ]);
    newsApi.fetchNewsItems.mockResolvedValue([
      newsItem(),
      newsItem({ id: "news-2", normalized_title: "搜索命中的候选新闻", source_title: "搜索命中的候选新闻" })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const anchored = wrapper.find(".candidate-card.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("搜索命中的候选新闻");
    // 去重状态使用已定义的 state-chip 胶囊，而不是无样式的 status-pill
    expect(wrapper.find(".candidate-meta .state-chip").text()).toContain("去重");
    expect(wrapper.text()).toContain("raw_item_id");
    expect(wrapper.text()).toContain("data_source_id");
    expect(wrapper.find('[aria-label="候选追溯链"]').text()).toContain("数据源");
    expect(wrapper.find('[aria-label="候选追溯链"]').text()).toContain("payload: title / link");
    expect(wrapper.find('[aria-label="候选追溯链"]').text()).toContain("去重组");
    expect(wrapper.find('[aria-label="候选追溯链"]').text()).toContain("确认原始信号已经完整入库");
  });

  it("highlights a candidate group from a raw trace route", async () => {
    routeState.query = { raw_item_id: "raw-2" };
    newsApi.fetchDedupeGroups.mockResolvedValue([
      group(),
      group({
        id: "group-2",
        dedupe_key: "raw-hit",
        winner_news_item_id: "news-2",
        winner_title: "Raw 命中的候选新闻",
        lineage: {
          nodes: [
            {
              object_type: "raw_item",
              object_id: "raw-2",
              label: "Raw 命中的候选新闻",
              status: "preserved",
              review_note: "确认原始信号已经完整入库。",
              target_path: "/news?raw_item_id=raw-2",
              occurred_at: "2026-07-05T09:00:00Z",
              metadata: { payload_keys: ["title"] }
            }
          ]
        },
        items: [
          {
            id: "group-item-2",
            news_item_id: "news-2",
            is_winner: true,
            duplicate_reason: "winner",
            rank_score: 1,
            title: "Raw 命中的候选新闻",
            source_type: "rss",
            source_name: "Raw RSS",
            source_url: "https://example.com/raw-hit"
          }
        ]
      })
    ]);
    newsApi.fetchNewsItems.mockResolvedValue([
      newsItem(),
      newsItem({ id: "news-2", raw_item_id: "raw-2", normalized_title: "Raw 命中的候选新闻" })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const anchored = wrapper.find(".candidate-card.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.text()).toContain("Raw 命中的候选新闻");
  });

  it("bulk adopts selected recommended candidates into a daily report", async () => {
    newsApi.fetchDedupeGroups.mockResolvedValue([
      group({
        recommendation: {
          run_id: "run-1",
          run_key: "run",
          day_key: "2026-07-05",
          recommendation_item_id: "rec-1",
          rank: 1,
          selected: false,
          final_score: 88,
          quality_score: 80,
          topic_score: 90,
          freshness_score: 70,
          feedback_score: 0,
          diversity_score: 0,
          source_score: 60,
          heat_score: 0,
          recommendation_reason: "technical_detail",
          admission_level: "P1",
          admission_score: 88,
          admission_pool: "ai_engineering",
          noise_types: [],
          reject_reasons: [],
          scorer_breakdown: {},
          expert_routes: ["AI工程"]
        }
      })
    ]);
    const wrapper = mountPage();
    await flushPromises();

    const checkbox = wrapper.find(".candidate-select input");
    await checkbox.setValue(true);
    await wrapper.find(".candidate-bulk-actions .icon-button").trigger("click");
    await flushPromises();

    expect(reportsApi.bulkAdoptDailyReportCandidates).toHaveBeenCalledWith({
      workspace_code: "planning_intel",
      day_key: expect.any(String),
      dedupe_group_ids: ["group-1"]
    });
    expect(wrapper.text()).toContain("批量采信完成：新增 1");
    expect(newsApi.fetchDedupeGroups).toHaveBeenCalledTimes(2);
  });

  it("passes candidate filters and sorting to the backend", async () => {
    const wrapper = mountPage();
    await flushPromises();
    newsApi.fetchDedupeGroups.mockClear();

    await wrapper.find('select[aria-label="推荐状态"]').setValue("recommended");
    await flushPromises();

    // 默认排序为 score_desc（ordering_consistency candidate_pool），筛选变化不改默认排序
    expect(newsApi.fetchDedupeGroups).toHaveBeenLastCalledWith(
      "planning_intel",
      100,
      expect.objectContaining({
        recommendationStatus: "recommended",
        dailyStatus: "all",
        admissionLevel: "",
        sourceType: "",
        sort: "score_desc"
      })
    );

    // 其他排序仅显式选择时生效
    await wrapper.find('select[aria-label="排序方式"]').setValue("updated_desc");
    await flushPromises();

    expect(newsApi.fetchDedupeGroups).toHaveBeenLastCalledWith(
      "planning_intel",
      100,
      expect.objectContaining({
        recommendationStatus: "recommended",
        sort: "updated_desc"
      })
    );
  });

  it("defaults the candidate pool sort to score_desc and shows 未评分 for unscored candidates", async () => {
    // ordering_consistency candidate_pool（recommendation_ranking.json）：
    // 不带显式排序选择时列表以 final_score 降序请求后端。
    const wrapper = mountPage();
    await flushPromises();

    expect(newsApi.fetchDedupeGroups).toHaveBeenCalledWith(
      "planning_intel",
      100,
      expect.objectContaining({ sort: "score_desc" })
    );
    const sortSelect = wrapper.find('select[aria-label="排序方式"]').element as HTMLSelectElement;
    expect(sortSelect.value).toBe("score_desc");

    // empty_metrics：final_score 缺失的历史候选显示「未评分」而非 0.0
    const judge = wrapper.find(".candidate-judge");
    expect(judge.text()).toContain("未评分");
    expect(judge.text()).not.toContain("0.0");
    expect(judge.text()).not.toContain("—");
  });

  it("bulk rejects selected recommended candidates into a daily report", async () => {
    newsApi.fetchDedupeGroups.mockResolvedValue([
      group({
        recommendation: {
          run_id: "run-1",
          run_key: "run",
          day_key: "2026-07-05",
          recommendation_item_id: "rec-1",
          rank: 1,
          selected: false,
          final_score: 88,
          quality_score: 80,
          topic_score: 90,
          freshness_score: 70,
          feedback_score: 0,
          diversity_score: 0,
          source_score: 60,
          heat_score: 0,
          recommendation_reason: "technical_detail",
          admission_level: "P1",
          admission_score: 88,
          admission_pool: "ai_engineering",
          noise_types: [],
          reject_reasons: [],
          scorer_breakdown: {},
          expert_routes: ["AI工程"]
        }
      })
    ]);
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find(".candidate-select input").setValue(true);
    const rejectButton = wrapper.findAll("button").find((button) => button.text().includes("批量剔除"));
    expect(rejectButton).toBeTruthy();
    await rejectButton!.trigger("click");
    await flushPromises();

    expect(reportsApi.bulkRejectDailyReportCandidates).toHaveBeenCalledWith({
      workspace_code: "planning_intel",
      day_key: expect.any(String),
      dedupe_group_ids: ["group-1"]
    });
    expect(wrapper.text()).toContain("批量剔除完成：新增 1");
    expect(newsApi.fetchDedupeGroups).toHaveBeenCalledTimes(2);
  });

  it("hides candidate write actions for workspace viewers", async () => {
    newsApi.fetchDedupeGroups.mockResolvedValue([
      group({
        recommendation: {
          run_id: "run-1",
          run_key: "run",
          day_key: "2026-07-05",
          recommendation_item_id: "rec-1",
          rank: 1,
          selected: false,
          final_score: 88,
          quality_score: 80,
          topic_score: 90,
          freshness_score: 70,
          feedback_score: 0,
          diversity_score: 0,
          source_score: 60,
          heat_score: 0,
          recommendation_reason: "technical_detail",
          admission_level: "P1",
          admission_score: 88,
          admission_pool: "ai_engineering",
          noise_types: [],
          reject_reasons: [],
          scorer_breakdown: {},
          expert_routes: ["AI工程"]
        }
      })
    ]);

    const wrapper = mountPage("viewer");
    await flushPromises();

    expect(wrapper.find(".candidate-select input").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("批量采信");
    expect(wrapper.text()).not.toContain("批量剔除");
    expect(reportsApi.bulkAdoptDailyReportCandidates).not.toHaveBeenCalled();
    expect(reportsApi.bulkRejectDailyReportCandidates).not.toHaveBeenCalled();
  });

  it("loads and toggles candidate watcher state from the details panel", async () => {
    routeState.query = { dedupe_group_id: "group-1" };
    const wrapper = mountPage();
    await flushPromises();

    const anchored = wrapper.find(".candidate-card.anchored");
    expect(anchored.exists()).toBe(true);
    const details = wrapper.find("details.candidate-details");
    (details.element as HTMLDetailsElement).open = true;
    await details.trigger("toggle");
    await flushPromises();

    expect(watchersApi.fetchObjectWatcher).toHaveBeenCalledWith("dedupe_group", "group-1");
    const watchButton = wrapper.findAll("button").find((button) => button.text().includes("关注候选"));
    expect(watchButton?.attributes("aria-pressed")).toBe("false");
    await watchButton?.trigger("click");
    await flushPromises();

    expect(watchersApi.updateObjectWatcher).toHaveBeenCalledWith("dedupe_group", "group-1", true);
    expect(wrapper.text()).toContain("已关注该候选");
  });
});
