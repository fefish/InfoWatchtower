import { defineStore } from "pinia";

import { fetchSetupStatus } from "../api/setup";

export const useSetupStore = defineStore("setup", {
  state: () => ({
    checked: false,
    needsSetup: false,
    loading: false
  }),
  actions: {
    async loadStatus() {
      if (this.checked || this.loading) {
        return;
      }
      this.loading = true;
      try {
        const response = await fetchSetupStatus();
        this.needsSetup = response.needs_setup;
      } catch {
        this.needsSetup = false;
      } finally {
        this.checked = true;
        this.loading = false;
      }
    },
    markComplete() {
      this.needsSetup = false;
      this.checked = true;
    },
    reset() {
      this.checked = false;
      this.needsSetup = false;
      this.loading = false;
    }
  }
});
