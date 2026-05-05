import { createRouter, createWebHistory } from "vue-router";

import AppShell from "../layouts/AppShell.vue";
import DashboardPage from "../pages/DashboardPage.vue";
import LoginPage from "../pages/LoginPage.vue";
import PlaceholderPage from "../pages/PlaceholderPage.vue";
import SourcesPage from "../pages/SourcesPage.vue";
import UsersPage from "../pages/UsersPage.vue";
import { useSessionStore } from "../stores/session";

const plannedPages = [
  ["sources/:id", "数据源详情", "展示单个数据源的抓取规则、近期 raw items 和错误记录。"],
  ["news", "候选池", "展示去重 winner、重复来源、标签、推荐分和采信状态。"],
  ["recommendations", "推荐运行", "展示推荐 run、分数拆解、推荐原因和日报候选。"],
  ["daily-reports", "日报", "按时间线展示已发布日报、点赞、评分和评论。"],
  ["daily-reports/:id", "日报详情", "展示某一天日报的完整条目、反馈和追溯信息。"],
  ["daily-reports/:id/edit", "日报编辑", "管理员采信、剔除、排序、编辑并发布日报。"],
  ["weekly-reports", "周报", "周报候选、采信和自动生成能力将在这里实现。"],
  ["requirements", "内部需求", "从洞察转出的需求，并追溯到触发新闻和原始数据。"],
  ["tasks", "指派任务", "管理员给用户指派专题跟进任务。"],
  ["exports", "SQL导出", "生成、下载和追溯公司内网 SQL。"],
  ["sync", "同步", "公网/内网同步包导出、导入、历史和冲突处理。"],
  ["audit-logs", "审计日志", "查看关键管理操作和系统任务记录。"]
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
        ...plannedPages.map(([path, title, description]) => ({
          path,
          component: PlaceholderPage,
          props: { title, description }
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
