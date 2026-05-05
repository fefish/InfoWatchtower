import { defineStore } from "pinia";

import {
  fetchWorkspaces,
  fetchWorkspaceSections,
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
    current: (state) => state.options.find((item) => item.code === state.currentCode)
  },
  actions: {
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
