<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'

const entries = ref<any[]>([])
const raw = ref(false)
const showProcess = ref(false)
const autoScroll = ref(true)
const list = ref<HTMLElement | null>(null)
let source: EventSource | null = null

const visibleEntries = computed(() => entries.value.filter(entry => raw.value || showProcess.value || !/^\[(?:NAV|ADB|MAA)\]/.test(entry.message)))

const scriptNames: Record<string, string> = {
  daily: '一键日课', pumpkin: '南瓜', raid: '联队战', sortie: '合战场',
  yosari: '异去', osaka: '挖地', expedition: '远征', practice: '演练', smith: '锻刀',
  sakura: '刷花', sugar: '炼糖', repair: '手入', snapshot: '库存',
  scheduler: '排班', system: '系统',
}

function clean(message: string) {
  return raw.value ? message : String(message).replace(/^\[[^\]]+\]\s*/, '')
}
function scriptName(script: string) { return raw.value ? script : (scriptNames[script] || script) }
function time(ts: number) { return ts ? new Date(ts * 1000).toLocaleTimeString() : '' }
function level(message: string) {
  if (/🛑|✗|翻车|异常退出/.test(message)) return 'bad'
  if (/⚠/.test(message)) return 'warn'
  if (/✓|✅|完成|成功|已领/.test(message)) return 'ok'
  return ''
}
function exportDiagnostics() { window.location.assign('/api/diagnostics/export') }
async function scrollEnd() { await nextTick(); if (autoScroll.value) list.value?.scrollTo({ top: list.value.scrollHeight }) }
async function load() { entries.value = (await api.logs()).logs || []; scrollEnd() }
function connect() {
  source = new EventSource('/api/logs/stream')
  source.onmessage = event => {
    if (!event.data) return
    try {
      const entry = JSON.parse(event.data)
      entries.value.push(entry)
      if (entries.value.length > 500) entries.value.shift()
      if (entry.script === 'scheduler' && String(entry.message || '').startsWith('⏳')) {
        window.dispatchEvent(new CustomEvent('maamaru:scheduler-warning', { detail: entry.message }))
      }
      scrollEnd()
    } catch (_) {}
  }
  source.onerror = () => { source?.close(); source = null; window.setTimeout(connect, 3000) }
}
onMounted(() => { load(); connect() })
onBeforeUnmount(() => source?.close())
</script>

<template>
  <section class="log-panel" :class="raw ? 'raw-mode' : 'visual-mode'">
    <PanelHeader title="日志" :subtitle="`${visibleEntries.length} 条`">
      <template #actions>
      <div class="head-actions">
        <button class="secondary" :class="{ active: !raw }" @click="raw = false">可视化</button>
        <button class="secondary" :class="{ active: raw }" @click="raw = true">源码日志</button>
        <button v-if="!raw" class="secondary" :class="{ active: showProcess }" @click="showProcess = !showProcess">过程</button>
        <button class="secondary" @click="entries = []">清屏</button>
        <button class="secondary" :class="{ active: autoScroll }" @click="autoScroll = !autoScroll">自动滚动</button>
        <button class="secondary" title="导出可直接附在 Issue 中的安全诊断包" @click="exportDiagnostics">排错包</button>
      </div>
      </template>
    </PanelHeader>
    <div ref="list" class="log-list">
      <div v-for="entry in visibleEntries" :key="entry.id" class="log-row" :class="level(entry.message)">
        <time>{{ time(entry.ts) }}</time><b>{{ scriptName(entry.script) }}</b><span>{{ clean(entry.message) }}</span>
      </div>
    </div>
    <footer class="log-status-bar"><span>{{ visibleEntries.length }} 条进度</span><span>● 空闲</span></footer>
  </section>
</template>
