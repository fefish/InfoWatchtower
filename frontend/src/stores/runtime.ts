import { defineStore } from "pinia";

import {
  fetchRuntime,
  type AuthMembershipMapping,
  type DeployMode,
  type RuntimeCapabilities
} from "../api/meta";

const DEPLOY_MODE_BADGES: Record<DeployMode, string> = {
  standalone: "",
  cloud: "云端",
  intranet: "内网",
  extranet: "外网"
};

function fullCapabilities(): RuntimeCapabilities {
  return { ingestion: true, sync_publisher: true, sync_consumer: true, embedding: true, search: true };
}

function emptyCapabilities(): RuntimeCapabilities {
  return { ingestion: false, sync_publisher: false, sync_consumer: false, embedding: false, search: false };
}

function emptyAuthMembershipMapping(): AuthMembershipMapping {
  return { status: "empty", default_workspaces: [], department_workspaces: [] };
}

export const useRuntimeStore = defineStore("runtime", {
  state: () => ({
    checked: false,
    loading: false,
    metaError: false,
    deployMode: "standalone" as DeployMode,
    instanceId: "",
    authMode: "public_password",
    appVersion: "",
    authMembershipMapping: emptyAuthMembershipMapping(),
    capabilities: fullCapabilities()
  }),
  getters: {
    canIngest: (state) => state.capabilities.ingestion,
    isSyncConsumer: (state) => state.capabilities.sync_consumer,
    deployModeBadge: (state) => DEPLOY_MODE_BADGES[state.deployMode] ?? ""
  },
  actions: {
    async load() {
      if (this.checked || this.loading) {
        return;
      }
      this.loading = true;
      try {
        const runtime = await fetchRuntime();
        this.deployMode = runtime.deploy_mode;
        this.instanceId = runtime.instance_id;
        this.authMode = runtime.auth_mode;
        this.appVersion = runtime.app_version;
        this.authMembershipMapping = runtime.auth_membership_mapping ?? emptyAuthMembershipMapping();
        this.capabilities = { ...runtime.capabilities };
        this.metaError = false;
      } catch {
        // meta 接口失败时保守禁用全部能力（fail-closed），防止 intranet 等受限形态误放开采集入口；
        // 界面据 metaError 提示"运行时信息加载失败"并提供重试（reload）。
        this.metaError = true;
        this.deployMode = "standalone";
        this.authMode = "public_password";
        this.authMembershipMapping = emptyAuthMembershipMapping();
        this.capabilities = emptyCapabilities();
      } finally {
        this.checked = true;
        this.loading = false;
      }
    },
    async reload() {
      // 手动重试入口：重置 checked 后重新拉取 meta。
      if (this.loading) {
        return;
      }
      this.checked = false;
      await this.load();
    }
  }
});
