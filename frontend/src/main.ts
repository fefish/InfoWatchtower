import "element-plus/dist/index.css";
import "./styles/base.css";

import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { router } from "./router";
import { installUnauthorizedRedirect } from "./stores/session";

const app = createApp(App);

app.use(createPinia());
app.use(router);
// 全局 401 联动：session 过期时清空登录态并带 redirect 跳回登录页（api/http.ts onUnauthorized）。
installUnauthorizedRedirect(router);
app.mount("#app");
