import { createRouter, createWebHistory } from "vue-router";

import AppShell from "../layouts/AppShell.vue";
import DailyReportsPage from "../pages/DailyReportsPage.vue";
import DailyReportDetailPage from "../pages/DailyReportDetailPage.vue";
import DashboardPage from "../pages/DashboardPage.vue";
import ExportsPage from "../pages/ExportsPage.vue";
import IngestionRunsPage from "../pages/IngestionRunsPage.vue";
import LoginPage from "../pages/LoginPage.vue";
import ModuleRoadmapPage from "../pages/ModuleRoadmapPage.vue";
import NewsPage from "../pages/NewsPage.vue";
import RecommendationsPage from "../pages/RecommendationsPage.vue";
import SourceDetailPage from "../pages/SourceDetailPage.vue";
import SourcesPage from "../pages/SourcesPage.vue";
import UsersPage from "../pages/UsersPage.vue";
import { useSessionStore } from "../stores/session";

const roadmapPages = [
  {
    path: "weekly-reports",
    title: "周报",
    subtitle: "从日报采信、用户反馈和热度分中生成周报候选，管理员最终调整采信与排序。",
    stage: "Stage 8 · Weekly Intelligence",
    capabilities: ["按周汇总日报采信条目", "结合反馈热度与管理员选择生成周报草稿", "保留周报条目到日报、新闻、raw 的追溯链路"],
    nextSteps: ["补 weekly_reports / weekly_report_items 后端模型和 API", "实现周报候选池和采信编辑界面", "接入周报发布、锁定和审计日志"]
  },
  {
    path: "requirements",
    title: "内部需求",
    subtitle: "把外部新闻沉淀为 insight、implication 和可进入内部协同的需求。",
    stage: "Strategic Loop",
    capabilities: ["从日报条目创建需求", "记录洞察、战略含义、机会或风险", "追溯到触发新闻、raw 和数据源"],
    nextSteps: ["补 requirements API", "补从日报条目一键转需求入口", "补需求状态、负责人和优先级"]
  },
  {
    path: "tasks",
    title: "指派任务",
    subtitle: "管理员把关注方向和遗留问题指派给用户，形成持续跟踪闭环。",
    stage: "Strategic Loop",
    capabilities: ["从需求或新闻创建任务", "指派负责人、截止时间和状态", "任务反馈反哺推荐与来源评分"],
    nextSteps: ["补 tasks API", "补任务列表、详情和状态变更", "把任务反馈接入热度和推荐分"]
  },
  {
    path: "sync",
    title: "同步",
    subtitle: "支持公网和公司内网之间的数据包导出、导入、冲突检查和运行记录。",
    stage: "Multi Environment",
    capabilities: ["导出公网可迁移同步包", "内网导入并保留原始 ID 映射", "记录冲突、覆盖策略和同步审计"],
    nextSteps: ["补 sync package API", "补导出/导入前校验", "补双环境数据源和日报同步策略"]
  },
  {
    path: "audit-logs",
    title: "审计日志",
    subtitle: "查看关键管理操作、日报发布、SQL 导出和系统任务记录。",
    stage: "Governance",
    capabilities: ["按用户、动作、对象和时间筛选", "追溯日报发布与 SQL 导出", "支撑公网部署后的安全审计"],
    nextSteps: ["补 audit logs 列表 API", "补筛选和分页", "覆盖数据源配置、日报编辑、导出和同步操作"]
  }
];

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: LoginPage
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
          path: "exports",
          name: "exports",
          component: ExportsPage
        },
        ...roadmapPages.map((page) => ({
          path: page.path,
          component: ModuleRoadmapPage,
          props: {
            title: page.title,
            subtitle: page.subtitle,
            stage: page.stage,
            capabilities: page.capabilities,
            nextSteps: page.nextSteps
          }
        }))
      ]
    }
  ]
});

router.beforeEach(async (to) => {
  const session = useSessionStore();
  if (!session.checked) {
    await session.loadCurrentUser();
  }

  if (to.path === "/login") {
    return session.isAuthenticated ? "/dashboard" : true;
  }

  if (!session.isAuthenticated) {
    return {
      path: "/login",
      query: { redirect: to.fullPath }
    };
  }
  return true;
});
