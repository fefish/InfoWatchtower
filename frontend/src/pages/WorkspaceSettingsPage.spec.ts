import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceSettingsPage from "./WorkspaceSettingsPage.vue";
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
  updateWorkspaceSection: vi.fn()
}));

const renditionsApi = vi.hoisted(() => ({
  fetchReportFormats: vi.fn(),
  createReportFormat: vi.fn(),
  updateReportFormat: vi.fn(),
  deleteReportFormat: vi.fn()
}));

vi.mock("../api/workspaces", () => workspacesApi);
vi.mock("../api/renditions", () => renditionsApi);

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

function mountPage(
  options: {
    workspaceRole?: string;
    userRoles?: string[];
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

  return mount(WorkspaceSettingsPage, {
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

  it("renders the five settings cards for workspace admins", async () => {
    const wrapper = mountPage();
    await flushPromises();

    for (const cardLabel of ["基本信息", "成员与角色", "标签策略设置", "报告设置", "导航分区"]) {
      expect(wrapper.find(`[aria-label="${cardLabel}"]`).exists()).toBe(true);
    }
    // 锚点导航覆盖五个卡片（候选池入口跳 #labels 依赖该锚点）。
    expect(wrapper.find('a[href="#labels"]').exists()).toBe(true);
    expect(wrapper.find("#labels").exists()).toBe(true);
    expect(workspacesApi.fetchWorkspaceMembers).toHaveBeenCalledWith("planning_intel");
    expect(workspacesApi.fetchWorkspaceLabelPolicy).toHaveBeenCalledWith("planning_intel");
    expect(workspacesApi.fetchWorkspaceReportPolicy).toHaveBeenCalledWith("planning_intel");
    expect(workspacesApi.fetchWorkspaceSectionsManage).toHaveBeenCalledWith("planning_intel");
    expect(renditionsApi.fetchReportFormats).toHaveBeenCalledWith("planning_intel");
  });

  it("hides all management cards for workspace members and viewers", async () => {
    for (const role of ["member", "viewer"]) {
      vi.clearAllMocks();
      const wrapper = mountPage({ workspaceRole: role });
      await flushPromises();

      expect(wrapper.text()).toContain("需要工作台管理员权限");
      expect(wrapper.find('[aria-label="标签策略设置"]').exists()).toBe(false);
      expect(wrapper.find('[aria-label="报告设置"]').exists()).toBe(false);
      expect(workspacesApi.fetchWorkspaceMembers).not.toHaveBeenCalled();
      expect(workspacesApi.fetchWorkspaceLabelPolicy).not.toHaveBeenCalled();
      expect(renditionsApi.fetchReportFormats).not.toHaveBeenCalled();
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
});
