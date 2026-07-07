# 前端浏览器 e2e（Playwright）

浏览器级 e2e 脚手架，对应部署拓扑文档的 C-8 backlog。当前首批 smoke 全部用
`page.route` 打桩 `/api/**`，验证真实浏览器里的路由、渲染和部署形态开关，不依赖后端进程。

## 本地运行

```bash
cd frontend
npm install                       # 安装 @playwright/test 等依赖
npx playwright install chromium   # 首次运行需下载浏览器（内网环境需配代理或离线包）
npm run e2e                       # 自动拉起 vite dev（127.0.0.1:5173）并执行 e2e/ 下用例
```

仓库根也提供 `make e2e`（install chromium + playwright test 的组合），是**可选 target**：
不进 `make test` 与 CI 门禁，原因是 chromium 首次需 ~100MB 下载且耗时（见根 Makefile 注释）。

- `playwright.config.ts` 的 `webServer` 会自动启动 `npm run dev`；本地已开着 dev server 时会直接复用。
- stub 回调里只拦截 `pathname` 以 `/api/` 开头的请求：glob `**/api/**` 也会命中 vite
  的源码模块 URL（如 `/src/api/http.ts`），这类请求必须 `route.fallback()` 放行，
  否则 JSON stub 顶掉 JS 模块导致整页白屏（2026-07 首次真跑踩过的坑）。
- 单跑某条用例：`npm run e2e -- --grep 登录页`。
- 带界面调试：`npm run e2e -- --headed` 或 `npx playwright test --ui`。

## 现有用例（e2e/smoke.e2e.ts）

1. 登录页可达：账号/密码表单与提交按钮可见。
2. 数据源页「导入数据」先弹导入预览面板（识别记录数、确认导入按钮），不直接落库。
3. `/api/meta/runtime` 返回 intranet 形态时：顶栏出现「内网」徽标，抓取导航与运行抓取/补采按钮全部隐藏。

## 约定

- e2e 用例统一命名 `*.e2e.ts`（`playwright.config.ts` 的 `testMatch` 已锁定）：Vitest 只收集
  `**/*.spec.ts`，两边互不误收集，`npx vitest run` 不会碰到 Playwright 用例。
- 打桩数据尽量贴近后端 schema（字段名与 `src/api/*.ts` 的类型一致），避免测过界面测不出契约漂移。
- CI 接线（独立 job、浏览器缓存、失败工件上传）由部署/文档侧统一处理，本目录不写 CI 配置。
