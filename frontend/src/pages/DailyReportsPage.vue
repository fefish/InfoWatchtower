<script setup lang="ts">
import {
  CheckCircle2,
  CircleSlash2,
  ExternalLink,
  FileText,
  Heart,
  MessageCircle,
  Pencil,
  RefreshCw,
  Save,
  Send,
  Sparkles,
  Star
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";

import {
  createDailyReportItemComment,
  createDailyPipelineRun,
  fetchDailyReportItemComments,
  fetchDailyReports,
  publishDailyReport,
  rateDailyReportItem,
  reactToDailyReportItem,
  updateDailyReportItem,
  type CommentRecord,
  type DailyReportItemRecord,
  type DailyReportRecord
} from "../api/reports";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const reports = ref<DailyReportRecord[]>([]);
const loading = ref(false);
const generating = ref(false);
const publishingId = ref("");
const selectedReportId = ref("");
const selectedItemId = ref("");
const editingItemId = ref("");
const savingItemId = ref("");
const actingItemId = ref("");
const loadingCommentsId = ref("");
const error = ref("");
const message = ref("");
const targetDayKey = ref(todayKey());
const commentsByItem = ref<Record<string, CommentRecord[]>>({});
const commentDrafts = ref<Record<string, string>>({});

const editorDraft = reactive({
  title: "",
  summary: "",
  keyPoints: "",
  notes: "",
  adoptionStatus: 2
});

const selectedReport = computed(() => {
  return reports.value.find((report) => report.id === selectedReportId.value) ?? reports.value[0] ?? null;
});

const reportItems = computed(() => selectedReport.value?.items ?? []);

const selectedItem = computed(() => {
  return reportItems.value.find((item) => item.id === selectedItemId.value) ?? reportItems.value[0] ?? null;
});

const adoptedCount = computed(() => reportItems.value.filter((item) => item.adoption_status === 2).length);
const averageRating = computed(() => {
  const rated = reportItems.value.filter((item) => item.rating_count > 0);
  if (!rated.length) {
    return "0.0";
  }
  const total = rated.reduce((sum, item) => sum + item.rating_avg, 0);
  return (total / rated.length).toFixed(1);
});

async function loadReports() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    reports.value = await fetchDailyReports(workspace.currentCode);
    if (!reports.value.some((report) => report.id === selectedReportId.value)) {
      selectedReportId.value = reports.value[0]?.id ?? "";
    }
    ensureSelectedItem();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载日报失败";
  } finally {
    loading.value = false;
  }
}

async function generateDraft() {
  if (!workspace.currentCode) {
    return;
  }
  generating.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await createDailyPipelineRun({
      workspace_code: workspace.currentCode,
      day_key: targetDayKey.value || null,
      source_types: ["rss", "paper_rss", "page_manual", "page_monitor"],
      ingestion_limit: null,
      recommendation_limit: 15,
      source_daily_limit: 2,
      create_daily_draft: true,
      run_ingestion: true
    });
    message.value = `已生成 ${result.day_key ?? "当日"} 草稿：raw 扫描 ${result.raw_scanned}，候选 ${result.candidates_total}，采信 ${result.selected_total}，成稿 ${result.generated_total}`;
    await loadReports();
    if (result.daily_report_id) {
      selectedReportId.value = result.daily_report_id;
      ensureSelectedItem();
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "生成日报草稿失败";
  } finally {
    generating.value = false;
  }
}

async function publishReport(report: DailyReportRecord) {
  publishingId.value = report.id;
  error.value = "";
  message.value = "";
  try {
    await publishDailyReport(report.id);
    message.value = `已发布：${report.title}`;
    await loadReports();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "发布日报失败";
  } finally {
    publishingId.value = "";
  }
}

function ensureSelectedItem() {
  const report = selectedReport.value;
  if (!report) {
    selectedItemId.value = "";
    return;
  }
  if (!report.items.some((item) => item.id === selectedItemId.value)) {
    selectedItemId.value = report.items[0]?.id ?? "";
  }
}

function selectReport(report: DailyReportRecord) {
  selectedReportId.value = report.id;
  selectedItemId.value = report.items[0]?.id ?? "";
  editingItemId.value = "";
}

function selectItem(item: DailyReportItemRecord) {
  selectedItemId.value = item.id;
}

function displayTitle(item: DailyReportItemRecord) {
  return item.editor_title || item.generated_news.title;
}

function displaySummary(item: DailyReportItemRecord) {
  return item.editor_summary || item.generated_news.summary;
}

function displayKeyPoints(item: DailyReportItemRecord) {
  return item.editor_key_points || item.generated_news.key_points;
}

function contentField(item: DailyReportItemRecord, key: string) {
  const content = item.editor_content_json || item.generated_news.content_json || {};
  const value = content[key];
  return typeof value === "string" ? value : "";
}

function sourceLineage(item: DailyReportItemRecord, key: string) {
  const source = item.generated_news.content_json.source;
  if (!source || typeof source !== "object") {
    return "";
  }
  const value = (source as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

function statusLabel(status: string) {
  return status === "published" ? "已发布" : "草稿";
}

function adoptionLabel(status: number) {
  if (status === 2) {
    return "采信";
  }
  if (status === 1) {
    return "备选";
  }
  return "剔除";
}

function todayKey() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date());
}

function beginEdit(item: DailyReportItemRecord) {
  editingItemId.value = item.id;
  editorDraft.title = displayTitle(item);
  editorDraft.summary = displaySummary(item);
  editorDraft.keyPoints = displayKeyPoints(item);
  editorDraft.notes = item.editor_notes;
  editorDraft.adoptionStatus = item.adoption_status;
}

function cancelEdit() {
  editingItemId.value = "";
}

async function saveEdit(item: DailyReportItemRecord) {
  savingItemId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateDailyReportItem(item.id, {
      adoption_status: editorDraft.adoptionStatus,
      editor_title: editorDraft.title,
      editor_summary: editorDraft.summary,
      editor_key_points: editorDraft.keyPoints,
      editor_notes: editorDraft.notes
    });
    replaceItem(updated);
    editingItemId.value = "";
    message.value = "日报条目已保存";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存日报条目失败";
  } finally {
    savingItemId.value = "";
  }
}

async function setAdoption(item: DailyReportItemRecord, status: number) {
  actingItemId.value = item.id;
  error.value = "";
  try {
    const updated = await updateDailyReportItem(item.id, { adoption_status: status });
    replaceItem(updated);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新采信状态失败";
  } finally {
    actingItemId.value = "";
  }
}

async function likeItem(item: DailyReportItemRecord) {
  actingItemId.value = item.id;
  error.value = "";
  try {
    await reactToDailyReportItem(item.id);
    await loadReports();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "点赞失败";
  } finally {
    actingItemId.value = "";
  }
}

async function rateItem(item: DailyReportItemRecord, score: number) {
  actingItemId.value = item.id;
  error.value = "";
  try {
    await rateDailyReportItem(item.id, score);
    await loadReports();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "评分失败";
  } finally {
    actingItemId.value = "";
  }
}

async function loadComments(item: DailyReportItemRecord) {
  loadingCommentsId.value = item.id;
  error.value = "";
  try {
    commentsByItem.value = {
      ...commentsByItem.value,
      [item.id]: await fetchDailyReportItemComments(item.id)
    };
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载评论失败";
  } finally {
    loadingCommentsId.value = "";
  }
}

async function submitComment(item: DailyReportItemRecord) {
  const body = (commentDrafts.value[item.id] || "").trim();
  if (!body) {
    return;
  }
  actingItemId.value = item.id;
  error.value = "";
  try {
    const comment = await createDailyReportItemComment(item.id, body);
    commentsByItem.value = {
      ...commentsByItem.value,
      [item.id]: [...(commentsByItem.value[item.id] || []), comment]
    };
    commentDrafts.value = { ...commentDrafts.value, [item.id]: "" };
    await loadReports();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "提交评论失败";
  } finally {
    actingItemId.value = "";
  }
}

function replaceItem(updated: DailyReportItemRecord) {
  const report = selectedReport.value;
  if (!report) {
    return;
  }
  const index = report.items.findIndex((item) => item.id === updated.id);
  if (index >= 0) {
    report.items.splice(index, 1, updated);
  }
}

watch(selectedReport, ensureSelectedItem);

watch(selectedItem, (item) => {
  if (item && commentsByItem.value[item.id] === undefined) {
    void loadComments(item);
  }
});

watch(
  () => workspace.currentCode,
  () => {
    selectedReportId.value = "";
    selectedItemId.value = "";
    editingItemId.value = "";
    void loadReports();
  }
);

onMounted(loadReports);
</script>

<template>
  <section class="report-command">
    <div>
      <p class="eyebrow">阶段 5 · Daily Intelligence</p>
      <h2>日报</h2>
      <p>从去重 winner 生成推荐稿，编辑采信后形成每日情报。</p>
    </div>
    <div class="toolbar-actions">
      <label class="date-control" title="日报日期">
        <span>日期</span>
        <input v-model="targetDayKey" type="date" />
      </label>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadReports">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
      <button type="button" class="icon-button" :disabled="generating" @click="generateDraft">
        <Sparkles :size="18" />
        <span>{{ generating ? "生成中" : "生成日报草稿" }}</span>
      </button>
    </div>
  </section>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="message" class="form-success">{{ message }}</p>

  <section v-if="selectedReport" class="daily-report-layout enhanced">
    <aside class="report-timeline">
      <p class="eyebrow">Reports</p>
      <button
        v-for="report in reports"
        :key="report.id"
        type="button"
        class="report-tab"
        :class="{ active: report.id === selectedReport.id }"
        @click="selectReport(report)"
      >
        <strong>{{ report.day_key }}</strong>
        <span>{{ statusLabel(report.status) }} · {{ report.items.length }} 条</span>
      </button>
    </aside>

    <article class="daily-report-card editorial">
      <header class="daily-report-header">
        <div>
          <p class="eyebrow">{{ selectedReport.workspace_code }} · {{ selectedReport.domain_code }}</p>
          <h3>{{ selectedReport.title }}</h3>
          <p>{{ selectedReport.summary }}</p>
        </div>
        <button
          v-if="selectedReport.status !== 'published'"
          type="button"
          class="icon-button secondary"
          :disabled="publishingId === selectedReport.id"
          @click="publishReport(selectedReport)"
        >
          <CheckCircle2 :size="18" />
          <span>{{ publishingId === selectedReport.id ? "发布中" : "发布" }}</span>
        </button>
      </header>

      <div class="report-metrics">
        <span>{{ reportItems.length }} 条入稿</span>
        <span>{{ adoptedCount }} 条采信</span>
        <span>{{ averageRating }} 平均评分</span>
      </div>

      <div class="daily-item-list">
        <article
          v-for="(item, index) in reportItems"
          :key="item.id"
          class="daily-item story"
          :class="{ active: selectedItem?.id === item.id }"
          @click="selectItem(item)"
        >
          <div class="story-index">{{ String(index + 1).padStart(2, "0") }}</div>
          <div class="story-body">
            <div class="daily-item-meta">
              <span>{{ item.generated_news.category }}</span>
              <span>{{ adoptionLabel(item.adoption_status) }}</span>
              <span>{{ item.reaction_count }} 赞</span>
              <span>{{ item.comment_count }} 评论</span>
            </div>
            <h4>{{ displayTitle(item) }}</h4>
            <p>{{ displaySummary(item) }}</p>
            <div class="story-content-grid">
              <p v-if="contentField(item, 'technologyAndInnovation')">
                {{ contentField(item, "technologyAndInnovation") }}
              </p>
              <p v-if="contentField(item, 'valueAndImpact')">
                {{ contentField(item, "valueAndImpact") }}
              </p>
            </div>
            <a v-if="item.generated_news.source_url" :href="item.generated_news.source_url" target="_blank">
              <ExternalLink :size="14" />
              <span>{{ item.generated_news.source_url }}</span>
            </a>
          </div>
        </article>
      </div>
    </article>

    <aside v-if="selectedItem" class="report-editor-panel">
      <div class="editor-panel-section">
        <p class="eyebrow">当前条目</p>
        <h3>{{ displayTitle(selectedItem) }}</h3>
        <div class="editor-actions">
          <button
            type="button"
            class="mini-action"
            :class="{ active: selectedItem.adoption_status === 2 }"
            :disabled="actingItemId === selectedItem.id"
            @click="setAdoption(selectedItem, 2)"
          >
            <CheckCircle2 :size="15" />
            <span>采信</span>
          </button>
          <button
            type="button"
            class="mini-action"
            :class="{ active: selectedItem.adoption_status === 1 }"
            :disabled="actingItemId === selectedItem.id"
            @click="setAdoption(selectedItem, 1)"
          >
            <FileText :size="15" />
            <span>备选</span>
          </button>
          <button
            type="button"
            class="mini-action"
            :class="{ active: selectedItem.adoption_status === 0 }"
            :disabled="actingItemId === selectedItem.id"
            @click="setAdoption(selectedItem, 0)"
          >
            <CircleSlash2 :size="15" />
            <span>剔除</span>
          </button>
        </div>
      </div>

      <div class="editor-panel-section">
        <div class="section-title-row">
          <p class="eyebrow">编辑</p>
          <button
            v-if="editingItemId !== selectedItem.id"
            type="button"
            class="mini-action"
            @click="beginEdit(selectedItem)"
          >
            <Pencil :size="15" />
            <span>编辑</span>
          </button>
        </div>
        <div v-if="editingItemId === selectedItem.id" class="editor-form">
          <label>
            标题
            <input v-model="editorDraft.title" />
          </label>
          <label>
            摘要
            <textarea v-model="editorDraft.summary" rows="5" />
          </label>
          <label>
            要点
            <textarea v-model="editorDraft.keyPoints" rows="3" />
          </label>
          <label>
            编辑备注
            <textarea v-model="editorDraft.notes" rows="3" />
          </label>
          <div class="editor-actions">
            <button
              type="button"
              class="mini-action active"
              :disabled="savingItemId === selectedItem.id"
              @click="saveEdit(selectedItem)"
            >
              <Save :size="15" />
              <span>{{ savingItemId === selectedItem.id ? "保存中" : "保存" }}</span>
            </button>
            <button type="button" class="mini-action" @click="cancelEdit">取消</button>
          </div>
        </div>
        <div v-else class="editor-readonly">
          <p>{{ displaySummary(selectedItem) }}</p>
          <small>{{ displayKeyPoints(selectedItem) }}</small>
        </div>
      </div>

      <div class="editor-panel-section">
        <p class="eyebrow">反馈</p>
        <div class="feedback-row">
          <button
            type="button"
            class="mini-action"
            :disabled="actingItemId === selectedItem.id"
            @click="likeItem(selectedItem)"
          >
            <Heart :size="15" />
            <span>{{ selectedItem.reaction_count }}</span>
          </button>
          <button
            v-for="score in 5"
            :key="score"
            type="button"
            class="star-button"
            :disabled="actingItemId === selectedItem.id"
            @click="rateItem(selectedItem, score)"
          >
            <Star :size="15" :fill="score <= Math.round(selectedItem.rating_avg) ? 'currentColor' : 'none'" />
          </button>
        </div>
        <div class="comment-box">
          <textarea
            v-model="commentDrafts[selectedItem.id]"
            rows="3"
            placeholder="写一条评论或判断依据"
          />
          <button
            type="button"
            class="mini-action active"
            :disabled="actingItemId === selectedItem.id"
            @click="submitComment(selectedItem)"
          >
            <Send :size="15" />
            <span>发送</span>
          </button>
        </div>
        <div class="comment-list">
          <p v-if="loadingCommentsId === selectedItem.id" class="muted-line">评论加载中</p>
          <article v-for="comment in commentsByItem[selectedItem.id] || []" :key="comment.id">
            <MessageCircle :size="14" />
            <p>{{ comment.body }}</p>
          </article>
        </div>
      </div>

      <div class="editor-panel-section">
        <p class="eyebrow">追溯</p>
        <dl class="lineage-list">
          <div>
            <dt>news</dt>
            <dd>{{ sourceLineage(selectedItem, "news_item_id") || selectedItem.generated_news.news_item_id }}</dd>
          </div>
          <div>
            <dt>raw</dt>
            <dd>{{ sourceLineage(selectedItem, "raw_item_id") || "未返回" }}</dd>
          </div>
          <div>
            <dt>source</dt>
            <dd>{{ sourceLineage(selectedItem, "data_source_id") || "未返回" }}</dd>
          </div>
        </dl>
      </div>
    </aside>
  </section>

  <section v-else class="placeholder-panel">
    <div>
      <p class="eyebrow">日报草稿</p>
      <h2>{{ loading ? "正在加载" : "还没有日报" }}</h2>
      <p>先完成抓取、标准化和去重，然后点击“生成日报草稿”。</p>
    </div>
    <FileText :size="42" />
  </section>
</template>
