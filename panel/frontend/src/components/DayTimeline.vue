<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import type { DayTimeline } from '../types'
import PaperCard from './PaperCard.vue'

const DAY = 1440
const data = ref<DayTimeline | null>(null)
let timer: number | undefined

async function load() {
  try {
    data.value = await api.dayTimeline()
  } catch {
    /* 静默失败，下轮轮询再试 */
  }
}

onMounted(() => {
  load()
  timer = window.setInterval(load, 30000)
})
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})

const TICKS = [0, 240, 480, 720, 960, 1200, 1440]

const TEAM_NAMES: Record<number, string> = { 1: '一', 2: '二', 3: '三', 4: '四', 5: '五' }

const STATE_LABELS: Record<string, string> = {
  pending: '待派出',
  waiting_busy: '等空位',
  waiting_unknown: '等确认',
  ready: '可派出',
  dispatched: '已派出',
  expired: '已跳过',
  missed: '已错过',
  failed_unknown: '待确认',
}

const STATE_CLASSES: Record<string, string> = {
  pending: 'is-pending',
  waiting_busy: 'is-waiting',
  waiting_unknown: 'is-waiting',
  ready: 'is-ready',
  dispatched: 'is-done',
  expired: 'is-expired',
  missed: 'is-missed',
  failed_unknown: 'is-failed',
}

const TONE_LABELS: Record<string, string> = {
  ok: '顺利完成',
  failed: '翻车',
  stopped: '被叫停',
  running: '正在跑',
}

function pct(min: number): number {
  return Math.min(100, Math.max(0, (min / DAY) * 100))
}

function fmtMin(min: number): string {
  const h = Math.floor(min / 60)
  const m = Math.floor(min % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function fmtTs(ts: number): string {
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function tickLabel(min: number): string {
  return min === DAY ? '24:00' : `${min / 60}:00`
}

function durationText(min: number): string {
  if (min <= 0) return ''
  return min >= 60 ? `${Math.floor(min / 60)}h${String(min % 60).padStart(2, '0')}分` : `${min}分`
}

const nowMin = computed(() => {
  if (!data.value) return 0
  return Math.min(DAY, Math.max(0, (data.value.now - data.value.day_start) / 60))
})

const expeditionBlocks = computed(() => {
  if (!data.value) return []
  return data.value.expeditions.map((e) => {
    const team = TEAM_NAMES[e.team_no] ?? String(e.team_no)
    const stateLabel = STATE_LABELS[e.state] ?? e.state
    const bits = [`${fmtMin(e.time_min)} 部队${team} ${e.map_code}`]
    if (e.duration_min) bits[0] += `（${durationText(e.duration_min)}）`
    bits.push(stateLabel)
    if (e.late_min && e.state === 'dispatched') bits.push(`晚${e.late_min}分钟`)
    if (e.blocked_reason) bits.push(e.blocked_reason)
    if (!e.enabled) bits.push('未启用')
    return {
      key: `${e.time_min}-${e.team_no}-${e.map_code}`,
      left: pct(e.time_min),
      width: Math.max(pct(Math.max(e.duration_min, 10)), 0.7),
      cls: [STATE_CLASSES[e.state] ?? 'is-pending', e.enabled ? '' : 'is-disabled'],
      title: bits.join(' · '),
      text: e.map_code,
    }
  })
})

const runBlocks = computed(() => {
  if (!data.value) return []
  const dayStart = data.value.day_start
  return data.value.runs.map((r, i) => {
    const start = Math.min(DAY, Math.max(0, ((r.started_at - dayStart) / 60)))
    const end = r.ended_at
      ? Math.min(DAY, Math.max(start, (r.ended_at - dayStart) / 60))
      : nowMin.value
    const range = r.ended_at
      ? `${fmtTs(r.started_at)}–${fmtTs(r.ended_at)}`
      : r.tone === 'running'
        ? `${fmtTs(r.started_at)}–进行中`
        : `${fmtTs(r.started_at)}–记录中断`
    return {
      key: `${r.script}-${i}`,
      left: pct(start),
      width: Math.max(pct(Math.max(end - start, 4)), 0.7),
      cls: `is-${r.tone}`,
      title: `${r.label} ${range} · ${TONE_LABELS[r.tone] ?? r.status}`,
      text: r.label,
    }
  })
})
</script>

<template>
  <PaperCard variant="dashboard" class="timeline-card">
    <h3>🕒 今天的时间表 <small>远征班次和任务运行都在这条轴上</small></h3>
    <template v-if="data">
      <div class="tl-chart">
        <div class="tl-ticks">
          <span v-for="t in TICKS" :key="t" class="tl-tick" :class="{ 'tl-tick-end': t === DAY }" :style="{ left: pct(t) + '%' }">{{ tickLabel(t) }}</span>
        </div>
        <div class="tl-axis">
          <span v-for="t in TICKS" :key="`g${t}`" class="tl-gridline" :style="{ left: pct(t) + '%' }"></span>
          <div v-for="m in data.markers" :key="m.kind" class="tl-marker" :style="{ left: pct(m.time_min) + '%' }">
            <i>{{ m.label }}</i>
          </div>
          <div class="tl-now" :style="{ left: pct(nowMin) + '%' }"></div>
          <div class="tl-lane">
            <span class="tl-lane-tag">远征</span>
            <div v-for="b in expeditionBlocks" :key="b.key" class="tl-block" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title">{{ b.text }}</div>
          </div>
          <div class="tl-lane">
            <span class="tl-lane-tag">任务</span>
            <div v-for="b in runBlocks" :key="b.key" class="tl-block" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title">{{ b.text }}</div>
            <span v-if="!runBlocks.length" class="tl-lane-empty">今天还没有任务记录</span>
          </div>
        </div>
      </div>
      <div class="tl-list">
        <p v-for="b in expeditionBlocks" :key="b.key" class="tl-list-row"><span class="slot-chip" :class="b.cls[0]">{{ b.title }}</span></p>
        <p v-for="b in runBlocks" :key="b.key" class="tl-list-row"><span class="slot-chip" :class="b.cls">{{ b.title }}</span></p>
        <p v-if="!expeditionBlocks.length && !runBlocks.length" class="empty">今天的时间表还空着</p>
      </div>
      <p v-if="data.hint" class="tl-hint">{{ data.hint }}</p>
    </template>
    <p v-else class="empty">时间表加载中…</p>
  </PaperCard>
</template>
