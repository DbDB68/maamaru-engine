<script setup lang="ts">
import { ref } from 'vue'
import PanelHeader from './PanelHeader.vue'
import SideNavItem from './SideNavItem.vue'
import TemplateLab from './TemplateLab.vue'
import FlowLab from './FlowLab.vue'
import RunTimeline from './RunTimeline.vue'

// 顶级页签的可见性由 App.vue 用 template-lab status（开发版且非账房）统一把关；
// 这里只管三个子页签的切换。
const tab = ref<'template' | 'flow' | 'run'>('template')
</script>

<template>
  <section class="devtools-panel">
    <PanelHeader variant="page" title="识别工具" subtitle="从真实画面取样、框选识别范围，再把动作接进流程；跑过的任务一步步回看。" />
    <nav class="dev-tabs" aria-label="识别工具">
      <SideNavItem :active="tab === 'template'" @click="tab = 'template'">模板工坊</SideNavItem>
      <SideNavItem :active="tab === 'flow'" @click="tab = 'flow'">流程工坊</SideNavItem>
      <SideNavItem :active="tab === 'run'" @click="tab = 'run'">跑况时间线</SideNavItem>
    </nav>
    <!-- v-show 不用 v-if：工坊里有没保存的草稿、时间线有跟随状态，切换页签不许丢 -->
    <div v-show="tab === 'template'" class="dev-tab-pane"><TemplateLab /></div>
    <div v-show="tab === 'flow'" class="dev-tab-pane"><FlowLab /></div>
    <div v-show="tab === 'run'" class="dev-tab-pane"><RunTimeline /></div>
  </section>
</template>

<style scoped>
.devtools-panel { min-width: 0; color: var(--ink); }
.dev-tabs { display: flex; gap: 4px; margin: 0 0 14px; }
.dev-tab-pane { min-width: 0; }
</style>
