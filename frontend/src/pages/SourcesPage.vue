<script setup lang="ts">
import { Bot, DownloadCloud, FileText, Globe2, Monitor, Plus, RefreshCw, Rss, Settings, Tag, Trash2, X } from "lucide-vue-next";
import { computed, reactive, ref, watch } from "vue";

import {
  fetchSource,
  fetchSources,
  importLegacySources,
  updateSourceWorkspaceConfig,
  type DataSourceRecord
} from "../api/sources";
import {
  fetchWorkspaceLabelPolicy,
  updateWorkspaceLabelPolicy,
  type WorkspaceLabelPolicy
} from "../api/workspaces";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const sources = ref<DataSourceRecord[]>([]);
const loading = ref(false);
const importing = ref(false);
const savingPolicy = ref(false);
const savingConfig = ref(false);
const fetchingSourceId = ref("");
const error = ref("");
const lastImportMessage = ref("");
const selectedSource = ref<DataSourceRecord | null>(null);
const activePolicyTab = ref<"level1" | "level2" | "format">("level1");

const legacyPrimaryCategories = [
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
  planning_intel: {
    labelSetCode: "ai_sql_categories",
    newsFormatCode: "company_sql_v1",
    requiredContentFields: [...companySqlContentFields],
    primaryCategories: legacyPrimaryCategories,
    secondaryLabelsByPrimary: {} as Record<string, string[]>,
    defaultCategory: "AI 应用",
    fallbackCategory: "AI 应用"
  },
  ai_tools: {
    labelSetCode: "ai_tools_categories",
    newsFormatCode: "tool_intel_v1",
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
  requiredContentFields: [...companySqlContentFields],
  allowedPrimaryCategories: [...legacyPrimaryCategories],
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

const configForm = reactive({
  enabled: true,
  sourceWeight: 1,
  dailyLimit: ""
});

const counts = computed(() => {
  const next = new Map<string, number>();
  for (const source of sources.value) {
    next.set(source.source_type, (next.get(source.source_type) ?? 0) + 1);
  }
  return Array.from(next.entries()).sort(([left], [right]) => left.localeCompare(right));
});

const enabledInWorkspaceCount = computed(
  () => sources.value.filter((source) => source.workspace_link_enabled).length
);

const activePrimaryCategories = computed(() =>
  policyForm.allowedPrimaryCategories.length > 0 ? policyForm.allowedPrimaryCategories : legacyPrimaryCategories
);
const secondaryLabelTotal = computed(() =>
  activePrimaryCategories.value.reduce(
    (total, category) => total + secondaryLabelsFor(category).length,
    0
  )
);

const currentPolicyPreset = computed(() => {
  if (workspace.currentCode === "ai_tools") {
    return workspacePolicyPresets.ai_tools;
  }
  return workspacePolicyPresets.planning_intel;
});

async function loadWorkspacePolicy() {
  if (!workspace.currentCode) {
    return;
  }
  try {
    const policy = await fetchWorkspaceLabelPolicy(workspace.currentCode);
    fillPolicyForm(policy);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载工作台标签策略失败";
  }
}

function fillPolicyForm(policy: WorkspaceLabelPolicy) {
  policyForm.labelSetCode = policy.label_set_code;
  policyForm.newsFormatCode = policy.news_format_code;
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

async function loadSources() {
  loading.value = true;
  error.value = "";
  try {
    const payload = await fetchSources(workspace.currentCode || undefined);
    sources.value = payload;
    if (selectedSource.value) {
      selectedSource.value = payload.find((source) => source.id === selectedSource.value?.id) ?? null;
      if (selectedSource.value) {
        fillConfigForm(selectedSource.value);
      }
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载数据源失败";
  } finally {
    loading.value = false;
  }
}

async function importSeeds() {
  importing.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const result = await importLegacySources();
    lastImportMessage.value = `导入完成：新增 ${result.created}，更新 ${result.updated}，总计 ${result.total}`;
    await loadSources();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导入旧种子源失败";
  } finally {
    importing.value = false;
  }
}

function canFetchSource(source: DataSourceRecord) {
  return (
    source.enabled &&
    source.workspace_link_enabled &&
    ["rss", "paper_rss", "page_manual", "page_monitor"].includes(source.source_type)
  );
}

function sourceTypeLabel(type: string) {
  const labels: Record<string, string> = {
    rss: "RSS",
    paper_rss: "论文 RSS",
    wiseflow: "Wiseflow",
    page_manual: "页面手工",
    page_monitor: "页面监控"
  };
  return labels[type] ?? type;
}

function sourceIcon(type: string) {
  const icons = {
    rss: Rss,
    paper_rss: FileText,
    wiseflow: Bot,
    page_manual: Globe2,
    page_monitor: Monitor
  };
  return icons[type as keyof typeof icons] ?? Globe2;
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function fillConfigForm(source: DataSourceRecord) {
  configForm.enabled = Boolean(source.workspace_link_enabled);
  configForm.sourceWeight = source.workspace_source_weight ?? 1;
  configForm.dailyLimit = source.workspace_daily_limit == null ? "" : String(source.workspace_daily_limit);
}

function openConfig(source: DataSourceRecord) {
  selectedSource.value = source;
  fillConfigForm(source);
}

function closeConfig() {
  selectedSource.value = null;
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
  lastImportMessage.value = "";
  try {
    const updated = await updateWorkspaceLabelPolicy(workspace.currentCode, {
      label_set_code: policyForm.labelSetCode,
      news_format_code: policyForm.newsFormatCode,
      required_content_fields: policyForm.requiredContentFields,
      allowed_primary_categories: categories,
      secondary_labels_by_primary: policyForm.secondaryLabelsByPrimary,
      default_category: policyForm.defaultCategory,
      fallback_category: policyForm.fallbackCategory
    });
    fillPolicyForm(updated);
    lastImportMessage.value = `已保存：${workspace.current?.name} 的统一标签策略`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存工作台标签策略失败";
  } finally {
    savingPolicy.value = false;
  }
}

async function saveConfig() {
  if (!selectedSource.value || !workspace.currentCode) {
    return;
  }
  const dailyLimit = configForm.dailyLimit.trim() === "" ? null : Number(configForm.dailyLimit);
  if (dailyLimit !== null && (Number.isNaN(dailyLimit) || dailyLimit < 0)) {
    error.value = "日限必须为空或非负数字";
    return;
  }
  const sourceWeight = Number(configForm.sourceWeight);
  if (Number.isNaN(sourceWeight) || sourceWeight < 0) {
    error.value = "权重必须是非负数字";
    return;
  }

  savingConfig.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const updated = await updateSourceWorkspaceConfig(selectedSource.value.id, {
      workspace_code: workspace.currentCode,
      enabled: configForm.enabled,
      source_weight: sourceWeight,
      daily_limit: dailyLimit
    });
    sources.value = sources.value.map((source) => (source.id === updated.id ? updated : source));
    selectedSource.value = updated;
    fillConfigForm(updated);
    lastImportMessage.value = `已保存：${updated.name} 的数据源配置`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存工作台配置失败";
  } finally {
    savingConfig.value = false;
  }
}

async function fetchOneSource(source: DataSourceRecord) {
  fetchingSourceId.value = source.id;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const result = await fetchSource(source.id);
    lastImportMessage.value = `抓取完成：${source.name}，拉取 ${result.fetched}，新增 ${result.created}，更新 ${result.updated}`;
    await loadSources();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "抓取数据源失败";
  } finally {
    fetchingSourceId.value = "";
  }
}

watch(
  () => workspace.currentCode,
  (code) => {
    if (code) {
      void loadWorkspacePolicy();
      void loadSources();
    }
  },
  { immediate: true }
);
</script>

<template>
  <section class="source-command">
    <div class="source-title">
      <p class="eyebrow">来源运营</p>
      <h2>数据源管理</h2>
    </div>
    <div class="source-metrics" aria-label="数据源概览">
      <span><b>{{ sources.length }}</b> 共享源</span>
      <span><b>{{ enabledInWorkspaceCount }}</b> 已启用</span>
      <span v-for="[type, count] in counts" :key="type"><b>{{ count }}</b> {{ sourceTypeLabel(type) }}</span>
    </div>
    <div class="toolbar-actions">
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadSources" title="刷新">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
      <button type="button" class="icon-button" :disabled="importing" @click="importSeeds" title="导入旧种子源">
        <DownloadCloud :size="18" />
        <span>{{ importing ? "导入中" : "导入旧源" }}</span>
      </button>
    </div>
  </section>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="lastImportMessage" class="form-success">{{ lastImportMessage }}</p>

  <section class="source-page-grid">
    <div class="source-list">
      <header class="source-list-title">
        <div>
          <p class="eyebrow">数据源池</p>
          <h3>活跃数据源</h3>
        </div>
        <span>{{ enabledInWorkspaceCount }} / {{ sources.length }} 已启用</span>
      </header>

      <div class="source-feed">
        <article
          v-for="source in sources"
          :key="source.id"
          class="source-row"
          :data-source-type="source.source_type"
          :class="{
            inactive: !source.workspace_link_enabled,
            selected: selectedSource?.id === source.id
          }"
        >
          <div class="source-icon">
            <component :is="sourceIcon(source.source_type)" :size="18" />
          </div>

          <div class="source-body">
            <div class="source-heading">
              <strong>{{ source.name }}</strong>
              <span :class="source.workspace_link_enabled ? 'status-on' : 'status-off'">
                {{ source.workspace_link_enabled ? "启用" : "停用" }}
              </span>
            </div>
            <a v-if="source.url" class="source-url" :href="source.url" target="_blank" rel="noreferrer">
              {{ source.url }}
            </a>
            <span v-else class="source-url">无公开 URL</span>

            <div class="source-meta-line">
              <span class="type-badge">{{ sourceTypeLabel(source.source_type) }}</span>
              <span class="meta-chip">{{ source.domain_code }}</span>
              <span v-if="source.info_category || source.primary_category" class="meta-chip">
                {{ source.info_category || source.primary_category }}
              </span>
              <span class="source-freshness">
                {{ source.last_success_at ? `最近成功 ${formatDateTime(source.last_success_at)}` : "暂无成功抓取" }}
              </span>
              <span v-if="source.last_error" class="source-error">{{ source.last_error }}</span>
            </div>
          </div>

          <div class="source-actions">
            <button type="button" class="table-action" @click="openConfig(source)" title="配置数据源">
              <Settings :size="14" />
              <span>配置</span>
            </button>
            <button
              v-if="canFetchSource(source)"
              type="button"
              class="table-action"
              :disabled="fetchingSourceId === source.id"
              @click="fetchOneSource(source)"
              title="抓取 RSS"
            >
              <RefreshCw :size="14" />
              <span>{{ fetchingSourceId === source.id ? "抓取中" : "抓取" }}</span>
            </button>
          </div>
        </article>
      </div>

      <p v-if="!loading && sources.length === 0" class="empty-state">暂无数据源，可先导入旧种子源。</p>
    </div>

    <aside class="control-rail">
      <section class="policy-panel">
        <header class="policy-header">
          <div>
            <p class="eyebrow">标签策略</p>
            <h3>{{ policyForm.labelSetCode }}</h3>
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

    </aside>
  </section>

  <div v-if="selectedSource" class="config-backdrop" @click="closeConfig"></div>
  <aside v-if="selectedSource" class="config-panel" aria-label="数据源配置">
    <header>
      <div>
        <p class="eyebrow">数据源配置</p>
        <h3>{{ selectedSource.name }}</h3>
      </div>
      <button type="button" class="panel-close" @click="closeConfig" title="关闭">
        <X :size="18" />
      </button>
    </header>

    <label class="switch-row">
      <input v-model="configForm.enabled" type="checkbox" />
      <span>启用</span>
    </label>

    <div class="config-grid">
      <label>
        <span>权重</span>
        <input v-model.number="configForm.sourceWeight" type="number" min="0" step="0.1" />
      </label>
      <label>
        <span>日报日限</span>
        <input v-model="configForm.dailyLimit" type="number" min="0" placeholder="不限" />
      </label>
    </div>

    <button type="button" class="config-save" :disabled="savingConfig" @click="saveConfig">
      {{ savingConfig ? "保存中" : "保存配置" }}
    </button>
  </aside>
</template>
