import { defineStore } from "pinia";

import { changePassword, fetchMe, login, logout, type SessionUser } from "../api/auth";

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
