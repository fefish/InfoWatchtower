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

vi.mock("../api/workspaces", () => workspacesApi);
vi.mock("../api/renditions", () => renditionsApi);
vi.mock("../api/scheduler", () => schedulerApi);
vi.mock("../api/generation", () => generationApi);

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
      key_source: "env"
    },
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
  workspacesApi.updateWorkspaceVisibility.mockResolvedValue({});
  workspacesApi.fetchWorkspaceJoinCode.mockResolvedValue(options.joinCode ?? null);
  workspacesApi.createWorkspaceJoinCode.mockResolvedValue(joinCodeRecord());
  workspacesApi.disableWorkspaceJoinCode.mockResolvedValue(undefined);

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
      "可见性与加入码"
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
      expect(workspacesApi.fetchWorkspaceMembers).not.toHaveBeenCalled();
      expect(workspacesApi.fetchWorkspaceLabelPolicy).not.toHaveBeenCalled();
      expect(renditionsApi.fetchReportFormats).not.toHaveBeenCalled();
      expect(schedulerApi.fetchWorkspaceSchedulePolicy).not.toHaveBeenCalled();
      expect(generationApi.fetchWorkspaceGenerationPolicy).not.toHaveBeenCalled();
      expect(workspacesApi.fetchWorkspaceJoinCode).not.toHaveBeenCalled();
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
    // 未配 key：显示实例级 env 配置指引
    expect(unconfiguredCard.text()).toContain("GENERATION_API_KEY");
    expect(unconfiguredCard.text()).toContain("development-quickstart.md");
  });

  it("saves the generation policy with nullable follow-instance fields", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find('input[aria-label="生成模型名"]').setValue("gpt-4o-mini");
    await wrapper.find('input[aria-label="生成温度"]').setValue("0.2");
    await buttonByText(wrapper, "保存生成模型策略").trigger("click");
    await flushPromises();

    expect(generationApi.updateWorkspaceGenerationPolicy).toHaveBeenCalledWith("planning_intel", {
      model: "gpt-4o-mini",
      temperature: 0.2,
      timeout_seconds: null,
      daily_generation_budget: null,
      fallback_behavior: "rule_fallback"
    });
    expect(wrapper.find(".form-success").text()).toContain("已保存：生成模型策略");
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
});
