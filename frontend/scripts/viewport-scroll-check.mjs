// WP3-D 自测脚本：375px / 1440px 双端逐路由无横滚检查。
// 用法：先起独立 vite（如 npx vite --port 5183 --strictPort），再
//   node scripts/viewport-scroll-check.mjs http://127.0.0.1:5183
// 全部 /api/** 用桩数据（与 e2e/smoke.e2e.ts 同思路），不依赖真实后端。
import { chromium } from "@playwright/test";

const baseURL = process.argv[2] ?? "http://127.0.0.1:5183";

const RUNTIME = {
  deploy_mode: "standalone",
  instance_id: "viewport-check",
  auth_mode: "public_password",
  app_version: "viewport-check",
  capabilities: {
    ingestion: true,
    sync_publisher: true,
    sync_consumer: true,
    embedding: true,
    search: true
  },
  auth_membership_mapping: { status: "empty", default_workspaces: [], department_workspaces: [] }
};

const SESSION_USER = {
  id: "user-check",
  external_provider: "local",
  external_id: "admin",
  employee_no: null,
  username: "admin",
  display_name: "布局自检管理员",
  department: null,
  email: null,
  status: "active",
  is_active: true,
  roles: ["super_admin"]
};

const WORKSPACES = [
  {
    code: "planning_intel",
    name: "规划部情报工作台",
    description: "布局自检工作台",
    workspace_type: "team",
    default_domain_code: "ai",
    enabled: true,
    current_user_workspace_role: "owner"
  }
];

const SECTIONS = [
  { section_key: "dashboard", name: "今日速览", section_type: "core", route_path: "/dashboard", sort_order: 1, enabled: true, group: "today" },
  { section_key: "source_management", name: "数据源管理", section_type: "core", route_path: "/sources", sort_order: 2, enabled: true, group: "collect" },
  { section_key: "ingestion_coverage", name: "抓取与覆盖", section_type: "core", route_path: "/ingestion-runs", sort_order: 3, enabled: true, group: "collect" },
  { section_key: "daily_reports", name: "日报", section_type: "core", route_path: "/daily-reports", sort_order: 4, enabled: true, group: "report" }
];

const SOURCES = [
  {
    id: "source-1",
    workspace_code: "shared",
    domain_code: "ai",
    source_type: "rss",
    name: "一个特别长名字的信息源用来验证窄屏不会撑破布局容器的场景",
    url: "https://example.com/very/long/path/rss.xml",
    enabled: true,
    default_focus_id: 1,
    backfill_days: 7,
    source_score: 80,
    last_fetch_at: "2026-07-05T08:00:00Z",
    last_success_at: "2026-07-05T08:00:00Z",
    last_error: "TimeoutError: upstream took toooooooooooooooooo long to respond with anything useful",
    primary_category: "AI",
    info_category: "",
    source_tags: [],
    source_secondary_tags: [],
    source_tier: "P1",
    source_channel_type: "media",
    expert_routes: [],
    inclusion_recommendation: "",
    metadata_only: false,
    needs_entry: false,
    fetch_entry_status: "",
    source_quality_notes: "",
    workspace_link_enabled: true,
    workspace_source_weight: 1,
    workspace_daily_limit: 2,
    workspace_clustering_config: {}
  }
];

const COVERAGE = {
  workspace_code: "planning_intel",
  day_key: "2026-07-07",
  run_id: "run-1",
  run_key: "run-key",
  run_type: "workspace_fetch",
  run_status: "completed",
  target_range: "2026-07-07",
  recommendation_run_id: "rec-run-1",
  recommendation_run_key: "rec-key",
  daily_report_id: "daily-1",
  daily_report_status: "draft",
  funnel: {
    enabled_sources: 294,
    run_sources: 294,
    source_succeeded: 254,
    source_failed: 40,
    items_fetched: 1024,
    raw_created: 812,
    raw_updated: 3,
    raw_in_target: 780,
    news_items: 512,
    dedupe_winners: 214,
    recommendation_candidates: 88,
    recommendation_selected: 24,
    generated_ready: 20,
    daily_adopted: 12
  },
  sources: []
};

// 已知返回对象的端点；其余 GET 一律回空数组（列表页兜底）
const OBJECT_ENDPOINTS = [
  ["/api/setup/status", { needs_setup: false }],
  ["/api/meta/runtime", RUNTIME],
  ["/api/auth/me", { user: SESSION_USER }],
  ["/api/notifications/unread-count", { unread_count: 0 }],
  ["/api/ingestion/coverage/trends", { workspace_code: "planning_intel", days: [] }],
  ["/api/ingestion/coverage", COVERAGE]
];

async function stub(page) {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    if (pathname === "/healthz") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ service: "infowatchtower", version: "check", environment: "check", database: { status: "ok" } })
      });
    }
    if (!pathname.startsWith("/api/")) {
      return route.fallback();
    }
    const json = (body, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    for (const [prefix, body] of OBJECT_ENDPOINTS) {
      if (pathname.startsWith(prefix)) {
        return json(body);
      }
    }
    if (/\/api\/workspaces\/[^/]+\/sections$/.test(pathname)) {
      return json(SECTIONS);
    }
    if (/\/api\/workspaces\/[^/]+\/label-policy$/.test(pathname)) {
      return json({
        workspace_code: "planning_intel",
        label_set_code: "ai_sql_categories",
        news_format_code: "company_sql_v1",
        export_category_mode: "news_primary",
        required_content_fields: [],
        allowed_primary_categories: ["AI 应用"],
        secondary_labels_by_primary: {},
        default_category: "AI 应用",
        fallback_category: "AI 应用",
        tagging_stages: ["generation"]
      });
    }
    if (/\/api\/workspaces\/[^/]+\/feedback-policy$/.test(pathname)) {
      return json({ viewer_can_react: true, viewer_can_rate: true, viewer_can_comment: true });
    }
    if (pathname.endsWith("/api/workspaces")) {
      return json(WORKSPACES);
    }
    if (pathname.endsWith("/api/sources")) {
      return json(SOURCES);
    }
    if (/\/api\/sources\/[^/]+$/.test(pathname)) {
      return json(SOURCES[0]);
    }
    return json([]);
  });
}

const ROUTES = [
  "/login",
  "/invite/TESTCODE",
  "/dashboard",
  "/users",
  "/account",
  "/notifications",
  "/sources",
  "/sources/source-1",
  "/ingestion-runs",
  "/news",
  "/recommendations",
  "/daily-reports",
  "/daily-reports/report-1",
  "/daily-reports/report-1/edit",
  "/weekly-reports",
  "/historical-reports",
  "/entity-milestones",
  "/quality-archive",
  "/exports",
  "/requirements",
  "/insights",
  "/tasks",
  "/sync",
  "/workspace-settings",
  "/audit-logs"
];

const VIEWPORTS = [
  { name: "375px", width: 375, height: 812 },
  { name: "1440px", width: 1440, height: 900 }
];

const browser = await chromium.launch();
let failures = 0;

for (const viewport of VIEWPORTS) {
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await stub(page);

  for (const routePath of ROUTES) {
    pageErrors.length = 0;
    try {
      await page.goto(`${baseURL}${routePath}`, { waitUntil: "networkidle", timeout: 20000 });
    } catch (error) {
      console.log(`FAIL ${viewport.name} ${routePath} — 导航失败: ${error.message.split("\n")[0]}`);
      failures += 1;
      continue;
    }
    await page.waitForTimeout(250);
    const metrics = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
      rendered: Boolean(document.querySelector("#app")?.children.length)
    }));
    const overflow = Math.max(metrics.scrollWidth, metrics.bodyScrollWidth) - metrics.clientWidth;
    const ok = overflow <= 1 && metrics.rendered;
    if (!ok) {
      failures += 1;
      console.log(
        `FAIL ${viewport.name} ${routePath} — overflow=${overflow}px rendered=${metrics.rendered}` +
          (pageErrors.length ? ` pageErrors=${pageErrors[0]}` : "")
      );
    } else {
      console.log(`ok   ${viewport.name} ${routePath} (overflow=${overflow}px)` + (pageErrors.length ? ` [pageerror: ${pageErrors[0].slice(0, 80)}]` : ""));
    }
  }
  await context.close();
}

await browser.close();
if (failures > 0) {
  console.log(`\n${failures} 处横滚/渲染失败`);
  process.exit(1);
}
console.log("\n全部路由 375px/1440px 无横滚");
