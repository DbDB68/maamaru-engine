<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
import ReportPanel from './components/ReportPanel.vue'
import PlanningPanel from './components/report/PlanningPanel.vue'
import StyleLab from './components/StyleLab.vue'
import SegmentedControl from './components/SegmentedControl.vue'
import FoxClerk from './components/FoxClerk.vue'
import { foxMood } from './foxMood'

const loading = ref(true)
const message = ref('')
const theme = ref<'washi' | 'pixel'>('washi')
const tab = ref<'report' | 'planning' | 'lab'>('report')

const tabItems = [
  { value: 'report', label: '成绩单' },
  { value: 'planning', label: '规划' },
  { value: 'lab', label: '试验田' },
]

function applyTheme() { document.body.dataset.theme = theme.value }
async function toggleTheme() {
  theme.value = theme.value === 'washi' ? 'pixel' : 'washi'
  applyTheme()
  await api.saveTheme(theme.value).catch(() => {})
}

async function load() {
  try {
    const [mode, saved] = await Promise.all([
      api.appMode().catch(() => ({ mode: 'ledger' as const })),
      api.settings().catch((): { theme?: string } => ({ theme: 'washi' })),
    ])
    if (mode.mode !== 'ledger') {
      message.value = '当前后端不是账房模式，页面可能不可用。'
    }
    theme.value = saved.theme === 'pixel' ? 'pixel' : 'washi'
    applyTheme()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '账房初始化失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="shell ledger-mode">
    <section class="honmaru-stage" aria-label="账房舞台">
      <div class="stage-brand"><strong>まあ丸</strong><small>纯净本丸账房</small></div>
      <span class="stage-seal" aria-hidden="true">账</span>
      <FoxClerk class="stage-fox" :action="foxMood" />
      <div class="stage-status">
        <small>本丸账房</small>
        <strong>今天只算账</strong>
        <span>不连接游戏 · 手动记录与规划</span>
      </div>
    </section>
    <header class="topbar">
      <nav class="topnav">
        <SegmentedControl
          class="ledger-tab-switch"
          :model-value="tab"
          :items="tabItems"
          label="账房主标签"
          variant="wide"
          @update:model-value="tab = $event as 'report' | 'planning' | 'lab'"
        />
      </nav>
      <div class="top-status">
        <i></i><span>纯净模式</span>
        <button
          class="theme-button"
          :title="theme === 'washi' ? '切换像素主题' : '切换和纸主题'"
          :aria-label="theme === 'washi' ? '切换像素主题' : '切换和纸主题'"
          @click="toggleTheme"
        ></button>
      </div>
    </header>
    <main v-if="!loading" class="single-layout report-page">
      <p v-if="message" class="report-error">{{ message }}</p>
      <Transition name="tab-swap" mode="out-in">
        <ReportPanel v-if="tab === 'report'" />
        <StyleLab v-else-if="tab === 'lab'" />
        <PlanningPanel v-else />
      </Transition>
    </main>
    <div v-else class="single-layout report-page loading">正在整理账房……</div>
  </div>
</template>

<style scoped>
.ledger-tab-switch {
  margin-bottom: -1px;
}
.loading {
  display: grid;
  place-items: center;
  color: var(--ink-dim);
  font-family: var(--pixel-font);
}
.tab-swap-enter-active,
.tab-swap-leave-active {
  transition: opacity .18s ease, transform .18s ease;
}
.tab-swap-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.tab-swap-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
@media (prefers-reduced-motion: reduce) {
  .tab-swap-enter-active,
  .tab-swap-leave-active {
    transition: none;
  }
}
</style>
