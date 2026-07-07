<script setup lang="ts">
import {
  Bot,
  CheckCircle2,
  DownloadCloud,
  FileText,
  Globe2,
  MessageCircle,
  Monitor,
  Plus,
  RefreshCw,
  Rss,
  Settings,
  X
} from "lucide-vue-next";
import { computed, reactive, ref, watch } from "vue";

import {
  createSource,
  fetchSource,
  fetchSources,
  importLegacySources,
  importTechInsightLoopSources,
  previewSourceImport,
  updateSourceDefinition,
  updateSourceWorkspaceConfig,
  type DataSourceRecord,
  type SourceImportPreview
} from "../api/sources";
import AppModal from "../components/AppModal.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const runtime = useRuntimeStore();
const sources = ref<DataSourceRecord[]>([]);
const loading = ref(false);
const importing = ref(false);
const savingConfig = ref(false);
const fetchingSourceId = ref("");
const error = ref("");
const lastImportMessage = ref("");
const lastImportTone = ref<"success" | "info" | "warning">("success");
const importPreview = ref<SourceImportPreview | null>(null);
const importPreviewCatalog = ref<"legacy" | "tech">("legacy");
const previewLoading = ref(false);
const selectedSource = ref<DataSourceRecord | null>(null);

const configForm = reactive({
  enabled: true,
  sourceWeight: 1,
  dailyLimit: ""
});

const definitionForm = reactive({
  name: "",
  url: "",
  backfillDays: "7"
});
const savingDefinition = ref(false);

const customSourceTypes = [
  { value: "rss", label: "RSS" },
  { value: "paper_rss", label: "论文 RSS" },
  { value: "paper_api", label: "论文 API" },
  { value: "page_manual", label: "页面手工" },
  { value: "page_monitor", label: "页面监控" }
];
const showCreatePanel = ref(false);
const creatingSource = ref(false);
const createForm = reactive({
  name: "",
  sourceType: "rss",
  url: "",
  domainCode: "",
  backfillDays: "7"
});

// 新增信息源 Modal 的脏状态（frontend-product-design §10.1）：与打开时的快照比对，
// 有未保存输入时遮罩/Esc/关闭按钮先弹 sm 确认层，不允许静默丢输入。
const createFormBaseline = ref("");

function createFormSnapshot() {
  return JSON.stringify({ ...createForm });
}

const createFormDirty = computed(
  () => showCreatePanel.value && createFormSnapshot() !== createFormBaseline.value
);

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

const canManageIngestion = computed(() => runtime.canIngest);
const createUrlPlaceholder = computed(() =>
  createForm.sourceType === "paper_api"
    ? "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=artificial%20intelligence"
    : "https://..."
);

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

const importMessageClass = computed(() => {
  if (lastImportTone.value === "info") {
    return "form-info";
  }
  if (lastImportTone.value === "warning") {
    return "form-warning";
  }
  return "form-success";
});

function setResultMessage(text: string, tone: "success" | "info" | "warning" = "success") {
  lastImportMessage.value = text;
  lastImportTone.value = tone;
}

async function openImportPreview(catalog: "legacy" | "tech") {
  if (!canManageIngestion.value) {
    setResultMessage("当前部署形态为只读消费模式，不能导入或抓取数据源。", "warning");
    return;
  }
  previewLoading.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    importPreviewCatalog.value = catalog;
    importPreview.value = await previewSourceImport(catalog);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载导入预览失败";
  } finally {
    previewLoading.value = false;
  }
}

function closeImportPreview() {
  importPreview.value = null;
}

function previewTypeNote(type: string) {
  if (type === "manual" || type === "internal") {
    return PUSH_BASED_HINT;
  }
  if (type === "wechat") {
    return "微信公众号源导入后保持待配置（metadata-only），需等待 RSSHub 公众号入口或 wechat 桥就绪后启用抓取";
  }
  return "";
}

// 导入预览样本按 source_type 分组小计：推入式/微信待配置类型附语义提示，
// 避免导入后把这些源的 0 条抓取误读为失败。
const importPreviewGroups = computed(() => {
  const preview = importPreview.value;
  if (!preview) {
    return [];
  }
  const groups = new Map<string, SourceImportPreview["samples"]>();
  for (const sample of preview.samples) {
    const list = groups.get(sample.source_type) ?? [];
    list.push(sample);
    groups.set(sample.source_type, list);
  }
  return Array.from(groups.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([type, samples]) => ({ type, samples, note: previewTypeNote(type) }));
});

async function confirmImport() {
  if (!importPreview.value || !canManageIngestion.value) {
    return;
  }
  const catalog = importPreviewCatalog.value;
  importPreview.value = null;
  if (catalog === "tech") {
    await importTechSources();
  } else {
    await importSeeds();
  }
}

async function importSeeds() {
  importing.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const result = await importLegacySources();
    if (result.total === 0) {
      setResultMessage("未发现可导入的旧种子源：请检查种子文件路径或部署挂载是否缺失。", "warning");
    } else if (result.created === 0) {
      setResultMessage(
        result.updated > 0
          ? `源已全部存在，本次更新 ${result.updated} 条元数据`
          : "源已全部存在，本次未发生变更",
        "info"
      );
    } else {
      setResultMessage(`导入完成：新增 ${result.created}，更新 ${result.updated}，总计 ${result.total}`);
    }
    await loadSources();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导入旧种子源失败";
  } finally {
    importing.value = false;
  }
}

async function importTechSources() {
  importing.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const result = await importTechInsightLoopSources();
    if (result.total === 0) {
      setResultMessage("未识别到 Tech 源数据：请检查种子文件路径或部署挂载是否缺失。", "warning");
    } else if (result.created === 0) {
      setResultMessage(
        result.updated > 0
          ? `源已全部存在，本次更新 ${result.updated} 条元数据（识别 ${result.total} 行）`
          : "源已全部存在，本次未发生变更",
        "info"
      );
    } else {
      setResultMessage(
        `Tech 源导入完成：新增 ${result.created}，更新 ${result.updated}，识别 ${result.total} 行，可抓取入口 ${result.fetchable}，待补入口 ${result.metadata_only}`
      );
    }
    await loadSources();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导入 Tech Insight Loop 源失败";
  } finally {
    importing.value = false;
  }
}

function canFetchSource(source: DataSourceRecord) {
  return (
    canManageIngestion.value &&
    source.enabled &&
    source.workspace_link_enabled &&
    ["rss", "paper_rss", "paper_api", "page_manual", "page_monitor"].includes(source.source_type)
  );
}

function shortExpertRoutes(source: DataSourceRecord) {
  return source.expert_routes.slice(0, 2).join(" / ");
}

// 推入式源语义（backend-capability-test-matrix §3.1）：manual/internal（未配 api_url）
// 的条目由手工导入/内部系统写入，定时抓取如实返回 0 条新增是正常行为，不是源坏了。
const PUSH_BASED_HINT = "推入式源：由手工导入/内部系统写入，定时抓取 0 条是正常行为";
const WECHAT_PENDING_HINT =
  "微信公众号源待配置：需就绪 RSSHub 公众号路由（RSSHUB_BASE_URL）或文章 URL 入口后才能抓取";

function isPushBasedSource(source: DataSourceRecord) {
  if (source.source_type === "manual") {
    return true;
  }
  // internal 配置 fetch_config.api_url 后会升级为拉取器；API 未暴露 fetch_config，
  // 前端以 url 入口作为「可拉取」代理信号：无 URL 视为纯推入式。
  return source.source_type === "internal" && !source.url;
}

function isPendingWechatSource(source: DataSourceRecord) {
  return source.source_type === "wechat" && (source.needs_entry || source.metadata_only);
}

function sourceTypeLabel(type: string) {
  const labels: Record<string, string> = {
    rss: "RSS",
    paper_rss: "论文 RSS",
    paper_api: "论文 API",
    paper_page: "论文页面",
    wiseflow: "Wiseflow",
    crawler: "自定义爬虫",
    page_manual: "页面手工",
    page_monitor: "页面监控",
    csv: "CSV",
    manual: "手工导入",
    internal: "内部系统",
    wechat: "微信公众号"
  };
  return labels[type] ?? type;
}

function sourceIcon(type: string) {
  const icons = {
    rss: Rss,
    paper_rss: FileText,
    paper_api: FileText,
    paper_page: FileText,
    wiseflow: Bot,
    crawler: Bot,
    page_manual: Globe2,
    page_monitor: Monitor,
    csv: FileText,
    manual: DownloadCloud,
    internal: Monitor,
    wechat: MessageCircle
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
  definitionForm.name = source.name;
  definitionForm.url = source.url ?? "";
  definitionForm.backfillDays = String(source.backfill_days ?? 7);
}

function openCreatePanel() {
  if (!canManageIngestion.value) {
    setResultMessage("当前部署形态为只读消费模式，不能新增本地采集源。", "warning");
    return;
  }
  createForm.name = "";
  createForm.sourceType = "rss";
  createForm.url = "";
  createForm.domainCode = workspace.current?.default_domain_code ?? "ai";
  createForm.backfillDays = "7";
  createFormBaseline.value = createFormSnapshot();
  showCreatePanel.value = true;
}

function closeCreatePanel() {
  showCreatePanel.value = false;
}

async function submitCreateSource() {
  if (!workspace.currentCode) {
    return;
  }
  const name = createForm.name.trim();
  const url = createForm.url.trim();
  if (!name) {
    error.value = "请填写信息源名称";
    return;
  }
  if (!/^https?:\/\//.test(url)) {
    error.value = "URL 需以 http:// 或 https:// 开头";
    return;
  }
  const backfillDays = Number(createForm.backfillDays);
  if (Number.isNaN(backfillDays) || backfillDays < 0) {
    error.value = "回溯天数必须为非负数字";
    return;
  }

  creatingSource.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const result = await createSource({
      workspace_code: workspace.currentCode,
      name,
      source_type: createForm.sourceType,
      url,
      domain_code: createForm.domainCode.trim() || "ai",
      backfill_days: backfillDays
    });
    lastImportMessage.value = result.created
      ? `已创建信息源：${result.source.name}，并在当前工作台启用`
      : `共享池已有同 URL 源：${result.source.name}，已在当前工作台启用`;
    showCreatePanel.value = false;
    await loadSources();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建信息源失败";
  } finally {
    creatingSource.value = false;
  }
}

async function saveDefinition() {
  if (!selectedSource.value) {
    return;
  }
  const name = definitionForm.name.trim();
  const url = definitionForm.url.trim();
  if (!name) {
    error.value = "信息源名称不能为空";
    return;
  }
  if (url && !/^https?:\/\//.test(url)) {
    error.value = "URL 需以 http:// 或 https:// 开头";
    return;
  }
  const backfillDays = Number(definitionForm.backfillDays);
  if (Number.isNaN(backfillDays) || backfillDays < 0) {
    error.value = "回溯天数必须为非负数字";
    return;
  }

  savingDefinition.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const updated = await updateSourceDefinition(
      selectedSource.value.id,
      {
        name,
        ...(url ? { url } : {}),
        backfill_days: backfillDays
      },
      workspace.currentCode || undefined
    );
    sources.value = sources.value.map((source) => (source.id === updated.id ? updated : source));
    selectedSource.value = updated;
    fillConfigForm(updated);
    lastImportMessage.value = `已保存：${updated.name} 的源定义`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存源定义失败";
  } finally {
    savingDefinition.value = false;
  }
}

function openConfig(source: DataSourceRecord) {
  selectedSource.value = source;
  fillConfigForm(source);
}

function closeConfig() {
  selectedSource.value = null;
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
  if (!canFetchSource(source)) {
    setResultMessage("该源当前不可抓取：请确认部署形态、源入口和工作台启用状态。", "warning");
    return;
  }
  fetchingSourceId.value = source.id;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const result = await fetchSource(source.id, workspace.currentCode || undefined);
    if (result.fetched === 0) {
      setResultMessage(`抓取完成但未返回条目：${source.name}。请检查源当天是否发布、RSS 窗口和最近失败原因。`, "info");
    } else {
      setResultMessage(`抓取完成：${source.name}，拉取 ${result.fetched}，新增 ${result.created}，更新 ${result.updated}`);
    }
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
      void loadSources();
    }
  },
  { immediate: true }
);
</script>

<template>
  <section class="source-workbench layout-list">
    <section class="source-stats-card" aria-label="数据源概览">
      <div class="source-total-stat">
        <strong>{{ sources.length }}</strong>
        <span>共享源总数</span>
      </div>

      <div class="source-stat-divider" aria-hidden="true"></div>

      <div class="source-type-pills">
        <span class="metric-pill enabled">
          <CheckCircle2 :size="14" />
          {{ enabledInWorkspaceCount }} 已启用
        </span>
        <span v-for="[type, count] in counts" :key="type" class="metric-pill" :data-source-type="type">
          {{ count }} {{ sourceTypeLabel(type) }}
        </span>
      </div>

      <div class="source-stats-actions">
        <button
          v-if="canManageIngestion"
          type="button"
          class="icon-button"
          @click="openCreatePanel"
          title="自建信息源"
        >
          <Plus :size="16" />
          <span>新增源</span>
        </button>
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadSources" title="刷新">
          <RefreshCw :size="16" />
          <span>刷新</span>
        </button>
        <button
          v-if="canManageIngestion"
          type="button"
          class="icon-button"
          :disabled="importing || previewLoading"
          @click="openImportPreview('legacy')"
          title="导入旧种子源"
        >
          <DownloadCloud :size="16" />
          <span>{{ importing || previewLoading ? "检查中" : "导入数据" }}</span>
        </button>
        <button
          v-if="canManageIngestion"
          type="button"
          class="icon-button secondary"
          :disabled="importing || previewLoading"
          @click="openImportPreview('tech')"
          title="导入 Tech Insight Loop 源治理"
        >
          <DownloadCloud :size="16" />
          <span>导入 Tech 源</span>
        </button>
      </div>
    </section>

    <p class="workspace-form-hint sources-policy-note">
      标签策略与报告格式已移至
      <RouterLink to="/workspace-settings#labels">工作台配置</RouterLink>
      统一管理。
    </p>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="lastImportMessage" :class="importMessageClass">{{ lastImportMessage }}</p>

    <section class="source-page-grid single-column">
      <div class="source-list">
      <header class="source-list-title">
        <div>
          <p class="eyebrow">数据源池</p>
          <h3>活跃数据源</h3>
          <p>管理和配置正在抓取的情报来源。</p>
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
                {{ source.needs_entry ? "待补入口" : source.workspace_link_enabled ? "启用" : "停用" }}
              </span>
            </div>
            <a v-if="source.url" class="source-url" :href="source.url" target="_blank" rel="noreferrer">
              {{ source.url }}
            </a>
            <span v-else class="source-url">无公开 URL</span>

            <div class="source-meta-line">
              <span class="type-badge">{{ sourceTypeLabel(source.source_type) }}</span>
              <span
                v-if="isPushBasedSource(source)"
                class="meta-chip push-based-chip"
                :title="PUSH_BASED_HINT"
              >
                推入式
              </span>
              <span
                v-else-if="isPendingWechatSource(source)"
                class="meta-chip needs-entry-chip wechat-pending-chip"
                :title="WECHAT_PENDING_HINT"
              >
                待配置
              </span>
              <span v-if="source.source_tier" class="meta-chip source-tier-chip">{{ source.source_tier }}</span>
              <span v-if="source.source_channel_type" class="meta-chip">{{ source.source_channel_type }}</span>
              <span v-if="source.source_score" class="meta-chip">质量 {{ source.source_score.toFixed(1) }}</span>
              <span v-if="source.needs_entry" class="meta-chip needs-entry-chip">待补入口</span>
              <span class="meta-chip">{{ source.domain_code }}</span>
              <span v-if="source.info_category || source.primary_category" class="meta-chip">
                {{ source.info_category || source.primary_category }}
              </span>
              <span v-for="tag in source.source_tags.slice(0, 2)" :key="`${source.id}-${tag}`" class="meta-chip source-tag-chip">
                {{ tag }}
              </span>
              <span class="source-freshness">
                {{ source.last_success_at ? `最近成功 ${formatDateTime(source.last_success_at)}` : "暂无成功抓取" }}
              </span>
              <span v-if="shortExpertRoutes(source)" class="meta-chip route-chip">
                {{ shortExpertRoutes(source) }}
              </span>
              <span v-if="source.last_error" class="source-error">{{ source.last_error }}</span>
            </div>
          </div>

          <div class="source-actions">
            <RouterLink class="table-action" :to="`/sources/${source.id}`" title="查看数据源详情">
              <FileText :size="14" />
              <span>详情</span>
            </RouterLink>
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

      <p v-if="!loading && sources.length === 0" class="empty-state">
        {{ canManageIngestion ? "暂无数据源，可先导入旧种子源。" : "当前为只读消费模式，等待外网同步后会显示数据源。" }}
      </p>
      </div>
    </section>
  </section>

  <!-- 单源配置：按 frontend-product-design §10.2 三条判定保留的上下文面板（context-panel）——
       ① 编辑页面列表当前选中的一项；② 需同时看到背后列表以便对照/连续切换；
       ③ 提交是可反复保存的配置编辑。创建/确认类弹层一律走居中 AppModal。 -->
  <div v-if="selectedSource" class="config-backdrop" @click="closeConfig"></div>
  <aside v-if="selectedSource" class="config-panel context-panel" aria-label="数据源配置">
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

    <div class="config-section-divider">
      <span>源定义</span>
      <small v-if="selectedSource.needs_entry">该源为待补入口，填入 URL 后即可抓取</small>
      <small v-else>修改共享池中的源名称、入口和回溯范围</small>
    </div>

    <div class="config-grid">
      <label>
        <span>名称</span>
        <input v-model="definitionForm.name" placeholder="信息源名称" />
      </label>
      <label>
        <span>回溯天数</span>
        <input v-model="definitionForm.backfillDays" type="number" min="0" />
      </label>
    </div>
    <label class="config-url-field">
      <span>URL / RSS 入口</span>
      <input v-model="definitionForm.url" placeholder="https://..." />
    </label>

    <button type="button" class="config-save secondary" :disabled="savingDefinition" @click="saveDefinition">
      {{ savingDefinition ? "保存中" : "保存源定义" }}
    </button>
  </aside>

  <!-- 新增信息源：居中 Modal md 档（frontend-product-design §10.3 迁移清单第 3 项）。
       创建类操作不满足上下文面板判定（§10.2 条件 1/3），原右上 config-panel 浮层收编到 AppModal。 -->
  <AppModal
    :open="showCreatePanel"
    title="新增信息源"
    size="md"
    :dirty="createFormDirty"
    @close="closeCreatePanel"
  >
    <template #header-meta>
      <p class="eyebrow">数据源池</p>
    </template>

    <p class="workspace-form-hint">
      新增源进入全局共享池并自动在当前工作台（{{ workspace.current?.name }}）启用；
      如果共享池已存在同 URL 源，将直接复用并启用，不会产生重复源。
    </p>

    <div class="config-grid">
      <label>
        <span>名称</span>
        <input v-model="createForm.name" placeholder="例如 机器之心 RSS" />
      </label>
      <label>
        <span>类型</span>
        <select v-model="createForm.sourceType">
          <option v-for="item in customSourceTypes" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
      </label>
      <label>
        <span>主题域</span>
        <input v-model="createForm.domainCode" placeholder="ai / hardware / policy" />
      </label>
      <label>
        <span>回溯天数</span>
        <input v-model="createForm.backfillDays" type="number" min="0" />
      </label>
    </div>
    <label class="config-url-field">
      <span>URL / RSS 入口</span>
      <input v-model="createForm.url" :placeholder="createUrlPlaceholder" />
    </label>

    <template #footer>
      <button type="button" class="icon-button" :disabled="creatingSource" @click="submitCreateSource">
        {{ creatingSource ? "创建中" : "创建并启用" }}
      </button>
    </template>
  </AppModal>

  <!-- 数据源导入预览：居中 Modal sm 档（§10.3 迁移清单第 4 项，决策确认类）。 -->
  <AppModal
    :open="Boolean(importPreview)"
    :title="importPreviewCatalog === 'tech' ? 'Tech Insight Loop 源治理' : '旧种子源'"
    size="sm"
    @close="closeImportPreview"
  >
    <template #header-meta>
      <p class="eyebrow">导入预览</p>
    </template>

    <template v-if="importPreview">
      <div class="preview-metrics">
        <span><strong>{{ importPreview.total }}</strong> 识别记录</span>
        <span><strong>{{ importPreview.would_create }}</strong> 将新增</span>
        <span><strong>{{ importPreview.would_update }}</strong> 将更新</span>
      </div>

      <div class="preview-list">
        <section v-for="group in importPreviewGroups" :key="group.type" class="preview-group">
          <header class="preview-group-head">
            <span class="type-badge">{{ sourceTypeLabel(group.type) }}</span>
            <small>样本 {{ group.samples.length }} 条</small>
          </header>
          <p v-if="group.note" class="preview-group-note">{{ group.note }}</p>
          <article v-for="sample in group.samples" :key="`${group.type}-${sample.name}-${sample.url}`">
            <strong>{{ sample.name }}</strong>
            <span>{{ sourceTypeLabel(sample.source_type) }}</span>
            <small>{{ sample.url || "无 URL" }}</small>
          </article>
        </section>
      </div>
    </template>

    <template #footer>
      <button type="button" class="icon-button" :disabled="importing" @click="confirmImport">
        {{ importing ? "导入中" : "确认导入" }}
      </button>
    </template>
  </AppModal>
</template>
