import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// 布局模板与间距系统看护（frontend-product-design §9 / page-specs §1.1、§3）。
// §3 逐页总表是唯一事实源：每个 AppShell 业务页必须在根容器声明所属模板类；
// /login、/setup、/invite/:code 在 AppShell 之外，标注 auth 居中窄卡布局，不占用四模板。
// WorkspaceSettingsPage 归 Wave2（WP3-H）迁移 layout-settings，迁移前保持 .module-page 别名容器。

const pagesDir = dirname(fileURLToPath(import.meta.url));

function pageSource(name: string): string {
  return readFileSync(join(pagesDir, name), "utf-8");
}

const TEMPLATE_BY_PAGE: Record<string, string> = {
  // dashboard 模板
  "DashboardPage.vue": "layout-dashboard",
  // list 模板
  "SourcesPage.vue": "layout-list", // list*：唯一允许固定侧栏例外（标签策略面板，AGENTS 保护线）
  "IngestionRunsPage.vue": "layout-list",
  "NewsPage.vue": "layout-list",
  "RecommendationsPage.vue": "layout-list",
  "DailyReportsPage.vue": "layout-list",
  "WeeklyReportsPage.vue": "layout-list",
  "HistoricalReportsPage.vue": "layout-list",
  "EntityMilestonesPage.vue": "layout-list",
  "QualityArchivePage.vue": "layout-list",
  "InsightsPage.vue": "layout-list",
  "RequirementsPage.vue": "layout-list",
  "TopicTasksPage.vue": "layout-list",
  "SyncRunsPage.vue": "layout-list",
  "ExportsPage.vue": "layout-list",
  "AuditLogsPage.vue": "layout-list",
  "NotificationsPage.vue": "layout-list",
  // detail 模板
  "SourceDetailPage.vue": "layout-detail",
  "DailyReportDetailPage.vue": "layout-detail",
  // settings 模板
  "UsersPage.vue": "layout-settings",
  "AccountPage.vue": "layout-settings"
};

const AUTH_PAGES = ["LoginPage.vue", "SetupPage.vue", "InvitePage.vue"];

describe("布局模板归位（page-specs §3 总表）", () => {
  for (const [page, template] of Object.entries(TEMPLATE_BY_PAGE)) {
    it(`${page} 声明 ${template} 模板容器`, () => {
      const source = pageSource(page);
      const classAttrs = source.match(/class="[^"]*"/g) ?? [];
      const declared = classAttrs.filter((attr) => attr.includes(template));
      expect(declared.length, `${page} 缺少 ${template} 容器类`).toBeGreaterThan(0);
      // 不允许同页声明第二种模板
      for (const other of ["layout-list", "layout-detail", "layout-dashboard", "layout-settings"]) {
        if (other === template) continue;
        expect(source.includes(other), `${page} 混入了 ${other}`).toBe(false);
      }
    });
  }

  it("auth 页保持居中窄卡布局，不占用四模板", () => {
    for (const page of AUTH_PAGES) {
      const source = pageSource(page);
      expect(source).toContain('class="login-page"');
      expect(source).not.toMatch(/layout-(list|detail|dashboard|settings)/);
    }
  });

  it("WorkspaceSettingsPage 迁移前保持 module-page 别名容器（Wave2 归位 layout-settings）", () => {
    const source = pageSource("WorkspaceSettingsPage.vue");
    expect(source).toContain('class="module-page workspace-settings-page"');
  });
});

describe("间距 tokens 与页面容器（frontend-product-design §9.1/§9.2）", () => {
  const baseCss = readFileSync(join(pagesDir, "..", "styles", "base.css"), "utf-8");

  it("定义 §9.1 的 7 档 spacing token", () => {
    expect(baseCss).toContain("--space-page-x: 28px");
    expect(baseCss).toContain("--space-page-y: 24px");
    expect(baseCss).toContain("--space-section: 32px");
    expect(baseCss).toContain("--space-card: 20px");
    expect(baseCss).toContain("--space-card-pad: 20px");
    expect(baseCss).toContain("--space-inline: 12px");
    expect(baseCss).toContain("--space-control: 8px");
  });

  it("四个模板类共用同一 1200px 页面容器定义（容器属性只有一处定义）", () => {
    const containerRule = baseCss.match(
      /\.layout-list,\n\.layout-detail,\n\.layout-dashboard,\n\.layout-settings,\n\.module-page \{[^}]+\}/
    );
    expect(containerRule).not.toBeNull();
    expect(containerRule![0]).toContain("max-width: 1200px");
    expect(containerRule![0]).toContain("padding: var(--space-page-y) var(--space-page-x)");
    expect(containerRule![0]).toContain("gap: var(--space-section)");
    // 旧的自定容器宽度不再各自定义
    expect(baseCss).not.toContain("min(1320px, calc(100% - 48px))");
  });

  it("两种列结构：单列与主列+340px 固定侧栏（≤1120px 堆叠）", () => {
    expect(baseCss).toContain("grid-template-columns: minmax(0, 1fr) 340px");
    const stackBreak = baseCss.match(/@media \(max-width: 1120px\) \{\s*\.layout-columns \{[^}]+\}/);
    expect(stackBreak).not.toBeNull();
    expect(stackBreak![0]).toContain("grid-template-columns: minmax(0, 1fr)");
  });

  it("≤860px 窄屏把 --space-page-x 降为 16px", () => {
    const narrow = baseCss.match(/@media \(max-width: 860px\) \{\s*:root \{\s*--space-page-x: 16px;/);
    expect(narrow).not.toBeNull();
  });

  it("settings 模板内容窄列 max-width 860px 居中", () => {
    const settingsRule = baseCss.match(/\.layout-settings > \* \{[^}]+\}/);
    expect(settingsRule).not.toBeNull();
    expect(settingsRule![0]).toContain("max-width: 860px");
  });
});
