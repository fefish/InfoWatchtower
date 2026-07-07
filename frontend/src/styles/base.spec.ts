/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// 全页边距审计（2026-07）的回归锚点：
// 页面模板里使用的布局/反馈类必须在 base.css 有定义，
// 否则会退回浏览器默认样式，出现“裸表单 / 无边距 / 无配色”的退化。
// vitest 的 css 处理会把 `?raw` 导入吞成空串，这里直接读源文件。
const css = readFileSync(resolve(process.cwd(), "src/styles/base.css"), "utf-8");

describe("base.css 布局与反馈类基线", () => {
  it.each([
    // 表单反馈条：error/success/info/warning 四态齐全
    ".form-error",
    ".form-success",
    ".form-info",
    ".form-warning",
    // 用户/邀请/组等裸 form-grid-two 表单的输入基线
    ".form-grid-two > label",
    // SQL 导出导入回执表单
    ".receipt-form",
    ".form-grid",
    ".receipt-failure-row",
    ".receipt-list",
    // 洞察研判筛选工具条与行内编辑
    ".toolbar-card",
    ".insight-row.anchored",
    // 任务详情弹层胶囊与正文滚动
    ".headline-chip-row .chip-blue",
    ".headline-chip-row .chip-orange",
    ".task-detail-body",
    // 推荐评分预览与数据源导入预览
    ".preview-result",
    ".preview-metrics",
    ".source-page-grid.single-column",
    // 行内登记事件表单按钮不整行拉伸
    ".inline-milestone-form .icon-button"
  ])("定义了 %s", (selector) => {
    expect(css).toContain(selector);
  });

  it("ops-row 两子元素行使用 minmax(0,1fr) auto 两列模板", () => {
    const match = css.match(
      /\.topic-task-row,\s*\.requirement-row,\s*\.insight-row,\s*\.implication-row\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto/
    );
    expect(match).not.toBeNull();
  });

  it("平板图标栏侧边栏限定在 901-1120px，不再覆盖 ≤900px 的横向侧边栏", () => {
    expect(css).toContain("@media (min-width: 901px) and (max-width: 1120px)");
  });

  it("窄屏 topbar 标题列锁回容器宽，长副标题省略而不是撑出横滚", () => {
    expect(css).toMatch(/\.topbar-subtitle\s*\{[^}]*min-width:\s*0/);
  });

  it("candidate/recommendation 卡片主体锁单列 minmax(0,1fr)，长指标行不得撑破卡片", () => {
    expect(css).toMatch(
      /\.candidate-body,\s*\.recommendation-body,\s*\.detail-news-body\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/
    );
  });
});
