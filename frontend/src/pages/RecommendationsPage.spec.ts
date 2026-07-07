import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RecommendationsPage from "./RecommendationsPage.vue";
import { useWorkspaceStore } from "../stores/workspace";

const api = vi.hoisted(() => ({
  fetchRecommendationRuns: vi.fn(),
  fetchRecommendationRun: vi.fn(),
  createRecommendationRun: vi.fn(),
  fetchScorerPolicy: vi.fn(),
  previewScorer: vi.fn(),
  bulkAdoptDailyReportCandidates: vi.fn(),
  bulkRejectDailyReportCandidates: vi.fn()
}));

vi.mock("../api/recommendations", () => ({
  fetchRecommendationRuns: api.fetchRecommendationRuns,
  fetchRecommendationRun: api.fetchRecommendationRun,
  createRecommendationRun: api.createRecommendationRun,
  fetchScorerPolicy: api.fetchScorerPolicy,
  previewScorer: api.previewScorer
}));

vi.mock("../api/reports", () => ({
  bulkAdoptDailyReportCandidates: api.bulkAdoptDailyReportCandidates,
  bulkRejectDailyReportCandidates: api.bulkRejectDailyReportCandidates
}));

const baseRun = {
  id: "run-1",
  run_key: "planning_intel:2026-05-05",
  workspace_code: "planning_intel",
  domain_code: "ai",
  status: "completed",
  started_at: null,
  completed_at: "2026-05-05T01:00:00Z",
  params_json: {},
  summary_json: {},
  items: []
};

function recommendationItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "item-1",
    news_item_id: "news-1",
    dedupe_group_id: "group-1",
    rank: 1,
    quality_score: 80,
    topic_score: 90,
    freshness_score: 70,
    feedback_score: 0,
    diversity_score: 10,
    source_score: 90,
    heat_score: 0,
    final_score: 78,
    selected: false,
    recommendation_reason: "admission=P2",
    admission_level: "P2",
    admission_score: 72,
    admission_pool: "ai_engineering",
    noise_types: [],
    reject_reasons: [],
    scorer_breakdown: {},
    expert_routes: ["AI Infra"],
    source_title: "Observation pool candidate",
    source_name: "Example RSS",
    source_url: "https://example.com/observation",
    daily_report: null,
    ...overrides
  };
}

function mountPage() {
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

  return mount(RecommendationsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("RecommendationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchRecommendationRuns.mockResolvedValue([]);
    api.fetchRecommendationRun.mockResolvedValue(null);
    api.fetchScorerPolicy.mockResolvedValue({
      workspace_code: "planning_intel",
      config_loaded: true,
      enabled: true,
      config_version: "content-scorer-2026-test",
      config_path: "/repo/config/scoring/content_scorer_v2.json",
      thresholds: { P0: 96, P1: 84, P2: 56, P3: 40 },
      daily_levels: ["P0", "P1"],
      weekly_levels: ["P0", "P1", "P2"],
      weights: [
        { name: "topic", value: 40 },
        { name: "impact", value: 10 },
        { name: "source", value: 8 }
      ],
      top_topics: [
        { name: "AI推理与服务加速", value: 10 },
        { name: "基础竞争力", value: 10 }
      ],
      source_tiers: [{ name: "P0", value: 8 }],
      source_channels: [{ name: "官方技术规范/标准/RFC/Release", value: 5 }],
      noise_rule_count: 12,
      direct_reject_noise_types: ["commercial_finance", "rumor"],
      formula_notes: ["topic score formula"]
    });
    api.previewScorer.mockResolvedValue({
      workspace_code: "planning_intel",
      source_title: "New inference serving architecture improves agent latency benchmark",
      admission_level: "P1",
      admission_score: 88.5,
      admission_pool: "ai_engineering",
      eligible_for_daily: true,
      noise_types: ["commercial_finance"],
      reject_reasons: [],
      positive_reasons: ["technical_detail"],
      expert_routes: ["AI Infra"],
      scorer_breakdown: { mode: "content_scorer_v2" },
      persistence: "not_persisted"
    });
    api.bulkAdoptDailyReportCandidates.mockResolvedValue({
      report: { day_key: "2026-05-05" },
      created_total: 1,
      updated_total: 0,
      skipped_total: 0,
      skipped_items: []
    });
    api.bulkRejectDailyReportCandidates.mockResolvedValue({
      report: { day_key: "2026-05-05" },
      created_total: 1,
      updated_total: 0,
      skipped_total: 0,
      skipped_items: []
    });
  });

  it("shows the backend scorer policy summary", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(api.fetchScorerPolicy).toHaveBeenCalledWith("planning_intel");
    expect(wrapper.text()).toContain("内容评分器");
    expect(wrapper.text()).toContain("规则已启用");
    expect(wrapper.text()).toContain("content-scorer-2026-test");
    expect(wrapper.text()).toContain("P1≥84");
    expect(wrapper.text()).toContain("P0 / P1");
    expect(wrapper.text()).toContain("周报：P0 / P1 / P2");
    expect(wrapper.text()).toContain("topic 40");
    expect(wrapper.text()).toContain("12 条规则");
    expect(wrapper.text()).toContain("commercial_finance");
  });

  it("previews a scorer result without creating a recommendation run", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find('[aria-label="评分预览"] button.icon-button').trigger("click");
    await flushPromises();

    expect(api.previewScorer).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        source_title: "New inference serving architecture improves agent latency benchmark",
        source_type: "rss",
        source_tier: "P0",
        source_tags: ["AI基础设施", "推理服务"]
      })
    );
    expect(api.createRecommendationRun).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("P1 · 88.50");
    expect(wrapper.text()).toContain("ai_engineering");
    expect(wrapper.text()).toContain("可进日报候选");
    expect(wrapper.text()).toContain("commercial_finance");
    expect(wrapper.text()).toContain("未写入推荐 run");
  });

  it("reviews P2/P3 observation candidates through the daily report adoption API", async () => {
    const runBefore = {
      ...baseRun,
      items: [
        recommendationItem({
          id: "item-p2",
          dedupe_group_id: "group-p2",
          source_title: "P2 observation candidate",
          admission_level: "P2",
          selected: false
        }),
        recommendationItem({
          id: "item-p1",
          dedupe_group_id: "group-p1",
          source_title: "Selected P1 candidate",
          admission_level: "P1",
          selected: true
        })
      ]
    };
    const runAfter = {
      ...runBefore,
      items: [
        {
          ...runBefore.items[0],
          daily_report: {
            daily_report_id: "report-1",
            daily_report_item_id: "daily-item-1",
            day_key: "2026-05-05",
            report_status: "draft",
            adoption_status: 2,
            generated_news_id: "generated-1",
            generation_status: "ready"
          }
        },
        runBefore.items[1]
      ]
    };
    api.fetchRecommendationRuns.mockResolvedValue([{ ...baseRun, items: [] }]);
    api.fetchRecommendationRun.mockResolvedValueOnce(runBefore).mockResolvedValueOnce(runAfter);
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find('input[type="date"]').setValue("2026-05-05");
    expect(wrapper.find('[aria-label="观察池复核"]').text()).toContain("P2 observation candidate");
    expect(wrapper.find('[aria-label="观察池复核"]').text()).not.toContain("Selected P1 candidate");

    await wrapper.find('[aria-label="观察池复核"] input[type="checkbox"]').setValue(true);
    await wrapper.find('[aria-label="观察池复核"] button.icon-button').trigger("click");
    await flushPromises();

    expect(api.bulkAdoptDailyReportCandidates).toHaveBeenCalledWith({
      workspace_code: "planning_intel",
      day_key: "2026-05-05",
      dedupe_group_ids: ["group-p2"]
    });
    expect(api.fetchRecommendationRun).toHaveBeenLastCalledWith("run-1");
    expect(wrapper.text()).toContain("观察池采信完成");
    expect(wrapper.text()).toContain("已采信 · 2026-05-05");
  });
});
