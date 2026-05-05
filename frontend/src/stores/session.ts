import { defineStore } from "pinia";

type UserRole = "super_admin" | "editor_admin" | "analyst" | "viewer";

interface SessionUser {
  id: string;
  displayName: string;
  roles: UserRole[];
}

export const useSessionStore = defineStore("session", {
  state: () => ({
    user: null as SessionUser | null
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.user)
  },
  actions: {
    setDemoUser() {
      this.user = {
        id: "demo-admin",
        displayName: "规划部管理员",
        roles: ["super_admin"]
      };
    },
    clear() {
      this.user = null;
    }
  }
});
