import { createRouter, createWebHistory } from "vue-router";

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
import InvitePage from "../pages/InvitePage.vue";
import LoginPage from "../pages/LoginPage.vue";
import NewsPage from "../pages/NewsPage.vue";
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
import { useSessionStore } from "../stores/session";
import { useSetupStore } from "../stores/setup";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
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
  ]
});

router.beforeEach(async (to) => {
  const setup = useSetupStore();
  if (!setup.checked) {
    await setup.loadStatus();
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
  return true;
});
