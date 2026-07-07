import { defineStore } from "pinia";

import { HttpError } from "../api/http";
import {
  fetchRuntime,
  type AuthMembershipMapping,
  type DeployMode,
  type RuntimeCapabilities
} from "../api/meta";

/** meta 失败的可诊断分类：stale-backend=后端活着但没有 /api/meta/runtime（版本过旧）；unreachable=网络层失败。 */
export type MetaErrorKind = "stale-backend" | "unreachable" | "http-error";

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
    metaErrorKind: null as MetaErrorKind | null,
    metaErrorStatus: null as number | null,
    deployMode: "standalone" as DeployMode,
    instanceId: "",
    authMode: "public_password",
    authGuestEnabled: false,
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
        this.authGuestEnabled = runtime.auth_guest_enabled ?? false;
        this.appVersion = runtime.app_version;
        this.authMembershipMapping = runtime.auth_membership_mapping ?? emptyAuthMembershipMapping();
        this.capabilities = { ...runtime.capabilities };
        this.metaError = false;
        this.metaErrorKind = null;
        this.metaErrorStatus = null;
      } catch (error) {
        // meta 接口失败时保守禁用全部能力（fail-closed），防止 intranet 等受限形态误放开采集入口。
        // 失败必须可诊断：404 几乎总是"前端新、后端旧"（后端进程/镜像没随代码更新，缺 /api/meta/runtime 路由），
        // 提示重启/重建后端而不是让用户对着"加载失败"抓瞎。
        this.metaError = true;
        if (error instanceof HttpError) {
          this.metaErrorStatus = error.status;
          this.metaErrorKind = error.status === 404 ? "stale-backend" : "http-error";
        } else {
          this.metaErrorStatus = null;
          this.metaErrorKind = "unreachable";
        }
        this.deployMode = "standalone";
        this.authMode = "public_password";
        this.authGuestEnabled = false;
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
