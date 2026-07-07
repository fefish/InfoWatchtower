<script setup lang="ts">
import {
  Building2,
  Clock,
  Copy,
  Cpu,
  FileText,
  KeyRound,
  LayoutGrid,
  Plus,
  RefreshCw,
  Settings,
  Tag,
  Trash2,
  Users,
  X
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";

import {
  fetchWorkspaceGenerationPolicy,
  pingGeneration,
  updateWorkspaceGenerationPolicy,
  type GenerationPingRecord,
  type WorkspaceGenerationPolicyRecord
} from "../api/generation";
import {
  createReportFormat,
  deleteReportFormat,
  fetchReportFormats,
  updateReportFormat,
  type ReportFormatRecord
} from "../api/renditions";
import {
  fetchWorkspaceSchedulePolicy,
  updateWorkspaceSchedulePolicy,
  type WorkspaceSchedulePolicyRecord
} from "../api/scheduler";
import {
  createWorkspaceJoinCode,
  disableWorkspaceJoinCode,
  fetchWorkspaceJoinCode,
  fetchWorkspaceLabelPolicy,
  fetchWorkspaceMembers,
  fetchWorkspaceReportPolicy,
  fetchWorkspaceSectionsManage,
  removeWorkspaceMember,
  updateWorkspace,
  updateWorkspaceLabelPolicy,
  updateWorkspaceReportPolicy,
  updateWorkspaceSection,
  updateWorkspaceVisibility,
  upsertWorkspaceMember,
  type WorkspaceJoinCodeRecord,
  type WorkspaceLabelPolicy,
  type WorkspaceMemberRecord,
  type WorkspaceSectionManageRecord
} from "../api/workspaces";
import AppModal from "../components/AppModal.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const session = useSessionStore();
const workspace = useWorkspaceStore();
const runtime = useRuntimeStore();

const error = ref("");
const message = ref("");

const workspaceRoleRank: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3
};

// 与 AppShell 同口径：super_admin / editor_admin 全局角色视同 owner，
// 其余取当前工作台 membership 角色，未知按 viewer 保守处理。
const effectiveWorkspaceRole = computed(() => {
  const globalRoles = session.user?.roles ?? [];
  if (globalRoles.includes("super_admin") || globalRoles.includes("editor_admin")) {
    return "owner";
  }
  return workspace.currentRole ?? "viewer";
});
const canManage = computed(
  () => (workspaceRoleRank[effectiveWorkspaceRole.value] ?? 0) >= workspaceRoleRank.admin
);

// ---------- a) 基本信息 ----------
const basicsForm = reactive({
  name: "",
  description: "",
  defaultDomainCode: "ai"
});
const savingBasics = ref(false);

function fillBasicsForm() {
  basicsForm.name = workspace.current?.name ?? "";
  basicsForm.description = workspace.current?.description ?? "";
  basicsForm.defaultDomainCode = workspace.current?.default_domain_code ?? "ai";
}

async function saveBasics() {
  if (!workspace.currentCode) {
    return;
  }
  const name = basicsForm.name.trim();
  if (!name) {
    error.value = "工作台名称不能为空";
    return;
  }
  savingBasics.value = true;
  error.value = "";
  message.value = "";
  try {
    await updateWorkspace(workspace.currentCode, {
      name,
      description: basicsForm.description.trim(),
      default_domain_code: basicsForm.defaultDomainCode.trim() || "ai"
    });
    await workspace.loadWorkspaces();
    fillBasicsForm();
    message.value = "已保存：工作台基本信息";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存工作台基本信息失败";
  } finally {
    savingBasics.value = false;
  }
}

// ---------- b) 成员与角色 ----------
const members = ref<WorkspaceMemberRecord[]>([]);
const memberRoleDrafts = reactive<Record<string, string>>({});
const savingMemberId = ref("");

async function loadMembers() {
  if (!workspace.currentCode) {
    return;
  }
  members.value = await fetchWorkspaceMembers(workspace.currentCode);
  for (const member of members.value) {
    memberRoleDrafts[member.user.id] = member.workspace_role;
  }
}

const ownerCount = computed(
  () => members.value.filter((member) => member.workspace_role === "owner").length
);

async function saveMemberRole(member: WorkspaceMemberRecord) {
  const nextRole = memberRoleDrafts[member.user.id] || member.workspace_role;
  if (!workspace.currentCode || nextRole === member.workspace_role) {
    return;
  }
  if (member.workspace_role === "owner" && nextRole !== "owner" && ownerCount.value <= 1) {
    error.value = "不能降级最后一位 owner";
    return;
  }
  savingMemberId.value = member.user.id;
  error.value = "";
  message.value = "";
  try {
    await upsertWorkspaceMember(workspace.currentCode, {
      user_id: member.user.id,
      workspace_role: nextRole,
      confirm_dangerous_change: member.workspace_role === "owner" && nextRole !== "owner"
    });
    await loadMembers();
    message.value = `已更新成员角色：${member.user.display_name} → ${nextRole}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新成员角色失败";
  } finally {
    savingMemberId.value = "";
  }
}

async function removeMember(member: WorkspaceMemberRecord) {
  if (!workspace.currentCode) {
    return;
  }
  if (member.workspace_role === "owner" && ownerCount.value <= 1) {
    error.value = "不能移除最后一位 owner";
    return;
  }
  savingMemberId.value = member.user.id;
  error.value = "";
  message.value = "";
  try {
    await removeWorkspaceMember(workspace.currentCode, member.user.id, {
      confirmDangerousChange: member.workspace_role === "owner"
    });
    await loadMembers();
    message.value = `已移出工作台：${member.user.display_name}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "移除成员失败";
  } finally {
    savingMemberId.value = "";
  }
}

// ---------- c) 标签策略（由数据源管理页整体迁入） ----------
const activePolicyTab = ref<"level1" | "level2" | "format">("level1");
const savingPolicy = ref(false);

const aiSqlPrimaryCategories = [
  "AI Infra",
  "AI 应用",
  "测评技术",
  "大厂动态",
  "模型",
  "算法",
  "推理加速",
  "训练技术",
  "智能体",
  "基础竞争力"
];
const companySqlContentFields = [
  "background",
  "effects",
  "eventSummary",
  "technologyAndInnovation",
  "valueAndImpact"
];
const contentFieldLabels: Record<string, string> = {
  background: "背景",
  effects: "效果总结",
  eventSummary: "事件总结",
  technologyAndInnovation: "技术和创新点总结",
  valueAndImpact: "价值和影响"
};
const aiToolPrimaryCategories = ["工具新功能", "工具新案例", "工具新技术"];
const aiToolSecondaryLabels = ["cursor", "claude code", "opencode", "codex"];

const workspacePolicyPresets = {
  ai_sql: {
    labelSetCode: "ai_sql_categories",
    newsFormatCode: "company_sql_v1",
    exportCategoryMode: "news_primary",
    requiredContentFields: [...companySqlContentFields],
    primaryCategories: aiSqlPrimaryCategories,
    secondaryLabelsByPrimary: {},
    defaultCategory: "AI 应用",
    fallbackCategory: "AI 应用"
  },
  ai_tools: {
    labelSetCode: "ai_tools_categories",
    newsFormatCode: "tool_intel_v1",
    exportCategoryMode: "news_primary",
    requiredContentFields: [...companySqlContentFields],
    primaryCategories: aiToolPrimaryCategories,
    secondaryLabelsByPrimary: Object.fromEntries(
      aiToolPrimaryCategories.map((category) => [category, [...aiToolSecondaryLabels]])
    ) as Record<string, string[]>,
    defaultCategory: "工具新功能",
    fallbackCategory: "工具新功能"
  }
};

const policyForm = reactive({
  labelSetCode: "ai_sql_categories",
  newsFormatCode: "company_sql_v1",
  exportCategoryMode: "news_primary",
  requiredContentFields: [...companySqlContentFields],
  allowedPrimaryCategories: [...aiSqlPrimaryCategories],
  secondaryLabelsByPrimary: {} as Record<string, string[]>,
  defaultCategory: "AI 应用",
  fallbackCategory: "AI 应用"
});
const categoryDraft = ref("");
const contentFieldDraft = ref("");
const secondaryDraft = reactive({
  primary: "",
  label: ""
});

const activePrimaryCategories = computed(() =>
  policyForm.allowedPrimaryCategories.length > 0 ? policyForm.allowedPrimaryCategories : aiSqlPrimaryCategories
);
const secondaryLabelTotal = computed(() =>
  activePrimaryCategories.value.reduce(
    (total: number, category: string) => total + secondaryLabelsFor(category).length,
    0
  )
);
const currentPolicyPreset = computed(() => {
  if (workspace.currentCode === "ai_tools") {
    return workspacePolicyPresets.ai_tools;
  }
  return workspacePolicyPresets.ai_sql;
});

async function loadWorkspacePolicy() {
  if (!workspace.currentCode) {
    return;
  }
  const policy = await fetchWorkspaceLabelPolicy(workspace.currentCode);
  fillPolicyForm(policy);
}

function fillPolicyForm(policy: WorkspaceLabelPolicy) {
  policyForm.labelSetCode = policy.label_set_code;
  policyForm.newsFormatCode = policy.news_format_code;
  policyForm.exportCategoryMode = policy.export_category_mode || "news_primary";
  policyForm.requiredContentFields = normalizeContentFields(policy.required_content_fields);
  policyForm.allowedPrimaryCategories = [...policy.allowed_primary_categories];
  policyForm.secondaryLabelsByPrimary = normalizeSecondaryLabels(
    policy.secondary_labels_by_primary ?? {},
    policyForm.allowedPrimaryCategories
  );
  policyForm.defaultCategory = policy.default_category;
  policyForm.fallbackCategory = policy.fallback_category;
  secondaryDraft.primary = policyForm.allowedPrimaryCategories[0] ?? "";
  syncPolicyFallbacks();
}

function tagInputWidth(value: string) {
  const width = Array.from(value || "").reduce((total, character) => {
    return total + (/[一-鿿]/.test(character) ? 14 : 8);
  }, 18);
  return `${Math.max(54, Math.min(128, width))}px`;
}

function syncPolicyFallbacks() {
  if (!policyForm.allowedPrimaryCategories.includes(policyForm.defaultCategory)) {
    policyForm.defaultCategory = policyForm.allowedPrimaryCategories[0];
  }
  if (!policyForm.allowedPrimaryCategories.includes(policyForm.fallbackCategory)) {
    policyForm.fallbackCategory = policyForm.defaultCategory;
  }
  if (!policyForm.allowedPrimaryCategories.includes(secondaryDraft.primary)) {
    secondaryDraft.primary = policyForm.allowedPrimaryCategories[0] ?? "";
  }
}

function normalizedPolicyCategories() {
  const next: string[] = [];
  for (const category of policyForm.allowedPrimaryCategories) {
    const value = category.trim();
    if (value && !next.includes(value)) {
      next.push(value);
    }
  }
  return next;
}

function normalizeSecondaryLabels(labelsByPrimary: Record<string, string[]>, primaryCategories: string[]) {
  const normalized: Record<string, string[]> = {};
  for (const category of primaryCategories) {
    const labels = labelsByPrimary[category] ?? [];
    const next: string[] = [];
    for (const label of labels) {
      const value = label.trim();
      if (value && !next.includes(value)) {
        next.push(value);
      }
    }
    if (next.length > 0) {
      normalized[category] = next;
    }
  }
  return normalized;
}

function secondaryLabelsFor(category: string) {
  return policyForm.secondaryLabelsByPrimary[category] ?? [];
}

function addPolicyCategory() {
  const value = categoryDraft.value.trim();
  if (!value || policyForm.allowedPrimaryCategories.includes(value)) {
    categoryDraft.value = "";
    return;
  }
  policyForm.allowedPrimaryCategories.push(value);
  policyForm.secondaryLabelsByPrimary[value] = [];
  categoryDraft.value = "";
  syncPolicyFallbacks();
}

function renamePolicyCategory(index: number, value: string) {
  const previous = policyForm.allowedPrimaryCategories[index];
  policyForm.allowedPrimaryCategories[index] = value;
  if (previous !== value) {
    policyForm.secondaryLabelsByPrimary[value] = policyForm.secondaryLabelsByPrimary[previous] ?? [];
    delete policyForm.secondaryLabelsByPrimary[previous];
  }
  syncPolicyFallbacks();
}

function removePolicyCategory(index: number) {
  if (policyForm.allowedPrimaryCategories.length <= 1) {
    return;
  }
  const [removed] = policyForm.allowedPrimaryCategories.slice(index, index + 1);
  policyForm.allowedPrimaryCategories.splice(index, 1);
  delete policyForm.secondaryLabelsByPrimary[removed];
  syncPolicyFallbacks();
}

function resetPolicyCategories() {
  const preset = currentPolicyPreset.value;
  policyForm.labelSetCode = preset.labelSetCode;
  policyForm.newsFormatCode = preset.newsFormatCode;
  policyForm.exportCategoryMode = preset.exportCategoryMode;
  policyForm.requiredContentFields = [...preset.requiredContentFields];
  policyForm.allowedPrimaryCategories = [...preset.primaryCategories];
  policyForm.secondaryLabelsByPrimary = normalizeSecondaryLabels(
    preset.secondaryLabelsByPrimary,
    policyForm.allowedPrimaryCategories
  );
  policyForm.defaultCategory = preset.defaultCategory;
  policyForm.fallbackCategory = preset.fallbackCategory;
  secondaryDraft.primary = policyForm.allowedPrimaryCategories[0] ?? "";
}

function normalizeContentFields(fields: string[]) {
  const next: string[] = [];
  for (const field of fields) {
    const value = field.trim();
    if (value && !next.includes(value)) {
      next.push(value);
    }
  }
  return next.length ? next : [...companySqlContentFields];
}

function addContentField() {
  const value = contentFieldDraft.value.trim();
  if (!value || policyForm.requiredContentFields.includes(value)) {
    contentFieldDraft.value = "";
    return;
  }
  policyForm.requiredContentFields.push(value);
  contentFieldDraft.value = "";
}

function contentFieldLabel(field: string) {
  return contentFieldLabels[field] ?? "自定义字段";
}

function renameContentField(index: number, value: string) {
  policyForm.requiredContentFields[index] = value;
}

function removeContentField(index: number) {
  if (
    policyForm.newsFormatCode === "company_sql_v1" &&
    policyForm.requiredContentFields.length <= companySqlContentFields.length
  ) {
    error.value = "company_sql_v1 不能删除公司 SQL 必填字段";
    return;
  }
  policyForm.requiredContentFields.splice(index, 1);
}

function addSecondaryLabel() {
  const primary = secondaryDraft.primary || policyForm.allowedPrimaryCategories[0];
  const label = secondaryDraft.label.trim();
  if (!primary || !label) {
    return;
  }
  const labels = policyForm.secondaryLabelsByPrimary[primary] ?? [];
  if (!labels.includes(label)) {
    policyForm.secondaryLabelsByPrimary[primary] = [...labels, label];
  }
  secondaryDraft.label = "";
}

function renameSecondaryLabel(primary: string, index: number, value: string) {
  const labels = [...secondaryLabelsFor(primary)];
  labels[index] = value;
  policyForm.secondaryLabelsByPrimary[primary] = labels;
}

function removeSecondaryLabel(primary: string, index: number) {
  const labels = [...secondaryLabelsFor(primary)];
  labels.splice(index, 1);
  policyForm.secondaryLabelsByPrimary[primary] = labels;
}

async function saveWorkspacePolicy() {
  if (!workspace.currentCode) {
    return;
  }
  const categories = normalizedPolicyCategories();
  if (categories.length === 0) {
    error.value = "至少保留一个一级标签";
    return;
  }
  policyForm.allowedPrimaryCategories = categories;
  policyForm.requiredContentFields = normalizeContentFields(policyForm.requiredContentFields);
  policyForm.secondaryLabelsByPrimary = normalizeSecondaryLabels(
    policyForm.secondaryLabelsByPrimary,
    categories
  );
  syncPolicyFallbacks();
  savingPolicy.value = true;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateWorkspaceLabelPolicy(workspace.currentCode, {
      label_set_code: policyForm.labelSetCode,
      news_format_code: policyForm.newsFormatCode,
      export_category_mode: policyForm.exportCategoryMode,
      required_content_fields: policyForm.requiredContentFields,
      allowed_primary_categories: categories,
      secondary_labels_by_primary: policyForm.secondaryLabelsByPrimary,
      default_category: policyForm.defaultCategory,
      fallback_category: policyForm.fallbackCategory
    });
    fillPolicyForm(updated);
    message.value = `已保存：${workspace.current?.name} 的统一标签策略`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存工作台标签策略失败";
  } finally {
    savingPolicy.value = false;
  }
}

// ---------- d) 报告设置 ----------
const autoPublishDaily = ref(true);
const savingReportPolicy = ref(false);
const reportFormats = ref<ReportFormatRecord[]>([]);
const togglingFormatId = ref("");
const creatingFormat = ref(false);
const showFormatForm = ref(false);

const reportFormatFieldOptions = [
  { value: "tag_line", label: "标签行" },
  { value: "bullet_points", label: "要点" },
  { value: "takeaway", label: "总结" },
  { value: "five_fields", label: "五段正文" },
  { value: "summary", label: "摘要" },
  { value: "source_link", label: "来源链接" },
  { value: "score", label: "推荐分" }
];

const formatForm = reactive({
  formatCode: "",
  name: "",
  description: "",
  groupBy: "board",
  headlineAutoTopN: 6,
  itemFields: ["tag_line", "bullet_points", "takeaway", "source_link"] as string[],
  exportMd: true,
  exportHtml: true
});

async function loadReportSettings() {
  if (!workspace.currentCode) {
    return;
  }
  const [policy, formats] = await Promise.all([
    fetchWorkspaceReportPolicy(workspace.currentCode),
    fetchReportFormats(workspace.currentCode)
  ]);
  autoPublishDaily.value = policy.auto_publish_daily;
  reportFormats.value = formats;
}

async function toggleAutoPublish(event: Event) {
  if (!workspace.currentCode) {
    return;
  }
  const checked = event.target instanceof HTMLInputElement && event.target.checked;
  savingReportPolicy.value = true;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateWorkspaceReportPolicy(workspace.currentCode, {
      auto_publish_daily: checked
    });
    autoPublishDaily.value = updated.auto_publish_daily;
    message.value = updated.auto_publish_daily
      ? "已开启：日报出稿后自动发布"
      : "已关闭：日报回到人工发布工作流";
  } catch (exc) {
    autoPublishDaily.value = !checked;
    error.value = exc instanceof Error ? exc.message : "保存报告发布策略失败";
  } finally {
    savingReportPolicy.value = false;
  }
}

async function toggleReportFormat(format: ReportFormatRecord, event: Event) {
  const checked = event.target instanceof HTMLInputElement && event.target.checked;
  togglingFormatId.value = format.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateReportFormat(format.id, { enabled: checked });
    reportFormats.value = reportFormats.value.map((item) => (item.id === updated.id ? updated : item));
    message.value = `${updated.enabled ? "已启用" : "已停用"}：${updated.name}`;
  } catch (exc) {
    await loadReportSettings();
    error.value = exc instanceof Error ? exc.message : "更新报告格式失败";
  } finally {
    togglingFormatId.value = "";
  }
}

async function removeReportFormat(format: ReportFormatRecord) {
  togglingFormatId.value = format.id;
  error.value = "";
  message.value = "";
  try {
    await deleteReportFormat(format.id);
    reportFormats.value = reportFormats.value.filter((item) => item.id !== format.id);
    message.value = `已删除自定义格式：${format.name}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "删除报告格式失败";
  } finally {
    togglingFormatId.value = "";
  }
}

function toggleFormatField(field: string, event: Event) {
  const checked = event.target instanceof HTMLInputElement && event.target.checked;
  if (checked && !formatForm.itemFields.includes(field)) {
    formatForm.itemFields = [...formatForm.itemFields, field];
  }
  if (!checked) {
    formatForm.itemFields = formatForm.itemFields.filter((item) => item !== field);
  }
}

async function submitReportFormat() {
  if (!workspace.currentCode) {
    return;
  }
  const formatCode = formatForm.formatCode.trim();
  const name = formatForm.name.trim();
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(formatCode)) {
    error.value = "格式代码需以小写字母开头，只含小写字母、数字和下划线";
    return;
  }
  if (!name) {
    error.value = "请填写格式名称";
    return;
  }
  if (formatForm.itemFields.length === 0) {
    error.value = "至少选择一个条目字段";
    return;
  }
  creatingFormat.value = true;
  error.value = "";
  message.value = "";
  try {
    const created = await createReportFormat({
      workspace_code: workspace.currentCode,
      format_code: formatCode,
      name,
      description: formatForm.description.trim(),
      group_by: formatForm.groupBy,
      headline_enabled: formatForm.headlineAutoTopN > 0,
      headline_auto_top_n: Math.max(0, Math.floor(formatForm.headlineAutoTopN)),
      item_fields: [...formatForm.itemFields],
      export_targets: [
        ...(formatForm.exportMd ? ["md"] : []),
        ...(formatForm.exportHtml ? ["html"] : [])
      ]
    });
    reportFormats.value = [...reportFormats.value, created];
    showFormatForm.value = false;
    formatForm.formatCode = "";
    formatForm.name = "";
    formatForm.description = "";
    message.value = `已新增报告格式：${created.name}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "新增报告格式失败";
  } finally {
    creatingFormat.value = false;
  }
}

// ---------- e) 导航分区 ----------
const manageSections = ref<WorkspaceSectionManageRecord[]>([]);
const togglingSectionKey = ref("");

async function loadManageSections() {
  if (!workspace.currentCode) {
    return;
  }
  manageSections.value = await fetchWorkspaceSectionsManage(workspace.currentCode);
}

async function toggleSection(section: WorkspaceSectionManageRecord, event: Event) {
  if (!workspace.currentCode) {
    return;
  }
  const checked = event.target instanceof HTMLInputElement && event.target.checked;
  togglingSectionKey.value = section.section_key;
  error.value = "";
  message.value = "";
  try {
    await updateWorkspaceSection(workspace.currentCode, section.section_key, { enabled: checked });
    await loadManageSections();
    await workspace.loadSections();
    message.value = `${checked ? "已启用" : "已停用"}分区：${section.name}`;
  } catch (exc) {
    await loadManageSections();
    error.value = exc instanceof Error ? exc.message : "更新导航分区失败";
  } finally {
    togglingSectionKey.value = "";
  }
}

// ---------- f) 自动化（schedule_policy，pipeline-jobs-design §8.2/§8.4） ----------
const schedulePolicy = ref<WorkspaceSchedulePolicyRecord | null>(null);
const scheduleError = ref("");
const savingSchedule = ref(false);
const scheduleConfirmOpen = ref(false);
const scheduleForm = reactive({
  // 三态：follow=跟随实例总闸（null）/ on / off
  enabled: "follow" as "follow" | "on" | "off",
  dailyTime: "",
  dayOffset: "",
  retryMaxAttempts: 1,
  retryBackoffSeconds: 900,
  weeklyEnabled: false,
  weeklyDay: 5,
  weeklyTime: "17:00"
});

// 实例总闸关闭或部署禁采集（intranet）时整卡只读并解释原因（page-specs §19.5.3）。
const scheduleReadOnlyReason = computed(() => {
  if (!runtime.canIngest) {
    return "当前部署形态已禁用采集能力（intranet 等 pull-only 形态），自动调度不可配置。";
  }
  if (schedulePolicy.value && !schedulePolicy.value.instance.scheduler_enabled) {
    return "实例调度总闸已关闭（INGESTION_SCHEDULER_ENABLED=false），工作台策略不能越过总闸，本卡只读。";
  }
  return "";
});
const scheduleReadOnly = computed(() => Boolean(scheduleReadOnlyReason.value));

function fillScheduleForm(record: WorkspaceSchedulePolicyRecord) {
  const policy = record.policy;
  scheduleForm.enabled = policy.enabled === null ? "follow" : policy.enabled ? "on" : "off";
  scheduleForm.dailyTime = policy.daily_time ?? "";
  scheduleForm.dayOffset = policy.day_offset === null ? "" : String(policy.day_offset);
  scheduleForm.retryMaxAttempts = policy.retry.max_attempts;
  scheduleForm.retryBackoffSeconds = policy.retry.backoff_seconds;
  scheduleForm.weeklyEnabled = policy.weekly.enabled;
  scheduleForm.weeklyDay = policy.weekly.weekly_day;
  scheduleForm.weeklyTime = policy.weekly.weekly_time;
}

async function loadSchedulePolicy() {
  if (!workspace.currentCode) {
    return;
  }
  scheduleError.value = "";
  try {
    schedulePolicy.value = await fetchWorkspaceSchedulePolicy(workspace.currentCode);
    fillScheduleForm(schedulePolicy.value);
  } catch (exc) {
    schedulePolicy.value = null;
    scheduleError.value = exc instanceof Error ? exc.message : "加载自动化策略失败";
  }
}

// 生效值来源标注（§8.4：「跟随实例默认 12:00」vs「本工作台 09:30」）
const dailyTimeSourceLabel = computed(() => {
  const record = schedulePolicy.value;
  if (!record) {
    return "";
  }
  return record.policy.daily_time
    ? `本工作台 ${record.policy.daily_time}`
    : `跟随实例默认 ${record.instance.daily_time || "未配置"}`;
});
const dayOffsetSourceLabel = computed(() => {
  const record = schedulePolicy.value;
  if (!record) {
    return "";
  }
  return record.policy.day_offset !== null
    ? `本工作台 ${record.policy.day_offset} 天`
    : `跟随实例默认 ${record.instance.day_offset} 天`;
});
const enabledSourceLabel = computed(() => {
  const record = schedulePolicy.value;
  if (!record) {
    return "";
  }
  if (record.policy.enabled === null) {
    return `跟随实例总闸（当前${record.instance.scheduler_enabled ? "开启" : "关闭"}）`;
  }
  return record.policy.enabled ? "本工作台开启" : "本工作台退出自动调度";
});

function formatRunAt(value: string | null | undefined) {
  if (!value) {
    return "未排期";
  }
  return value.slice(0, 16).replace("T", " ");
}

function scheduleUpdatePayload() {
  return {
    enabled: scheduleForm.enabled === "follow" ? null : scheduleForm.enabled === "on",
    daily_time: scheduleForm.dailyTime.trim() || null,
    day_offset: scheduleForm.dayOffset === "" ? null : Number(scheduleForm.dayOffset),
    // source_types 不在本卡编辑：原样回传存量值，避免全量 PATCH 把它冲回默认
    source_types: schedulePolicy.value?.policy.source_types ?? null,
    retry: {
      max_attempts: Number(scheduleForm.retryMaxAttempts),
      backoff_seconds: Number(scheduleForm.retryBackoffSeconds)
    },
    weekly: {
      enabled: scheduleForm.weeklyEnabled,
      weekly_day: Number(scheduleForm.weeklyDay),
      weekly_time: scheduleForm.weeklyTime.trim() || "17:00"
    }
  };
}

// 保存前展示影响确认（AppModal sm，产品设计 §10.3：新增确认交互一律 Modal sm）
function requestScheduleSave() {
  if (scheduleReadOnly.value) {
    return;
  }
  scheduleConfirmOpen.value = true;
}

async function confirmScheduleSave() {
  if (!workspace.currentCode) {
    return;
  }
  scheduleConfirmOpen.value = false;
  savingSchedule.value = true;
  scheduleError.value = "";
  message.value = "";
  try {
    schedulePolicy.value = await updateWorkspaceSchedulePolicy(
      workspace.currentCode,
      scheduleUpdatePayload()
    );
    fillScheduleForm(schedulePolicy.value);
    message.value = `已保存：自动化策略（下次运行 ${formatRunAt(schedulePolicy.value.resolved.next_run_at)}）`;
  } catch (exc) {
    scheduleError.value = exc instanceof Error ? exc.message : "保存自动化策略失败";
  } finally {
    savingSchedule.value = false;
  }
}

// ---------- g) 生成模型（generation_policy，generation-provider-design §5） ----------
const generationPolicy = ref<WorkspaceGenerationPolicyRecord | null>(null);
const generationError = ref("");
const savingGeneration = ref(false);
const generationForm = reactive({
  model: "",
  temperature: "",
  timeoutSeconds: "",
  dailyBudget: "",
  fallbackBehavior: "rule_fallback"
});
const pingResult = ref<GenerationPingRecord | null>(null);
const pinging = ref(false);
const pingError = ref("");

// 「测试连通」权限门与后端一致：仅 super_admin / editor_admin（其余角色不渲染按钮）
const canPingGeneration = computed(() => {
  const roles = session.user?.roles ?? [];
  return roles.includes("super_admin") || roles.includes("editor_admin");
});

function fillGenerationForm(record: WorkspaceGenerationPolicyRecord) {
  const policy = record.policy;
  generationForm.model = policy.model ?? "";
  generationForm.temperature = policy.temperature === null ? "" : String(policy.temperature);
  generationForm.timeoutSeconds = policy.timeout_seconds === null ? "" : String(policy.timeout_seconds);
  generationForm.dailyBudget =
    policy.daily_generation_budget === null ? "" : String(policy.daily_generation_budget);
  generationForm.fallbackBehavior = policy.fallback_behavior || "rule_fallback";
}

async function loadGenerationPolicy() {
  if (!workspace.currentCode) {
    return;
  }
  generationError.value = "";
  try {
    generationPolicy.value = await fetchWorkspaceGenerationPolicy(workspace.currentCode);
    fillGenerationForm(generationPolicy.value);
  } catch (exc) {
    generationPolicy.value = null;
    generationError.value = exc instanceof Error ? exc.message : "加载生成模型配置失败";
  }
}

async function saveGenerationPolicy() {
  if (!workspace.currentCode) {
    return;
  }
  savingGeneration.value = true;
  generationError.value = "";
  message.value = "";
  try {
    generationPolicy.value = await updateWorkspaceGenerationPolicy(workspace.currentCode, {
      model: generationForm.model.trim() || null,
      temperature: generationForm.temperature === "" ? null : Number(generationForm.temperature),
      timeout_seconds:
        generationForm.timeoutSeconds === "" ? null : Number(generationForm.timeoutSeconds),
      daily_generation_budget:
        generationForm.dailyBudget === "" ? null : Number(generationForm.dailyBudget),
      fallback_behavior: generationForm.fallbackBehavior
    });
    fillGenerationForm(generationPolicy.value);
    message.value = "已保存：生成模型策略";
  } catch (exc) {
    generationError.value = exc instanceof Error ? exc.message : "保存生成模型策略失败";
  } finally {
    savingGeneration.value = false;
  }
}

async function runGenerationPing() {
  if (!workspace.currentCode) {
    return;
  }
  pinging.value = true;
  pingError.value = "";
  pingResult.value = null;
  try {
    pingResult.value = await pingGeneration(workspace.currentCode);
  } catch (exc) {
    // 请求本身失败（403/网络）也不得渲染成成功
    pingError.value = exc instanceof Error ? exc.message : "连通性测试失败";
  } finally {
    pinging.value = false;
  }
}

// ---------- h) 可见性与加入码（workspace-configuration-design §14，page-specs §19.5） ----------
const joinCode = ref<WorkspaceJoinCodeRecord | null>(null);
const joinCodeError = ref("");
const visibilityConfirmOpen = ref(false);
const savingVisibility = ref(false);
const rotateConfirmOpen = ref(false);
const savingJoinCode = ref(false);
const copyFeedback = ref("");
const joinCodeForm = reactive({
  defaultRole: "viewer" as "viewer" | "member",
  expiresInDays: "",
  maxUses: ""
});

const currentVisibility = computed(() => workspace.current?.visibility ?? "private");

async function loadJoinCode() {
  if (!workspace.currentCode) {
    return;
  }
  joinCodeError.value = "";
  try {
    joinCode.value = await fetchWorkspaceJoinCode(workspace.currentCode);
  } catch (exc) {
    joinCode.value = null;
    joinCodeError.value = exc instanceof Error ? exc.message : "加载加入码失败";
  }
}

// 切到 internal_public 前必须确认「任何登录用户可发现并以 viewer 订阅」影响提示
function requestVisibilityToggle() {
  if (currentVisibility.value === "internal_public") {
    void applyVisibility("private");
    return;
  }
  visibilityConfirmOpen.value = true;
}

async function confirmVisibilityPublic() {
  visibilityConfirmOpen.value = false;
  await applyVisibility("internal_public");
}

async function applyVisibility(next: "private" | "internal_public") {
  if (!workspace.currentCode) {
    return;
  }
  savingVisibility.value = true;
  joinCodeError.value = "";
  message.value = "";
  try {
    await updateWorkspaceVisibility(workspace.currentCode, next);
    await workspace.loadWorkspaces();
    message.value =
      next === "internal_public"
        ? "已切换为组织内公开：任何登录用户可发现并以 viewer 订阅本工作台"
        : "已切换为私有：仅成员可见，凭加入码或管理员添加加入";
  } catch (exc) {
    joinCodeError.value = exc instanceof Error ? exc.message : "切换可见性失败";
  } finally {
    savingVisibility.value = false;
  }
}

function joinCodeCreatePayload() {
  return {
    default_role: joinCodeForm.defaultRole,
    expires_in_days: joinCodeForm.expiresInDays === "" ? null : Number(joinCodeForm.expiresInDays),
    max_uses: joinCodeForm.maxUses === "" ? null : Number(joinCodeForm.maxUses)
  };
}

// 生成（无 active 码）直接调；轮换（已有 active 码）必须先确认「旧码立即失效」
function requestJoinCodeCreate() {
  if (joinCode.value) {
    rotateConfirmOpen.value = true;
    return;
  }
  void createJoinCode();
}

async function confirmRotateJoinCode() {
  rotateConfirmOpen.value = false;
  await createJoinCode();
}

async function createJoinCode() {
  if (!workspace.currentCode) {
    return;
  }
  savingJoinCode.value = true;
  joinCodeError.value = "";
  message.value = "";
  copyFeedback.value = "";
  try {
    const rotated = Boolean(joinCode.value);
    joinCode.value = await createWorkspaceJoinCode(workspace.currentCode, joinCodeCreatePayload());
    message.value = rotated
      ? `已轮换加入码：旧码立即失效，新码 ${joinCode.value.code}`
      : `已生成加入码：${joinCode.value.code}`;
  } catch (exc) {
    joinCodeError.value = exc instanceof Error ? exc.message : "生成加入码失败";
  } finally {
    savingJoinCode.value = false;
  }
}

async function disableJoinCode() {
  if (!workspace.currentCode) {
    return;
  }
  savingJoinCode.value = true;
  joinCodeError.value = "";
  message.value = "";
  copyFeedback.value = "";
  try {
    await disableWorkspaceJoinCode(workspace.currentCode);
    joinCode.value = null;
    message.value = "已停用加入码：现有码即刻失效";
  } catch (exc) {
    joinCodeError.value = exc instanceof Error ? exc.message : "停用加入码失败";
  } finally {
    savingJoinCode.value = false;
  }
}

async function copyJoinCode() {
  if (!joinCode.value) {
    return;
  }
  copyFeedback.value = "";
  try {
    await navigator.clipboard.writeText(joinCode.value.code);
    copyFeedback.value = "已复制加入码";
  } catch (exc) {
    // 复制失败显示真实错误（page-specs §19.5.4），不显示假成功
    joinCodeError.value = exc instanceof Error ? `复制失败：${exc.message}` : "复制失败";
  }
}

function formatExpiresAt(value: string | null) {
  if (!value) {
    return "长期有效";
  }
  return `${value.slice(0, 16).replace("T", " ")} 到期`;
}

// ---------- 加载调度 ----------
let loadedForCode = "";

async function loadAll() {
  if (!workspace.currentCode || !canManage.value) {
    return;
  }
  loadedForCode = workspace.currentCode;
  error.value = "";
  fillBasicsForm();
  try {
    await Promise.all([
      loadMembers(),
      loadWorkspacePolicy(),
      loadReportSettings(),
      loadManageSections(),
      // 新三卡各自持有 card 级错误态：单卡后端不可用不拖垮整页
      loadSchedulePolicy(),
      loadGenerationPolicy(),
      loadJoinCode()
    ]);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载工作台配置失败";
  }
}

watch(
  () => [workspace.currentCode, canManage.value] as const,
  ([code, allowed]) => {
    if (code && allowed && loadedForCode !== code) {
      void loadAll();
    }
  },
  { immediate: true }
);

onMounted(() => {
  const hash = typeof window !== "undefined" ? window.location.hash : "";
  if (hash) {
    document.getElementById(hash.slice(1))?.scrollIntoView?.({ block: "start" });
  }
});
</script>

<template>
  <section class="module-page workspace-settings-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Workspace Settings</p>
        <h2><Settings :size="22" /> 工作台配置</h2>
        <p>{{ workspace.current?.name || "工作台" }} 的基本信息、成员、标签策略、报告设置与导航分区。</p>
      </div>
      <nav v-if="canManage" class="settings-anchor-nav" aria-label="配置分区导航">
        <a href="#basics">基本信息</a>
        <a href="#members">成员与角色</a>
        <a href="#labels">标签策略</a>
        <a href="#reports">报告设置</a>
        <a href="#nav-sections">导航分区</a>
        <a href="#automation">自动化</a>
        <a href="#generation">生成模型</a>
        <a href="#visibility">可见性与加入码</a>
      </nav>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section v-if="!canManage" class="module-card compact settings-denied">
      <h3>需要工作台管理员权限</h3>
      <p class="empty-state">
        工作台配置中心仅对当前工作台的 admin / owner 开放。如需调整标签策略、
        报告设置或成员角色，请联系工作台管理员。
      </p>
    </section>

    <template v-else>
      <!-- a) 基本信息 -->
      <section id="basics" class="module-card compact settings-card" aria-label="基本信息">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Basics</p>
            <h3><Building2 :size="18" /> 基本信息</h3>
          </div>
          <span class="metric-pill">{{ workspace.currentCode }}</span>
        </div>
        <div class="config-grid">
          <label>
            <span>名称</span>
            <input v-model="basicsForm.name" placeholder="工作台名称" />
          </label>
          <label>
            <span>默认主题域（domain pack）</span>
            <input v-model="basicsForm.defaultDomainCode" placeholder="ai / hardware / policy" />
          </label>
          <label class="config-grid-wide">
            <span>描述</span>
            <input v-model="basicsForm.description" placeholder="这个工作台负责什么" />
          </label>
        </div>
        <div class="settings-card-actions">
          <button type="button" class="config-save" :disabled="savingBasics" @click="saveBasics">
            {{ savingBasics ? "保存中" : "保存基本信息" }}
          </button>
        </div>
      </section>

      <!-- b) 成员与角色 -->
      <section id="members" class="module-card compact settings-card" aria-label="成员与角色">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Members</p>
            <h3><Users :size="18" /> 成员与角色</h3>
          </div>
          <span class="metric-pill">{{ members.length }} 位成员</span>
        </div>
        <p class="workspace-form-hint">
          这里维护当前工作台的成员角色（viewer / member / admin / owner）；
          邀请新用户与全局角色管理在
          <RouterLink to="/users">用户权限</RouterLink> 页完成。
        </p>
        <div class="settings-member-list">
          <div v-for="member in members" :key="member.user.id" class="settings-member-row">
            <span class="settings-member-copy">
              <strong>{{ member.user.display_name }}</strong>
              <small>{{ member.user.username }}{{ member.user.department ? ` · ${member.user.department}` : "" }}</small>
            </span>
            <select
              v-model="memberRoleDrafts[member.user.id]"
              :aria-label="`成员角色：${member.user.display_name}`"
            >
              <option value="viewer">viewer</option>
              <option value="member">member</option>
              <option value="admin">admin</option>
              <option value="owner">owner</option>
            </select>
            <button
              type="button"
              class="table-action"
              :disabled="savingMemberId === member.user.id || memberRoleDrafts[member.user.id] === member.workspace_role"
              @click="saveMemberRole(member)"
            >
              保存
            </button>
            <button
              type="button"
              class="table-action danger"
              :disabled="savingMemberId === member.user.id"
              title="移出工作台"
              @click="removeMember(member)"
            >
              <Trash2 :size="14" />
              <span>移出</span>
            </button>
          </div>
          <p v-if="members.length === 0" class="empty-state">暂无成员数据，请到用户权限页邀请成员或在下方按用户组批量加入。</p>
        </div>
      </section>

      <!-- c) 标签策略（自数据源管理页迁入） -->
      <section id="labels" class="policy-panel settings-card" aria-label="标签策略设置">
        <header class="policy-header">
          <div>
            <p class="policy-kicker">
              <Tag :size="16" />
              <span>标签策略设置</span>
            </p>
            <h3>{{ policyForm.labelSetCode }}</h3>
            <p>配置用于模型分类与去重后定稿的工作台标签，作用于候选池与日报出稿。</p>
          </div>
          <div class="policy-stats">
            <span>{{ activePrimaryCategories.length }} 一级</span>
            <span>{{ secondaryLabelTotal }} 二级</span>
          </div>
        </header>

        <div class="label-policy-grid">
          <div class="policy-tabs" role="tablist" aria-label="标签策略配置">
            <button
              type="button"
              :class="{ active: activePolicyTab === 'level1' }"
              @click="activePolicyTab = 'level1'"
            >
              一级标签 {{ activePrimaryCategories.length }}
            </button>
            <button
              type="button"
              :class="{ active: activePolicyTab === 'level2' }"
              @click="activePolicyTab = 'level2'"
            >
              二级标签 {{ secondaryLabelTotal }}
            </button>
            <button
              type="button"
              :class="{ active: activePolicyTab === 'format' }"
              @click="activePolicyTab = 'format'"
            >
              新闻结构
            </button>
          </div>

          <section v-if="activePolicyTab === 'level1'" class="policy-tab-panel">
            <div class="label-section-title">
              <span>一级标签</span>
              <small>用于模型分类与去重后定稿</small>
            </div>
            <div class="tag-cloud editable">
              <label
                v-for="(category, index) in policyForm.allowedPrimaryCategories"
                :key="`${category}-${index}`"
                class="tag-chip-edit"
              >
                <input
                  :value="category"
                  :style="{ width: tagInputWidth(category) }"
                  @input="renamePolicyCategory(index, ($event.target as HTMLInputElement).value)"
                  aria-label="一级标签名称"
                />
                <button
                  type="button"
                  :disabled="policyForm.allowedPrimaryCategories.length <= 1"
                  @click="removePolicyCategory(index)"
                  title="删除一级标签"
                >
                  <Trash2 :size="13" />
                </button>
              </label>
            </div>
            <div class="quick-add-card">
              <label>
                <span>新增一级标签</span>
                <div class="inline-control">
                  <input v-model="categoryDraft" placeholder="输入标签名称" @keydown.enter.prevent="addPolicyCategory" />
                  <button type="button" class="mini-icon-button add" @click="addPolicyCategory" title="新增一级标签">
                    <Plus :size="16" />
                  </button>
                </div>
              </label>
            </div>
          </section>

          <section v-else-if="activePolicyTab === 'level2'" class="policy-tab-panel">
            <div class="label-section-title">
              <span>二级标签</span>
              <small>只显示已配置项</small>
            </div>
            <div v-if="secondaryLabelTotal > 0" class="secondary-groups">
              <div
                v-for="category in activePrimaryCategories"
                v-show="secondaryLabelsFor(category).length > 0"
                :key="category"
                class="secondary-group"
              >
                <strong>{{ category }}</strong>
                <div class="secondary-line">
                  <label
                    v-for="(label, labelIndex) in secondaryLabelsFor(category)"
                    :key="`${category}-${label}-${labelIndex}`"
                    class="secondary-pill"
                  >
                    <input
                      :value="label"
                      @input="renameSecondaryLabel(category, labelIndex, ($event.target as HTMLInputElement).value)"
                      aria-label="二级标签名称"
                    />
                    <button type="button" @click="removeSecondaryLabel(category, labelIndex)" title="删除二级标签">
                      <X :size="12" />
                    </button>
                  </label>
                </div>
              </div>
            </div>
            <div v-else class="empty-policy-card">
              <Tag :size="24" />
              <p>暂无二级标签</p>
            </div>
            <div class="quick-add-card">
              <label>
                <span>新增二级标签</span>
                <div class="inline-control stackable">
                  <select v-model="secondaryDraft.primary">
                    <option v-for="category in activePrimaryCategories" :key="category" :value="category">
                      {{ category }}
                    </option>
                  </select>
                  <input v-model="secondaryDraft.label" placeholder="输入二级标签名" @keydown.enter.prevent="addSecondaryLabel" />
                  <button type="button" class="mini-icon-button add" @click="addSecondaryLabel" title="新增二级标签">
                    <Plus :size="16" />
                  </button>
                </div>
              </label>
            </div>
          </section>

          <section v-else class="policy-tab-panel">
            <div class="label-section-title">
              <span>新闻结构</span>
              <small>生成稿与 SQL 导出字段</small>
            </div>
            <label class="format-code-field">
              <span>格式代码</span>
              <input v-model="policyForm.newsFormatCode" placeholder="company_sql_v1" />
            </label>
            <label class="format-code-field">
              <span>SQL category 模式</span>
              <select v-model="policyForm.exportCategoryMode">
                <option value="news_primary">跟随新闻一级标签（AI 十分类）</option>
              </select>
            </label>
            <div class="format-field-list">
              <label
                v-for="(field, index) in policyForm.requiredContentFields"
                :key="`${field}-${index}`"
                class="tag-chip-edit format-chip"
              >
                <input
                  :value="field"
                  @input="renameContentField(index, ($event.target as HTMLInputElement).value)"
                  aria-label="新闻内容字段"
                />
                <small>{{ contentFieldLabel(field) }}</small>
                <button type="button" @click="removeContentField(index)" title="删除新闻字段">
                  <Trash2 :size="13" />
                </button>
              </label>
            </div>
            <div class="quick-add-card">
              <label>
                <span>新增新闻字段</span>
                <div class="inline-control">
                  <input v-model="contentFieldDraft" placeholder="新增字段" @keydown.enter.prevent="addContentField" />
                  <button type="button" class="mini-icon-button add" @click="addContentField" title="新增新闻字段">
                    <Plus :size="16" />
                  </button>
                </div>
              </label>
            </div>
          </section>
        </div>

        <footer class="policy-footer">
          <div class="policy-selects">
            <label>
              <span>默认标签</span>
              <select v-model="policyForm.defaultCategory">
                <option v-for="category in activePrimaryCategories" :key="category" :value="category">
                  {{ category }}
                </option>
              </select>
            </label>
            <label>
              <span>兜底标签</span>
              <select v-model="policyForm.fallbackCategory">
                <option v-for="category in activePrimaryCategories" :key="category" :value="category">
                  {{ category }}
                </option>
              </select>
            </label>
          </div>

          <div class="policy-actions">
            <button type="button" class="ghost-button" @click="resetPolicyCategories">恢复默认</button>
            <button type="button" class="config-save" :disabled="savingPolicy" @click="saveWorkspacePolicy">
              {{ savingPolicy ? "保存中" : "保存策略" }}
            </button>
          </div>
        </footer>
      </section>

      <!-- d) 报告设置 -->
      <section id="reports" class="module-card compact settings-card" aria-label="报告设置">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Reports</p>
            <h3><FileText :size="18" /> 报告设置</h3>
          </div>
          <span class="metric-pill">{{ reportFormats.length }} 个格式</span>
        </div>

        <label class="switch-row settings-switch-row">
          <input
            type="checkbox"
            :checked="autoPublishDaily"
            :disabled="savingReportPolicy"
            aria-label="日报出稿后自动发布"
            @change="toggleAutoPublish"
          />
          <span>
            <strong>日报出稿后自动发布</strong>
            <small>开启后每日流水线出稿即发布（actor=system）；关闭回到人工发布工作流。</small>
          </span>
        </label>

        <div class="label-section-title">
          <span>报告格式</span>
          <small>同一份采信可产出多版成稿，要两个格式就配两个</small>
        </div>
        <div class="settings-format-list">
          <div v-for="format in reportFormats" :key="format.id" class="settings-format-row">
            <span class="settings-format-copy">
              <strong>{{ format.name }}</strong>
              <small>
                {{ format.format_code }} ·
                {{ format.group_by === "board" ? "按业务板块" : format.group_by === "category" ? "按一级标签" : "不分组" }}
                <template v-if="format.builtin"> · 内置</template>
                <template v-if="format.locked"> · 公司 SQL 口径锁定</template>
              </small>
            </span>
            <label class="switch-row">
              <input
                type="checkbox"
                :checked="format.enabled"
                :disabled="togglingFormatId === format.id"
                :aria-label="`启用报告格式：${format.name}`"
                @change="toggleReportFormat(format, $event)"
              />
              <span>{{ format.enabled ? "启用" : "停用" }}</span>
            </label>
            <button
              v-if="!format.builtin"
              type="button"
              class="table-action danger"
              :disabled="togglingFormatId === format.id"
              title="删除自定义格式"
              @click="removeReportFormat(format)"
            >
              <Trash2 :size="14" />
              <span>删除</span>
            </button>
          </div>
          <p v-if="reportFormats.length === 0" class="empty-state">暂无报告格式，刷新后会注册内置格式。</p>
        </div>

        <div class="settings-card-actions">
          <button type="button" class="icon-button secondary" @click="showFormatForm = !showFormatForm">
            <Plus :size="16" />
            <span>{{ showFormatForm ? "收起表单" : "新增自定义格式" }}</span>
          </button>
        </div>

        <div v-if="showFormatForm" class="settings-format-form">
          <div class="config-grid">
            <label>
              <span>格式代码（英文小写）</span>
              <input v-model="formatForm.formatCode" placeholder="例如 exec_brief_v1" />
            </label>
            <label>
              <span>名称</span>
              <input v-model="formatForm.name" placeholder="例如 高管简报版" />
            </label>
            <label>
              <span>分组方式</span>
              <select v-model="formatForm.groupBy">
                <option value="board">按业务板块</option>
                <option value="category">按一级标签</option>
                <option value="none">不分组</option>
              </select>
            </label>
            <label>
              <span>头条自动 Top N（0 关闭头条区）</span>
              <input v-model.number="formatForm.headlineAutoTopN" type="number" min="0" max="20" />
            </label>
            <label class="config-grid-wide">
              <span>描述</span>
              <input v-model="formatForm.description" placeholder="这一版给谁看、什么口径" />
            </label>
          </div>
          <div class="settings-checkbox-line" role="group" aria-label="条目字段">
            <span class="settings-checkbox-label">条目字段</span>
            <label v-for="option in reportFormatFieldOptions" :key="option.value" class="settings-checkbox">
              <input
                type="checkbox"
                :checked="formatForm.itemFields.includes(option.value)"
                @change="toggleFormatField(option.value, $event)"
              />
              <span>{{ option.label }}</span>
            </label>
          </div>
          <div class="settings-checkbox-line" role="group" aria-label="导出目标">
            <span class="settings-checkbox-label">导出目标</span>
            <label class="settings-checkbox">
              <input v-model="formatForm.exportMd" type="checkbox" />
              <span>Markdown</span>
            </label>
            <label class="settings-checkbox">
              <input v-model="formatForm.exportHtml" type="checkbox" />
              <span>HTML</span>
            </label>
          </div>
          <div class="settings-card-actions">
            <button type="button" class="config-save" :disabled="creatingFormat" @click="submitReportFormat">
              {{ creatingFormat ? "创建中" : "创建报告格式" }}
            </button>
          </div>
        </div>
      </section>

      <!-- e) 导航分区 -->
      <section id="nav-sections" class="module-card compact settings-card" aria-label="导航分区">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Sections</p>
            <h3><LayoutGrid :size="18" /> 导航分区</h3>
          </div>
          <span class="metric-pill">{{ manageSections.length }} 个分区</span>
        </div>
        <p class="workspace-form-hint">
          可选模块可自由启停；核心分区承载主链路导航，不能停用。
        </p>
        <div class="settings-section-list">
          <div v-for="section in manageSections" :key="section.section_key" class="settings-section-row">
            <span class="settings-section-copy">
              <strong>{{ section.name }}</strong>
              <small>{{ section.section_key }}<template v-if="section.core"> · 核心分区</template></small>
            </span>
            <label class="switch-row" :title="section.core ? '核心分区不可停用' : ''">
              <input
                type="checkbox"
                :checked="section.enabled"
                :disabled="section.core || togglingSectionKey === section.section_key"
                :aria-label="`启用分区：${section.name}`"
                @change="toggleSection(section, $event)"
              />
              <span>{{ section.enabled ? "启用" : "停用" }}</span>
            </label>
          </div>
          <p v-if="manageSections.length === 0" class="empty-state">暂无分区数据，请先选择工作台或刷新页面重新加载分区注册表。</p>
        </div>
      </section>

      <!-- f) 自动化（schedule_policy，pipeline-jobs-design §8.2/§8.4） -->
      <section id="automation" class="module-card compact settings-card" aria-label="自动化">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Automation</p>
            <h3><Clock :size="18" /> 自动化</h3>
          </div>
          <span
            v-if="schedulePolicy"
            class="metric-pill"
            :data-tone="schedulePolicy.resolved.effective_enabled ? 'ok' : 'warn'"
          >
            {{ schedulePolicy.resolved.effective_enabled ? "自动调度中" : "未自动调度" }}
          </span>
        </div>
        <p class="workspace-form-hint">
          每天固定时刻自动跑抓取→去重→推荐→日报流水线；字段留空即跟随实例默认，改动下一个
          60 秒 tick 生效，无需重启。
        </p>
        <p v-if="scheduleError" class="form-error">{{ scheduleError }}</p>
        <p v-if="scheduleReadOnlyReason" class="form-info schedule-readonly-reason">{{ scheduleReadOnlyReason }}</p>

        <template v-if="schedulePolicy">
          <div class="schedule-resolved-line">
            <span class="metric-pill">下次运行：{{ formatRunAt(schedulePolicy.resolved.next_run_at) }}</span>
            <span class="metric-pill">时区 {{ schedulePolicy.instance.timezone }}</span>
            <span class="metric-pill">
              生效来源：{{ schedulePolicy.resolved.policy_source === "workspace" ? "本工作台策略" : "实例默认" }}
            </span>
          </div>
          <div class="config-grid">
            <label>
              <span>自动调度</span>
              <select v-model="scheduleForm.enabled" :disabled="scheduleReadOnly" aria-label="自动调度开关">
                <option value="follow">跟随实例总闸</option>
                <option value="on">开启（总闸开时生效）</option>
                <option value="off">退出自动调度</option>
              </select>
              <small>{{ enabledSourceLabel }}</small>
            </label>
            <label>
              <span>每日触发时刻（HH:MM，留空跟随实例）</span>
              <input
                v-model="scheduleForm.dailyTime"
                :disabled="scheduleReadOnly"
                placeholder="例如 09:30"
                aria-label="每日触发时刻"
              />
              <small>{{ dailyTimeSourceLabel }}</small>
            </label>
            <label>
              <span>目标日偏移（0=当天，-1=昨天）</span>
              <select v-model="scheduleForm.dayOffset" :disabled="scheduleReadOnly" aria-label="目标日偏移">
                <option value="">跟随实例默认</option>
                <option v-for="offset in [0, -1, -2, -3, -4, -5, -6, -7]" :key="offset" :value="String(offset)">
                  {{ offset }} 天
                </option>
              </select>
              <small>{{ dayOffsetSourceLabel }}</small>
            </label>
            <label>
              <span>run 失败自动重试次数（0-5）</span>
              <input
                v-model.number="scheduleForm.retryMaxAttempts"
                type="number"
                min="0"
                max="5"
                :disabled="scheduleReadOnly"
                aria-label="run 失败自动重试次数"
              />
            </label>
            <label>
              <span>首次退避间隔（秒，60-21600，指数翻倍）</span>
              <input
                v-model.number="scheduleForm.retryBackoffSeconds"
                type="number"
                min="60"
                max="21600"
                :disabled="scheduleReadOnly"
                aria-label="重试退避秒数"
              />
            </label>
          </div>

          <label class="switch-row settings-switch-row">
            <input
              v-model="scheduleForm.weeklyEnabled"
              type="checkbox"
              :disabled="scheduleReadOnly"
              aria-label="周报草稿自动组稿"
            />
            <span>
              <strong>周报草稿自动组稿</strong>
              <small>到点从最近 7 天已发布日报的采信条目刷新本周周报草稿；发布仍是编辑决策。</small>
            </span>
          </label>
          <div v-if="scheduleForm.weeklyEnabled" class="config-grid">
            <label>
              <span>组稿触发日（ISO 星期，1=周一）</span>
              <select v-model.number="scheduleForm.weeklyDay" :disabled="scheduleReadOnly" aria-label="周报组稿触发日">
                <option v-for="day in [1, 2, 3, 4, 5, 6, 7]" :key="day" :value="day">周{{ ["一", "二", "三", "四", "五", "六", "日"][day - 1] }}</option>
              </select>
            </label>
            <label>
              <span>组稿触发时刻（HH:MM）</span>
              <input v-model="scheduleForm.weeklyTime" :disabled="scheduleReadOnly" aria-label="周报组稿触发时刻" />
            </label>
          </div>

          <div class="settings-card-actions">
            <button
              type="button"
              class="config-save"
              :disabled="savingSchedule || scheduleReadOnly"
              @click="requestScheduleSave"
            >
              {{ savingSchedule ? "保存中" : "保存自动化策略" }}
            </button>
          </div>
        </template>
        <p v-else-if="!scheduleError" class="empty-state">正在加载自动化策略。</p>
      </section>

      <!-- g) 生成模型（generation_policy，generation-provider-design §5） -->
      <section id="generation" class="module-card compact settings-card" aria-label="生成模型">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Generation</p>
            <h3><Cpu :size="18" /> 生成模型</h3>
          </div>
          <span
            v-if="generationPolicy"
            class="metric-pill"
            :data-tone="generationPolicy.resolved.key_configured ? 'ok' : 'warn'"
          >
            key {{ generationPolicy.resolved.key_configured ? "已配置" : "未配置" }}
          </span>
        </div>
        <p v-if="generationError" class="form-error">{{ generationError }}</p>

        <template v-if="generationPolicy">
          <div class="schedule-resolved-line generation-status-line">
            <span class="metric-pill">provider：{{ generationPolicy.resolved.provider }}</span>
            <span class="metric-pill">生效模型：{{ generationPolicy.resolved.model }}</span>
            <span class="metric-pill">{{ generationPolicy.resolved.base_url_host }}</span>
            <span class="metric-pill" :data-tone="generationPolicy.resolved.enabled ? 'ok' : 'warn'">
              {{ generationPolicy.resolved.enabled ? "生成已启用" : "生成未启用" }}
            </span>
          </div>
          <p v-if="!generationPolicy.resolved.key_configured" class="form-info generation-key-hint">
            实例尚未配置生成 API key：由运维在部署 env 配置 GENERATION_API_KEY（或兼容的
            MINIMAX_API_KEY），配置方法见 docs/deployment/development-quickstart.md §2.2。
            key 只存部署环境，不进本页面、数据库或审计。
          </p>

          <div class="config-grid">
            <label>
              <span>模型名（留空跟随实例）</span>
              <input v-model="generationForm.model" placeholder="例如 MiniMax-M2.5" aria-label="生成模型名" />
            </label>
            <label>
              <span>温度（0-2，留空跟随实例）</span>
              <input
                v-model="generationForm.temperature"
                type="number"
                step="0.1"
                min="0"
                max="2"
                aria-label="生成温度"
              />
            </label>
            <label>
              <span>单条超时（5-300 秒，留空跟随实例）</span>
              <input
                v-model="generationForm.timeoutSeconds"
                type="number"
                min="5"
                max="300"
                aria-label="生成超时秒数"
              />
            </label>
            <label>
              <span>每日预算（条数上限，留空不限）</span>
              <input
                v-model="generationForm.dailyBudget"
                type="number"
                min="1"
                max="1000"
                aria-label="每日生成预算"
              />
            </label>
            <label>
              <span>降级行为</span>
              <select v-model="generationForm.fallbackBehavior" aria-label="生成降级行为">
                <option value="rule_fallback">规则降级稿（fallback_needs_review，不进公司 SQL）</option>
                <option value="fail">直接失败，留待重跑</option>
              </select>
            </label>
          </div>

          <div class="settings-card-actions">
            <button
              v-if="canPingGeneration"
              type="button"
              class="icon-button secondary"
              :disabled="pinging"
              @click="runGenerationPing"
            >
              <RefreshCw :size="14" />
              <span>{{ pinging ? "测试中" : "测试连通" }}</span>
            </button>
            <button
              type="button"
              class="config-save"
              :disabled="savingGeneration"
              @click="saveGenerationPolicy"
            >
              {{ savingGeneration ? "保存中" : "保存生成模型策略" }}
            </button>
          </div>
          <p v-if="pingError" class="form-error generation-ping-result">{{ pingError }}</p>
          <p
            v-else-if="pingResult"
            class="generation-ping-result"
            :class="pingResult.status === 'ok' ? 'form-success' : 'form-error'"
          >
            <template v-if="pingResult.status === 'ok'">
              连通正常：{{ pingResult.provider }} · {{ pingResult.model }} · {{ pingResult.latency_ms }}ms
            </template>
            <template v-else>
              连通失败（{{ pingResult.error_code || "unknown" }}）：{{ pingResult.error_message || "provider 无响应" }}
            </template>
          </p>
        </template>
        <p v-else-if="!generationError" class="empty-state">正在加载生成模型配置。</p>
      </section>

      <!-- h) 可见性与加入码（workspace-configuration-design §14，page-specs §19.5） -->
      <section id="visibility" class="module-card compact settings-card" aria-label="可见性与加入码">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Visibility &amp; Join Code</p>
            <h3><KeyRound :size="18" /> 可见性与加入码</h3>
          </div>
          <span class="metric-pill" :data-tone="currentVisibility === 'internal_public' ? 'warn' : 'ok'">
            {{ currentVisibility === "internal_public" ? "组织内公开" : "私有" }}
          </span>
        </div>
        <p v-if="joinCodeError" class="form-error">{{ joinCodeError }}</p>

        <label class="switch-row settings-switch-row">
          <input
            type="checkbox"
            :checked="currentVisibility === 'internal_public'"
            :disabled="savingVisibility"
            aria-label="组织内公开"
            @click.prevent="requestVisibilityToggle"
          />
          <span>
            <strong>组织内公开（internal_public）</strong>
            <small>开启后任何登录用户可在「发现工作台」看到本台并以 viewer 订阅；私有工作台不出现在任何发现列表。</small>
          </span>
        </label>

        <div class="label-section-title">
          <span>工作台加入码</span>
          <small>已注册同事凭码可自助加入本工作台（含私有工作台），不建号、不改全局角色</small>
        </div>

        <template v-if="joinCode">
          <div class="join-code-row">
            <code class="join-code-value" aria-label="当前加入码">{{ joinCode.code }}</code>
            <button type="button" class="icon-button secondary" @click="copyJoinCode">
              <Copy :size="14" />
              <span>复制</span>
            </button>
            <span v-if="copyFeedback" class="form-success join-code-copy-feedback">{{ copyFeedback }}</span>
          </div>
          <p class="workspace-form-hint">
            默认角色 {{ joinCode.default_role }} · {{ formatExpiresAt(joinCode.expires_at) }} ·
            已用 {{ joinCode.use_count }}{{ joinCode.max_uses !== null ? ` / 上限 ${joinCode.max_uses}` : "（不限次数）" }}
          </p>
        </template>
        <p v-else class="workspace-form-hint">
          当前没有有效加入码。生成后把 8 位码发给已注册同事，即可自助加入本工作台。
        </p>

        <div class="config-grid">
          <label>
            <span>默认角色</span>
            <select v-model="joinCodeForm.defaultRole" aria-label="加入码默认角色">
              <option value="viewer">viewer（只读）</option>
              <option value="member">member（可编辑）</option>
            </select>
          </label>
          <label>
            <span>有效期（天，留空长期有效）</span>
            <input v-model="joinCodeForm.expiresInDays" type="number" min="1" max="365" aria-label="加入码有效期天数" />
          </label>
          <label>
            <span>使用次数上限（留空不限）</span>
            <input v-model="joinCodeForm.maxUses" type="number" min="1" aria-label="加入码使用次数上限" />
          </label>
        </div>
        <div class="settings-card-actions">
          <button
            v-if="joinCode"
            type="button"
            class="table-action danger"
            :disabled="savingJoinCode"
            @click="disableJoinCode"
          >
            停用加入码
          </button>
          <button type="button" class="config-save" :disabled="savingJoinCode" @click="requestJoinCodeCreate">
            {{ savingJoinCode ? "处理中" : joinCode ? "轮换加入码" : "生成加入码" }}
          </button>
        </div>
      </section>
    </template>

    <!-- 确认弹层（AppModal sm，产品设计 §10.3：新增确认交互一律 Modal sm） -->
    <AppModal
      :open="scheduleConfirmOpen"
      size="sm"
      title="确认保存自动化策略？"
      @close="scheduleConfirmOpen = false"
    >
      <p class="workspace-form-hint">
        保存后下一个调度 tick 即按新策略触发：{{ scheduleForm.enabled === "off" ? "本工作台将退出自动调度。" : `每日
        ${scheduleForm.dailyTime || schedulePolicy?.instance.daily_time || "实例默认时刻"} 自动跑流水线。` }}
        改动会写入审计（workspace.schedule_policy.update）。
      </p>
      <template #footer>
        <button type="button" class="icon-button secondary" @click="scheduleConfirmOpen = false">取消</button>
        <button type="button" class="icon-button" @click="confirmScheduleSave">确认保存</button>
      </template>
    </AppModal>

    <AppModal
      :open="visibilityConfirmOpen"
      size="sm"
      title="切换为组织内公开？"
      @close="visibilityConfirmOpen = false"
    >
      <p class="workspace-form-hint">
        切换后任何登录用户可发现本工作台，并可自助以 viewer 身份订阅阅读已发布内容；
        游客入口开启时游客也可只读浏览。确认要公开吗？
      </p>
      <template #footer>
        <button type="button" class="icon-button secondary" @click="visibilityConfirmOpen = false">取消</button>
        <button type="button" class="icon-button" @click="confirmVisibilityPublic">确认公开</button>
      </template>
    </AppModal>

    <AppModal
      :open="rotateConfirmOpen"
      size="sm"
      title="轮换加入码？"
      @close="rotateConfirmOpen = false"
    >
      <p class="workspace-form-hint">
        轮换会生成新码并使旧码立即失效：已发出的旧码将不能再加入。确认轮换吗？
      </p>
      <template #footer>
        <button type="button" class="icon-button secondary" @click="rotateConfirmOpen = false">取消</button>
        <button type="button" class="icon-button" @click="confirmRotateJoinCode">确认轮换</button>
      </template>
    </AppModal>
  </section>
</template>

<style scoped>
/* WP3-H 新三卡的局部布线样式：表面材质仍沿用 base.css 的 module-card / metric-pill /
   config-grid（Liquid Glass 基线），这里只补新结构的排布，避免与并行 WP 抢 base.css。 */
.schedule-resolved-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 12px;
}

.schedule-readonly-reason,
.generation-key-hint {
  margin-top: 4px;
}

.config-grid label small {
  color: var(--text-muted, rgba(71, 85, 105, 0.9));
  font-size: 12px;
}

.generation-ping-result {
  margin-top: 8px;
}

.join-code-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin: 4px 0 8px;
}

.join-code-value {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.24em;
  padding: 6px 12px;
  border-radius: 10px;
  border: 1px solid rgba(100, 116, 139, 0.28);
  background: rgba(148, 163, 184, 0.12);
  user-select: all;
}

.join-code-copy-feedback {
  font-size: 12px;
}
</style>
