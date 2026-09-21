<script setup lang="ts">
import { ref } from 'vue'
import PanelHeader from './PanelHeader.vue'
import SideNavItem from './SideNavItem.vue'
import TemplateLab from './TemplateLab.vue'
import FlowLab from './FlowLab.vue'

// 顶级页签的可见性由 App.vue 用 template-lab status（开发版且非账房）统一把关；
// 这里只管两个子页签的切换。
const tab = ref<'template' | 'flow'>('template')
</script>

<template>
  <section class="devtools-panel">
    <PanelHeader variant="page" title="开发工具" subtitle="做模板、拼流程，开发版的私房工具，改完即跑。" />
    <nav class="dev-tabs" aria-label="开发工具">
      <SideNavItem :active="tab === 'template'" @click="tab = 'template'">模板工坊</SideNavItem>
      <SideNavItem :active="tab === 'flow'" @click="tab = 'flow'">流程工坊</SideNavItem>
    </nav>
    <!-- v-show 不用 v-if：两个工坊都有没保存的草稿，切换页签不许丢 -->
    <div v-show="tab === 'template'" class="dev-tab-pane"><TemplateLab /></div>
    <div v-show="tab === 'flow'" class="dev-tab-pane"><FlowLab /></div>
  </section>
</template>

<style scoped>
.devtools-panel { min-width: 0; color: var(--ink); }
.dev-tabs { display: flex; gap: 4px; margin: 0 0 14px; }
.dev-tab-pane { min-width: 0; }
</style>
