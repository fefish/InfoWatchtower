import { expect, test, type Page } from "@playwright/test";

// 首批 smoke：全部经 page.route 打桩 /api/**，验证浏览器里的真实路由/渲染/形态开关，
// 不依赖后端进程。真实后端旅程（登录→抓取→日报→导出）后续按 C-8 backlog 扩展。

const RUNTIME_STANDALONE = {
  deploy_mode: "standalone",
  instance_id: "e2e-smoke",
  auth_mode: "public_password",
  app_version: "e2e",
  capabilities: {
    ingestion: true,
    sync_publisher: true,
    sync_consumer: true,
    embedding: true,
    search: true
  },
  auth_membership_mapping: {
    status: "empty",
    default_workspaces: [],
    department_workspaces: []
  }
};

const RUNTIME_INTRANET = {
  ...RUNTIME_STANDALONE,
  deploy_mode: "intranet",
  auth_mode: "intranet_header",
  capabilities: {
    ingestion: false,
    sync_publisher: false,
    sync_consumer: true,
    embedding: false,
    search: true
  }
};

const SESSION_USER = {
  id: "user-e2e",
  external_provider: "local",
  external_id: "admin",
  employee_no: null,
  username: "admin",
  display_name: "e2e 管理员",
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
    description: "e2e smoke 工作台",
    workspace_type: "team",
    default_domain_code: "ai",
    enabled: true,
    current_user_workspace_role: "owner"
  }
];

const SECTIONS = [
  {
    section_key: "dashboard",
    name: "今日速览",
    section_type: "core",
    route_path: "/dashboard",
    sort_order: 1,
    enabled: true,
    group: "today"
  },
  {
    section_key: "source_management",
    name: "数据源管理",
    section_type: "core",
    route_path: "/sources",
    sort_order: 2,
    enabled: true,
    group: "collect"
  },
  {
    section_key: "ingestion_coverage",
    name: "抓取与覆盖",
    section_type: "core",
    route_path: "/ingestion-runs",
    sort_order: 3,
    enabled: true,
    group: "collect"
  }
];

const IMPORT_PREVIEW = {
  catalog: "legacy",
  total: 361,
  would_create: 294,
  would_update: 67,
  samples: [{ name: "OpenAI Blog", source_type: "rss", url: "https://openai.com/blog/rss.xml" }]
};

type StubOptions = {
  runtime?: typeof RUNTIME_STANDALONE;
  authenticated?: boolean;
};

/** 按 pathname 打桩全部 /api/**；未命中的 GET 回空对象，防止悬挂请求拖垮测试。 */
async function stubApi(page: Page, options: StubOptions = {}) {
  const runtime = options.runtime ?? RUNTIME_STANDALONE;
  const authenticated = options.authenticated ?? true;

  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const fulfillJson = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (pathname.endsWith("/api/setup/status")) {
      return fulfillJson({ needs_setup: false });
    }
    if (pathname.endsWith("/api/meta/runtime")) {
      return fulfillJson(runtime);
    }
    if (pathname.endsWith("/api/auth/me")) {
      return authenticated
        ? fulfillJson({ user: SESSION_USER })
        : fulfillJson({ detail: "unauthenticated" }, 401);
    }
    if (/\/api\/workspaces\/[^/]+\/sections$/.test(pathname)) {
      return fulfillJson(SECTIONS);
    }
    if (/\/api\/workspaces\/[^/]+\/label-policy$/.test(pathname)) {
      return fulfillJson({
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
    if (pathname.endsWith("/api/workspaces")) {
      return fulfillJson(WORKSPACES);
    }
    if (pathname.endsWith("/api/notifications/unread-count")) {
      return fulfillJson({ unread_count: 0 });
    }
    if (pathname.endsWith("/api/sources/import-preview")) {
      return fulfillJson(IMPORT_PREVIEW);
    }
    if (pathname.endsWith("/api/sources")) {
      return fulfillJson([]);
    }
    if (pathname.endsWith("/api/ingestion/runs")) {
      return fulfillJson([]);
    }
    if (pathname.includes("/api/ingestion/")) {
      // coverage / trends / scheduler / failed-source-retry-summary 等页面自带兜底，空对象即可。
      return fulfillJson({});
    }
    return fulfillJson({});
  });
}

test("登录页可达并展示账号密码表单", async ({ page }) => {
  await stubApi(page, { authenticated: false });

  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "登录工作台" })).toBeVisible();
  await expect(page.locator('input[autocomplete="username"]')).toBeVisible();
  await expect(page.locator('input[autocomplete="current-password"]')).toBeVisible();
  await expect(page.getByRole("button", { name: /进入/ })).toBeEnabled();
});

test("数据源页导入数据先弹出导入预览", async ({ page }) => {
  await stubApi(page);

  await page.goto("/sources");
  await page.getByRole("button", { name: /导入数据/ }).click();

  const previewPanel = page.locator('[aria-label="数据源导入预览"]');
  await expect(previewPanel).toBeVisible();
  await expect(previewPanel).toContainText("导入预览");
  await expect(previewPanel).toContainText("361");
  await expect(previewPanel.getByRole("button", { name: /确认导入/ })).toBeVisible();
});

test("intranet 形态下抓取入口与导航隐藏", async ({ page }) => {
  await stubApi(page, { runtime: RUNTIME_INTRANET });

  await page.goto("/ingestion-runs");

  // 顶栏出现「内网」形态徽标，采集入口被运行时能力开关关掉。
  await expect(page.locator(".deploy-badge")).toHaveText("内网");
  await expect(page.locator('nav[aria-label="主导航"]')).not.toContainText("抓取与覆盖");
  await expect(page.getByRole("button", { name: /运行抓取/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /运行补采/ })).toHaveCount(0);
});
