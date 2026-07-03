<script setup lang="ts">
import { CheckCircle2, ExternalLink, Pencil, RefreshCw, Save } from "lucide-vue-next";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";

import {
  fetchDailyReport,
  updateDailyReportItem,
  type DailyReportItemRecord,
  type DailyReportRecord
} from "../api/reports";

const route = useRoute();
const report = ref<DailyReportRecord | null>(null);
const loading = ref(false);
const savingId = ref("");
const editingId = ref("");
const error = ref("");
const message = ref("");

const editMode = computed(() => route.path.endsWith("/edit"));
const draft = reactive({
  title: "",
  summary: "",
  keyPoints: "",
  notes: "",
  adoptionStatus: 2
});

async function loadReport() {
  loading.value = true;
  error.value = "";
  try {
    report.value = await fetchDailyReport(String(route.params.id));
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载日报失败";
  } finally {
    loading.value = false;
  }
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

function beginEdit(item: DailyReportItemRecord) {
  editingId.value = item.id;
  draft.title = displayTitle(item);
  draft.summary = displaySummary(item);
  draft.keyPoints = displayKeyPoints(item);
  draft.notes = item.editor_notes;
  draft.adoptionStatus = item.adoption_status;
}

async function saveItem(item: DailyReportItemRecord) {
  savingId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateDailyReportItem(item.id, {
      editor_title: draft.title,
      editor_summary: draft.summary,
      editor_key_points: draft.keyPoints,
      editor_notes: draft.notes,
      adoption_status: draft.adoptionStatus
    });
    const index = report.value?.items.findIndex((entry) => entry.id === updated.id) ?? -1;
    if (report.value && index >= 0) {
      report.value.items.splice(index, 1, updated);
    }
    editingId.value = "";
    message.value = "日报条目已保存";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存失败";
  } finally {
    savingId.value = "";
  }
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

onMounted(loadReport);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">{{ editMode ? "Daily Report Edit" : "Daily Report Detail" }}</p>
        <h2>{{ report?.title || "日报详情" }}</h2>
        <p>{{ report?.summary || "展示日报完整条目、采信状态、编辑稿和原文追溯。" }}</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadReport">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section v-if="report" class="module-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">{{ report.workspace_code }} · {{ report.domain_code }}</p>
          <h3>{{ report.day_key }} · {{ report.status }}</h3>
        </div>
        <div class="module-mini-stats">
          <span>{{ report.items.length }} 条</span>
          <span>{{ report.items.filter((item) => item.adoption_status === 2).length }} 采信</span>
        </div>
      </div>

      <div class="report-detail-feed">
        <article v-for="(item, index) in report.items" :key="item.id" class="detail-news-card">
          <div class="rank-badge">{{ index + 1 }}</div>
          <div class="detail-news-body">
            <div class="candidate-meta">
              <span class="category-chip">{{ item.generated_news.category }}</span>
              <span class="state-chip">{{ adoptionLabel(item.adoption_status) }}</span>
              <span>{{ item.reaction_count }} 赞</span>
              <span>{{ item.comment_count }} 评论</span>
            </div>

            <template v-if="editMode && editingId === item.id">
              <div class="editor-form wide">
                <label>
                  标题
                  <input v-model="draft.title" />
                </label>
                <label>
                  摘要
                  <textarea v-model="draft.summary" rows="3"></textarea>
                </label>
                <label>
                  关键词
                  <input v-model="draft.keyPoints" />
                </label>
                <label>
                  备注
                  <textarea v-model="draft.notes" rows="3"></textarea>
                </label>
                <label>
                  采信状态
                  <select v-model.number="draft.adoptionStatus">
                    <option :value="2">采信</option>
                    <option :value="1">备选</option>
                    <option :value="0">剔除</option>
                  </select>
                </label>
                <button type="button" class="icon-button" :disabled="savingId === item.id" @click="saveItem(item)">
                  <Save :size="17" />
                  <span>{{ savingId === item.id ? "保存中" : "保存" }}</span>
                </button>
              </div>
            </template>
            <template v-else>
              <h3>{{ displayTitle(item) }}</h3>
              <p>{{ displaySummary(item) }}</p>
              <p class="muted-line">{{ displayKeyPoints(item) }}</p>
              <div class="story-footer">
                <a v-if="item.generated_news.source_url" :href="item.generated_news.source_url" target="_blank">
                  <ExternalLink :size="14" />
                  <span>{{ item.generated_news.source_url }}</span>
                </a>
                <button v-if="editMode" type="button" class="mini-action" @click="beginEdit(item)">
                  <Pencil :size="14" />
                  编辑
                </button>
                <CheckCircle2 v-if="item.adoption_status === 2" :size="16" />
              </div>
            </template>
          </div>
        </article>
      </div>
    </section>

    <section v-else class="module-card">
      <p class="empty-state">{{ loading ? "加载中..." : "没有找到这份日报，请从日报列表重新选择。" }}</p>
    </section>
  </section>
</template>
