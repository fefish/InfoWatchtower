import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, type PropType } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationsPage from "./NotificationsPage.vue";
import type { NotificationPreferenceRecord, NotificationRecord } from "../api/notifications";
import { useWorkspaceStore } from "../stores/workspace";

const notificationsApi = vi.hoisted(() => ({
  archiveNotification: vi.fn(),
  fetchNotificationPreferences: vi.fn(),
  fetchNotifications: vi.fn(),
  fetchUnreadNotificationCount: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  markNotificationRead: vi.fn(),
  updateNotificationPreference: vi.fn()
}));

vi.mock("../api/notifications", () => ({
  archiveNotification: notificationsApi.archiveNotification,
  fetchNotificationPreferences: notificationsApi.fetchNotificationPreferences,
  fetchNotifications: notificationsApi.fetchNotifications,
  fetchUnreadNotificationCount: notificationsApi.fetchUnreadNotificationCount,
  markAllNotificationsRead: notificationsApi.markAllNotificationsRead,
  markNotificationRead: notificationsApi.markNotificationRead,
  updateNotificationPreference: notificationsApi.updateNotificationPreference
}));

type LinkTarget = string | { path: string; query?: Record<string, string> };

const routerLinkStub = defineComponent({
  props: {
    to: {
      type: [String, Object] as PropType<LinkTarget>,
      required: true
    }
  },
  computed: {
    href(): string {
      const to = this.to;
      if (typeof to === "string") {
        return to;
      }
      const query = to.query ? `?${new URLSearchParams(to.query).toString()}` : "";
      return `${to.path}${query}`;
    }
  },
  template: `<a :href="href"><slot /></a>`
});

function notificationRecord(overrides: Partial<NotificationRecord> = {}): NotificationRecord {
  return {
    id: "notification-1",
    workspace_code: "planning_intel",
    status: "unread",
    priority: "normal",
    delivery_channel: "in_app",
    target_label: "进入日报",
    target_path: "/daily-reports?item_id=item-1&comment_id=comment-1",
    read_at: null,
    created_at: "2026-07-05T09:00:00Z",
    activity_event: {
      id: "event-1",
      workspace_code: "planning_intel",
      domain_code: "ai",
      actor_user_id: "user-2",
      actor_name: "分析员",
      event_type: "comment.created",
      object_type: "comment",
      object_id: "comment-1",
      target_object_type: "daily_report_item",
      target_object_id: "item-1",
      summary: "分析员 评论了日报条目",
      metadata_json: {
        comment_id: "comment-1",
        daily_report_item_id: "item-1"
      },
      sync_policy: "local_only",
      created_at: "2026-07-05T09:00:00Z"
    },
    ...overrides
  };
}

function preferenceRecord(overrides: Partial<NotificationPreferenceRecord> = {}): NotificationPreferenceRecord {
  return {
    workspace_code: "planning_intel",
    event_type: "comment.created",
    in_app_enabled: true,
    email_enabled: false,
    ...overrides
  };
}

function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  workspace.options = [
    {
      code: "planning_intel",
      name: "规划部情报工作台",
      description: "",
      workspace_type: "intelligence_workspace",
      default_domain_code: "ai",
      enabled: true
    }
  ];
  return mount(NotificationsPage, {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: routerLinkStub
      }
    }
  });
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    notificationsApi.fetchUnreadNotificationCount.mockResolvedValue({ unread_count: 1 });
    notificationsApi.fetchNotifications.mockResolvedValue([notificationRecord()]);
    notificationsApi.fetchNotificationPreferences.mockResolvedValue([
      preferenceRecord(),
      preferenceRecord({ event_type: "comment.mentioned" }),
      preferenceRecord({ event_type: "sync_conflict.created" }),
      preferenceRecord({ event_type: "ingestion.failed_source_retry_due" }),
      preferenceRecord({ event_type: "ingestion.failed_source_retry_blocked" }),
      preferenceRecord({ event_type: "weekly_report_item.updated" }),
      preferenceRecord({ event_type: "requirement.status_changed" })
    ]);
    notificationsApi.markNotificationRead.mockResolvedValue(
      notificationRecord({
        status: "read",
        read_at: "2026-07-05T09:10:00Z"
      })
    );
    notificationsApi.archiveNotification.mockResolvedValue(
      notificationRecord({
        status: "archived",
        read_at: "2026-07-05T09:12:00Z"
      })
    );
    notificationsApi.markAllNotificationsRead.mockResolvedValue({ unread_count: 0 });
    notificationsApi.updateNotificationPreference.mockImplementation((payload) => Promise.resolve(payload));
  });

  it("loads real notifications and marks a single item as read", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(notificationsApi.fetchUnreadNotificationCount).toHaveBeenCalledTimes(1);
    expect(notificationsApi.fetchNotifications).toHaveBeenCalledWith("unread", 50);
    expect(notificationsApi.fetchNotificationPreferences).toHaveBeenCalledWith("planning_intel");
    expect(wrapper.text()).toContain("消息通知");
    expect(wrapper.text()).toContain("通知偏好");
    expect(wrapper.text()).toContain("日报条目新评论");
    expect(wrapper.text()).toContain("评论提及我");
    expect(wrapper.text()).toContain("失败源重试到期");
    expect(wrapper.text()).toContain("需求状态提醒");
    expect(wrapper.text()).toContain("分析员 评论了日报条目");
    expect(wrapper.text()).toContain("comment.created");
    const reportLink = wrapper.findAll("a").find((link) => link.text().includes("进入日报"));
    expect(reportLink?.attributes("href")).toBe("/daily-reports?item_id=item-1&comment_id=comment-1");

    const markReadButton = wrapper.find(".notification-row button.mini-action");
    await markReadButton.trigger("click");
    await flushPromises();

    expect(notificationsApi.markNotificationRead).toHaveBeenCalledWith("notification-1");
    expect(wrapper.text()).toContain("消息已标记为已读");
    expect(wrapper.find(".notification-row").exists()).toBe(false);
  });

  it("links mention notifications to the mentioned comment anchor", async () => {
    const base = notificationRecord();
    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({
        id: "notification-mention",
        priority: "important",
        target_label: "进入日报",
        target_path: "/daily-reports?item_id=item-1&comment_id=comment-mentioned",
        activity_event: {
          ...base.activity_event,
          id: "event-mention",
          event_type: "comment.mentioned",
          object_type: "comment",
          object_id: "comment-mentioned",
          target_object_type: "daily_report_item",
          target_object_id: "item-1",
          summary: "分析员 在评论中提到了你",
          metadata_json: {
            comment_id: "comment-mentioned",
            daily_report_item_id: "item-1",
            mentioned_user_ids: ["user-1"]
          }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("important");
    const reportLink = wrapper.findAll("a").find((link) => link.text().includes("进入日报"));
    expect(reportLink?.attributes("href")).toBe("/daily-reports?item_id=item-1&comment_id=comment-mentioned");
  });

  it("archives a notification and exposes the archived filter", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("归档");
    const archiveButton = wrapper.findAll(".notification-row button").find((button) => button.text().includes("归档"));
    expect(archiveButton).toBeTruthy();
    await archiveButton!.trigger("click");
    await flushPromises();

    expect(notificationsApi.archiveNotification).toHaveBeenCalledWith("notification-1");
    expect(wrapper.text()).toContain("消息已归档");
    expect(wrapper.find(".notification-row").exists()).toBe(false);

    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({ status: "archived", read_at: "2026-07-05T09:12:00Z" })
    ]);
    const archivedTab = wrapper.findAll("button").find((button) => button.text() === "归档");
    await archivedTab!.trigger("click");
    await flushPromises();

    expect(notificationsApi.fetchNotifications).toHaveBeenLastCalledWith("archived", 50);
    expect(wrapper.find(".notification-row").text()).toContain("archived");
    expect(wrapper.find(".notification-row").text()).not.toContain("归档");
  });

  it("updates in-app notification preferences for the current workspace", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("周报条目更新提醒");
    const commentPreference = wrapper.find('input[aria-label="日报条目新评论站内消息"]');
    await commentPreference.setValue(false);
    await flushPromises();

    expect(notificationsApi.updateNotificationPreference).toHaveBeenCalledWith({
      workspace_code: "planning_intel",
      event_type: "comment.created",
      in_app_enabled: false,
      email_enabled: false
    });
    expect(wrapper.text()).toContain("通知偏好已保存");
  });

  it("links report publish notifications to the matching report pages", async () => {
    const base = notificationRecord();
    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({
        id: "notification-daily",
        target_label: "进入日报",
        target_path: "/daily-reports?report_id=report-1",
        activity_event: {
          ...base.activity_event,
          id: "event-daily",
          event_type: "daily_report.published",
          object_type: "daily_report",
          object_id: "report-1",
          target_object_type: "daily_report",
          target_object_id: "report-1",
          summary: "分析员 发布了日报：规划部日报",
          metadata_json: { daily_report_id: "report-1", day_key: "2026-07-05" }
        }
      }),
      notificationRecord({
        id: "notification-weekly",
        target_label: "进入周报",
        target_path: "/weekly-reports?report_id=weekly-1",
        activity_event: {
          ...base.activity_event,
          id: "event-weekly",
          event_type: "weekly_report.published",
          object_type: "weekly_report",
          object_id: "weekly-1",
          target_object_type: "weekly_report",
          target_object_id: "weekly-1",
          summary: "分析员 发布了周报：2026-W27",
          metadata_json: { weekly_report_id: "weekly-1", week_key: "2026-W27" }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const links = wrapper.findAll("a");
    expect(links.find((link) => link.text().includes("进入日报"))?.attributes("href")).toBe(
      "/daily-reports?report_id=report-1"
    );
    expect(links.find((link) => link.text().includes("进入周报"))?.attributes("href")).toBe(
      "/weekly-reports?report_id=weekly-1"
    );
  });

  it("uses backend target metadata for weekly report item anchors", async () => {
    const base = notificationRecord();
    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({
        id: "notification-weekly-item",
        target_label: "进入周报条目",
        target_path: "/weekly-reports?item_id=weekly-item-1",
        activity_event: {
          ...base.activity_event,
          id: "event-weekly-item",
          event_type: "weekly_report_item.updated",
          object_type: "weekly_report_item",
          object_id: "weekly-item-1",
          target_object_type: "weekly_report_item",
          target_object_id: "weekly-item-1",
          summary: "周报条目需要复核",
          metadata_json: { weekly_report_item_id: "weekly-item-1" }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const weeklyItemLink = wrapper.findAll("a").find((link) => link.text().includes("进入周报条目"));
    expect(weeklyItemLink?.attributes("href")).toBe("/weekly-reports?item_id=weekly-item-1");
  });

  it("links sync conflict notifications to the matching conflict anchor", async () => {
    const base = notificationRecord();
    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({
        id: "notification-sync",
        priority: "important",
        target_label: "查看同步",
        target_path: "/sync?conflict_id=conflict-1",
        activity_event: {
          ...base.activity_event,
          id: "event-sync",
          event_type: "sync_conflict.created",
          object_type: "sync_conflict",
          object_id: "conflict-1",
          target_object_type: "data_sources",
          target_object_id: "source-1",
          summary: "同步冲突需要处置：data_sources source-1",
          metadata_json: {
            sync_conflict_id: "conflict-1",
            sync_run_id: "run-1",
            object_type: "data_sources",
            object_id: "source-1"
          }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const syncLink = wrapper.findAll("a").find((link) => link.text().includes("查看同步"));
    expect(syncLink?.attributes("href")).toBe("/sync?conflict_id=conflict-1");
  });

  it("links failed-source retry notifications to the matching ingestion run", async () => {
    const base = notificationRecord();
    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({
        id: "notification-ingestion",
        priority: "important",
        target_label: "查看抓取",
        target_path: "/ingestion-runs?run_id=run-failed",
        activity_event: {
          ...base.activity_event,
          id: "event-ingestion",
          event_type: "ingestion.failed_source_retry_blocked",
          object_type: "ingestion_run",
          object_id: "run-failed",
          target_object_type: "ingestion_run",
          target_object_id: "run-failed",
          summary: "失败源自动重试已阻塞：planning_intel:ingestion:failed，2 个失败源",
          metadata_json: {
            ingestion_run_id: "run-failed",
            run_key: "planning_intel:ingestion:failed",
            failed_source_count: 2,
            attempt_count: 3,
            alert_state: "blocked"
          }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("ingestion.failed_source_retry_blocked");
    const ingestionLink = wrapper.findAll("a").find((link) => link.text().includes("查看抓取"));
    expect(ingestionLink?.attributes("href")).toBe("/ingestion-runs?run_id=run-failed");
  });

  it("links task assignment notifications to the matching task anchor", async () => {
    const base = notificationRecord();
    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({
        id: "notification-task",
        target_label: "查看任务",
        target_path: "/tasks?task_id=task-1",
        activity_event: {
          ...base.activity_event,
          id: "event-task",
          event_type: "task.assigned",
          object_type: "topic_task",
          object_id: "task-1",
          target_object_type: "topic_task",
          target_object_id: "task-1",
          summary: "管理员 指派了任务：跟进同步冲突复盘",
          metadata_json: {
            topic_task_id: "task-1",
            assignee_user_id: "user-3"
          }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const taskLink = wrapper.findAll("a").find((link) => link.text().includes("查看任务"));
    expect(taskLink?.attributes("href")).toBe("/tasks?task_id=task-1");
  });

  it("links requirement status notifications to the matching requirement anchor", async () => {
    const base = notificationRecord();
    notificationsApi.fetchNotifications.mockResolvedValue([
      notificationRecord({
        id: "notification-requirement",
        target_label: "查看需求",
        target_path: "/requirements?requirement_id=req-1",
        activity_event: {
          ...base.activity_event,
          id: "event-requirement",
          event_type: "requirement.status_changed",
          object_type: "requirement",
          object_id: "req-1",
          target_object_type: "requirement",
          target_object_id: "req-1",
          summary: "管理员 更新了需求状态：跟踪外部信号",
          metadata_json: {
            requirement_id: "req-1",
            previous_status: "open",
            status: "done"
          }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const requirementLink = wrapper.findAll("a").find((link) => link.text().includes("查看需求"));
    expect(requirementLink?.attributes("href")).toBe("/requirements?requirement_id=req-1");
  });

  it("marks all unread notifications as read", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const markAllButton = wrapper.findAll("button").find((button) => button.text().includes("全部已读"));
    expect(markAllButton).toBeTruthy();
    await markAllButton!.trigger("click");
    await flushPromises();

    expect(notificationsApi.markAllNotificationsRead).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("全部未读消息已标记为已读");
    expect(wrapper.find(".notification-row").exists()).toBe(false);
  });
});
