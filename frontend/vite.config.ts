import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";
// 子路径部署（docs/deployment/deployment-topology.md §4.1）：门户以 /watchtower/ 等前缀承载前端时，
// 构建时传 VITE_BASE_PATH，静态资源、router history 与 API 前缀（api/http.ts 的 apiUrl）随之生效。
const basePath = process.env.VITE_BASE_PATH ?? "/";

export default defineConfig({
  base: basePath,
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      "/api": apiProxyTarget,
      "/healthz": apiProxyTarget
    }
  }
});
