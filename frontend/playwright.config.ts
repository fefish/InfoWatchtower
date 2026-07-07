import { defineConfig, devices } from "@playwright/test";

// 浏览器级 e2e 脚手架（docs/deployment/deployment-topology.md C-8）。
// 首次运行前需要下载浏览器：npx playwright install chromium（见 e2e/README.md）。
// smoke 用 page.route 打桩 /api/**，不依赖真实后端；后续接真实后端旅程时再扩 webServer。
export default defineConfig({
  testDir: "./e2e",
  // e2e 用例统一命名 *.e2e.ts：与 Vitest 的 **/*.spec.ts 收集规则彻底分离，互不误收集。
  testMatch: /.*\.e2e\.ts$/,
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry"
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ],
  webServer: {
    command: "npm run dev -- --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000
  }
});
