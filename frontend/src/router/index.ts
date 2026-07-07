import { createRouter, createWebHistory, type Router, type RouterHistory, type RouteRecordRaw } from "vue-router";

import AccountPage from "../pages/AccountPage.vue";
import AppShell from "../layouts/AppShell.vue";
import AuditLogsPage from "../pages/AuditLogsPage.vue";
import DailyReportsPage from "../pages/DailyReportsPage.vue";
import DailyReportDetailPage from "../pages/DailyReportDetailPage.vue";
import DashboardPage from "../pages/DashboardPage.vue";
import EntityMilestonesPage from "../pages/EntityMilestonesPage.vue";
import ExportsPage from "../pages/ExportsPage.vue";
import HistoricalReportsPage from "../pages/HistoricalReportsPage.vue";
import IngestionRunsPage from "../pages/IngestionRunsPage.vue";
import InsightsPage from "../pages/InsightsPage.vue";
import InvitePage from "../pages/InvitePage.vue";
import LoginPage from "../pages/LoginPage.vue";
import NewsPage from "../pages/NewsPage.vue";
import NotificationsPage from "../pages/NotificationsPage.vue";
import QualityArchivePage from "../pages/QualityArchivePage.vue";
import RecommendationsPage from "../pages/RecommendationsPage.vue";
import RequirementsPage from "../pages/RequirementsPage.vue";
import SourceDetailPage from "../pages/SourceDetailPage.vue";
import SourcesPage from "../pages/SourcesPage.vue";
import SyncRunsPage from "../pages/SyncRunsPage.vue";
import SetupPage from "../pages/SetupPage.vue";
import TopicTasksPage from "../pages/TopicTasksPage.vue";
import UsersPage from "../pages/UsersPage.vue";
import WeeklyReportsPage from "../pages/WeeklyReportsPage.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useSessionStore } from "../stores/session";
import { useSetupStore } from "../stores/setup";
import { useWorkspaceStore } from "../stores/workspace";

// viewer（游客）可访问的阅读路由前缀：日报/周报/历史报告/实体大事记 + 个人页。
// 管理路由（数据源/抓取/候选池/推荐/导出/用户/审计/同步/运营等）对 viewer 整组
// 重定向到 /daily-reports（与工作台分区 min_role 口径一致，搜索在顶栏不占路由）。
const VIEWER_PATH_PREFIXES = [
  "/daily-reports",
  "/weekly-reports",
  "/historical-reports",
  "/entity-milestones",
  "/account",
  "/notifications"
];

function isViewerReadablePath(path: string) {
  return VIEWER_PATH_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export const routes: RouteRecordRaw[] = [
    {
      path: "/login",
      name: "login",
      component: LoginPage
    },
    {
      path: "/invite/:code",
      name: "invite",
      component: InvitePage
    },
    {
      path: "/setup",
      name: "setup",
      component: SetupPage
    },
    {
      path: "/",
      component: AppShell,
      children: [
        {
          path: "",
          redirect: "/dashboard"
        },
        {
          path: "dashboard",
          name: "dashboard",
          component: DashboardPage
        },
        {
          path: "users",
          name: "users",
          component: UsersPage
        },
        {
          path: "account",
          name: "account",
          component: AccountPage
        },
        {
          path: "notifications",
          name: "notifications",
          component: NotificationsPage
        },
        {
          path: "sources",
          name: "sources",
          component: SourcesPage
        },
        {
          path: "sources/:id",
          name: "source-detail",
          component: SourceDetailPage
        },
        {
          path: "ingestion-runs",
          name: "ingestion-runs",
          component: IngestionRunsPage
        },
        {
          path: "news",
          name: "news",
          component: NewsPage
        },
        {
          path: "recommendations",
          name: "recommendations",
          component: RecommendationsPage
        },
        {
          path: "daily-reports",
          name: "daily-reports",
          component: DailyReportsPage
        },
        {
          path: "daily-reports/:id",
          name: "daily-report-detail",
          component: DailyReportDetailPage
        },
        {
          path: "daily-reports/:id/edit",
          name: "daily-report-edit",
          component: DailyReportDetailPage
        },
        {
          path: "weekly-reports",
          name: "weekly-reports",
          component: WeeklyReportsPage
        },
        {
          path: "historical-reports",
          name: "historical-reports",
          component: HistoricalReportsPage
        },
        {
          path: "entity-milestones",
          name: "entity-milestones",
          component: EntityMilestonesPage
        },
        {
          path: "quality-archive",
          name: "quality-archive",
          component: QualityArchivePage
        },
        {
          path: "exports",
          name: "exports",
          component: ExportsPage
        },
        {
          path: "requirements",
          name: "requirements",
          component: RequirementsPage
        },
        {
          path: "insights",
          name: "insights",
          component: InsightsPage
        },
        {
          path: "tasks",
          name: "tasks",
          component: TopicTasksPage
        },
        {
          path: "sync",
          name: "sync",
          component: SyncRunsPage
        },
        {
          path: "audit-logs",
          name: "audit-logs",
          component: AuditLogsPage
        }
      ]
    }
];

export function installRouterGuards(appRouter: Router) {
  appRouter.beforeEach(async (to) => {
    const setup = useSetupStore();
    if (!setup.checked) {
      await setup.loadStatus();
    }
    const runtime = useRuntimeStore();
    if (!runtime.checked) {
      await runtime.load();
    }
    if (setup.needsSetup) {
      return to.path === "/setup" ? true : "/setup";
    }
    if (to.path === "/setup") {
      return "/login";
    }

    const session = useSessionStore();
    if (!session.checked) {
      await session.loadCurrentUser();
    }

    if (to.path === "/login") {
      return session.isAuthenticated ? "/dashboard" : true;
    }

    if (to.path.startsWith("/invite/")) {
      return true;
    }

    if (!session.isAuthenticated) {
      return {
        path: "/login",
        query: { redirect: to.fullPath }
      };
    }
    if (session.user?.status === "must_change_password" && to.path !== "/account") {
      return "/account";
    }

    // viewer（游客）阅读视角：当前工作台角色是 viewer（且非 super_admin /
    // editor_admin）时默认落地 /daily-reports，访问管理路由一律重定向回日报。
    const globalRoles = session.user?.roles ?? [];
    const hasGlobalAdminRole = globalRoles.includes("super_admin") || globalRoles.includes("editor_admin");
    if (!hasGlobalAdminRole && !isViewerReadablePath(to.path)) {
      const workspace = useWorkspaceStore();
      await workspace.ensureLoaded();
      if (workspace.currentRole === "viewer") {
        return "/daily-reports";
      }
    }
    return true;
  });
}

// history base 跟随构建期 VITE_BASE_PATH（vite.config.ts 注入 import.meta.env.BASE_URL），
// 支撑门户子路径部署（如 /watchtower/）。
export function createInfoWatchtowerRouter(history: RouterHistory = createWebHistory(import.meta.env.BASE_URL)) {
  const appRouter = createRouter({
    history,
    routes
  });
  installRouterGuards(appRouter);
  return appRouter;
}

export const router = createInfoWatchtowerRouter();
