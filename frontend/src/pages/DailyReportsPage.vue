<script setup lang="ts">
import {
  Bell,
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
  Star,
  X
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createDailyReportItemComment,
  createDailyReportItemEntityMilestone,
  createDailyReportItemInsight,
  createDailyPipelineRun,
  fetchDailyReportItemComments,
  fetchDailyReports,
  publishDailyReport,
  rateDailyReportItem,
  regenerateDailyReportGeneratedNews,
  reactToDailyReportItem,
  updateDailyReportItem,
  type CommentRecord,
  type DailyReportItemRecord,
  type DailyReportRecord
} from "../api/reports";
import {
  createReportFormat,
  dailyRenditionExportUrl,
  deleteReportFormat,
  fetchReportFormats,
  regenerateDailyRendition,
  updateReportFormat,
  type ReportFormatRecord,
  type ReportRenditionRecord
} from "../api/renditions";
import {
  fetchObjectWatcher,
  updateObjectWatcher,
  type ObjectWatcherRecord
} from "../api/watchers";
import { fetchWorkspaceFeedbackPolicy, type WorkspaceFeedbackPolicy } from "../api/workspaces";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const route = useRoute();
const reports = ref<DailyReportRecord[]>([]);
const loading = ref(false);
const generating = ref(false);
const publishingId = ref("");
const regeneratingReportId = ref("");
const selectedReportId = ref("");
const selectedItemId = ref("");
const detailOpen = ref(false);
const editingItemId = ref("");
const savingItemId = ref("");
const actingItemId = ref("");
const strategyItemId = ref("");
const milestoneItemId = ref("");
const milestoneSavingId = ref("");
const loadingCommentsId = ref("");
const loadingWatcherId = ref("");
const watchingItemId = ref("");
const error = ref("");
const message = ref("");
const targetDayKey = ref(todayKey());
const commentsByItem = ref<Record<string, CommentRecord[]>>({});
const commentDrafts = ref<Record<string, string>>({});
const milestoneDrafts = ref<Record<string, string>>({});
const watchersByItem = ref<Record<string, ObjectWatcherRecord>>({});
const feedbackPolicy = ref<WorkspaceFeedbackPolicy>({
  workspace_code: "",
  viewer_can_react: true,
  viewer_can_rate: true,
  viewer_can_comment: true,
  viewer_can_edit: false,
  notify_on_comment: true,
  notify_on_publish: false
});
const pendingItemAnchorId = computed(() => {
  const value = route.query.item_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingCommentAnchorId = computed(() => {
  const value = route.query.comment_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingReportAnchorId = computed(() => {
  const value = route.query.report_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingRenditionAnchorId = computed(() => {
  const value = route.query.rendition_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingRenditionFormatCode = computed(() => {
  const value = route.query.format_code;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const contentFieldLabels = [
  ["background", "背景"],
  ["effects", "效果总结"],
  ["eventSummary", "事件总结"],
  ["technologyAndInnovation", "技术和创新点总结"],
  ["valueAndImpact", "价值和影响"]
] as const;
const keywordNoiseMarkers = [
  "采用",
  "作为",
  "支持",
  "提升",
  "具备",
  "适用于",
  "通过",
  "实现",
  "提供",
  "能够",
  "旨在",
  "面向",
  "解决"
];
const keywordHints = [
  "AI Infra",
  "AI 应用",
  "测评技术",
  "大厂动态",
  "模型",
  "算法",
  "推理加速",
  "训练技术",
  "智能体",
  "基础竞争力",
  "工具新功能",
  "工具新案例",
  "工具新技术",
  "视频生成",
  "端到端",
  "归一化流",
  "扩散模型",
  "原生似然估计",
  "因果预测",
  "多模态",
  "模型评估",
  "基准测试",
  "Cursor",
  "Claude Code",
  "OpenCode",
  "Codex"
];

const editorDraft = reactive({
  title: "",
  summary: "",
  keyPoints: "",
  contentJson: {} as Record<string, string>,
  notes: "",
  adoptionStatus: 2
});

const selectedReport = computed(() => {
  return reports.value.find((report) => report.id === selectedReportId.value) ?? reports.value[0] ?? null;
});

const reportItems = computed(() => selectedReport.value?.items ?? []);

const selectedItem = computed(() => {
  return reportItems.value.find((item) => item.id === selectedItemId.value) ?? null;
});

const detailItem = computed(() => (detailOpen.value ? selectedItem.value : null));

const adoptedCount = computed(() => reportItems.value.filter((item) => item.adoption_status === 2).length);
const roleRank: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3
};
const currentWorkspaceRole = computed(() => workspace.current?.current_user_workspace_role ?? "");
const isViewerOnly = computed(() => roleRank[currentWorkspaceRole.value] === 0);
const canReact = computed(() => !isViewerOnly.value || feedbackPolicy.value.viewer_can_react);
const canRate = computed(() => !isViewerOnly.value || feedbackPolicy.value.viewer_can_rate);
const canComment = computed(() => !isViewerOnly.value || feedbackPolicy.value.viewer_can_comment);
const canCreateStrategyLoop = computed(() => roleRank[currentWorkspaceRole.value] >= 2);
const canCreateEntityMilestone = computed(() => roleRank[currentWorkspaceRole.value] >= 1);

// ---- 成稿格式（renditions）----
const formats = ref<ReportFormatRecord[]>([]);
const activeFormatCode = ref("company_sql_v1");
const rendition = ref<ReportRenditionRecord | null>(null);
const renditionLoading = ref(false);
const headlineSavingId = ref("");
const showFormatPanel = ref(false);
const formatBusyId = ref("");
const creatingFormat = ref(false);

const formatFieldOptions = [
  ["tag_line", "标签行"],
  ["bullet_points", "📋要点"],
  ["takeaway", "📌总结"],
  ["five_fields", "五段正文"],
  ["summary", "摘要"],
  ["source_link", "来源链接"],
  ["score", "推荐分"]
] as const;

const formatForm = reactive({
  code: "",
  name: "",
  groupBy: "board",
  headlineEnabled: true,
  headlineTopN: 6,
  fields: ["tag_line", "bullet_points", "takeaway", "source_link"] as string[],
  exportMd: true,
  exportHtml: true
});

const enabledFormats = computed(() =>
  formats.value.filter((fmt) => fmt.enabled).sort((left, right) => left.sort_order - right.sort_order)
);
const activeFormat = computed(
  () => formats.value.find((fmt) => fmt.format_code === activeFormatCode.value) ?? null
);
const renditionSnapshots = computed(() => rendition.value?.body_json.items ?? {});
const renditionGroups = computed(() => rendition.value?.body_json.groups ?? []);
const renditionHeadlines = computed(() =>
  (rendition.value?.body_json.headlines ?? [])
    .map((id) => renditionSnapshots.value[id])
    .filter((snapshot) => Boolean(snapshot))
);
const renditionFields = computed(() => rendition.value?.body_json.item_fields ?? []);

async function loadFormats() {
  if (!workspace.currentCode) {
    return;
  }
  try {
    formats.value = await fetchReportFormats(workspace.currentCode);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载成稿格式失败";
    formats.value = [];
  }
  if (!enabledFormats.value.some((fmt) => fmt.format_code === activeFormatCode.value)) {
    activeFormatCode.value = "company_sql_v1";
  }
  if (applyPendingRenditionAnchor()) {
    return;
  }
  // 对齐快报心智：默认打开成品阅读（技术洞察版），编审是其中一个视图
  if (
    activeFormatCode.value === "company_sql_v1" &&
    enabledFormats.value.some((fmt) => fmt.format_code === "tech_insight_v1")
  ) {
    activeFormatCode.value = "tech_insight_v1";
    void loadRendition();
  }
}

async function loadFeedbackPolicy() {
  if (!workspace.currentCode) {
    return;
  }
  try {
    feedbackPolicy.value = await fetchWorkspaceFeedbackPolicy(workspace.currentCode);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载反馈策略失败";
  }
}

async function switchFormat(code: string) {
  activeFormatCode.value = code;
  if (code !== "company_sql_v1") {
    await loadRendition();
  }
}

async function loadRendition() {
  const report = selectedReport.value;
  if (!report || activeFormatCode.value === "company_sql_v1") {
    rendition.value = null;
    return;
  }
  renditionLoading.value = true;
  try {
    rendition.value = await regenerateDailyRendition(report.id, activeFormatCode.value);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "生成成稿失败";
    rendition.value = null;
  } finally {
    renditionLoading.value = false;
  }
}

function renditionExportHref(target: "md" | "html") {
  const report = selectedReport.value;
  if (!report) {
    return "#";
  }
  return dailyRenditionExportUrl(report.id, activeFormatCode.value, target);
}

async function toggleHeadline(itemId: string, current: boolean) {
  headlineSavingId.value = itemId;
  error.value = "";
  try {
    await updateDailyReportItem(itemId, { is_headline: !current });
    const report = selectedReport.value;
    if (report) {
      const item = report.items.find((candidate) => candidate.id === itemId);
      if (item) {
        item.is_headline = !current;
      }
    }
    await loadRendition();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新头条失败";
  } finally {
    headlineSavingId.value = "";
  }
}

async function toggleFormatEnabled(fmt: ReportFormatRecord) {
  formatBusyId.value = fmt.id;
  error.value = "";
  try {
    const updated = await updateReportFormat(fmt.id, { enabled: !fmt.enabled });
    formats.value = formats.value.map((candidate) => (candidate.id === updated.id ? updated : candidate));
    if (!updated.enabled && activeFormatCode.value === updated.format_code) {
      activeFormatCode.value = "company_sql_v1";
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新格式失败";
  } finally {
    formatBusyId.value = "";
  }
}

async function removeFormat(fmt: ReportFormatRecord) {
  formatBusyId.value = fmt.id;
  error.value = "";
  try {
    await deleteReportFormat(fmt.id);
    formats.value = formats.value.filter((candidate) => candidate.id !== fmt.id);
    if (activeFormatCode.value === fmt.format_code) {
      activeFormatCode.value = "company_sql_v1";
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "删除格式失败";
  } finally {
    formatBusyId.value = "";
  }
}

function toggleFormField(field: string) {
  if (formatForm.fields.includes(field)) {
    formatForm.fields = formatForm.fields.filter((candidate) => candidate !== field);
  } else {
    formatForm.fields = [...formatForm.fields, field];
  }
}

async function submitCustomFormat() {
  if (!workspace.currentCode) {
    return;
  }
  const code = formatForm.code.trim();
  const name = formatForm.name.trim();
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(code)) {
    error.value = "格式标识需为小写字母开头的英文标识";
    return;
  }
  if (!name || formatForm.fields.length === 0) {
    error.value = "请填写格式名称并至少选择一个条目字段";
    return;
  }
  creatingFormat.value = true;
  error.value = "";
  try {
    const targets = [
      ...(formatForm.exportMd ? ["md"] : []),
      ...(formatForm.exportHtml ? ["html"] : [])
    ];
    const created = await createReportFormat({
      workspace_code: workspace.currentCode,
      format_code: code,
      name,
      group_by: formatForm.groupBy,
      headline_enabled: formatForm.headlineEnabled,
      headline_auto_top_n: formatForm.headlineTopN,
      item_fields: formatForm.fields,
      export_targets: targets
    });
    formats.value = [...formats.value, created];
    formatForm.code = "";
    formatForm.name = "";
    message.value = `已注册格式：${created.name}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建格式失败";
  } finally {
    creatingFormat.value = false;
  }
}
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
    applyPendingReportAnchor();
    applyPendingItemAnchor();
    applyPendingRenditionAnchor();
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
      generation_timeout_seconds: 45,
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

async function regenerateReport(report: DailyReportRecord) {
  regeneratingReportId.value = report.id;
  error.value = "";
  message.value = "";
  try {
    const result = await regenerateDailyReportGeneratedNews(report.id, {
      replace_ready: false,
      generation_timeout_seconds: 45
    });
    const index = reports.value.findIndex((candidate) => candidate.id === report.id);
    if (index >= 0) {
      reports.value.splice(index, 1, result.report);
    }
    message.value = `生成稿重跑完成：尝试 ${result.attempted_total} 条，ready ${result.ready_total} 条，fallback ${result.fallback_total} 条，跳过 ${result.skipped_total} 条`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "重跑生成稿失败";
  } finally {
    regeneratingReportId.value = "";
  }
}

function ensureSelectedItem() {
  const report = selectedReport.value;
  if (!report) {
    selectedItemId.value = "";
    detailOpen.value = false;
    return;
  }
  if (!report.items.some((item) => item.id === selectedItemId.value)) {
    selectedItemId.value = "";
    detailOpen.value = false;
    editingItemId.value = "";
  }
}

function applyPendingItemAnchor() {
  const itemId = pendingItemAnchorId.value;
  if (!itemId || reports.value.length === 0) {
    return;
  }
  const report = reports.value.find((candidate) => candidate.items.some((item) => item.id === itemId));
  if (!report) {
    return;
  }
  selectedReportId.value = report.id;
  selectedItemId.value = itemId;
  detailOpen.value = true;
}

function applyPendingReportAnchor() {
  const reportId = pendingReportAnchorId.value;
  if (!reportId || reports.value.length === 0) {
    return;
  }
  const report = reports.value.find((candidate) => candidate.id === reportId);
  if (!report) {
    return;
  }
  selectedReportId.value = report.id;
  if (!pendingItemAnchorId.value) {
    selectedItemId.value = "";
    detailOpen.value = false;
  }
}

function applyPendingRenditionAnchor() {
  const formatCode = pendingRenditionFormatCode.value;
  if (!pendingRenditionAnchorId.value || !formatCode) {
    return false;
  }
  if (!enabledFormats.value.some((fmt) => fmt.format_code === formatCode)) {
    return false;
  }
  activeFormatCode.value = formatCode;
  if (formatCode === "company_sql_v1") {
    rendition.value = null;
  } else {
    void loadRendition();
  }
  return true;
}

function selectReport(report: DailyReportRecord) {
  selectedReportId.value = report.id;
  selectedItemId.value = "";
  detailOpen.value = false;
  editingItemId.value = "";
}

function selectItem(item: DailyReportItemRecord) {
  selectedItemId.value = item.id;
  detailOpen.value = true;
  editingItemId.value = "";
}

function closeItemDetail() {
  detailOpen.value = false;
  editingItemId.value = "";
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

function displayKeywordList(item: DailyReportItemRecord) {
  const raw = displayKeyPoints(item);
  const keywords = raw
    .split(/[，,；;、。.!?\n]/)
    .map((part) => part.trim())
    .filter((keyword) => isDisplayKeyword(keyword) && keyword !== item.generated_news.category)
    .slice(0, 8);
  if (keywords.length >= 2) {
    return keywords;
  }
  return deriveKeywordList(item);
}

function isDisplayKeyword(keyword: string) {
  if (!keyword || keyword.length > 32) {
    return false;
  }
  if (keyword.length >= 7 && keywordNoiseMarkers.some((marker) => keyword.includes(marker))) {
    return false;
  }
  return true;
}

function deriveKeywordList(item: DailyReportItemRecord) {
  const text = [displayTitle(item), displaySummary(item), detailContentText(item)].join(" ");
  const candidates = [
    ...Array.from(text.matchAll(/\b[A-Z][A-Za-z0-9][A-Za-z0-9+._:-]{1,}\b/g)).map((match) => match[0]),
    ...keywordHints.filter((hint) => text.toLowerCase().includes(hint.toLowerCase()))
  ];
  const seen = new Set<string>();
  return candidates
    .map((keyword) => keyword.trim())
    .filter((keyword) => {
      const key = keyword.toLowerCase();
      if (!isDisplayKeyword(keyword) || keyword === item.generated_news.category || seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .slice(0, 8);
}

function detailContentText(item: DailyReportItemRecord) {
  return contentFieldLabels.map(([key]) => contentField(item, key)).join(" ");
}

function normalizeKeyPointString(value: string) {
  return value
    .split(/[，,；;、。.!?\n]/)
    .map((part) => part.trim())
    .filter(isDisplayKeyword)
    .slice(0, 8)
    .join(", ");
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

function isAnchoredComment(comment: CommentRecord) {
  return pendingCommentAnchorId.value === comment.id;
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

function generationLabel(status: string) {
  if (status === "ready") {
    return "LLM成稿";
  }
  if (status === "fallback_needs_review") {
    return "待重跑";
  }
  return status || "未知";
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
  editorDraft.keyPoints = displayKeywordList(item).join(", ");
  const content = item.editor_content_json || item.generated_news.content_json || {};
  editorDraft.contentJson = Object.fromEntries(
    contentFieldLabels.map(([key]) => {
      const value = content[key];
      return [key, typeof value === "string" ? value : ""];
    })
  );
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
      editor_key_points: normalizeKeyPointString(editorDraft.keyPoints) || displayKeywordList(item).join(", "),
      editor_content_json: {
        ...item.generated_news.content_json,
        ...(item.editor_content_json ?? {}),
        ...editorDraft.contentJson
      },
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
  if (!canReact.value) {
    return;
  }
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
  if (!canRate.value) {
    return;
  }
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

async function loadWatcherStatus(item: DailyReportItemRecord) {
  if (watchersByItem.value[item.id]) {
    return;
  }
  loadingWatcherId.value = item.id;
  try {
    watchersByItem.value = {
      ...watchersByItem.value,
      [item.id]: await fetchObjectWatcher("daily_report_item", item.id)
    };
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载关注状态失败";
  } finally {
    loadingWatcherId.value = "";
  }
}

function watcherStatus(item: DailyReportItemRecord) {
  return watchersByItem.value[item.id] ?? null;
}

async function toggleWatchItem(item: DailyReportItemRecord) {
  const current = watcherStatus(item);
  watchingItemId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateObjectWatcher("daily_report_item", item.id, !(current?.watching ?? false));
    watchersByItem.value = {
      ...watchersByItem.value,
      [item.id]: updated
    };
    message.value = updated.watching ? "已关注该日报条目" : "已取消关注该日报条目";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新关注状态失败";
  } finally {
    watchingItemId.value = "";
  }
}

async function submitComment(item: DailyReportItemRecord) {
  const body = (commentDrafts.value[item.id] || "").trim();
  if (!body) {
    return;
  }
  if (!canComment.value) {
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

async function createStrategyLoop(item: DailyReportItemRecord) {
  const report = selectedReport.value;
  if (!canCreateStrategyLoop.value) {
    return;
  }
  strategyItemId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const result = await createDailyReportItemInsight(item.id, {
      insight_title: displayTitle(item),
      insight_summary: displaySummary(item),
      implication_title: `研判：${displayTitle(item)}`,
      implication_description: displaySummary(item),
      requirement_title: `跟进：${displayTitle(item)}`,
      requirement_description: displaySummary(item),
      requirement_status: "draft",
      source_note: report ? `由 ${report.day_key} 日报条目沉淀` : "由日报条目沉淀"
    });
    message.value = `已沉淀内部需求：${result.requirement.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "沉淀内部需求失败";
  } finally {
    strategyItemId.value = "";
  }
}

function toggleMilestoneForm(item: DailyReportItemRecord) {
  milestoneItemId.value = milestoneItemId.value === item.id ? "" : item.id;
  milestoneDrafts.value = {
    ...milestoneDrafts.value,
    [item.id]: milestoneDrafts.value[item.id] ?? ""
  };
}

async function createEntityMilestone(item: DailyReportItemRecord) {
  if (!canCreateEntityMilestone.value) {
    return;
  }
  const entityName = (milestoneDrafts.value[item.id] || "").trim();
  if (!entityName) {
    error.value = "请先填写实体名称";
    return;
  }
  const report = selectedReport.value;
  milestoneSavingId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const result = await createDailyReportItemEntityMilestone(item.id, {
      entity_name: entityName,
      event_title: displayTitle(item),
      event_brief: displaySummary(item),
      impact_brief: displaySummary(item),
      board: item.generated_news.category,
      source_note: report ? `由 ${report.day_key} 日报条目登记` : "由日报条目登记"
    });
    milestoneDrafts.value = { ...milestoneDrafts.value, [item.id]: "" };
    milestoneItemId.value = "";
    message.value = `已登记实体事件：${result.entity_name} · ${result.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登记实体事件失败";
  } finally {
    milestoneSavingId.value = "";
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

function isAnchoredRenditionFormat(fmt: ReportFormatRecord) {
  return Boolean(pendingRenditionAnchorId.value && pendingRenditionFormatCode.value === fmt.format_code);
}

function isAnchoredRenditionView() {
  return Boolean(pendingRenditionAnchorId.value && rendition.value?.id === pendingRenditionAnchorId.value);
}

watch(selectedReport, ensureSelectedItem);

watch(pendingItemAnchorId, () => {
  applyPendingItemAnchor();
  ensureSelectedItem();
});

watch(pendingRenditionFormatCode, () => {
  applyPendingRenditionAnchor();
});

watch(detailItem, (item) => {
  if (item && commentsByItem.value[item.id] === undefined) {
    void loadComments(item);
  }
  if (item) {
    void loadWatcherStatus(item);
  }
});

watch(
  () => workspace.currentCode,
  () => {
    selectedReportId.value = "";
    selectedItemId.value = "";
    detailOpen.value = false;
    editingItemId.value = "";
    watchersByItem.value = {};
    activeFormatCode.value = "company_sql_v1";
    rendition.value = null;
    void loadFeedbackPolicy();
    void loadReports();
    void loadFormats();
  }
);

watch(selectedReportId, () => {
  if (activeFormatCode.value !== "company_sql_v1") {
    void loadRendition();
  }
});

onMounted(() => {
  void loadFeedbackPolicy();
  void loadReports();
  void loadFormats();
});
</script>

<template>
  <section class="report-command">
    <div>
      <p class="eyebrow">Daily Intelligence</p>
      <h2>日报</h2>
      <p>从推荐链路生成日报草稿，也支持把已校验公司 SQL 预览回填为可查看、可采信、可导出的日报。</p>
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
        <div class="toolbar-actions compact">
          <button
            v-if="selectedReport.status !== 'published'"
            type="button"
            class="icon-button secondary"
            :disabled="regeneratingReportId === selectedReport.id"
            @click="regenerateReport(selectedReport)"
          >
            <Sparkles :size="18" />
            <span>{{ regeneratingReportId === selectedReport.id ? "重跑中" : "重跑生成稿" }}</span>
          </button>
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
        </div>
      </header>

      <div class="report-metrics">
        <span>{{ reportItems.length }} 条入稿</span>
        <span>{{ adoptedCount }} 条采信</span>
        <span>{{ averageRating }} 平均评分</span>
      </div>

      <div class="rendition-bar">
        <div class="coverage-filter" role="tablist" aria-label="成稿格式">
          <button
            v-for="fmt in enabledFormats"
            :key="fmt.format_code"
            type="button"
            :class="{ active: activeFormatCode === fmt.format_code, anchored: isAnchoredRenditionFormat(fmt) }"
            :aria-current="isAnchoredRenditionFormat(fmt) ? 'true' : undefined"
            @click="switchFormat(fmt.format_code)"
          >
            {{ fmt.format_code === "company_sql_v1" ? `${fmt.name} · 编审` : fmt.name }}
          </button>
        </div>
        <div class="rendition-actions">
          <a
            v-if="activeFormat?.export_targets.includes('md')"
            class="table-action"
            :href="renditionExportHref('md')"
            target="_blank"
          >
            导出 MD
          </a>
          <a
            v-if="activeFormat?.export_targets.includes('html')"
            class="table-action"
            :href="renditionExportHref('html')"
            target="_blank"
          >
            导出 HTML
          </a>
          <button type="button" class="table-action" @click="showFormatPanel = true">格式</button>
        </div>
      </div>

      <div
        v-if="activeFormatCode !== 'company_sql_v1'"
        class="rendition-view"
        :class="{ anchored: isAnchoredRenditionView() }"
        :aria-current="isAnchoredRenditionView() ? 'true' : undefined"
      >
        <p v-if="renditionLoading" class="empty-state">正在生成成稿…</p>
        <template v-else-if="rendition">
          <section v-if="activeFormat?.headline_enabled && renditionHeadlines.length" class="rendition-headlines">
            <h4>今日头条</h4>
            <ol>
              <li v-for="snapshot in renditionHeadlines" :key="snapshot.item_id">
                {{ snapshot.title }}
              </li>
            </ol>
          </section>

          <section v-for="group in renditionGroups" :key="group.key" class="rendition-group">
            <h4>
              {{ group.title }}
              <small>{{ group.item_ids.length }} 条</small>
            </h4>
            <article
              v-for="(itemId, index) in group.item_ids"
              :key="itemId"
              class="rendition-item"
            >
              <template v-if="renditionSnapshots[itemId]">
                <div class="rendition-item-head">
                  <h5>{{ index + 1 }}、{{ renditionSnapshots[itemId].title }}</h5>
                  <button
                    v-if="activeFormat?.headline_enabled"
                    type="button"
                    class="headline-toggle"
                    :class="{ active: renditionSnapshots[itemId].is_headline }"
                    :disabled="headlineSavingId === itemId"
                    :title="renditionSnapshots[itemId].is_headline ? '移出头条' : '设为头条'"
                    @click="toggleHeadline(itemId, renditionSnapshots[itemId].is_headline)"
                  >
                    <Star :size="14" />
                    <span>{{ renditionSnapshots[itemId].is_headline ? "头条" : "设头条" }}</span>
                  </button>
                </div>
                <p v-if="renditionFields.includes('tag_line') && renditionSnapshots[itemId].tag_line.length" class="rendition-tags">
                  <span v-for="tag in renditionSnapshots[itemId].tag_line" :key="tag">【{{ tag }}】</span>
                </p>
                <p v-if="renditionFields.includes('bullet_points') && renditionSnapshots[itemId].bullet_points.length" class="rendition-block">
                  📋 <strong>要点</strong>：{{ renditionSnapshots[itemId].bullet_points.join("；") }}
                </p>
                <p v-if="renditionFields.includes('takeaway') && renditionSnapshots[itemId].takeaway" class="rendition-block">
                  📌 <strong>总结</strong>：{{ renditionSnapshots[itemId].takeaway }}
                </p>
                <p v-if="renditionFields.includes('summary') && renditionSnapshots[itemId].summary" class="rendition-block">
                  {{ renditionSnapshots[itemId].summary }}
                </p>
                <p class="rendition-source">
                  <a
                    v-if="renditionSnapshots[itemId].source_url"
                    :href="renditionSnapshots[itemId].source_url || '#'"
                    target="_blank"
                  >
                    来源：{{ renditionSnapshots[itemId].source_name || "原文链接" }}
                  </a>
                  <span v-else>来源：{{ renditionSnapshots[itemId].source_name || "未知" }}</span>
                  <span v-if="renditionSnapshots[itemId].insight_source === 'rule_fallback'" class="rendition-fallback">
                    规则降级稿
                  </span>
                </p>
              </template>
            </article>
          </section>
          <p v-if="renditionGroups.length === 0" class="empty-state">
            本报告暂无采信条目，先在内网版视图完成采信。
          </p>
        </template>
      </div>

      <div v-if="activeFormatCode === 'company_sql_v1'" class="daily-item-list">
        <article
          v-for="(item, index) in reportItems"
          :key="item.id"
          class="daily-item story"
          :class="{ active: detailItem?.id === item.id }"
          @click="selectItem(item)"
        >
          <div class="story-index">{{ String(index + 1).padStart(2, "0") }}</div>
          <div class="story-body">
            <div class="daily-item-meta">
              <span class="category-chip">{{ item.generated_news.category }}</span>
              <span class="state-chip">{{ adoptionLabel(item.adoption_status) }}</span>
              <span class="state-chip subtle">{{ generationLabel(item.generated_news.generation_status) }}</span>
              <span>{{ item.reaction_count }} 赞</span>
              <span>{{ item.comment_count }} 评论</span>
            </div>
            <h4>{{ displayTitle(item) }}</h4>
            <p>{{ displaySummary(item) }}</p>
            <div class="story-footer">
              <a
                v-if="item.generated_news.source_url"
                :href="item.generated_news.source_url"
                target="_blank"
                @click.stop
              >
                <ExternalLink :size="14" />
                <span>{{ item.generated_news.source_url }}</span>
              </a>
              <span>点击查看详情并处理</span>
            </div>
          </div>
        </article>
      </div>
    </article>
  </section>

  <Teleport to="body">
    <div v-if="detailItem" class="report-modal-backdrop" @click.self="closeItemDetail">
      <section class="report-detail-modal" role="dialog" aria-modal="true">
        <header class="report-modal-header">
          <div>
            <div class="headline-chip-row">
              <span class="category-chip large">{{ detailItem.generated_news.category }}</span>
              <span class="state-chip">{{ adoptionLabel(detailItem.adoption_status) }}</span>
            </div>
            <h3>{{ displayTitle(detailItem) }}</h3>
          </div>
          <button type="button" class="panel-close" aria-label="关闭详情" @click="closeItemDetail">
            <X :size="18" />
          </button>
        </header>

        <div class="report-modal-body">
          <article class="modal-story-detail">
            <p class="modal-summary">{{ displaySummary(detailItem) }}</p>
            <div class="modal-keyword-row">
              <div class="keyword-list" aria-label="关键词">
                <span
                  v-for="keyword in displayKeywordList(detailItem)"
                  :key="keyword"
                  class="keyword-chip key-chip"
                >
                  {{ keyword }}
                </span>
              </div>
              <div class="daily-item-meta">
                <span>{{ detailItem.reaction_count }} 赞</span>
                <span>{{ detailItem.comment_count }} 评论</span>
              </div>
            </div>
            <section v-for="[fieldKey, fieldLabel] in contentFieldLabels" :key="fieldKey" v-show="contentField(detailItem, fieldKey)">
              <h4>{{ fieldLabel }}</h4>
              <p>{{ contentField(detailItem, fieldKey) }}</p>
            </section>
            <a v-if="detailItem.generated_news.source_url" :href="detailItem.generated_news.source_url" target="_blank">
              <ExternalLink :size="14" />
              <span>{{ detailItem.generated_news.source_url }}</span>
            </a>
          </article>

          <aside class="modal-editor-panel">
            <div class="editor-panel-section">
              <p class="eyebrow">当前处理</p>
              <div class="editor-actions">
                <button
                  type="button"
                  class="mini-action"
                  :class="{ active: detailItem.adoption_status === 2 }"
                  :disabled="actingItemId === detailItem.id"
                  @click="setAdoption(detailItem, 2)"
                >
                  <CheckCircle2 :size="15" />
                  <span>采信</span>
                </button>
                <button
                  type="button"
                  class="mini-action"
                  :class="{ active: detailItem.adoption_status === 1 }"
                  :disabled="actingItemId === detailItem.id"
                  @click="setAdoption(detailItem, 1)"
                >
                  <FileText :size="15" />
                  <span>备选</span>
                </button>
                <button
                  type="button"
                  class="mini-action"
                  :class="{ active: detailItem.adoption_status === 0 }"
                  :disabled="actingItemId === detailItem.id"
                  @click="setAdoption(detailItem, 0)"
                >
                  <CircleSlash2 :size="15" />
                  <span>剔除</span>
                </button>
                <button
                  v-if="canCreateStrategyLoop"
                  type="button"
                  class="mini-action"
                  :disabled="strategyItemId === detailItem.id"
                  @click="createStrategyLoop(detailItem)"
                >
                  <Sparkles :size="15" />
                  <span>{{ strategyItemId === detailItem.id ? "沉淀中" : "沉淀需求" }}</span>
                </button>
                <button
                  v-if="canCreateEntityMilestone"
                  type="button"
                  class="mini-action"
                  :class="{ active: milestoneItemId === detailItem.id }"
                  @click="toggleMilestoneForm(detailItem)"
                >
                  <FileText :size="15" />
                  <span>登记事件</span>
                </button>
              </div>
              <form
                v-if="milestoneItemId === detailItem.id"
                class="inline-milestone-form"
                @submit.prevent="createEntityMilestone(detailItem)"
              >
                <label>
                  实体名称
                  <input v-model="milestoneDrafts[detailItem.id]" placeholder="公司、模型、产品或技术名" />
                </label>
                <button type="submit" class="primary-button" :disabled="milestoneSavingId === detailItem.id">
                  <Save :size="15" />
                  <span>{{ milestoneSavingId === detailItem.id ? "登记中" : "保存事件" }}</span>
                </button>
              </form>
            </div>

            <div class="editor-panel-section">
              <div class="section-title-row">
                <p class="eyebrow">编辑</p>
                <button
                  v-if="editingItemId !== detailItem.id"
                  type="button"
                  class="mini-action"
                  @click="beginEdit(detailItem)"
                >
                  <Pencil :size="15" />
                  <span>编辑</span>
                </button>
              </div>
              <div v-if="editingItemId === detailItem.id" class="editor-form">
                <label>
                  标题
                  <input v-model="editorDraft.title" />
                </label>
                <label>
                  摘要 / 一句话概括
                  <textarea v-model="editorDraft.summary" rows="5" />
                </label>
                <label>
                  关键词（逗号或分号分隔，避免整句）
                  <textarea v-model="editorDraft.keyPoints" rows="3" />
                </label>
                <div class="editor-content-fields">
                  <label v-for="[fieldKey, fieldLabel] in contentFieldLabels" :key="fieldKey">
                    {{ fieldLabel }}
                    <textarea v-model="editorDraft.contentJson[fieldKey]" rows="4" />
                  </label>
                </div>
                <label>
                  编辑备注
                  <textarea v-model="editorDraft.notes" rows="3" />
                </label>
                <div class="editor-actions">
                  <button
                    type="button"
                    class="mini-action active"
                    :disabled="savingItemId === detailItem.id"
                    @click="saveEdit(detailItem)"
                  >
                    <Save :size="15" />
                    <span>{{ savingItemId === detailItem.id ? "保存中" : "保存" }}</span>
                  </button>
                  <button type="button" class="mini-action" @click="cancelEdit">取消</button>
                </div>
              </div>
              <div v-else class="editor-readonly">
                <p>{{ displaySummary(detailItem) }}</p>
                <div class="keyword-list compact" aria-label="关键词">
                  <span
                    v-for="keyword in displayKeywordList(detailItem)"
                    :key="keyword"
                    class="keyword-chip key-chip"
                  >
                    {{ keyword }}
                  </span>
                </div>
              </div>
            </div>

            <div class="editor-panel-section">
              <p class="eyebrow">反馈</p>
              <div class="feedback-row">
                <button
                  type="button"
                  class="mini-action"
                  :class="{ active: watcherStatus(detailItem)?.watching }"
                  :disabled="watchingItemId === detailItem.id || loadingWatcherId === detailItem.id"
                  :aria-pressed="watcherStatus(detailItem)?.watching ? 'true' : 'false'"
                  @click="toggleWatchItem(detailItem)"
                >
                  <Bell :size="15" />
                  <span>{{ watcherStatus(detailItem)?.watching ? "已关注" : "关注" }}</span>
                  <span v-if="watcherStatus(detailItem)">· {{ watcherStatus(detailItem)?.watcher_count }}</span>
                </button>
                <button
                  type="button"
                  class="mini-action"
                  :disabled="actingItemId === detailItem.id || !canReact"
                  @click="likeItem(detailItem)"
                >
                  <Heart :size="15" />
                  <span>{{ detailItem.reaction_count }}</span>
                </button>
                <button
                  v-for="score in 5"
                  :key="score"
                  type="button"
                  class="star-button"
                  :disabled="actingItemId === detailItem.id || !canRate"
                  @click="rateItem(detailItem, score)"
                >
                  <Star :size="15" :fill="score <= Math.round(detailItem.rating_avg) ? 'currentColor' : 'none'" />
                </button>
              </div>
              <p v-if="!canReact || !canRate || !canComment" class="muted-line">
                当前工作台已关闭浏览者的部分反馈入口。
              </p>
              <div class="comment-box">
                <textarea
                  v-model="commentDrafts[detailItem.id]"
                  rows="3"
                  placeholder="写一条评论或判断依据"
                  :disabled="!canComment"
                />
                <button
                  type="button"
                  class="mini-action active"
                  :disabled="actingItemId === detailItem.id || !canComment"
                  @click="submitComment(detailItem)"
                >
                  <Send :size="15" />
                  <span>发送</span>
                </button>
              </div>
              <div class="comment-list">
                <p v-if="loadingCommentsId === detailItem.id" class="muted-line">评论加载中</p>
                <article
                  v-for="comment in commentsByItem[detailItem.id] || []"
                  :key="comment.id"
                  class="comment-row"
                  :class="{ anchored: isAnchoredComment(comment) }"
                  :aria-current="isAnchoredComment(comment) ? 'true' : undefined"
                >
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
                  <dd>{{ sourceLineage(detailItem, "news_item_id") || detailItem.generated_news.news_item_id }}</dd>
                </div>
                <div>
                  <dt>raw</dt>
                  <dd>{{ sourceLineage(detailItem, "raw_item_id") || "未返回" }}</dd>
                </div>
                <div>
                  <dt>source</dt>
                  <dd>{{ sourceLineage(detailItem, "data_source_id") || "未返回" }}</dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>
      </section>
    </div>
  </Teleport>

  <section v-if="!selectedReport" class="placeholder-panel">
    <div>
      <p class="eyebrow">日报草稿</p>
      <h2>{{ loading ? "正在加载" : "还没有日报" }}</h2>
      <p>
        当前工作台还没有可展示的日报。可以先完成抓取、标准化和去重后生成草稿；
        已经产出的公司 SQL 预览也可以通过回填脚本同步到日报工作台。
      </p>
    </div>
    <FileText :size="42" />
  </section>

  <div v-if="showFormatPanel" class="config-backdrop" @click="showFormatPanel = false"></div>
  <aside v-if="showFormatPanel" class="config-panel format-panel" aria-label="成稿格式管理">
    <header>
      <div>
        <p class="eyebrow">一次采信，多版成稿</p>
        <h3>成稿格式</h3>
      </div>
      <button type="button" class="panel-close" @click="showFormatPanel = false" title="关闭">
        <X :size="18" />
      </button>
    </header>

    <div class="format-list">
      <div v-for="fmt in formats" :key="fmt.id" class="format-row">
        <div class="format-row-main">
          <strong>{{ fmt.name }}</strong>
          <small>
            {{ fmt.format_code }}
            · {{ fmt.group_by === "board" ? "按板块" : fmt.group_by === "category" ? "按分类" : "平铺" }}
            <template v-if="fmt.export_targets.length"> · 导出 {{ fmt.export_targets.join("/").toUpperCase() }}</template>
            <template v-if="fmt.locked"> · 锁定（公司 SQL 口径）</template>
          </small>
        </div>
        <div class="format-row-actions">
          <label class="switch-row compact" :title="fmt.enabled ? '停用' : '启用'">
            <input
              type="checkbox"
              :checked="fmt.enabled"
              :disabled="formatBusyId === fmt.id"
              @change="toggleFormatEnabled(fmt)"
            />
          </label>
          <button
            v-if="!fmt.builtin"
            type="button"
            class="mini-icon-button"
            :disabled="formatBusyId === fmt.id"
            title="删除格式"
            @click="removeFormat(fmt)"
          >
            <X :size="14" />
          </button>
        </div>
      </div>
    </div>

    <div class="config-section-divider">
      <span>注册自定义格式</span>
      <small>格式只影响成稿视图与导出，不影响采信和公司 SQL</small>
    </div>

    <div class="config-grid">
      <label>
        <span>标识（英文）</span>
        <input v-model="formatForm.code" placeholder="leader_brief_v1" />
      </label>
      <label>
        <span>名称</span>
        <input v-model="formatForm.name" placeholder="领导一页纸" />
      </label>
      <label>
        <span>分组维度</span>
        <select v-model="formatForm.groupBy">
          <option value="board">业务板块</option>
          <option value="category">成品新闻十分类</option>
          <option value="none">平铺</option>
        </select>
      </label>
      <label>
        <span>头条条数</span>
        <input v-model.number="formatForm.headlineTopN" type="number" min="0" max="20" />
      </label>
    </div>

    <label class="switch-row">
      <input v-model="formatForm.headlineEnabled" type="checkbox" />
      <span>启用头条区</span>
    </label>

    <div class="format-field-picks">
      <span class="format-field-title">条目字段</span>
      <label v-for="[field, label] in formatFieldOptions" :key="field" class="format-field-pick">
        <input
          type="checkbox"
          :checked="formatForm.fields.includes(field)"
          @change="toggleFormField(field)"
        />
        <span>{{ label }}</span>
      </label>
    </div>

    <div class="format-field-picks">
      <span class="format-field-title">导出目标</span>
      <label class="format-field-pick">
        <input v-model="formatForm.exportMd" type="checkbox" />
        <span>Markdown</span>
      </label>
      <label class="format-field-pick">
        <input v-model="formatForm.exportHtml" type="checkbox" />
        <span>HTML</span>
      </label>
    </div>

    <button type="button" class="config-save" :disabled="creatingFormat" @click="submitCustomFormat">
      {{ creatingFormat ? "注册中" : "注册格式" }}
    </button>
  </aside>
</template>
