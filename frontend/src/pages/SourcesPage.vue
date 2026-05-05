<script setup lang="ts">
import { DownloadCloud, Plus, RefreshCw, Settings, Trash2, X } from "lucide-vue-next";
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

const policyForm = reactive({
  labelSetCode: "ai_sql_categories",
  allowedPrimaryCategories: [...legacyPrimaryCategories],
  defaultCategory: "AI 应用",
  fallbackCategory: "AI 应用"
});
const categoryDraft = ref("");

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
  policyForm.allowedPrimaryCategories = [...policy.allowed_primary_categories];
  policyForm.defaultCategory = policy.default_category;
  policyForm.fallbackCategory = policy.fallback_category;
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
  return source.enabled && source.workspace_link_enabled && ["rss", "paper_rss"].includes(source.source_type);
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

function addPolicyCategory() {
  const value = categoryDraft.value.trim();
  if (!value || policyForm.allowedPrimaryCategories.includes(value)) {
    categoryDraft.value = "";
    return;
  }
  policyForm.allowedPrimaryCategories.push(value);
  categoryDraft.value = "";
  syncPolicyFallbacks();
}

function renamePolicyCategory(index: number, value: string) {
  policyForm.allowedPrimaryCategories[index] = value;
  syncPolicyFallbacks();
}

function removePolicyCategory(index: number) {
  if (policyForm.allowedPrimaryCategories.length <= 1) {
    return;
  }
  policyForm.allowedPrimaryCategories.splice(index, 1);
  syncPolicyFallbacks();
}

function resetPolicyCategories() {
  policyForm.allowedPrimaryCategories = [...legacyPrimaryCategories];
  policyForm.defaultCategory = "AI 应用";
  policyForm.fallbackCategory = "AI 应用";
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
  syncPolicyFallbacks();
  savingPolicy.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const updated = await updateWorkspaceLabelPolicy(workspace.currentCode, {
      label_set_code: policyForm.labelSetCode,
      allowed_primary_categories: categories,
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
  <section class="toolbar-band">
    <div>
      <p class="eyebrow">阶段 3</p>
      <h2>数据源、标签配置与 RSS raw 入库</h2>
      <p>工作台统一标签策略约束模型生成新闻结构和去重后的标签定稿；数据源只管理接入和采集权重。</p>
    </div>
    <div class="toolbar-actions">
      <button type="button" class="icon-button" :disabled="loading" @click="loadSources" title="刷新">
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

  <section class="policy-panel">
    <div class="policy-copy">
      <p class="eyebrow">工作台统一标签策略</p>
      <h3>{{ workspace.current?.name }} · {{ policyForm.labelSetCode }}</h3>
      <p>模型在 raw 生成新闻结构时只能从这些一级标签里选；去重合并后会再次按同一套标签定稿。</p>
    </div>

    <div class="policy-controls">
      <div class="category-editor">
        <div v-for="(category, index) in policyForm.allowedPrimaryCategories" :key="`${category}-${index}`" class="category-edit">
          <input
            :value="category"
            @input="renamePolicyCategory(index, ($event.target as HTMLInputElement).value)"
            aria-label="一级标签名称"
          />
          <button
            type="button"
            class="mini-icon-button"
            :disabled="policyForm.allowedPrimaryCategories.length <= 1"
            @click="removePolicyCategory(index)"
            title="删除标签"
          >
            <Trash2 :size="14" />
          </button>
        </div>
        <div class="category-add">
          <input v-model="categoryDraft" placeholder="新增一级标签" @keydown.enter.prevent="addPolicyCategory" />
          <button type="button" class="mini-icon-button add" @click="addPolicyCategory" title="新增标签">
            <Plus :size="16" />
          </button>
          <button type="button" class="ghost-button" @click="resetPolicyCategories">恢复默认</button>
        </div>
      </div>

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
        <button type="button" class="config-save" :disabled="savingPolicy" @click="saveWorkspacePolicy">
          {{ savingPolicy ? "保存中" : "保存工作台策略" }}
        </button>
      </div>
    </div>
  </section>

  <section class="summary-strip">
    <div>
      <span>当前工作台</span>
      <strong>{{ workspace.current?.name }}</strong>
    </div>
    <div>
      <span>共享源</span>
      <strong>{{ sources.length }}</strong>
    </div>
    <div>
      <span>当前工作台启用</span>
      <strong>{{ enabledInWorkspaceCount }}</strong>
    </div>
    <div v-for="[type, count] in counts" :key="type">
      <span>{{ sourceTypeLabel(type) }}</span>
      <strong>{{ count }}</strong>
    </div>
  </section>

  <section class="source-workbench" :class="{ 'has-panel': selectedSource }">
    <div class="source-list">
      <div class="source-list-head">
        <span>数据源</span>
        <span>类型</span>
        <span>状态</span>
        <span>操作</span>
      </div>

      <article
        v-for="source in sources"
        :key="source.id"
        class="source-row"
        :class="{ inactive: !source.workspace_link_enabled }"
      >
        <div class="source-main">
          <strong>{{ source.name }}</strong>
          <a v-if="source.url" :href="source.url" target="_blank" rel="noreferrer">{{ source.url }}</a>
          <span v-else>无公开 URL</span>
        </div>

        <div class="source-cell">
          <strong>{{ sourceTypeLabel(source.source_type) }}</strong>
          <span>{{ source.domain_code }}</span>
          <span>{{ source.info_category || source.primary_category || "" }}</span>
        </div>

        <div class="source-cell">
          <strong>{{ source.workspace_link_enabled ? "当前工作台启用" : "当前工作台停用" }}</strong>
          <span>{{ source.last_success_at ? `最近成功 ${formatDateTime(source.last_success_at)}` : "暂无成功抓取" }}</span>
          <span v-if="source.last_error">{{ source.last_error }}</span>
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

      <p v-if="!loading && sources.length === 0" class="empty-state">暂无数据源，可先导入旧种子源。</p>
    </div>

    <aside v-if="selectedSource" class="config-panel">
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
        <span>当前工作台启用</span>
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
  </section>
</template>
