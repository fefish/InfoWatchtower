import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceSettingsPage from "./WorkspaceSettingsPage.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const workspacesApi = vi.hoisted(() => ({
  fetchWorkspaces: vi.fn(),
  fetchWorkspaceSections: vi.fn(),
  createWorkspace: vi.fn(),
  updateWorkspace: vi.fn(),
  fetchWorkspaceMembers: vi.fn(),
  upsertWorkspaceMember: vi.fn(),
  removeWorkspaceMember: vi.fn(),
  fetchWorkspaceLabelPolicy: vi.fn(),
  updateWorkspaceLabelPolicy: vi.fn(),
  fetchWorkspaceReportPolicy: vi.fn(),
  updateWorkspaceReportPolicy: vi.fn(),
  fetchWorkspaceSectionsManage: vi.fn(),
  updateWorkspaceSection: vi.fn(),
  updateWorkspaceVisibility: vi.fn(),
  fetchWorkspaceJoinCode: vi.fn(),
  createWorkspaceJoinCode: vi.fn(),
  disableWorkspaceJoinCode: vi.fn()
}));

const renditionsApi = vi.hoisted(() => ({
  fetchReportFormats: vi.fn(),
  createReportFormat: vi.fn(),
  updateReportFormat: vi.fn(),
  deleteReportFormat: vi.fn()
}));

const schedulerApi = vi.hoisted(() => ({
  fetchWorkspaceSchedulePolicy: vi.fn(),
  updateWorkspaceSchedulePolicy: vi.fn()
}));

const generationApi = vi.hoisted(() => ({
  fetchWorkspaceGenerationPolicy: vi.fn(),
  updateWorkspaceGenerationPolicy: vi.fn(),
  pingGeneration: vi.fn()
}));

const credentialsApi = vi.hoisted(() => ({
  fetchGenerationProviders: vi.fn(),
  listLlmCredentials: vi.fn(),
  createLlmCredential: vi.fn(),
  updateLlmCredential: vi.fn(),
  disableLlmCredential: vi.fn()
}));

const recommendationsApi = vi.hoisted(() => ({
  fetchFeedbackRollups: vi.fn(),
  fetchRubricRevisionProposals: vi.fn(),
  fetchWorkspaceRecommendationPolicy: vi.fn(),
  reviewRubricRevisionProposal: vi.fn(),
  runFeedbackRollup: vi.fn()
}));

vi.mock("../api/workspaces", () => workspacesApi);
vi.mock("../api/renditions", () => renditionsApi);
vi.mock("../api/scheduler", () => schedulerApi);
vi.mock("../api/generation", () => generationApi);
vi.mock("../api/credentials", () => credentialsApi);
vi.mock("../api/recommendations", () => recommendationsApi);

// AppModal 行为（焦点圈定/Esc/脏确认）由 AppModal.spec.ts 看护；
// 页面 spec 只断言确认层的打开时机与确认后的 API 调用形状。
const AppModalStub = {
  props: ["open", "title", "size", "dirty", "bodyClass", "confirmText"],
  emits: ["close"],
  template: `
    <div v-if="open" class="app-modal-stub" role="dialog" :data-size="size">
      <h3>{{ title }}</h3>
      <slot />
      <slot name="footer" />
    </div>
  `
};

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

function memberRecord(overrides: Record<string, unknown> = {}) {
  return {
    user: {
      id: "user-owner",
      external_provider: "local",
      external_id: "owner",
      employee_no: null,
      username: "owner",
      display_name: "工作台负责人",
      department: "规划部",
      email: null,
      status: "active",
      is_active: true,
      roles: ["viewer"]
    },
    workspace_role: "owner",
    enabled: true,
    ...overrides
  };
}

function reportFormat(overrides: Record<string, unknown> = {}) {
  return {
    id: "fmt-sql",
    workspace_code: "planning_intel",
    format_code: "company_sql_v1",
    name: "内网版",
    description: "",
    builtin: true,
    locked: true,
    group_by: "category",
    headline_enabled: false,
    headline_auto_top_n: 0,
    item_fields: ["five_fields", "source_link"],
    export_targets: [],
    enabled: true,
    sort_order: 10,
    ...overrides
  };
}

function manageSection(overrides: Record<string, unknown> = {}) {
  return {
    section_key: "daily_reports",
    name: "日报",
    group: "curate",
    sort_order: 40,
    enabled: true,
    core: true,
    ...overrides
  };
}

function schedulePolicyRecord(overrides: Record<string, unknown> = {}) {
  return {
    workspace_code: "planning_intel",
    policy: {
      enabled: null,
      daily_time: null,
      day_offset: null,
      source_types: null,
      retry: { max_attempts: 1, backoff_seconds: 900 },
      weekly: { enabled: false, weekly_day: 5, weekly_time: "17:00" }
    },
    resolved: {
      effective_enabled: true,
      effective_daily_time: "12:00",
      effective_day_offset: -1,
      effective_source_types: ["rss"],
      policy_source: "instance",
      next_run_at: "2026-07-09T12:00:00+08:00",
      retry: { max_attempts: 1, backoff_seconds: 900 },
      weekly: { enabled: false, weekly_day: 5, weekly_time: "17:00" }
    },
    instance: {
      scheduler_enabled: true,
      daily_time: "12:00",
      timezone: "Asia/Shanghai",
      day_offset: -1,
      source_types: ["rss"],
      workspace_code: "planning_intel"
    },
    ...overrides
  };
}

function generationPolicyRecord(overrides: Record<string, unknown> = {}) {
  return {
    workspace_code: "planning_intel",
    policy: {
      credential_id: null,
      model: null,
      temperature: null,
      max_tokens: null,
      timeout_seconds: null,
      daily_generation_budget: null,
      fallback_behavior: "rule_fallback"
    },
    resolved: {
      provider: "minimax",
      model: "MiniMax-M2.5",
      base_url_host: "api.minimaxi.com",
      enabled: true,
      key_configured: true,
      key_source: "env",
      credential_id: null,
      credential_label: null
    },
    credential_options: [],
    ...overrides
  };
}

// 与 config/contracts/llm_providers.json catalog 同构的目录切片（sort_order 排序，custom 恒末位）
function providerCatalogFixture() {
  return {
    catalog: [
      {
        code: "deepseek",
        name: "DeepSeek",
        default_base_url: "https://api.deepseek.com/v1",
        auth_header: "authorization_bearer",
        key_required: true,
        common_models: ["deepseek-chat", "deepseek-reasoner"],
        notes: "",
        sort_order: 30
      },
      {
        code: "minimax",
        name: "MiniMax",
        default_base_url: "https://api.minimaxi.com/v1",
        auth_header: "authorization_bearer",
        key_required: true,
        common_models: ["MiniMax-M2.7-highspeed"],
        notes: "",
        sort_order: 60
      },
      {
        code: "ollama",
        name: "Ollama (本地/自托管)",
        default_base_url: "http://localhost:11434/v1",
        auth_header: "authorization_bearer",
        key_required: false,
        common_models: ["qwen3"],
        notes: "Self-hosted; key input may stay empty.",
        sort_order: 80
      },
      {
        code: "custom",
        name: "自定义（兜底 base_url + key）",
        default_base_url: null,
        auth_header: "authorization_bearer",
        key_required: false,
        common_models: [],
        notes: "",
        sort_order: 90
      }
    ]
  };
}

function credentialRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "cred-1",
    provider: "deepseek",
    base_url: "https://api.deepseek.com/v1",
    base_url_host: "api.deepseek.com",
    label: "测试",
    key_masked: "****abcd",
    enabled: true,
    disabled_at: null,
    created_at: "2026-07-08T09:00:00+08:00",
    updated_at: "2026-07-08T09:00:00+08:00",
    ...overrides
  };
}

function credentialOption(overrides: Record<string, unknown> = {}) {
  return {
    id: "cred-1",
    label: "测试",
    provider: "deepseek",
    base_url_host: "api.deepseek.com",
    key_masked: "****abcd",
    ...overrides
  };
}

// WP4-G 反馈回哺区 fixture（feedback-heat-scoring §16.3 / page-specs §19.5.3）
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
      precision_at_6: 0.5,
      rerank_uplift: 0.1667,
      normalized_adopt_rate: 0.2857,
      low_data_sources: [{ id: "src-low", name: "Low Data Source" }]
    },
    computed_at: "2026-07-06T03:00:00+08:00",
    ...overrides
  };
}

function proposalRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "proposal-1",
    workspace_code: "planning_intel",
    rollup_id: "rollup-1",
    rollup_period_key: "2026-W27",
    base_rubric_version: 3,
    prompt_version: "revision_prompt_v1",
    proposed_rubric: { topics: [] },
    change_summary: [
      {
        op: "adjust_topic_weight",
        target_code: "inference_serving",
        from: 4,
        to: 4.5,
        rationale: "采信样本集中在推理服务"
      }
    ],
    sample_refs: { adopted: ["news-1"], rejected: ["news-2"] },
    status: "pending_review",
    review_comment: "",
    reviewed_at: null,
    compile_fingerprint: "",
    created_at: "2026-07-06T03:00:00+08:00",
    ...overrides
  };
}

function joinCodeRecord(overrides: Record<string, unknown> = {}) {
  return {
    code: "7F2KQ9XN",
    default_role: "viewer",
    expires_at: null,
    max_uses: 20,
    use_count: 3,
    created_at: "2026-07-07T09:00:00+08:00",
    created_by: "工作台负责人",
    ...overrides
  };
}

function mountPage(
  options: {
    workspaceRole?: string;
    userRoles?: string[];
    visibility?: string;
    canIngest?: boolean;
    schedulePolicy?: ReturnType<typeof schedulePolicyRecord>;
    generationPolicy?: ReturnType<typeof generationPolicyRecord>;
    joinCode?: ReturnType<typeof joinCodeRecord> | null;
    feedbackRollups?: ReturnType<typeof feedbackRollupRecord>[];
    pendingProposals?: ReturnType<typeof proposalRecord>[];
  } = {}
) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const session = useSessionStore();
  session.user = {
    id: "user-1",
    external_provider: "local",
    external_id: "admin",
    employee_no: null,
    username: "admin",
    display_name: "配置管理员",
    department: null,
    email: null,
    roles: (options.userRoles ?? ["viewer"]) as never,
    status: "active",
    is_active: true
  };
  session.checked = true;

  const runtime = useRuntimeStore();
  runtime.checked = true;
  runtime.capabilities = {
    ingestion: options.canIngest ?? true,
    sync_publisher: true,
    sync_consumer: true,
    embedding: true,
    search: true
  };

  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  workspace.options = [
    {
      code: "planning_intel",
      name: "规划部情报工作台",
      description: "行业信号与日报周报。",
      workspace_type: "intelligence_workspace",
      default_domain_code: "ai",
      enabled: true,
      visibility: options.visibility ?? "private",
      current_user_workspace_role: options.workspaceRole ?? "admin"
    }
  ];

  workspacesApi.fetchWorkspaces.mockResolvedValue(workspace.options);
  workspacesApi.fetchWorkspaceSections.mockResolvedValue([]);
  workspacesApi.updateWorkspace.mockResolvedValue(workspace.options[0]);
  workspacesApi.fetchWorkspaceMembers.mockResolvedValue([
    memberRecord(),
    memberRecord({
      user: {
        ...memberRecord().user,
        id: "user-member",
        username: "analyst",
        display_name: "情报分析员"
      },
      workspace_role: "member"
    })
  ]);
  workspacesApi.upsertWorkspaceMember.mockResolvedValue(memberRecord({ workspace_role: "admin" }));
  workspacesApi.removeWorkspaceMember.mockResolvedValue(undefined);
  workspacesApi.fetchWorkspaceLabelPolicy.mockResolvedValue(labelPolicy());
  workspacesApi.updateWorkspaceLabelPolicy.mockResolvedValue(labelPolicy());
  workspacesApi.fetchWorkspaceReportPolicy.mockResolvedValue({
    workspace_code: "planning_intel",
    auto_publish_daily: true
  });
  workspacesApi.updateWorkspaceReportPolicy.mockResolvedValue({
    workspace_code: "planning_intel",
    auto_publish_daily: false
  });
  workspacesApi.fetchWorkspaceSectionsManage.mockResolvedValue([
    manageSection(),
    manageSection({
      section_key: "tool_catalog",
      name: "工具目录",
      group: "system",
      sort_order: 95,
      enabled: false,
      core: false
    })
  ]);
  workspacesApi.updateWorkspaceSection.mockResolvedValue({
    section_key: "tool_catalog",
    name: "工具目录",
    enabled: true
  });
  renditionsApi.fetchReportFormats.mockResolvedValue([
    reportFormat(),
    reportFormat({
      id: "fmt-insight",
      format_code: "tech_insight_v1",
      name: "技术洞察版",
      locked: false,
      group_by: "board",
      headline_enabled: true,
      headline_auto_top_n: 6,
      item_fields: ["tag_line", "bullet_points", "takeaway", "source_link"],
      export_targets: ["md", "html"],
      sort_order: 20
    })
  ]);
  renditionsApi.updateReportFormat.mockResolvedValue(reportFormat({ id: "fmt-insight", enabled: false }));
  renditionsApi.createReportFormat.mockResolvedValue(
    reportFormat({ id: "fmt-custom", format_code: "exec_brief_v1", name: "高管简报版", builtin: false, locked: false })
  );
  renditionsApi.deleteReportFormat.mockResolvedValue(undefined);
  schedulerApi.fetchWorkspaceSchedulePolicy.mockResolvedValue(
    options.schedulePolicy ?? schedulePolicyRecord()
  );
  schedulerApi.updateWorkspaceSchedulePolicy.mockResolvedValue(schedulePolicyRecord());
  generationApi.fetchWorkspaceGenerationPolicy.mockResolvedValue(
    options.generationPolicy ?? generationPolicyRecord()
  );
  generationApi.updateWorkspaceGenerationPolicy.mockResolvedValue(generationPolicyRecord());
  generationApi.pingGeneration.mockResolvedValue({
    status: "ok",
    provider: "minimax",
    model: "MiniMax-M2.5",
    base_url_host: "api.minimaxi.com",
    key_configured: true,
    latency_ms: 812,
    error_code: null,
    error_message: null
  });
  credentialsApi.fetchGenerationProviders.mockResolvedValue(providerCatalogFixture());
  credentialsApi.listLlmCredentials.mockResolvedValue([]);
  credentialsApi.createLlmCredential.mockResolvedValue(credentialRecord());
  credentialsApi.updateLlmCredential.mockResolvedValue(credentialRecord());
  credentialsApi.disableLlmCredential.mockResolvedValue(credentialRecord({ enabled: false }));
  workspacesApi.updateWorkspaceVisibility.mockResolvedValue({});
  workspacesApi.fetchWorkspaceJoinCode.mockResolvedValue(options.joinCode ?? null);
  workspacesApi.createWorkspaceJoinCode.mockResolvedValue(joinCodeRecord());
  workspacesApi.disableWorkspaceJoinCode.mockResolvedValue(undefined);
  recommendationsApi.fetchFeedbackRollups.mockResolvedValue({
    items: options.feedbackRollups ?? [],
    total: (options.feedbackRollups ?? []).length
  });
  recommendationsApi.fetchRubricRevisionProposals.mockResolvedValue({
    items: options.pendingProposals ?? []
  });
  recommendationsApi.fetchWorkspaceRecommendationPolicy.mockResolvedValue({
    workspace_code: "planning_intel",
    policy: {
      rubric_version: 3,
      rubric_status: "active",
      feedback_workflow: {
        weekly_rollup_enabled: true,
        monthly_review_enabled: true,
        proposal_generation_enabled: true,
        exploration_epsilon: 0
      }
    },
    resolved: {}
  });
  recommendationsApi.runFeedbackRollup.mockResolvedValue({
    ...feedbackRollupRecord(),
    source_breakdown: {},
    topic_breakdown: {},
    sample_refs: {}
  });
  recommendationsApi.reviewRubricRevisionProposal.mockResolvedValue(
    proposalRecord({ status: "accepted" })
  );

  return mount(WorkspaceSettingsPage, {
    global: {
      plugins: [pinia],
      stubs: {
        AppModal: AppModalStub,
        RouterLink: {
          props: ["to"],
          template: '<a :href="typeof to === \'string\' ? to : \'#\'"><slot /></a>'
        }
      }
    }
  });
}

function dialogByTitle(wrapper: ReturnType<typeof mount>, title: string) {
  return wrapper.findAll(".app-modal-stub").find((node) => node.text().includes(title));
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll("button").find((item) => item.text().includes(text));
  if (!button) {
    throw new Error(`Button not found: ${text}`);
  }
  return button;
}

describe("WorkspaceSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the eight settings cards for workspace admins", async () => {
    const wrapper = mountPage();
    await flushPromises();

    for (const cardLabel of [
      "基本信息",
      "成员与角色",
      "标签策略设置",
      "报告设置",
      "导航分区",
      "自动化",
      "生成模型",
      "可见性与加入码",
      "反馈回哺"
    ]) {
      expect(wrapper.find(`[aria-label="${cardLabel}"]`).exists()).toBe(true);
    }
    // 锚点导航覆盖各卡片（候选池入口跳 #labels 依赖该锚点）。
    expect(wrapper.find('a[href="#labels"]').exists()).toBe(true);
    expect(wrapper.find("#labels").exists()).toBe(true);
    expect(wrapper.find('a[href="#automation"]').exists()).toBe(true);
    expect(wrapper.find('a[href="#generation"]').exists()).toBe(true);
    expect(wrapper.find('a[href="#visibility"]').exists()).toBe(true);
    expect(workspacesApi.fetchWorkspaceMembers).toHaveBeenCalledWith("planning_intel");
    expect(workspacesApi.fetchWorkspaceLabelPolicy).toHaveBeenCalledWith("planning_intel");
    expect(workspacesApi.fetchWorkspaceReportPolicy).toHaveBeenCalledWith("planning_intel");
    expect(workspacesApi.fetchWorkspaceSectionsManage).toHaveBeenCalledWith("planning_intel");
    expect(renditionsApi.fetchReportFormats).toHaveBeenCalledWith("planning_intel");
    expect(schedulerApi.fetchWorkspaceSchedulePolicy).toHaveBeenCalledWith("planning_intel");
    expect(generationApi.fetchWorkspaceGenerationPolicy).toHaveBeenCalledWith("planning_intel");
    expect(workspacesApi.fetchWorkspaceJoinCode).toHaveBeenCalledWith("planning_intel");
  });

  it("hides all management cards for workspace members and viewers", async () => {
    for (const role of ["member", "viewer"]) {
      vi.clearAllMocks();
      const wrapper = mountPage({ workspaceRole: role });
      await flushPromises();

      expect(wrapper.text()).toContain("需要工作台管理员权限");
      expect(wrapper.find('[aria-label="标签策略设置"]').exists()).toBe(false);
      expect(wrapper.find('[aria-label="报告设置"]').exists()).toBe(false);
      expect(wrapper.find('[aria-label="自动化"]').exists()).toBe(false);
      expect(wrapper.find('[aria-label="生成模型"]').exists()).toBe(false);
      expect(wrapper.find('[aria-label="可见性与加入码"]').exists()).toBe(false);
      // WP4-G 反馈回哺区随卡片门禁一起隐藏（member/viewer 整区不渲染、零调用）。
      expect(wrapper.find('[aria-label="反馈回哺"]').exists()).toBe(false);
      expect(workspacesApi.fetchWorkspaceMembers).not.toHaveBeenCalled();
      expect(workspacesApi.fetchWorkspaceLabelPolicy).not.toHaveBeenCalled();
      expect(renditionsApi.fetchReportFormats).not.toHaveBeenCalled();
      expect(schedulerApi.fetchWorkspaceSchedulePolicy).not.toHaveBeenCalled();
      expect(generationApi.fetchWorkspaceGenerationPolicy).not.toHaveBeenCalled();
      expect(workspacesApi.fetchWorkspaceJoinCode).not.toHaveBeenCalled();
      expect(recommendationsApi.fetchFeedbackRollups).not.toHaveBeenCalled();
      expect(recommendationsApi.fetchRubricRevisionProposals).not.toHaveBeenCalled();
    }
  });

  it("saves workspace basic info through PATCH /api/workspaces/{code}", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find('input[placeholder="工作台名称"]').setValue("规划部情报中心");
    await wrapper.find('input[placeholder="这个工作台负责什么"]').setValue("统一配置中心测试");
    await buttonByText(wrapper, "保存基本信息").trigger("click");
    await flushPromises();

    expect(workspacesApi.updateWorkspace).toHaveBeenCalledWith("planning_intel", {
      name: "规划部情报中心",
      description: "统一配置中心测试",
      default_domain_code: "ai"
    });
    expect(wrapper.find(".form-success").text()).toContain("已保存：工作台基本信息");
  });

  it("saves the migrated label policy with the same call shape as the old sources panel", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "保存策略").trigger("click");
    await flushPromises();

    expect(workspacesApi.updateWorkspaceLabelPolicy).toHaveBeenCalledWith("planning_intel", {
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
      fallback_category: "AI 应用"
    });
    expect(wrapper.find(".form-success").text()).toContain("统一标签策略");
  });

  it("shows an error instead of success when the label policy save fails", async () => {
    const wrapper = mountPage();
    await flushPromises();
    workspacesApi.updateWorkspaceLabelPolicy.mockRejectedValueOnce(new Error("permission denied"));

    await buttonByText(wrapper, "保存策略").trigger("click");
    await flushPromises();

    expect(wrapper.find(".form-error").text()).toContain("permission denied");
    expect(wrapper.find(".form-success").exists()).toBe(false);
  });

  it("toggles auto_publish_daily through the report policy API", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const toggle = wrapper.find('input[aria-label="日报出稿后自动发布"]');
    expect((toggle.element as HTMLInputElement).checked).toBe(true);
    await toggle.setValue(false);
    await flushPromises();

    expect(workspacesApi.updateWorkspaceReportPolicy).toHaveBeenCalledWith("planning_intel", {
      auto_publish_daily: false
    });
    expect(wrapper.find(".form-success").text()).toContain("人工发布工作流");
  });

  it("manages report formats: toggle enabled and create a custom format", async () => {
    const wrapper = mountPage();
    await flushPromises();

    // 两个内置格式都在注册表里列出（“要两个格式就配两个”在这里达成）。
    expect(wrapper.text()).toContain("内网版");
    expect(wrapper.text()).toContain("技术洞察版");
    expect(wrapper.text()).toContain("公司 SQL 口径锁定");

    await wrapper.find('input[aria-label="启用报告格式：技术洞察版"]').setValue(false);
    await flushPromises();
    expect(renditionsApi.updateReportFormat).toHaveBeenCalledWith("fmt-insight", { enabled: false });

    await buttonByText(wrapper, "新增自定义格式").trigger("click");
    await wrapper.find('input[placeholder="例如 exec_brief_v1"]').setValue("exec_brief_v1");
    await wrapper.find('input[placeholder="例如 高管简报版"]').setValue("高管简报版");
    await buttonByText(wrapper, "创建报告格式").trigger("click");
    await flushPromises();

    expect(renditionsApi.createReportFormat).toHaveBeenCalledWith({
      workspace_code: "planning_intel",
      format_code: "exec_brief_v1",
      name: "高管简报版",
      description: "",
      group_by: "board",
      headline_enabled: true,
      headline_auto_top_n: 6,
      item_fields: ["tag_line", "bullet_points", "takeaway", "source_link"],
      export_targets: ["md", "html"]
    });
    expect(wrapper.text()).toContain("已新增报告格式：高管简报版");
  });

  it("toggles optional navigation sections and locks core sections", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const coreToggle = wrapper.find('input[aria-label="启用分区：日报"]');
    expect(coreToggle.attributes("disabled")).toBeDefined();

    await wrapper.find('input[aria-label="启用分区：工具目录"]').setValue(true);
    await flushPromises();

    expect(workspacesApi.updateWorkspaceSection).toHaveBeenCalledWith("planning_intel", "tool_catalog", {
      enabled: true
    });
  });

  it("updates a member role through the members API", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find('select[aria-label="成员角色：情报分析员"]').setValue("admin");
    const memberRow = wrapper
      .findAll(".settings-member-row")
      .find((row) => row.text().includes("情报分析员"));
    if (!memberRow) {
      throw new Error("member row not found");
    }
    await memberRow.findAll("button").find((item) => item.text().includes("保存"))!.trigger("click");
    await flushPromises();

    expect(workspacesApi.upsertWorkspaceMember).toHaveBeenCalledWith("planning_intel", {
      user_id: "user-member",
      workspace_role: "admin",
      confirm_dangerous_change: false
    });
  });

  // ---------- 自动化卡（pipeline-jobs-design §8.2/§8.4，page-specs §19.5.3） ----------

  it("renders the automation card with next-run preview and effective-value source labels", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const card = wrapper.find('[aria-label="自动化"]');
    expect(card.text()).toContain("下次运行：2026-07-09 12:00");
    expect(card.text()).toContain("时区 Asia/Shanghai");
    // 每个字段标注生效值来源：策略为 null → 跟随实例默认
    expect(card.text()).toContain("跟随实例默认 12:00");
    expect(card.text()).toContain("跟随实例默认 -1 天");
    expect(card.text()).toContain("跟随实例总闸（当前开启）");
  });

  it("saves the schedule policy as a full document only after the impact confirm modal", async () => {
    const wrapper = mountPage();
    await flushPromises();
    schedulerApi.updateWorkspaceSchedulePolicy.mockResolvedValue(
      schedulePolicyRecord({
        policy: {
          enabled: null,
          daily_time: "09:30",
          day_offset: null,
          source_types: null,
          retry: { max_attempts: 1, backoff_seconds: 900 },
          weekly: { enabled: false, weekly_day: 5, weekly_time: "17:00" }
        },
        resolved: {
          ...schedulePolicyRecord().resolved,
          effective_daily_time: "09:30",
          policy_source: "workspace",
          next_run_at: "2026-07-09T09:30:00+08:00"
        }
      })
    );

    await wrapper.find('input[aria-label="每日触发时刻"]').setValue("09:30");
    await buttonByText(wrapper, "保存自动化策略").trigger("click");

    // 保存前必须先弹影响确认，未确认不发请求
    expect(schedulerApi.updateWorkspaceSchedulePolicy).not.toHaveBeenCalled();
    const confirm = dialogByTitle(wrapper, "确认保存自动化策略？");
    expect(confirm).toBeDefined();

    await confirm!.findAll("button").find((item) => item.text().includes("确认保存"))!.trigger("click");
    await flushPromises();

    expect(schedulerApi.updateWorkspaceSchedulePolicy).toHaveBeenCalledWith("planning_intel", {
      enabled: null,
      daily_time: "09:30",
      day_offset: null,
      source_types: null,
      retry: { max_attempts: 1, backoff_seconds: 900 },
      weekly: { enabled: false, weekly_day: 5, weekly_time: "17:00" }
    });
    expect(wrapper.find(".form-success").text()).toContain("已保存：自动化策略");
    expect(wrapper.text()).toContain("2026-07-09 09:30");
  });

  it("locks the automation card read-only when the instance master switch is off", async () => {
    const wrapper = mountPage({
      schedulePolicy: schedulePolicyRecord({
        resolved: { ...schedulePolicyRecord().resolved, effective_enabled: false, next_run_at: null },
        instance: { ...schedulePolicyRecord().instance, scheduler_enabled: false }
      })
    });
    await flushPromises();

    const card = wrapper.find('[aria-label="自动化"]');
    expect(card.text()).toContain("实例调度总闸已关闭");
    expect(card.find('select[aria-label="自动调度开关"]').attributes("disabled")).toBeDefined();
    expect(card.find('input[aria-label="每日触发时刻"]').attributes("disabled")).toBeDefined();
    const saveButton = card.findAll("button").find((item) => item.text().includes("保存自动化策略"));
    expect(saveButton!.attributes("disabled")).toBeDefined();
  });

  // ---------- 生成模型卡（generation-provider-design §5，page-specs §19.5.3） ----------

  it("shows generation resolved status with key as configured/not-configured only", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const card = wrapper.find('[aria-label="生成模型"]');
    expect(card.text()).toContain("provider：minimax");
    expect(card.text()).toContain("生效模型：MiniMax-M2.5");
    expect(card.text()).toContain("key 已配置");
    // 永不回显 key：卡片内不出现任何疑似 key 的字段
    expect(card.text()).not.toContain("sk-");

    const unconfigured = mountPage({
      generationPolicy: generationPolicyRecord({
        resolved: { ...generationPolicyRecord().resolved, key_configured: false, key_source: "" }
      })
    });
    await flushPromises();
    const unconfiguredCard = unconfigured.find('[aria-label="生成模型"]');
    expect(unconfiguredCard.text()).toContain("key 未配置");
    // §5 第 7 步：非 super_admin 的无配置引导——联系管理员 + 部署手册指引 +
    // 「规则降级是预期行为」说明（未配置期间不是故障）
    expect(unconfiguredCard.text()).toContain("请联系平台管理员");
    expect(unconfiguredCard.text()).toContain("development-quickstart.md");
    expect(unconfiguredCard.text()).toContain("不是故障");
  });

  it("shows the three-step setup guide to super_admin when nothing is configured", async () => {
    const wrapper = mountPage({
      userRoles: ["super_admin"],
      generationPolicy: generationPolicyRecord({
        resolved: { ...generationPolicyRecord().resolved, key_configured: false, key_source: "" },
        credential_options: []
      })
    });
    await flushPromises();
    const card = wrapper.find('[aria-label="生成模型"]');
    expect(card.text()).toContain("① 选择 provider");
    expect(card.text()).toContain("② 填入 API key 并保存");
    expect(card.text()).toContain("③ 测试连通");
    expect(card.text()).toContain("不是故障");
  });

  it("saves the generation policy with nullable follow-instance fields", async () => {
    const wrapper = mountPage();
    await flushPromises();

    // 模型下拉末项「自定义模型名…」切换为文本输入（§5 第 4 步）
    await wrapper.find('select[aria-label="生成模型选择"]').setValue("__custom__");
    await wrapper.find('input[aria-label="生成模型名"]').setValue("gpt-4o-mini");
    await wrapper.find('input[aria-label="生成温度"]').setValue("0.2");
    await buttonByText(wrapper, "保存生成模型策略").trigger("click");
    await flushPromises();

    expect(generationApi.updateWorkspaceGenerationPolicy).toHaveBeenCalledWith("planning_intel", {
      credential_id: null,
      model: "gpt-4o-mini",
      temperature: 0.2,
      timeout_seconds: null,
      daily_generation_budget: null,
      fallback_behavior: "rule_fallback"
    });
    expect(wrapper.find(".form-success").text()).toContain("已保存：生成模型策略");
  });

  it("offers catalog common models in the model dropdown for the resolved provider", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const select = wrapper.find('select[aria-label="生成模型选择"]');
    const optionTexts = select.findAll("option").map((option) => option.text());
    expect(optionTexts[0]).toContain("跟随实例默认");
    // resolved provider=minimax → 目录 common_models 进下拉
    expect(optionTexts).toContain("MiniMax-M2.7-highspeed");
    expect(optionTexts[optionTexts.length - 1]).toContain("自定义模型名");
    // 未选自定义时不渲染自定义文本输入
    expect(wrapper.find('input[aria-label="生成模型名"]').exists()).toBe(false);
  });

  // ---------- 凭据七步流（generation-provider-design §5，WP4-B） ----------

  it("prefills base_url from the provider catalog and requires it for custom", async () => {
    const wrapper = mountPage({ userRoles: ["super_admin"] });
    await flushPromises();

    const baseUrl = () =>
      (wrapper.find('input[aria-label="provider base_url"]').element as HTMLInputElement).value;
    // 初始 provider=minimax → 目录默认 base_url 预填
    expect(baseUrl()).toBe("https://api.minimaxi.com/v1");
    await wrapper.find('select[aria-label="provider 选择"]').setValue("deepseek");
    expect(baseUrl()).toBe("https://api.deepseek.com/v1");
    // ollama 预填本机默认并提示无需 key
    await wrapper.find('select[aria-label="provider 选择"]').setValue("ollama");
    expect(baseUrl()).toBe("http://localhost:11434/v1");
    expect(wrapper.find('[aria-label="新增 provider 凭据"]').text()).toContain("无需 key");
    // custom 无预填、必填：本地校验直接报错，不发请求
    await wrapper.find('select[aria-label="provider 选择"]').setValue("custom");
    expect(baseUrl()).toBe("");
    await wrapper.find('input[aria-label="API key"]').setValue("sk-x");
    await buttonByText(wrapper, "保存凭据并测试").trigger("click");
    await flushPromises();
    expect(credentialsApi.createLlmCredential).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("自定义 provider 必须填写 base_url");
  });

  it("stores the key write-only, clears the input, shows masked and auto-pings", async () => {
    const wrapper = mountPage({
      userRoles: ["super_admin"],
      generationPolicy: generationPolicyRecord({ credential_options: [credentialOption()] })
    });
    await flushPromises();

    await wrapper.find('select[aria-label="provider 选择"]').setValue("deepseek");
    await wrapper.find('input[aria-label="API key"]').setValue("sk-test-1234abcd");
    await wrapper.find('input[aria-label="凭据备注名"]').setValue("测试");
    await buttonByText(wrapper, "保存凭据并测试").trigger("click");
    await flushPromises();

    expect(credentialsApi.createLlmCredential).toHaveBeenCalledWith({
      provider: "deepseek",
      base_url: "https://api.deepseek.com/v1",
      api_key: "sk-test-1234abcd",
      label: "测试"
    });
    // write-only：保存成功后输入框清空，状态行只显示 label + masked（永不回显明文）
    const keyInput = wrapper.find('input[aria-label="API key"]');
    expect((keyInput.element as HTMLInputElement).value).toBe("");
    expect(wrapper.text()).toContain("已录入：测试（****abcd");
    expect(wrapper.text()).not.toContain("sk-test-1234abcd");
    // §5 第 6 步：保存后自动按凭据试连（credential_id 优先于 workspace_code）
    expect(generationApi.pingGeneration).toHaveBeenCalledWith("planning_intel", "cred-1");
  });

  it("hides the credential create entry from non super_admin but keeps the picker", async () => {
    const wrapper = mountPage({
      generationPolicy: generationPolicyRecord({ credential_options: [credentialOption()] })
    });
    await flushPromises();

    // 非 super_admin 看不到新建入口（key 输入框不存在）
    expect(wrapper.find('[aria-label="新增 provider 凭据"]').exists()).toBe(false);
    expect(wrapper.find('input[aria-label="API key"]').exists()).toBe(false);
    // 仍可从既有凭据下拉选择；「跟随实例 env」= null 选项恒在首位
    const select = wrapper.find('select[aria-label="凭据选择"]');
    expect(select.exists()).toBe(true);
    const options = select.findAll("option").map((option) => option.text());
    expect(options[0]).toContain("跟随实例 env");
    expect(options[1]).toContain("测试");
    expect(options[1]).toContain("****abcd");
  });

  it("saves credential_id via the policy PATCH when a credential is selected", async () => {
    const wrapper = mountPage({
      generationPolicy: generationPolicyRecord({ credential_options: [credentialOption()] })
    });
    await flushPromises();

    await wrapper.find('select[aria-label="凭据选择"]').setValue("cred-1");
    await buttonByText(wrapper, "保存生成模型策略").trigger("click");
    await flushPromises();

    expect(generationApi.updateWorkspaceGenerationPolicy).toHaveBeenCalledWith(
      "planning_intel",
      expect.objectContaining({ credential_id: "cred-1" })
    );
  });

  it("surfaces credential_missing explicitly without claiming env fallback", async () => {
    const wrapper = mountPage({
      generationPolicy: generationPolicyRecord({
        policy: { ...generationPolicyRecord().policy, credential_id: "cred-gone" },
        resolved: {
          ...generationPolicyRecord().resolved,
          key_configured: false,
          key_source: "credential_missing"
        },
        credential_options: []
      })
    });
    await flushPromises();

    const card = wrapper.find('[aria-label="生成模型"]');
    expect(card.text()).toContain("所选凭据已不可用");
    expect(card.text()).toContain("不会静默改用实例环境的 key");
  });

  it("shows the ping button only to super_admin/editor_admin", async () => {
    const wrapper = mountPage();
    await flushPromises();
    // 工作台 admin 但全局角色只有 viewer：与后端权限门一致，不渲染测试连通按钮
    expect(wrapper.findAll("button").some((item) => item.text().includes("测试连通"))).toBe(false);

    const adminWrapper = mountPage({ userRoles: ["super_admin"] });
    await flushPromises();
    expect(adminWrapper.findAll("button").some((item) => item.text().includes("测试连通"))).toBe(true);
  });

  it("renders ping latency on success and categorized error without fake success", async () => {
    const wrapper = mountPage({ userRoles: ["super_admin"] });
    await flushPromises();

    await buttonByText(wrapper, "测试连通").trigger("click");
    await flushPromises();

    expect(generationApi.pingGeneration).toHaveBeenCalledWith("planning_intel");
    let result = wrapper.find(".generation-ping-result");
    expect(result.text()).toContain("连通正常");
    expect(result.text()).toContain("812ms");
    expect(result.classes()).toContain("form-success");

    generationApi.pingGeneration.mockResolvedValue({
      status: "error",
      provider: "minimax",
      model: "MiniMax-M2.5",
      base_url_host: "api.minimaxi.com",
      key_configured: true,
      latency_ms: null,
      error_code: "auth_failed",
      error_message: "provider rejected the credential"
    });
    await buttonByText(wrapper, "测试连通").trigger("click");
    await flushPromises();

    result = wrapper.find(".generation-ping-result");
    expect(result.text()).toContain("连通失败（auth_failed）");
    expect(result.text()).toContain("provider rejected the credential");
    // 失败不得渲染成成功（假成功回归）
    expect(result.classes()).toContain("form-error");
    expect(result.classes()).not.toContain("form-success");
  });

  // ---------- 可见性与加入码卡（workspace-configuration-design §14，page-specs §19.5.3/.4） ----------

  it("requires the impact confirmation before switching visibility to internal_public", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find('input[aria-label="组织内公开"]').trigger("click");
    expect(workspacesApi.updateWorkspaceVisibility).not.toHaveBeenCalled();
    const confirm = dialogByTitle(wrapper, "切换为组织内公开？");
    expect(confirm).toBeDefined();
    expect(confirm!.text()).toContain("任何登录用户可发现");

    await confirm!.findAll("button").find((item) => item.text().includes("确认公开"))!.trigger("click");
    await flushPromises();

    expect(workspacesApi.updateWorkspaceVisibility).toHaveBeenCalledWith("planning_intel", "internal_public");
  });

  it("switches back to private without the public-impact confirmation", async () => {
    const wrapper = mountPage({ visibility: "internal_public" });
    await flushPromises();

    await wrapper.find('input[aria-label="组织内公开"]').trigger("click");
    await flushPromises();

    expect(workspacesApi.updateWorkspaceVisibility).toHaveBeenCalledWith("planning_intel", "private");
    expect(dialogByTitle(wrapper, "切换为组织内公开？")).toBeUndefined();
  });

  it("generates a join code directly when none is active", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("当前没有有效加入码");
    await buttonByText(wrapper, "生成加入码").trigger("click");
    await flushPromises();

    expect(workspacesApi.createWorkspaceJoinCode).toHaveBeenCalledWith("planning_intel", {
      default_role: "viewer",
      expires_in_days: null,
      max_uses: null
    });
    expect(wrapper.find(".join-code-value").text()).toBe("7F2KQ9XN");
    expect(wrapper.find(".form-success").text()).toContain("已生成加入码：7F2KQ9XN");
  });

  it("shows the active code read-only, rotates only after confirm and disables via the API", async () => {
    const wrapper = mountPage({ joinCode: joinCodeRecord() });
    await flushPromises();

    // 码值以只读文本呈现 + 元数据（默认角色/有效期/用量）
    expect(wrapper.find(".join-code-value").text()).toBe("7F2KQ9XN");
    expect(wrapper.find(".join-code-value input").exists()).toBe(false);
    expect(wrapper.text()).toContain("默认角色 viewer");
    expect(wrapper.text()).toContain("长期有效");
    expect(wrapper.text()).toContain("已用 3 / 上限 20");

    // 轮换必须先确认「旧码立即失效」
    await buttonByText(wrapper, "轮换加入码").trigger("click");
    expect(workspacesApi.createWorkspaceJoinCode).not.toHaveBeenCalled();
    const confirm = dialogByTitle(wrapper, "轮换加入码？");
    expect(confirm).toBeDefined();
    expect(confirm!.text()).toContain("旧码立即失效");
    workspacesApi.createWorkspaceJoinCode.mockResolvedValue(joinCodeRecord({ code: "N3WC0DE2" }));
    await confirm!.findAll("button").find((item) => item.text().includes("确认轮换"))!.trigger("click");
    await flushPromises();
    expect(workspacesApi.createWorkspaceJoinCode).toHaveBeenCalledWith("planning_intel", {
      default_role: "viewer",
      expires_in_days: null,
      max_uses: null
    });
    expect(wrapper.find(".join-code-value").text()).toBe("N3WC0DE2");
    expect(wrapper.find(".form-success").text()).toContain("已轮换加入码");

    // 停用走 DELETE，成功后回到生成引导
    await buttonByText(wrapper, "停用加入码").trigger("click");
    await flushPromises();
    expect(workspacesApi.disableWorkspaceJoinCode).toHaveBeenCalledWith("planning_intel");
    expect(wrapper.find(".join-code-value").exists()).toBe(false);
    expect(wrapper.text()).toContain("当前没有有效加入码");
  });

  it("copies the join code and surfaces the real clipboard error on failure", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const wrapper = mountPage({ joinCode: joinCodeRecord() });
    await flushPromises();

    await buttonByText(wrapper, "复制").trigger("click");
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith("7F2KQ9XN");
    expect(wrapper.text()).toContain("已复制加入码");

    // 复制失败显示真实错误，不显示假成功（page-specs §19.5.4）
    writeText.mockRejectedValue(new Error("clipboard denied"));
    await buttonByText(wrapper, "复制").trigger("click");
    await flushPromises();
    expect(wrapper.find(".form-error").text()).toContain("复制失败：clipboard denied");
  });

  // -------------------------------------------------------------------------
  // WP4-G 反馈回哺区（feedback-heat-scoring §16.3 / page-specs §19.5.3-§19.5.4；
  // 契约 feedback_workflow acceptance_assertions ui_empty_state）
  // -------------------------------------------------------------------------

  it("renders the feedback loop empty state without any 0.0 placeholder", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const card = wrapper.find('[aria-label="反馈回哺"]');
    expect(card.exists()).toBe(true);
    expect(card.text()).toContain("尚未生成反馈评估");
    expect(card.text()).toContain("0 条待审提案");
    expect(card.text()).not.toContain("0.0");
    expect(recommendationsApi.fetchFeedbackRollups).toHaveBeenCalledWith(
      "planning_intel",
      "weekly",
      1
    );
    expect(recommendationsApi.fetchRubricRevisionProposals).toHaveBeenCalledWith(
      "planning_intel",
      "pending_review"
    );
  });

  it("hides null metrics entirely instead of rendering 0.0", async () => {
    const wrapper = mountPage({
      feedbackRollups: [
        feedbackRollupRecord({
          status: "empty",
          proposal_status: "none",
          metrics: {
            precision_at_6: null,
            rerank_uplift: null,
            normalized_adopt_rate: null,
            low_data_sources: []
          }
        })
      ]
    });
    await flushPromises();

    const card = wrapper.find('[aria-label="反馈回哺"]');
    expect(card.text()).toContain("2026-W27");
    expect(card.text()).not.toContain("precision@6");
    expect(card.text()).not.toContain("rerank uplift");
    expect(card.text()).not.toContain("0.0");
  });

  it("shows metrics and rubric version when the latest rollup has samples", async () => {
    const wrapper = mountPage({ feedbackRollups: [feedbackRollupRecord()] });
    await flushPromises();

    const card = wrapper.find('[aria-label="反馈回哺"]');
    expect(card.text()).toContain("rubric v3");
    expect(card.text()).toContain("precision@6");
    expect(card.text()).toContain("0.5000");
    expect(card.text()).toContain("rerank uplift");
    expect(card.text()).toContain("低数据源");
  });

  it("runs the manual re-estimate with the specced call shape and surfaces real errors", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "手动重估").trigger("click");
    await flushPromises();
    expect(recommendationsApi.runFeedbackRollup).toHaveBeenCalledWith("planning_intel", {
      period_type: "weekly"
    });
    expect(wrapper.find(".form-success").text()).toContain("反馈重估完成");

    // 失败显示真实错误，不渲染成功（假成功回归）。
    recommendationsApi.runFeedbackRollup.mockRejectedValueOnce(new Error("rollup boom"));
    await buttonByText(wrapper, "手动重估").trigger("click");
    await flushPromises();
    expect(wrapper.find('[aria-label="反馈回哺"] .form-error').text()).toContain("rollup boom");
  });

  it("accepts a proposal only after the version-bump confirmation", async () => {
    const wrapper = mountPage({ pendingProposals: [proposalRecord()] });
    await flushPromises();

    expect(wrapper.find('[aria-label="反馈回哺"]').text()).toContain("1 条待审提案");
    await buttonByText(wrapper, "审阅提案").trigger("click");
    await flushPromises();

    const modal = dialogByTitle(wrapper, "rubric 修订提案");
    expect(modal).toBeDefined();
    expect(modal!.text()).toContain("adjust_topic_weight");
    expect(modal!.text()).toContain("inference_serving");
    expect(modal!.text()).toContain("4 → 4.5");
    expect(modal!.text()).toContain("采信样本集中在推理服务");

    // 「采纳并生效」先弹二次确认（提示 rubric_version 将 +1），未确认不得调 API。
    await buttonByText(wrapper, "采纳并生效").trigger("click");
    await flushPromises();
    expect(recommendationsApi.reviewRubricRevisionProposal).not.toHaveBeenCalled();
    const confirm = dialogByTitle(wrapper, "确认采纳该提案？");
    expect(confirm).toBeDefined();
    expect(confirm!.text()).toContain("v3 升级为 v4");

    await buttonByText(wrapper, "确认采纳").trigger("click");
    await flushPromises();
    expect(recommendationsApi.reviewRubricRevisionProposal).toHaveBeenCalledWith(
      "planning_intel",
      "proposal-1",
      { action: "accept", comment: "" }
    );
    expect(wrapper.find(".form-success").text()).toContain("提案已采纳并生效");
  });

  it("requires a comment before rejecting a proposal", async () => {
    const wrapper = mountPage({ pendingProposals: [proposalRecord()] });
    await flushPromises();

    await buttonByText(wrapper, "审阅提案").trigger("click");
    await flushPromises();

    // 空 comment 驳回：本地校验拦截，零 API 调用。
    await buttonByText(wrapper, "驳回").trigger("click");
    await flushPromises();
    expect(recommendationsApi.reviewRubricRevisionProposal).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("驳回必须填写理由");

    await wrapper.find(".proposal-comment-field textarea").setValue("证据不足，先驳回");
    await buttonByText(wrapper, "驳回").trigger("click");
    await flushPromises();
    expect(recommendationsApi.reviewRubricRevisionProposal).toHaveBeenCalledWith(
      "planning_intel",
      "proposal-1",
      { action: "reject", comment: "证据不足，先驳回" }
    );
    expect(wrapper.find(".form-success").text()).toContain("提案已驳回");
  });
});
