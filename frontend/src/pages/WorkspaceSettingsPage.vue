<script setup lang="ts">
import {
  Building2,
  FileText,
  LayoutGrid,
  Plus,
  Settings,
  Tag,
  Trash2,
  Users,
  X
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";

import {
  createReportFormat,
  deleteReportFormat,
  fetchReportFormats,
  updateReportFormat,
  type ReportFormatRecord
} from "../api/renditions";
import {
  fetchWorkspaceLabelPolicy,
  fetchWorkspaceMembers,
  fetchWorkspaceReportPolicy,
  fetchWorkspaceSectionsManage,
  removeWorkspaceMember,
  updateWorkspace,
  updateWorkspaceLabelPolicy,
  updateWorkspaceReportPolicy,
  updateWorkspaceSection,
  upsertWorkspaceMember,
  type WorkspaceLabelPolicy,
  type WorkspaceMemberRecord,
  type WorkspaceSectionManageRecord
} from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const session = useSessionStore();
const workspace = useWorkspaceStore();

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
      loadManageSections()
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
    </template>
  </section>
</template>
