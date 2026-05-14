<script setup lang="ts">
import { CheckCircle2, Construction, GitBranch, ShieldCheck } from "lucide-vue-next";

defineProps<{
  title: string;
  subtitle: string;
  stage: string;
  capabilities: string[];
  nextSteps: string[];
}>();
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">{{ stage }}</p>
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>
      </div>
      <span class="roadmap-status">
        <Construction :size="17" />
        后续建设
      </span>
    </header>

    <section class="module-grid two">
      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Product Contract</p>
            <h3>页面要承载的能力</h3>
          </div>
          <ShieldCheck :size="20" />
        </div>
        <ul class="module-checklist">
          <li v-for="item in capabilities" :key="item">
            <CheckCircle2 :size="16" />
            <span>{{ item }}</span>
          </li>
        </ul>
      </article>

      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Implementation Queue</p>
            <h3>后续接口与前端任务</h3>
          </div>
          <GitBranch :size="20" />
        </div>
        <ol class="module-timeline">
          <li v-for="item in nextSteps" :key="item">
            <span></span>
            <p>{{ item }}</p>
          </li>
        </ol>
      </article>
    </section>
  </section>
</template>
