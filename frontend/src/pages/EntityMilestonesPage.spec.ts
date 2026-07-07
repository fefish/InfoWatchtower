import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EntityMilestonesPage from "./EntityMilestonesPage.vue";
import type {
  EntityMilestoneDetailRecord,
  EntityMilestoneListItem,
  EntityTimelineSummaryRecord,
  TrackedEntityListItem,
  TrackedEntityTimelineRecord
} from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createEntityMilestone: vi.fn(),
  createRequirement: vi.fn(),
  createTrackedEntity: vi.fn(),
  fetchEntityMilestoneDetail: vi.fn(),
  fetchEntityTimelineSummary: vi.fn(),
  fetchTrackedEntities: vi.fn(),
  fetchTrackedEntityTimeline: vi.fn(),
  updateEntityMilestone: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

const routerState = vi.hoisted(() => ({
  push: vi.fn()
}));

vi.mock("../api/operations", () => ({
  createEntityMilestone: operationsApi.createEntityMilestone,
  createRequirement: operationsApi.createRequirement,
  createTrackedEntity: operationsApi.createTrackedEntity,
  fetchEntityMilestoneDetail: operationsApi.fetchEntityMilestoneDetail,
  fetchEntityTimelineSummary: operationsApi.fetchEntityTimelineSummary,
  fetchTrackedEntities: operationsApi.fetchTrackedEntities,
  fetchTrackedEntityTimeline: operationsApi.fetchTrackedEntityTimeline,
  updateEntityMilestone: operationsApi.updateEntityMilestone
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState,
  useRouter: () => routerState
}));

function entity(overrides: Partial<TrackedEntityListItem> = {}): TrackedEntityListItem {
  return {
    id: "entity-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    legacy_system: "current",
    legacy_id: "seed:openai",
    name: "OpenAI",
    entity_type: "company",
    rank: "A",
    aliases_json: ["欧宾AI"],
    influence_score: 90,
    milestone_count: 2,
    latest_event_time: "2026-07-05T09:00:00Z",
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function milestone(overrides: Partial<EntityMilestoneListItem> = {}): EntityMilestoneListItem {
  return {
    id: "milestone-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    legacy_system: "current",
    legacy_id: "entity-1:news-1",
    tracked_entity_id: "entity-1",
    entity_name: "OpenAI",
    entity_type: "company",
    legacy_article_id: null,
    legacy_report_id: null,
    raw_item_id: "raw-1",
    historical_report_id: null,
    event_time: "2026-07-05T09:00:00Z",
    event_type: "report_mention",
    title: "OpenAI 发布企业 Agent 平台",
    timeline_brief: "企业 Agent 平台上线",
    source_url: "https://example.com/openai-agent",
    source_name: "机器之心",
    board: "AI 应用",
    selected_for_timeline: false,
    curation_status: "candidate",
    importance_score: 55,
    importance_level: "medium",
    article_ref_resolved: true,
    report_ref_resolved: true,
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function milestoneDetail(overrides: Partial<EntityMilestoneDetailRecord> = {}): EntityMilestoneDetailRecord {
  return {
    ...milestone(),
    event_content: "完整事件正文",
    impact: "影响说明",
    event_brief: "事件摘要",
    impact_brief: "影响摘要",
    confidence_score: 0.6,
    event_dedupe_key: "entity-1:news-1",
    legacy_refs: {},
    metadata_json: {
      curation_status: "candidate",
      current_refs: { source_report_id: "report-1", news_item_id: "news-1" }
    },
    ...overrides
  };
}

function timelineRecord(overrides: Partial<TrackedEntityTimelineRecord> = {}): TrackedEntityTimelineRecord {
  return {
    entity: entity(),
    total_milestones: 2,
    candidate_count: 1,
    confirmed_count: 1,
    groups: [
      {
        month: "2026-07",
        milestone_count: 1,
        candidate_count: 1,
        milestones: [milestone()]
      },
      {
        month: "2026-06",
        milestone_count: 1,
        candidate_count: 0,
        milestones: [
          milestone({
            id: "milestone-confirmed",
            legacy_id: "manual:abc",
            event_time: "2026-06-20T09:00:00Z",
            title: "OpenAI 完成新一轮融资",
            curation_status: "confirmed",
            selected_for_timeline: true
          })
        ]
      }
    ],
    ...overrides
  };
}

function summary(): EntityTimelineSummaryRecord {
  return {
    workspace_code: "planning_intel",
    total_entities: 2,
    total_milestones: 2,
    selected_milestones: 1,
    unresolved_milestone_count: 0,
    unresolved_ref_count: 0,
    by_entity_type: { company: 2 },
    by_event_type: { report_mention: 1, manual: 1 },
    by_importance_level: { medium: 2 },
    earliest_event_time: "2026-06-20T09:00:00Z",
    latest_event_time: "2026-07-05T09:00:00Z"
  };
}

function mountPage(options: { workspaceRole?: string } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  workspace.options = [
    {
      code: "planning_intel",
      name: "规划部情报工作台",
      description: "",
      workspace_type: "intelligence_workspace",
      default_domain_code: "ai",
      enabled: true,
      current_user_workspace_role: options.workspaceRole ?? "viewer"
    }
  ];
  return mount(EntityMilestonesPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("EntityMilestonesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    operationsApi.fetchEntityTimelineSummary.mockResolvedValue(summary());
    operationsApi.fetchTrackedEntities.mockResolvedValue([entity(), entity({ id: "entity-2", name: "Anthropic" })]);
    operationsApi.fetchTrackedEntityTimeline.mockResolvedValue(timelineRecord());
    operationsApi.fetchEntityMilestoneDetail.mockImplementation((id: string) =>
      Promise.resolve(milestoneDetail({ id }))
    );
    operationsApi.updateEntityMilestone.mockImplementation((id: string, payload: Record<string, unknown>) =>
      Promise.resolve(
        milestoneDetail({
          id,
          curation_status: String(payload.curation_status || "confirmed"),
          selected_for_timeline: payload.curation_status !== "revoked"
        })
      )
    );
    operationsApi.createTrackedEntity.mockResolvedValue(entity({ id: "entity-new", name: "Moonshot" }));
    operationsApi.createEntityMilestone.mockResolvedValue(milestoneDetail({ id: "manual-1" }));
    operationsApi.createRequirement.mockResolvedValue({
      id: "req-1",
      title: "跟进：OpenAI 发布企业 Agent 平台"
    });
  });

  it("renders the month-grouped timeline with candidate styling and news trace link", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchTrackedEntityTimeline).toHaveBeenCalledWith("entity-1");
    const monthHeadings = wrapper.findAll(".timeline-month span");
    expect(monthHeadings.map((node) => node.text())).toEqual(["2026年07月", "2026年06月"]);
    expect(wrapper.find(".timeline-month small").text()).toContain("1 待确认");

    const candidateRow = wrapper.find(".milestone-row.candidate");
    expect(candidateRow.exists()).toBe(true);
    expect(candidateRow.text()).toContain("待确认");

    await candidateRow.find(".trace-toggle").trigger("click");
    const trace = wrapper.find(".trace-block");
    expect(trace.exists()).toBe(true);
    expect(trace.text()).toContain("机器之心");
    expect(trace.find("a").attributes("href")).toBe("https://example.com/openai-agent");
  });

  it("lets an admin confirm and reject a candidate from the timeline", async () => {
    const wrapper = mountPage({ workspaceRole: "admin" });
    await flushPromises();

    const confirmButton = wrapper.find(".candidate-actions .confirm");
    expect(confirmButton.exists()).toBe(true);
    await confirmButton.trigger("click");
    await flushPromises();
    expect(operationsApi.updateEntityMilestone).toHaveBeenCalledWith(
      "milestone-1",
      expect.objectContaining({ curation_status: "confirmed", selected_for_timeline: true })
    );

    const rejectButton = wrapper.find(".candidate-actions .reject");
    await rejectButton.trigger("click");
    await flushPromises();
    expect(operationsApi.updateEntityMilestone).toHaveBeenCalledWith(
      "milestone-1",
      expect.objectContaining({ curation_status: "revoked", selected_for_timeline: false })
    );
  });

  it("lets an admin add a tracked entity and manually backfill a milestone", async () => {
    const wrapper = mountPage({ workspaceRole: "admin" });
    await flushPromises();

    await wrapper.find(".entity-add-toggle").trigger("click");
    const entityForm = wrapper.find(".entity-create-form");
    await entityForm.findAll("input")[0].setValue("Moonshot");
    await entityForm.findAll("input")[1].setValue("月之暗面, Kimi");
    await entityForm.trigger("submit");
    await flushPromises();
    expect(operationsApi.createTrackedEntity).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        name: "Moonshot",
        aliases: ["月之暗面", "Kimi"]
      })
    );

    await wrapper.find(".manual-add-toggle").trigger("click");
    const manualForm = wrapper.find(".manual-milestone-form");
    await manualForm.findAll("input")[0].setValue("发布新一代旗舰模型");
    await manualForm.findAll("input")[2].setValue("2026-07-01");
    await manualForm.find("textarea").setValue("人工补录的里程碑");
    await manualForm.trigger("submit");
    await flushPromises();
    expect(operationsApi.createEntityMilestone).toHaveBeenCalledWith(
      expect.objectContaining({
        event_title: "发布新一代旗舰模型",
        event_brief: "人工补录的里程碑",
        event_time: "2026-07-01T00:00:00.000Z"
      })
    );
  });

  it("anchors a milestone from a search route", async () => {
    routeState.query = { milestone_id: "milestone-1" };
    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchEntityMilestoneDetail).toHaveBeenCalledWith("milestone-1");
    const anchored = wrapper.find(".milestone-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("OpenAI 发布企业 Agent 平台");
  });

  it("hides management entries from viewers", async () => {
    const wrapper = mountPage({ workspaceRole: "viewer" });
    await flushPromises();

    expect(wrapper.find(".entity-add-toggle").exists()).toBe(false);
    expect(wrapper.find(".manual-add-toggle").exists()).toBe(false);
    expect(wrapper.find(".candidate-actions").exists()).toBe(false);
    expect(wrapper.find(".milestone-actions").exists()).toBe(false);
    expect(wrapper.find(".milestone-row.candidate").exists()).toBe(true);
  });

  it("guides users to add entities when nothing is tracked yet", async () => {
    operationsApi.fetchTrackedEntities.mockResolvedValue([]);
    operationsApi.fetchEntityTimelineSummary.mockResolvedValue({
      ...summary(),
      total_entities: 0,
      total_milestones: 0
    });

    const wrapper = mountPage({ workspaceRole: "admin" });
    await flushPromises();

    expect(operationsApi.fetchTrackedEntityTimeline).not.toHaveBeenCalled();
    const emptyState = wrapper.find(".entity-empty");
    expect(emptyState.exists()).toBe(true);
    expect(emptyState.text()).toContain("先添加要跟踪的公司/产品");
  });
});
