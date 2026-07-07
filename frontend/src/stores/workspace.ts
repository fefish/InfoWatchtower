import { defineStore } from "pinia";

import {
  createWorkspace,
  fetchWorkspaces,
  fetchWorkspaceSections,
  type WorkspaceCreatePayload,
  type WorkspaceRecord,
  type WorkspaceSectionRecord
} from "../api/workspaces";

export const useWorkspaceStore = defineStore("workspace", {
  state: () => ({
    currentCode: "",
    options: [] as WorkspaceRecord[],
    sections: [] as WorkspaceSectionRecord[],
    loading: false,
    error: ""
  }),
  getters: {
    current: (state) => state.options.find((item) => item.code === state.currentCode),
    // 当前工作台角色（viewer/member/admin/owner），未加载或无 membership 时为 null。
    // super_admin 后端会折算成 owner（见 workspaces 路由 _current_workspace_role）。
    currentRole(): string | null {
      return this.current?.current_user_workspace_role ?? null;
    }
  },
  actions: {
    // 路由守卫用：只在还没加载过工作台列表时加载一次，避免每次导航重复请求。
    async ensureLoaded() {
      if (this.options.length > 0 || this.loading) {
        return;
      }
      await this.loadWorkspaces();
    },
    async loadWorkspaces() {
      this.loading = true;
      this.error = "";
      try {
        const options = await fetchWorkspaces();
        this.options = options;
        if (!options.some((item) => item.code === this.currentCode)) {
          this.currentCode = options[0]?.code ?? "";
        }
        await this.loadSections();
      } catch (exc) {
        this.error = exc instanceof Error ? exc.message : "加载工作台失败";
        this.options = [];
        this.sections = [];
      } finally {
        this.loading = false;
      }
    },
    async loadSections(code?: string) {
      const targetCode = code ?? this.currentCode;
      if (!targetCode) {
        this.sections = [];
        return;
      }
      this.sections = await fetchWorkspaceSections(targetCode);
    },
    async createWorkspace(payload: WorkspaceCreatePayload) {
      const created = await createWorkspace(payload);
      this.options = await fetchWorkspaces();
      this.currentCode = created.code;
      await this.loadSections(created.code);
      return created;
    },
    async setWorkspace(code: string) {
      if (!this.options.some((item) => item.code === code)) {
        return;
      }
      this.currentCode = code;
      this.error = "";
      try {
        await this.loadSections(code);
      } catch (exc) {
        this.error = exc instanceof Error ? exc.message : "加载工作台页面失败";
        this.sections = [];
      }
    }
  }
});
