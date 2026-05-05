import { defineStore } from "pinia";

export interface WorkspaceOption {
  code: string;
  name: string;
  description: string;
  extraModules: "tools"[];
}

const workspaceOptions: WorkspaceOption[] = [
  {
    code: "planning_intel",
    name: "规划部情报工作台",
    description: "行业信号、日报周报、专题洞察和内部需求闭环",
    extraModules: []
  },
  {
    code: "ai_tools",
    name: "AI 工具桌面",
    description: "同一套情报日报周报能力下，叠加 AI 工具目录和运行入口",
    extraModules: ["tools"]
  }
];

export const useWorkspaceStore = defineStore("workspace", {
  state: () => ({
    currentCode: "planning_intel",
    options: workspaceOptions
  }),
  getters: {
    current: (state) => state.options.find((item) => item.code === state.currentCode)
  },
  actions: {
    setWorkspace(code: string) {
      if (this.options.some((item) => item.code === code)) {
        this.currentCode = code;
      }
    }
  }
});
