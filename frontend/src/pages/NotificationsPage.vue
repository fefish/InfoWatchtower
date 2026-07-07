<script setup lang="ts">
import { Archive, Bell, CheckCheck, Circle, RefreshCw } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";

import {
  archiveNotification,
  fetchNotificationPreferences,
  fetchNotifications,
  fetchUnreadNotificationCount,
  markAllNotificationsRead,
  markNotificationRead,
  updateNotificationPreference,
  type NotificationPreferenceRecord,
  type NotificationRecord,
  type NotificationStatusFilter
} from "../api/notifications";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const notifications = ref<NotificationRecord[]>([]);
const preferences = ref<NotificationPreferenceRecord[]>([]);
const unreadCount = ref(0);
const statusFilter = ref<NotificationStatusFilter>("unread");
const loading = ref(false);
const savingId = ref("");
const archivingId = ref("");
const savingPreference = ref("");
const savingAll = ref(false);
const error = ref("");
const message = ref("");

const unreadInList = computed(() => notifications.value.filter((item) => item.status === "unread").length);
const preferenceLabels: Record<string, string> = {
  "comment.created": "日报条目新评论",
  "comment.replied": "日报条目回复",
  "comment.mentioned": "评论提及我",
  "sync_conflict.created": "同步冲突提醒",
  "ingestion.failed_source_retry_due": "失败源重试到期",
  "ingestion.failed_source_retry_blocked": "失败源重试阻塞",
  "daily_report.published": "日报发布提醒",
  "weekly_report.published": "周报发布提醒",
  "weekly_report_item.updated": "周报条目更新提醒",
  "task.assigned": "任务指派提醒",
  "requirement.status_changed": "需求状态提醒"
};

function notifyShellCountChanged() {
  window.dispatchEvent(new CustomEvent("infowatchtower:notifications-updated"));
}

async function loadNotifications() {
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    await ensureWorkspaceLoaded();
    const [count, list, nextPreferences] = await Promise.all([
      fetchUnreadNotificationCount(),
      fetchNotifications(statusFilter.value, 50),
      workspace.currentCode ? fetchNotificationPreferences(workspace.currentCode) : Promise.resolve([])
    ]);
    unreadCount.value = count.unread_count;
    notifications.value = list;
    preferences.value = nextPreferences;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载消息通知失败";
  } finally {
    loading.value = false;
  }
}

async function ensureWorkspaceLoaded() {
  if (!workspace.currentCode) {
    await workspace.loadWorkspaces();
  }
}

async function markRead(item: NotificationRecord) {
  savingId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await markNotificationRead(item.id);
    const index = notifications.value.findIndex((candidate) => candidate.id === item.id);
    if (statusFilter.value === "unread") {
      notifications.value = notifications.value.filter((candidate) => candidate.id !== item.id);
    } else if (index >= 0) {
      notifications.value.splice(index, 1, updated);
    }
    unreadCount.value = Math.max(0, unreadCount.value - (item.status === "unread" ? 1 : 0));
    message.value = "消息已标记为已读";
    notifyShellCountChanged();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "标记已读失败";
  } finally {
    savingId.value = "";
  }
}

async function archiveItem(item: NotificationRecord) {
  archivingId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await archiveNotification(item.id);
    const index = notifications.value.findIndex((candidate) => candidate.id === item.id);
    if (statusFilter.value === "archived") {
      if (index >= 0) {
        notifications.value.splice(index, 1, updated);
      }
    } else {
      notifications.value = notifications.value.filter((candidate) => candidate.id !== item.id);
    }
    unreadCount.value = Math.max(0, unreadCount.value - (item.status === "unread" ? 1 : 0));
    message.value = "消息已归档";
    notifyShellCountChanged();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "归档消息失败";
  } finally {
    archivingId.value = "";
  }
}

async function markAllRead() {
  savingAll.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await markAllNotificationsRead();
    unreadCount.value = result.unread_count;
    notifications.value = notifications.value.map((item) => ({
      ...item,
      status: "read",
      read_at: item.read_at || new Date().toISOString()
    }));
    if (statusFilter.value === "unread") {
      notifications.value = [];
    }
    message.value = "全部未读消息已标记为已读";
    notifyShellCountChanged();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "全部已读失败";
  } finally {
    savingAll.value = false;
  }
}

async function setPreference(item: NotificationPreferenceRecord, enabled: boolean) {
  savingPreference.value = item.event_type;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateNotificationPreference({
      ...item,
      in_app_enabled: enabled,
      email_enabled: false
    });
    preferences.value = preferences.value.map((candidate) =>
      candidate.event_type === updated.event_type ? updated : candidate
    );
    message.value = "通知偏好已保存，仅影响之后生成的消息";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存通知偏好失败";
  } finally {
    savingPreference.value = "";
  }
}

function preferenceLabel(eventType: string) {
  return preferenceLabels[eventType] || eventType;
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "未读";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function targetLabel(item: NotificationRecord) {
  return item.target_label;
}

function targetPath(item: NotificationRecord) {
  return item.target_path;
}

onMounted(loadNotifications);
</script>

<template>
  <section class="module-page notifications-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Collaboration</p>
        <h2>消息通知</h2>
        <p>当前用户收到的站内协作消息，来自日报条目的真实评论事件。</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadNotifications">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button type="button" class="icon-button" :disabled="savingAll || unreadCount === 0" @click="markAllRead">
          <CheckCheck :size="17" />
          <span>{{ savingAll ? "处理中" : "全部已读" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <div class="module-stats">
      <article><strong>{{ unreadCount }}</strong><span>未读消息</span></article>
      <article><strong>{{ notifications.length }}</strong><span>当前列表</span></article>
      <article><strong>{{ unreadInList }}</strong><span>列表未读</span></article>
    </div>

    <section class="module-card notification-preference-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Preferences</p>
          <h3>通知偏好</h3>
        </div>
        <span class="metric-pill">{{ workspace.current?.name || workspace.currentCode || "当前工作台" }}</span>
      </div>
      <div class="notification-preference-grid">
        <label v-for="item in preferences" :key="item.event_type" class="switch-row compact">
          <input
            type="checkbox"
            :checked="item.in_app_enabled"
            :disabled="savingPreference === item.event_type"
            :aria-label="`${preferenceLabel(item.event_type)}站内消息`"
            @change="setPreference(item, ($event.target as HTMLInputElement).checked)"
          />
          <span>{{ preferenceLabel(item.event_type) }}</span>
        </label>
      </div>
      <p class="muted-line">当前只控制站内消息；邮件投递通道尚未启用。</p>
    </section>

    <section class="module-card notification-list-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Inbox</p>
          <h3>站内消息</h3>
        </div>
        <div class="policy-tabs compact">
          <button type="button" :class="{ active: statusFilter === 'unread' }" @click="statusFilter = 'unread'; loadNotifications()">
            未读
          </button>
          <button type="button" :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'; loadNotifications()">
            全部
          </button>
          <button type="button" :class="{ active: statusFilter === 'read' }" @click="statusFilter = 'read'; loadNotifications()">
            已读
          </button>
          <button type="button" :class="{ active: statusFilter === 'archived' }" @click="statusFilter = 'archived'; loadNotifications()">
            归档
          </button>
        </div>
      </div>

      <article v-for="item in notifications" :key="item.id" class="notification-row" :class="{ unread: item.status === 'unread' }">
        <div class="notification-icon">
          <Bell v-if="item.status === 'unread'" :size="18" />
          <Circle v-else :size="16" />
        </div>
        <div class="notification-body">
          <div class="notification-title-row">
            <h3>{{ item.activity_event.summary }}</h3>
            <span class="metric-pill">{{ item.activity_event.event_type }}</span>
          </div>
          <p>
            {{ item.activity_event.actor_name || "系统" }} · {{ item.workspace_code }} ·
            {{ formatDateTime(item.created_at) }}
          </p>
          <div class="coverage-metrics">
            <span>{{ item.status }}</span>
            <span>{{ item.priority }}</span>
            <span>{{ item.delivery_channel }}</span>
            <span>{{ item.activity_event.sync_policy }}</span>
          </div>
        </div>
        <div class="notification-actions">
          <RouterLink class="mini-action" :to="targetPath(item)">
            <span>{{ targetLabel(item) }}</span>
          </RouterLink>
          <button
            v-if="item.status === 'unread'"
            type="button"
            class="mini-action active"
            :disabled="savingId === item.id"
            @click="markRead(item)"
          >
            <CheckCheck :size="15" />
            <span>{{ savingId === item.id ? "处理中" : "已读" }}</span>
          </button>
          <button
            v-if="item.status !== 'archived'"
            type="button"
            class="mini-action"
            :disabled="archivingId === item.id"
            @click="archiveItem(item)"
          >
            <Archive :size="15" />
            <span>{{ archivingId === item.id ? "处理中" : "归档" }}</span>
          </button>
        </div>
      </article>

      <p v-if="!loading && notifications.length === 0" class="empty-state">
        当前没有符合筛选条件的站内消息。站内通知来自评论、发布、同步冲突等真实协作事件。
      </p>
      <p v-if="loading" class="empty-state">加载中</p>
    </section>
  </section>
</template>
