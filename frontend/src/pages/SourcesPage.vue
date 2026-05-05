<script setup lang="ts">
import { DownloadCloud, RefreshCw, Settings, X } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";

import {
  fetchSource,
  fetchSourceLabelOptions,
  fetchSources,
  importLegacySources,
  updateSourceWorkspaceConfig,
  type DataSourceRecord,
  type SourceLabelOptions
} from "../api/sources";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const sources = ref<DataSourceRecord[]>([]);
const labelOptions = ref<SourceLabelOptions>({
  label_set_codes: ["ai_sql_categories"],
  primary_categories: []
});
const loading = ref(false);
const importing = ref(false);
const savingConfig = ref(false);
const fetchingSourceId = ref("");
const error = ref("");
const lastImportMessage = ref("");
const selectedSource = ref<DataSourceRecord | null>(null);

const configForm = reactive({
  enabled: true,
  sourceWeight: 1,
  dailyLimit: "",
  labelSetCode: "ai_sql_categories",
  defaultLabelPaths: [] as string[]
});

const labelDraft = reactive({
  primary: "",
  secondary: ""
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

async function loadLabelOptions() {
  try {
    labelOptions.value = await fetchSourceLabelOptions();
    labelDraft.primary = labelOptions.value.primary_categories[0] ?? "";
  } catch {
    labelOptions.value = {
      label_set_codes: ["ai_sql_categories"],
      primary_categories: []
    };
  }
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

function labelSummary(source: DataSourceRecord) {
  if (source.workspace_default_label_paths.length > 0) {
    return source.workspace_default_label_paths.join(" / ");
  }
  return source.primary_category || source.info_category || "未配置一级/二级标签";
}

function fillConfigForm(source: DataSourceRecord) {
  configForm.enabled = Boolean(source.workspace_link_enabled);
  configForm.sourceWeight = source.workspace_source_weight ?? 1;
  configForm.dailyLimit = source.workspace_daily_limit == null ? "" : String(source.workspace_daily_limit);
  configForm.labelSetCode = source.workspace_label_set_codes[0] ?? labelOptions.value.label_set_codes[0] ?? "ai_sql_categories";
  configForm.defaultLabelPaths = [...source.workspace_default_label_paths];
  labelDraft.primary = labelOptions.value.primary_categories[0] ?? "";
  labelDraft.secondary = "";
}

function openConfig(source: DataSourceRecord) {
  selectedSource.value = source;
  fillConfigForm(source);
}

function closeConfig() {
  selectedSource.value = null;
}

function addLabelPath() {
  const primary = labelDraft.primary.trim();
  const secondary = labelDraft.secondary.trim();
  if (!primary) {
    return;
  }
  const path = secondary ? `${primary}/${secondary}` : primary;
  if (!configForm.defaultLabelPaths.includes(path)) {
    configForm.defaultLabelPaths.push(path);
  }
  labelDraft.secondary = "";
}

function removeLabelPath(path: string) {
  configForm.defaultLabelPaths = configForm.defaultLabelPaths.filter((item) => item !== path);
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
      daily_limit: dailyLimit,
      label_set_codes: [configForm.labelSetCode],
      default_label_paths: configForm.defaultLabelPaths,
      clustering_config: selectedSource.value.workspace_clustering_config
    });
    sources.value = sources.value.map((source) => (source.id === updated.id ? updated : source));
    selectedSource.value = updated;
    fillConfigForm(updated);
    lastImportMessage.value = `已保存：${updated.name} 的工作台标签配置`;
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

onMounted(() => {
  void loadLabelOptions();
});

watch(
  () => workspace.currentCode,
  (code) => {
    if (code) {
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
      <p>数据源先进入共享池，各工作台通过启用链接复用这些源；标签路径决定后续聚类、推荐和日报采信目录。</p>
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
        <span>工作台标签</span>
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
        </div>

        <div class="source-cell">
          <strong>{{ labelSummary(source) }}</strong>
          <span>{{ source.workspace_label_set_codes.join(" / ") || "ai_sql_categories" }}</span>
        </div>

        <div class="source-cell">
          <strong>{{ source.workspace_link_enabled ? "当前工作台启用" : "当前工作台停用" }}</strong>
          <span>{{ source.last_success_at ? `最近成功 ${formatDateTime(source.last_success_at)}` : "暂无成功抓取" }}</span>
          <span v-if="source.last_error">{{ source.last_error }}</span>
        </div>

        <div class="source-actions">
          <button type="button" class="table-action" @click="openConfig(source)" title="配置工作台标签">
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
          <p class="eyebrow">工作台配置</p>
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

      <label class="config-field">
        <span>标签集</span>
        <select v-model="configForm.labelSetCode">
          <option v-for="code in labelOptions.label_set_codes" :key="code" :value="code">
            {{ code }}
          </option>
        </select>
      </label>

      <div class="label-builder">
        <label>
          <span>一级标签</span>
          <select v-model="labelDraft.primary">
            <option v-for="category in labelOptions.primary_categories" :key="category" :value="category">
              {{ category }}
            </option>
          </select>
        </label>
        <label>
          <span>二级标签</span>
          <input v-model="labelDraft.secondary" placeholder="可选" />
        </label>
        <button type="button" class="table-action" @click="addLabelPath">添加</button>
      </div>

      <div class="tag-stack">
        <button
          v-for="path in configForm.defaultLabelPaths"
          :key="path"
          type="button"
          class="tag-chip"
          @click="removeLabelPath(path)"
          :title="`移除 ${path}`"
        >
          {{ path }}
          <X :size="12" />
        </button>
        <span v-if="configForm.defaultLabelPaths.length === 0">未配置默认一级/二级标签</span>
      </div>

      <button type="button" class="config-save" :disabled="savingConfig" @click="saveConfig">
        {{ savingConfig ? "保存中" : "保存配置" }}
      </button>
    </aside>
  </section>
</template>
