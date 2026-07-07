import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EntityMilestonesPage from "./EntityMilestonesPage.vue";
import type {
  EntityMilestoneDetailRecord,
  EntityMilestoneListItem,
  EntityTimelineSummaryRecord,
  TrackedEntityListItem
} from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createRequirement: vi.fn(),
  fetchEntityMilestoneDetail: vi.fn(),
  fetchEntityMilestones: vi.fn(),
  fetchEntityTimelineSummary: vi.fn(),
  fetchTrackedEntities: vi.fn(),
  updateEntityMilestone: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/operations", () => ({
  createRequirement: operationsApi.createRequirement,
  fetchEntityMilestoneDetail: operationsApi.fetchEntityMilestoneDetail,
  fetchEntityMilestones: operationsApi.fetchEntityMilestones,
  fetchEntityTimelineSummary: operationsApi.fetchEntityTimelineSummary,
  fetchTrackedEntities: operationsApi.fetchTrackedEntities,
  updateEntityMilestone: operationsApi.updateEntityMilestone
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function entity(overrides: Partial<TrackedEntityListItem> = {}): TrackedEntityListItem {
  return {
    id: "entity-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    legacy_system: "tech_insight_loop",
    legacy_id: "legacy-entity-1",
    name: "OpenAI",
    entity_type: "company",
    rank: "A",
    aliases_json: [],
    influence_score: 90,
    milestone_count: 1,
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
    legacy_system: "tech_insight_loop",
    legacy_id: "legacy-milestone-1",
    tracked_entity_id: "entity-1",
    entity_name: "OpenAI",
    entity_type: "company",
    legacy_article_id: null,
    legacy_report_id: null,
    raw_item_id: null,
    historical_report_id: null,
    event_time: "2026-07-05T09:00:00Z",
    event_type: "release",
    title: "模型发布",
    timeline_brief: "发布新模型",
    source_url: null,
    source_name: "历史导入",
    board: "AI模型",
    selected_for_timeline: true,
    curation_status: "imported",
    importance_score: 90,
    importance_level: "high",
    article_ref_resolved: true,
    report_ref_resolved: true,
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function milestoneDetail(overrides: Partial<EntityMilestoneDetailRecord> = {}): EntityMilestoneDetailRecord {
  return {
    ...milestone(overrides),
    event_content: "完整事件正文",
    impact: "影响说明",
    event_brief: "事件摘要",
    impact_brief: "影响摘要",
    confidence_score: 0.9,
    event_dedupe_key: "event-key",
    legacy_refs: {},
    metadata_json: {},
    ...overrides
  };
}

function summary(): EntityTimelineSummaryRecord {
  return {
    workspace_code: "planning_intel",
    total_entities: 2,
    total_milestones: 2,
    selected_milestones: 2,
    unresolved_milestone_count: 0,
    unresolved_ref_count: 0,
    by_entity_type: { company: 2 },
    by_event_type: { release: 2 },
    by_importance_level: { high: 2 },
    earliest_event_time: "2026-07-01T00:00:00Z",
    latest_event_time: "2026-07-05T00:00:00Z"
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
    operationsApi.fetchEntityMilestones.mockResolvedValue([milestone()]);
    operationsApi.fetchEntityMilestoneDetail.mockImplementation((id: string) =>
      Promise.resolve(
        milestoneDetail({
          id,
          tracked_entity_id: id === "milestone-2" ? "entity-2" : "entity-1",
          entity_name: id === "milestone-2" ? "Anthropic" : "OpenAI",
          title: id === "milestone-2" ? "搜索命中的实体事件" : "模型发布"
        })
      )
    );
    operationsApi.updateEntityMilestone.mockImplementation((id: string, payload: Record<string, unknown>) =>
      Promise.resolve(
        milestoneDetail({
          id,
          legacy_system: "current",
          title: String(payload.event_title || "模型发布"),
          event_brief: String(payload.event_brief || "事件摘要"),
          curation_status: String(payload.curation_status || "confirmed"),
          selected_for_timeline: payload.curation_status === "revoked" ? false : true
        })
      )
    );
    operationsApi.createRequirement.mockResolvedValue({
      id: "req-1",
      workspace_code: "planning_intel",
      domain_code: "ai",
      title: "跟进：模型发布",
      description: "事件摘要",
      priority: "high",
      status: "open",
      due_at: null,
      owner_user_id: null,
      owner_name: null,
      source_count: 1,
      source_links: [],
      task_count: 0,
      metadata_json: {},
      created_at: "2026-07-05T09:00:00Z",
      updated_at: "2026-07-05T09:00:00Z"
    });
  });

  it("selects and highlights an entity milestone from a search route", async () => {
    routeState.query = { milestone_id: "milestone-2" };
    operationsApi.fetchEntityMilestones.mockResolvedValue([
      milestone({
        id: "milestone-2",
        tracked_entity_id: "entity-2",
        entity_name: "Anthropic",
        title: "搜索命中的实体事件"
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchEntityMilestones).toHaveBeenCalledWith(
      expect.objectContaining({ workspaceCode: "planning_intel", trackedEntityId: "entity-2" })
    );
    const anchoredEntity = wrapper.find(".entity-row.anchored");
    expect(anchoredEntity.exists()).toBe(true);
    expect(anchoredEntity.attributes("aria-current")).toBe("true");
    expect(anchoredEntity.text()).toContain("Anthropic");

    const anchoredMilestone = wrapper.find(".milestone-row.anchored");
    expect(anchoredMilestone.exists()).toBe(true);
    expect(anchoredMilestone.attributes("aria-current")).toBe("true");
    expect(anchoredMilestone.text()).toContain("搜索命中的实体事件");
  });

  it("edits confirms revokes and converts a current milestone to a requirement", async () => {
    operationsApi.fetchEntityMilestones.mockResolvedValue([
      milestone({ legacy_system: "current", legacy_id: "daily:item-1:entity-1", curation_status: "draft" })
    ]);
    operationsApi.fetchEntityMilestoneDetail.mockResolvedValue(
      milestoneDetail({
        legacy_system: "current",
        legacy_id: "daily:item-1:entity-1",
        curation_status: "draft",
        metadata_json: { current_refs: { daily_report_item_id: "item-1" } }
      })
    );
    const wrapper = mountPage({ workspaceRole: "admin" });
    await flushPromises();

    const editButton = wrapper.findAll(".milestone-actions .mini-action").find((button) => button.text().includes("编辑事件"));
    expect(editButton?.exists()).toBe(true);
    await editButton?.trigger("click");
    await wrapper.find(".milestone-edit-form input").setValue("人工确认后的实体事件");
    await wrapper.find(".milestone-edit-form").trigger("submit");
    await flushPromises();

    expect(operationsApi.updateEntityMilestone).toHaveBeenCalledWith(
      "milestone-1",
      expect.objectContaining({
        event_title: "人工确认后的实体事件",
        timeline_brief: expect.any(String)
      })
    );

    const confirmButton = wrapper.findAll(".milestone-actions .mini-action").find((button) => button.text().includes("确认"));
    await confirmButton?.trigger("click");
    await flushPromises();
    expect(operationsApi.updateEntityMilestone).toHaveBeenCalledWith(
      "milestone-1",
      expect.objectContaining({ curation_status: "confirmed", selected_for_timeline: true })
    );

    const revokeButton = wrapper.findAll(".milestone-actions .mini-action").find((button) => button.text().includes("撤销"));
    await revokeButton?.trigger("click");
    await flushPromises();
    expect(operationsApi.updateEntityMilestone).toHaveBeenCalledWith(
      "milestone-1",
      expect.objectContaining({ curation_status: "revoked", selected_for_timeline: false })
    );

    const requirementButton = wrapper.findAll(".milestone-actions .mini-action").find((button) => button.text().includes("转需求"));
    await requirementButton?.trigger("click");
    await flushPromises();
    expect(operationsApi.createRequirement).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        source_entity_milestone_id: "milestone-1"
      })
    );
  });
});
