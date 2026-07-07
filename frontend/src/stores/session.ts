import { defineStore } from "pinia";
import type { Router } from "vue-router";

import { changePassword, fetchMe, login, logout, type SessionUser } from "../api/auth";
import { onUnauthorized } from "../api/http";

export const useSessionStore = defineStore("session", {
  state: () => ({
    user: null as SessionUser | null,
    checked: false,
    loading: false
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.user)
  },
  actions: {
    async loadCurrentUser() {
      this.loading = true;
      try {
        const response = await fetchMe();
        this.user = response.user;
      } catch {
        this.user = null;
      } finally {
        this.checked = true;
        this.loading = false;
      }
    },
    async login(username: string, password: string) {
      this.loading = true;
      try {
        const response = await login(username, password);
        this.user = response.user;
        this.checked = true;
      } finally {
        this.loading = false;
      }
    },
    async logout() {
      await logout();
      this.clear();
    },
    async changePassword(currentPassword: string, newPassword: string) {
      this.loading = true;
      try {
        const response = await changePassword(currentPassword, newPassword);
        this.user = response.user;
        this.checked = true;
      } finally {
        this.loading = false;
      }
    },
    clear() {
      this.user = null;
      this.checked = true;
    }
  }
});

// 匿名可达路由：401 联动时已在这些页面就不再重复跳转（router 守卫各自兜底）。
const UNAUTHENTICATED_SAFE_PATHS = ["/login", "/setup"];

/**
 * 全局 401 联动装配（main.ts 调用）：运行中任何 API 收到 401
 * （/api/auth/login、/api/auth/me 除外，见 api/http.ts 豁免清单）时，
 * 清空 session store 并跳转 /login?redirect=当前路由，登录成功后可回到原页面。
 * 放在 store 模块内而不是 http.ts，是为了让 http.ts 保持零 store/router 依赖。
 */
export function installUnauthorizedRedirect(router: Router): void {
  onUnauthorized(() => {
    const session = useSessionStore();
    session.clear();
    const current = router.currentRoute.value;
    if (
      UNAUTHENTICATED_SAFE_PATHS.includes(current.path) ||
      current.path.startsWith("/invite/")
    ) {
      return;
    }
    void router.push({ path: "/login", query: { redirect: current.fullPath } });
  });
}
