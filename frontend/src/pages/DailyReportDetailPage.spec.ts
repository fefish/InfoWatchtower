import { mount, flushPromises } from "@vue/test-utils";
import { describe, expect, it, vi, beforeEach } from "vitest";

import DailyReportDetailPage from "./DailyReportDetailPage.vue";

const reportsApi = vi.hoisted(() => ({
  fetchDailyReport: vi.fn(),
  updateDailyReportItem: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  path: "/daily-reports/report-1",
  params: { id: "report-1" } as Record<string, string>
}));

vi.mock("../api/reports", () => ({
  fetchDailyReport: reportsApi.fetchDailyReport,
  updateDailyReportItem: reportsApi.updateDailyReportItem
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function reportItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "item-1",
    generated_news: {
      id: "generated-1",
      category: "模型",
      title: "AI 生成原始标题",
      summary: "AI 生成原始摘要",
      key_points: "原始要点",
      content_json: {
        background: "背景",
        effects: "效果",
        eventSummary: "事件",
        technologyAndInnovation: "技术",
        valueAndImpact: "价值"
      },
      source_url: "https://example.com/news",
      generation_status: "ready",
      news_item_id: "news-1",
      recommendation_item_id: "rec-1"
    },
    adoption_status: 2,
    is_headline: false,
    sort_order: 1,
    editor_title: null,
    editor_summary: null,
    editor_key_points: null,
    editor_content_json: null,
    editor_notes: "",
    reaction_count: 0,
    rating_count: 0,
    rating_avg: 0,
    comment_count: 0,
    ...overrides
  };
}

function reportRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "report-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    day_key: "2026-07-05",
    title: "规划部日报",
    summary: "今日摘要",
    status: "draft",
    published_at: null,
    items: [reportItem()],
    ...overrides
  };
}

function mountPage(path = "/daily-reports/report-1") {
  routeState.path = path;
  routeState.params = { id: "report-1" };
  return mount(DailyReportDetailPage);
}

describe("DailyReportDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reportsApi.fetchDailyReport.mockResolvedValue(reportRecord());
  });

  it("renders report items and prefers editor overrides over the generated originals", async () => {
    reportsApi.fetchDailyReport.mockResolvedValue(
      reportRecord({
        items: [
          reportItem({
            editor_title: "编辑改写后的标题",
            editor_summary: "编辑改写后的摘要",
            adoption_status: 1
          })
        ]
      })
    );
    const wrapper = mountPage();
    await flushPromises();

    expect(reportsApi.fetchDailyReport).toHaveBeenCalledWith("report-1");
    const card = wrapper.find(".detail-news-card");
    // editor_* 覆盖显示优先于 generated_news 原文；未覆盖的字段回退原文。
    expect(card.find("h3").text()).toBe("编辑改写后的标题");
    expect(card.text()).toContain("编辑改写后的摘要");
    expect(card.text()).not.toContain("AI 生成原始标题");
    expect(card.text()).toContain("原始要点");
    expect(card.find(".state-chip").text()).toBe("备选");
  });

  it("keeps the published detail route read-only without any edit controls", async () => {
    reportsApi.fetchDailyReport.mockResolvedValue(
      reportRecord({ status: "published", published_at: "2026-07-05T10:00:00Z" })
    );
    const wrapper = mountPage("/daily-reports/report-1");
    await flushPromises();

    // 详情路由（非 /edit）只读：不渲染编辑按钮，也不渲染编辑表单。
    const buttonTexts = wrapper.findAll("button").map((button) => button.text());
    expect(buttonTexts.some((text) => text.includes("编辑"))).toBe(false);
    expect(wrapper.find(".editor-form").exists()).toBe(false);
    expect(wrapper.text()).toContain("published");
  });

  it("saves report-layer edits only and never touches the generated originals", async () => {
    reportsApi.updateDailyReportItem.mockResolvedValue(
      reportItem({
        editor_title: "人工修订标题",
        editor_summary: "人工修订摘要",
        editor_key_points: "人工要点",
        editor_notes: "复核过来源",
        adoption_status: 0
      })
    );
    const wrapper = mountPage("/daily-reports/report-1/edit");
    await flushPromises();

    const editButton = wrapper.findAll("button").find((button) => button.text().includes("编辑"));
    expect(editButton).toBeTruthy();
    await editButton!.trigger("click");

    const form = wrapper.find(".editor-form");
    await form.find("input").setValue("人工修订标题");
    await form.find("textarea").setValue("人工修订摘要");
    await form.findAll("input")[1].setValue("人工要点");
    await form.findAll("textarea")[1].setValue("复核过来源");
    await form.find("select").setValue("0");
    await form.findAll("button").find((button) => button.text().includes("保存"))!.trigger("click");
    await flushPromises();

    // 调用形状锁定：payload 只含报告层 editor_*/adoption_status 字段，不包含 generated_news 原文字段。
    expect(reportsApi.updateDailyReportItem).toHaveBeenCalledWith("item-1", {
      editor_title: "人工修订标题",
      editor_summary: "人工修订摘要",
      editor_key_points: "人工要点",
      editor_notes: "复核过来源",
      adoption_status: 0
    });
    expect(wrapper.text()).toContain("日报条目已保存");
    // 保存后展示编辑稿与新采信状态，原始 generated_news 字段未被改写。
    const card = wrapper.find(".detail-news-card");
    expect(card.find("h3").text()).toBe("人工修订标题");
    expect(card.find(".state-chip").text()).toBe("剔除");
    expect(card.find(".category-chip").text()).toBe("模型");
  });

  it("shows the load error and the empty fallback when the report cannot be fetched", async () => {
    reportsApi.fetchDailyReport.mockRejectedValue(new Error("permission denied: workspace membership required"));
    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find(".form-error").text()).toContain("permission denied: workspace membership required");
    expect(wrapper.find(".empty-state").text()).toContain("没有找到这份日报");
  });
});
