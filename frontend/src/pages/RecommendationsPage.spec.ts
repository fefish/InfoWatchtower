import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RecommendationsPage from "./RecommendationsPage.vue";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const api = vi.hoisted(() => ({
  fetchRecommendationRuns: vi.fn(),
  fetchRecommendationRun: vi.fn(),
  createRecommendationRun: vi.fn(),
  fetchScorerPolicy: vi.fn(),
  previewScorer: vi.fn(),
  fetchFeedbackRollups: vi.fn(),
  fetchFeedbackRollupDetail: vi.fn(),
  bulkAdoptDailyReportCandidates: vi.fn(),
  bulkRejectDailyReportCandidates: vi.fn()
}));

vi.mock("../api/recommendations", () => ({
  fetchRecommendationRuns: api.fetchRecommendationRuns,
  fetchRecommendationRun: api.fetchRecommendationRun,
  createRecommendationRun: api.createRecommendationRun,
  fetchScorerPolicy: api.fetchScorerPolicy,
  previewScorer: api.previewScorer,
  fetchFeedbackRollups: api.fetchFeedbackRollups,
  fetchFeedbackRollupDetail: api.fetchFeedbackRollupDetail
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

// WP4-G 反馈评估卡 fixture（page-specs §9.3；契约 feedback_workflow）
function feedbackRollupRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "rollup-1",
    workspace_code: "planning_intel",
    period_type: "weekly",
    period_key: "2026-W27",
    window_start: "2026-06-29T00:00:00+08:00",
    window_end: "2026-07-06T00:00:00+08:00",
    status: "succeeded",
    proposal_status: "generated",
    metrics: {
      precision_at_6: 0.3333,
      precision_at_12: 0.2857,
      rerank_uplift: 0.1667,
      source_coverage: 0.5,
      topic_entropy: 0.5,
      normalized_adopt_rate: 0.2857,
      edit_rate: 0.5,
      low_data_sources: [{ id: "src-low", name: "Low Data Source" }]
    },
    computed_at: "2026-07-06T03:00:00+08:00",
    ...overrides
  };
}

function feedbackRollupDetailRecord(overrides: Record<string, unknown> = {}) {
  return {
    ...feedbackRollupRecord(),
    source_breakdown: {
      window: "28d",
      sources: [
        {
          data_source_id: "src-low",
          name: "Low Data Source",
          recommended_count: 2,
          adopted_count: 1,
          rejected_count: 0,
          normalized_adopt_rate: 0.5,
          reject_rate: 0,
          suggestion: "insufficient_data"
        }
      ],
      stale_source_suggestions: [
        { id: "src-stale", name: "Stale Source", suggestion: "suggest_disable", reason: "连续 4 周零推荐" }
      ]
    },
    topic_breakdown: {},
    sample_refs: {},
    ...overrides
  };
}

function mountPage(options: { workspaceRole?: string } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const session = useSessionStore();
  session.user = {
    id: "user-1",
    external_provider: "local",
    external_id: "admin",
    employee_no: null,
    username: "admin",
    display_name: "运营管理员",
    department: null,
    email: null,
    roles: ["viewer"] as never,
    status: "active",
    is_active: true
  };
  session.checked = true;
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  workspace.options = [
    {
      code: "planning_intel",
      name: "规划部情报工作台",
      description: "",
      workspace_type: "team",
      default_domain_code: "ai",
      enabled: true,
      current_user_workspace_role: options.workspaceRole ?? "admin"
    }
  ];

  return mount(RecommendationsPage, {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: {
          props: ["to"],
          template: '<a :href="typeof to === \'string\' ? to : \'#\'"><slot /></a>'
        }
      }
    }
  });
}

describe("RecommendationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchRecommendationRuns.mockResolvedValue([]);
    api.fetchRecommendationRun.mockResolvedValue(null);
    api.fetchFeedbackRollups.mockResolvedValue({ items: [], total: 0 });
    api.fetchFeedbackRollupDetail.mockResolvedValue(feedbackRollupDetailRecord());
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

  it("links the page header to the label policy card in workspace settings", async () => {
    // 候选池的“标签策略”心智入口：跳工作台配置中心的标签卡片锚点，不再有第二份编辑面板。
    const wrapper = mountPage();
    await flushPromises();

    const link = wrapper.find('a[href="/workspace-settings#labels"]');
    expect(link.exists()).toBe(true);
    expect(link.text()).toContain("标签策略");
    expect(wrapper.find(".policy-panel").exists()).toBe(false);
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

  it("hides the average score metric for a run without candidates instead of rendering 0.00", async () => {
    // 空指标隐藏（recommendation_ranking.json ordering_consistency empty_metrics）：
    // 无样本的均值类指标整体隐藏，不渲染占位 0.00。
    api.fetchRecommendationRuns.mockResolvedValue([{ ...baseRun, items: [] }]);
    api.fetchRecommendationRun.mockResolvedValue({ ...baseRun, items: [] });

    const wrapper = mountPage();
    await flushPromises();

    const stats = wrapper.find(".run-detail .module-mini-stats");
    expect(stats.exists()).toBe(true);
    expect(stats.text()).toContain("0 候选");
    expect(stats.text()).not.toContain("均分");
    expect(stats.text()).not.toContain("0.00");
  });

  it("shows the average score metric when the run has scored candidates", async () => {
    api.fetchRecommendationRuns.mockResolvedValue([{ ...baseRun, items: [] }]);
    api.fetchRecommendationRun.mockResolvedValue({
      ...baseRun,
      items: [recommendationItem({ final_score: 78 }), recommendationItem({ id: "item-2", final_score: 82 })]
    });

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find(".run-detail .module-mini-stats").text()).toContain("80.00 均分");
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

  // -------------------------------------------------------------------------
  // WP4-G 反馈评估卡（page-specs §9.3/§9.4；契约 feedback_workflow
  // acceptance_assertions ui_empty_state：空态 + null 指标整项隐藏 + 只读）
  // -------------------------------------------------------------------------

  it("renders the feedback evaluation empty state without a 0.0 placeholder", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const card = wrapper.find('[aria-label="反馈评估"]');
    expect(card.exists()).toBe(true);
    expect(api.fetchFeedbackRollups).toHaveBeenCalledWith("planning_intel", "weekly", 8);
    expect(card.text()).toContain("尚未生成反馈评估");
    expect(card.text()).not.toContain("0.0");
  });

  it("hides the feedback evaluation card and skips the call for members and viewers", async () => {
    for (const role of ["member", "viewer"]) {
      vi.clearAllMocks();
      api.fetchRecommendationRuns.mockResolvedValue([]);
      api.fetchScorerPolicy.mockResolvedValue(null);
      const wrapper = mountPage({ workspaceRole: role });
      await flushPromises();

      expect(wrapper.find('[aria-label="反馈评估"]').exists()).toBe(false);
      expect(api.fetchFeedbackRollups).not.toHaveBeenCalled();
    }
  });

  it("switches period_type and reloads the rollup list", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const monthlyButton = wrapper
      .findAll('[aria-label="反馈评估"] button')
      .find((button) => button.text() === "月");
    expect(monthlyButton).toBeDefined();
    await monthlyButton!.trigger("click");
    await flushPromises();
    expect(api.fetchFeedbackRollups).toHaveBeenLastCalledWith("planning_intel", "monthly", 8);
  });

  it("hides null metrics entirely in the expanded rollup detail", async () => {
    api.fetchFeedbackRollups.mockResolvedValue({
      items: [
        feedbackRollupRecord({
          status: "empty",
          proposal_status: "none",
          metrics: {
            precision_at_6: null,
            precision_at_12: null,
            rerank_uplift: null,
            source_coverage: null,
            topic_entropy: null,
            normalized_adopt_rate: null,
            edit_rate: null,
            low_data_sources: []
          }
        })
      ],
      total: 1
    });
    const wrapper = mountPage();
    await flushPromises();

    const card = wrapper.find('[aria-label="反馈评估"]');
    expect(card.text()).toContain("2026-W27");
    await card.find(".rollup-head").trigger("click");
    await flushPromises();
    expect(card.text()).toContain("本周期无可用指标");
    expect(card.text()).not.toContain("precision@6");
    expect(card.text()).not.toContain("0.0");
  });

  it("expands a rollup row into metrics, tier suggestions and stale source lists (read-only)", async () => {
    api.fetchFeedbackRollups.mockResolvedValue({ items: [feedbackRollupRecord()], total: 1 });
    const wrapper = mountPage();
    await flushPromises();

    const card = wrapper.find('[aria-label="反馈评估"]');
    await card.find(".rollup-head").trigger("click");
    await flushPromises();

    expect(api.fetchFeedbackRollupDetail).toHaveBeenCalledWith("planning_intel", "rollup-1");
    expect(card.text()).toContain("precision@6");
    expect(card.text()).toContain("0.3333");
    expect(card.text()).toContain("rerank uplift");
    expect(card.text()).toContain("edit_rate");
    expect(card.text()).toContain("源分层建议");
    expect(card.text()).toContain("Low Data Source");
    expect(card.text()).toContain("低数据");
    expect(card.text()).toContain("失效源清理建议");
    expect(card.text()).toContain("Stale Source");
    // 只读展示：不得出现未设计的源禁用/权重编辑动作（page-specs §9.4）。
    expect(card.text()).not.toContain("禁用该源");
    expect(card.find('input[type="checkbox"]').exists()).toBe(false);
  });
});
