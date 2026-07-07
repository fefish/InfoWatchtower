import { mount, flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReportTimeline from "./ReportTimeline.vue";

const operationsApi = vi.hoisted(() => ({
  fetchReportArchive: vi.fn(),
  fetchReportArchiveSummary: vi.fn()
}));

vi.mock("../api/operations", () => operationsApi);

type ObserverCallback = (entries: Array<{ isIntersecting: boolean }>) => void;

let observerCallback: ObserverCallback | null = null;

class IntersectionObserverStub {
  constructor(callback: ObserverCallback) {
    observerCallback = callback;
  }

  observe() {}

  unobserve() {}

  disconnect() {}
}

function archiveEntry(dateKey: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `archive-${dateKey}`,
    origin: "published",
    report_type: "daily",
    workspace_code: "planning_intel",
    title: `${dateKey} 日报`,
    date_key: dateKey,
    month: dateKey.slice(0, 7),
    status: "published",
    published_at: `${dateKey}T12:00:00Z`,
    item_count: 5,
    adopted_count: 4,
    headline_count: 1,
    adoption_rate: 0.8,
    top_sources: [],
    detail_kind: "daily_report",
    detail_id: `report-${dateKey}`,
    content_excerpt: "",
    ...overrides
  };
}

function summaryRecord(months: Array<{ month: string; count: number }>) {
  return {
    workspace_code: "planning_intel",
    total: 10,
    published_daily: 8,
    published_weekly: 2,
    legacy_reports: 0,
    total_items: 40,
    total_adopted: 30,
    average_adoption_rate: 0.75,
    months,
    latest_published_at: "2026-07-05T12:00:00Z"
  };
}

function mountTimeline(props: Record<string, unknown> = {}) {
  return mount(ReportTimeline, {
    props: {
      reportType: "daily",
      workspaceCode: "planning_intel",
      pageSize: 2,
      ...props
    }
  });
}

describe("ReportTimeline", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    observerCallback = null;
    vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
    operationsApi.fetchReportArchive.mockResolvedValue([]);
    operationsApi.fetchReportArchiveSummary.mockResolvedValue(summaryRecord([]));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("groups published nodes by month with month heads and count badges", async () => {
    operationsApi.fetchReportArchive.mockResolvedValueOnce([
      archiveEntry("2026-07-05"),
      archiveEntry("2026-06-30", { month: "2026-06", item_count: 3 })
    ]);

    const wrapper = mountTimeline();
    await flushPromises();

    // 已发布层调用形状：report_type + origin=published + offset/limit 分页（archive-knowledge-design §5.1）
    expect(operationsApi.fetchReportArchive).toHaveBeenCalledWith({
      workspaceCode: "planning_intel",
      reportType: "daily",
      origin: "published",
      offset: 0,
      limit: 2
    });

    const heads = wrapper.findAll(".timeline-month-head").map((head) => head.text());
    expect(heads).toEqual(["2026 年 7 月 · 1 份", "2026 年 6 月 · 1 份"]);
    const firstNode = wrapper.find(".timeline-node");
    expect(firstNode.find("strong").text()).toBe("07-05");
    expect(firstNode.find(".timeline-count").text()).toBe("5 条");
    expect(firstNode.find(".timeline-dot").classes()).toContain("published");
  });

  it("loads the next page with an incremented offset when the sentinel intersects", async () => {
    operationsApi.fetchReportArchive
      .mockResolvedValueOnce([archiveEntry("2026-07-05"), archiveEntry("2026-07-04")])
      .mockResolvedValueOnce([archiveEntry("2026-07-03")]);

    const wrapper = mountTimeline();
    await flushPromises();
    expect(wrapper.findAll(".timeline-node")).toHaveLength(2);

    observerCallback?.([{ isIntersecting: true }]);
    await flushPromises();

    expect(operationsApi.fetchReportArchive).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 2, limit: 2 })
    );
    expect(wrapper.findAll(".timeline-node")).toHaveLength(3);

    // 第二页不足一页视为到底：再次触底不再发请求（不无限打点）。
    observerCallback?.([{ isIntersecting: true }]);
    await flushPromises();
    expect(operationsApi.fetchReportArchive).toHaveBeenCalledTimes(2);
  });

  it("jumps to an unloaded month by fetching that month directly", async () => {
    operationsApi.fetchReportArchive
      .mockResolvedValueOnce([archiveEntry("2026-07-05"), archiveEntry("2026-07-04")])
      .mockResolvedValueOnce([archiveEntry("2026-03-10", { month: "2026-03" })]);
    operationsApi.fetchReportArchiveSummary.mockResolvedValue(
      summaryRecord([
        { month: "2026-07", count: 2 },
        { month: "2026-03", count: 1 }
      ])
    );

    const wrapper = mountTimeline();
    await flushPromises();

    const jump = wrapper.find(".timeline-month-jump");
    expect(jump.exists()).toBe(true);
    await jump.setValue("2026-03");
    await flushPromises();

    expect(operationsApi.fetchReportArchive).toHaveBeenLastCalledWith(
      expect.objectContaining({ month: "2026-03", origin: "published", reportType: "daily" })
    );
    expect(wrapper.find('[data-month="2026-03"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("2026 年 3 月 · 1 份");
  });

  it("shows a retriable error row instead of silently stopping on load failure", async () => {
    operationsApi.fetchReportArchive
      .mockRejectedValueOnce(new Error("archive unavailable"))
      .mockResolvedValueOnce([archiveEntry("2026-07-05")]);

    const wrapper = mountTimeline();
    await flushPromises();

    const errorRow = wrapper.find(".timeline-error");
    expect(errorRow.exists()).toBe(true);
    expect(errorRow.text()).toContain("archive unavailable");

    await errorRow.find("button").trigger("click");
    await flushPromises();

    expect(wrapper.find(".timeline-error").exists()).toBe(false);
    expect(wrapper.findAll(".timeline-node")).toHaveLength(1);
  });

  it("renders draft nodes only when the caller can view drafts", async () => {
    const localReports = [
      { id: "draft-1", key: "2026-07-06", status: "draft", itemCount: 4 },
      { id: "published-1", key: "2026-07-05", status: "published", itemCount: 6 }
    ];

    // viewer：草稿节点不渲染（归档索引不含草稿，本地层被过滤）。
    const viewerWrapper = mountTimeline({ localReports, canViewDrafts: false });
    await flushPromises();
    expect(viewerWrapper.findAll(".timeline-node")).toHaveLength(1);
    expect(viewerWrapper.text()).not.toContain("草稿");

    // member+：草稿节点渲染为灰点。
    const memberWrapper = mountTimeline({ localReports, canViewDrafts: true });
    await flushPromises();
    const nodes = memberWrapper.findAll(".timeline-node");
    expect(nodes).toHaveLength(2);
    expect(nodes[0].text()).toContain("草稿");
    expect(nodes[0].find(".timeline-dot").classes()).toContain("draft");
  });

  it("dedupes archive entries against local report objects by key", async () => {
    operationsApi.fetchReportArchive.mockResolvedValueOnce([archiveEntry("2026-07-05")]);

    const wrapper = mountTimeline({
      localReports: [{ id: "report-local", key: "2026-07-05", status: "published", itemCount: 9 }],
      canViewDrafts: true
    });
    await flushPromises();

    // 同一 day_key 以报告对象为准：只有一个节点，条数来自本地报告对象。
    const nodes = wrapper.findAll(".timeline-node");
    expect(nodes).toHaveLength(1);
    expect(nodes[0].find(".timeline-count").text()).toBe("9 条");

    await nodes[0].trigger("click");
    expect(wrapper.emitted("select")?.[0]?.[0]).toMatchObject({
      detailId: "report-local",
      origin: "local"
    });
  });

  it("labels weekly nodes with the week key and emits archive selections", async () => {
    operationsApi.fetchReportArchive.mockResolvedValueOnce([
      archiveEntry("2026-W27", {
        report_type: "weekly",
        month: "2026-06",
        detail_kind: "weekly_report",
        detail_id: "weekly-27"
      })
    ]);

    const wrapper = mountTimeline({ reportType: "weekly" });
    await flushPromises();

    const node = wrapper.find(".timeline-node");
    expect(node.find("strong").text()).toBe("2026-W27");

    await node.trigger("click");
    expect(wrapper.emitted("select")?.[0]?.[0]).toMatchObject({
      detailId: "weekly-27",
      origin: "archive",
      status: "published"
    });
  });

  it("shows the empty state only after the archive confirms there are no reports", async () => {
    const wrapper = mountTimeline();
    await flushPromises();

    expect(wrapper.find(".empty-state").text()).toContain("还没有报告，生成第一份日报后会出现在这里");
  });
});
