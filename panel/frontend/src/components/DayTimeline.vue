<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import type { DayTimeline } from '../types'
import PaperCard from './PaperCard.vue'

const props = withDefaults(defineProps<{ collapsible?: boolean }>(), {
  collapsible: false,
})

const DAY = 1440
const data = ref<DayTimeline | null>(null)
const expanded = ref(!props.collapsible)
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
const MINI_TICKS = [0, 360, 720, 1080, 1440]
const COMPACT_LIMIT = 4

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
  if (min < 60) return `${min}分`
  const hours = Math.floor(min / 60)
  const minutes = min % 60
  return minutes ? `${hours}小时${minutes}分` : `${hours}小时`
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
    const visibleDuration = Math.min(Math.max(e.duration_min, 10), DAY - e.time_min)
    const bits = [`${fmtMin(e.time_min)} 部队${team} ${e.map_code}`]
    if (e.duration_min) bits[0] += `（${durationText(e.duration_min)}）`
    bits.push(stateLabel)
    if (e.late_min && e.state === 'dispatched') bits.push(`晚${e.late_min}分钟`)
    if (e.blocked_reason) bits.push(e.blocked_reason)
    if (!e.enabled) bits.push('未启用')
    return {
      key: `${e.time_min}-${e.team_no}-${e.map_code}`,
      minute: e.time_min,
      left: pct(e.time_min),
      width: Math.max(pct(visibleDuration), 0.7),
      cls: [STATE_CLASSES[e.state] ?? 'is-pending', e.enabled ? '' : 'is-disabled'],
      title: bits.join(' · '),
      text: e.map_code,
      rowTitle: `部队${team} · ${e.map_code}`,
      rowDetail: e.enabled
        ? `${durationText(e.duration_min)}远征 · ${stateLabel}`
        : `${durationText(e.duration_min)}远征 · 排班未启用`,
      time: fmtMin(e.time_min),
      tone: STATE_CLASSES[e.state] ?? 'is-pending',
      enabled: e.enabled,
    }
  })
})

// 排班总开关关闭时，时间轴不再把整天的假定班次当成待办铺出来。
// 完整配置仍保留在自动排班页；这里仅展示真正会执行的班次。
const displayedExpeditionBlocks = computed(() => {
  return expeditionBlocks.value.some((block) => block.enabled)
    ? expeditionBlocks.value
    : []
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
      minute: start,
      left: pct(start),
      width: Math.max(pct(Math.max(end - start, 4)), 0.7),
      cls: `is-${r.tone}`,
      title: `${r.label} ${range} · ${TONE_LABELS[r.tone] ?? r.status}`,
      text: r.label,
      rowTitle: r.label,
      rowDetail: `${range} · ${TONE_LABELS[r.tone] ?? r.status}`,
      time: fmtTs(r.started_at),
      tone: `is-${r.tone}`,
      current: r.tone === 'running',
    }
  })
})

const suggestionBlocks = computed(() => {
  const suggestions = data.value?.suggestions
  if (!suggestions) return []
  return suggestions.map((s, i) => {
    const range = `${fmtMin(s.start_min)}–${fmtMin(s.start_min + s.duration_min)}`
    const detail = `挂 ${durationText(s.duration_min)}${s.note ? ` · ${s.note}` : ''}`
    return {
      key: `suggest-${i}`,
      minute: s.start_min,
      left: pct(s.start_min),
      width: Math.max(pct(Math.max(s.duration_min, 4)), 0.7),
      cls: 'is-suggest',
      title: `建议 ${range} ${detail}`,
      text: '建议',
      rowTitle: '挂机建议',
      rowDetail: `${range} ${detail}`,
      time: fmtMin(s.start_min),
      tone: 'is-suggest',
      current: false,
      durationMin: s.duration_min,
    }
  })
})

const shortfallText = computed(() => {
  const shortfall = data.value?.shortfall_seconds
  if (!shortfall || shortfall <= 0) return ''
  const covered = suggestionBlocks.value.reduce((sum, b) => sum + b.durationMin, 0)
  const lacking = Math.ceil(shortfall / 60)
  return `今天空窗只够约 ${durationText(covered)}，还差约 ${durationText(lacking)} 排不下。`
})

const compactRows = computed(() => {
  const expeditions = displayedExpeditionBlocks.value.map((b) => ({
    key: `exp-${b.key}`,
    minute: b.minute,
    time: b.time,
    title: b.rowTitle,
    detail: b.rowDetail,
    tone: b.tone,
    current: false,
    enabled: b.enabled,
  }))
  const runs = runBlocks.value.map((b) => ({
    key: `run-${b.key}`,
    minute: b.minute,
    time: b.current ? '现在' : b.time,
    title: b.rowTitle,
    detail: b.rowDetail,
    tone: b.tone,
    current: b.current,
    enabled: true,
  }))
  const suggestions = suggestionBlocks.value.map((b) => ({
    key: b.key,
    minute: b.minute,
    time: b.time,
    title: b.rowTitle,
    detail: b.rowDetail,
    tone: b.tone,
    current: false,
    enabled: true,
  }))
  const rows = [...expeditions, ...runs, ...suggestions]
  const current = rows.filter((row) => row.current)
  const futureEnabled = rows
    .filter((row) => !row.current && row.minute >= nowMin.value && row.enabled)
    .sort((a, b) => a.minute - b.minute)
  const recent = rows
    .filter((row) => !row.current && row.minute < nowMin.value)
    .sort((a, b) => b.minute - a.minute)

  const chosen = [...current, ...futureEnabled].slice(0, COMPACT_LIMIT)
  if (chosen.length < COMPACT_LIMIT) {
    chosen.push(...recent.slice(0, COMPACT_LIMIT - chosen.length).reverse())
  }
  return chosen
})

const compactHeading = computed(() => {
  if (compactRows.value.some((row) => row.current)) return '现在与接下来'
  if (compactRows.value.some((row) => row.minute >= nowMin.value)) return '接下来'
  return '今天留下的记录'
})

const totalItemCount = computed(() => displayedExpeditionBlocks.value.length + runBlocks.value.length)
const hiddenItemCount = computed(() => Math.max(0, totalItemCount.value - compactRows.value.length))
const showDetails = computed(() => !props.collapsible || expanded.value)

const caption = computed(() => {
  const running = runBlocks.value.find((block) => block.current)
  if (running) return `正在跑 ${running.rowTitle}`
  const nextEnabled = expeditionBlocks.value
    .filter((block) => block.minute >= nowMin.value && block.enabled)
    .sort((a, b) => a.minute - b.minute)[0]
  if (nextEnabled) return `下一班 ${nextEnabled.time} · ${nextEnabled.rowTitle}`
  if (expeditionBlocks.value.length && !expeditionBlocks.value.some((block) => block.enabled)) {
    return '远征排班未启用，今天只显示实际执务记录'
  }
  return '远征班次和任务记录，都收在今天这一页'
})
</script>

<template>
  <PaperCard variant="dashboard" class="timeline-card" :class="{ 'is-collapsible': props.collapsible, 'is-collapsed': props.collapsible && !expanded }">
    <div class="tl-card-head">
      <div>
        <h3><span aria-hidden="true">◷</span> 今天的时间表</h3>
        <p>{{ caption }}</p>
      </div>
      <div class="tl-card-actions">
        <time v-if="data">{{ fmtMin(nowMin) }}</time>
        <button v-if="props.collapsible" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
          {{ expanded ? '收起' : '展开' }}
        </button>
      </div>
    </div>
    <template v-if="data && showDetails">
      <div class="tl-chart tl-wide">
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
            <div v-for="b in displayedExpeditionBlocks" :key="b.key" class="tl-block" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title">{{ b.text }}</div>
            <span v-if="!displayedExpeditionBlocks.length" class="tl-lane-empty">远征排班未启用</span>
          </div>
          <div class="tl-lane">
            <span class="tl-lane-tag">任务</span>
            <div v-for="b in runBlocks" :key="b.key" class="tl-block" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title">{{ b.text }}</div>
            <span v-if="!runBlocks.length" class="tl-lane-empty">今天还没有任务记录</span>
          </div>
          <div v-if="data.suggestions" class="tl-lane">
            <span class="tl-lane-tag">建议</span>
            <div v-for="b in suggestionBlocks" :key="b.key" class="tl-block" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title">{{ b.text }}</div>
            <span v-if="!suggestionBlocks.length" class="tl-lane-empty">今天排不出合适的挂机空窗</span>
          </div>
        </div>
      </div>
      <div class="tl-compact">
        <div class="tl-mini-meta">
          <span><i class="is-expedition"></i>远征 <i class="is-task"></i>任务<template v-if="suggestionBlocks.length"> <i class="is-suggest"></i>建议</template></span>
          <span>04:00 日课刷新</span>
        </div>
        <div class="tl-mini-axis" aria-label="今天二十四小时概览">
          <span v-for="t in MINI_TICKS.slice(1, -1)" :key="`mini-grid-${t}`" class="tl-mini-grid" :style="{ left: pct(t) + '%' }"></span>
          <span class="tl-mini-reset" :style="{ left: pct(240) + '%' }" title="04:00 日课刷新"></span>
          <span class="tl-mini-now" :style="{ left: pct(nowMin) + '%' }" title="现在"></span>
          <span v-for="b in displayedExpeditionBlocks" :key="`mini-${b.key}`" class="tl-mini-block is-expedition" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title"></span>
          <span v-for="b in runBlocks" :key="`mini-${b.key}`" class="tl-mini-block is-task" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title"></span>
          <span v-for="b in suggestionBlocks" :key="`mini-${b.key}`" class="tl-mini-block is-suggest" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title"></span>
        </div>
        <div class="tl-mini-ticks">
          <span v-for="t in MINI_TICKS" :key="`mini-tick-${t}`">{{ t === DAY ? '24' : t / 60 }}</span>
        </div>
        <div v-if="compactRows.length" class="tl-agenda">
          <strong class="tl-agenda-title">{{ compactHeading }}</strong>
          <div v-for="row in compactRows" :key="row.key" class="tl-agenda-row" :class="{ 'is-current': row.current }">
            <time>{{ row.time }}</time>
            <span class="tl-agenda-dot" :class="row.tone"></span>
            <span class="tl-agenda-copy"><b>{{ row.title }}</b><small>{{ row.detail }}</small></span>
          </div>
          <p v-if="hiddenItemCount" class="tl-more">另外 {{ hiddenItemCount }} 项已经收进上面的时间轴。</p>
        </div>
        <p v-else class="empty">今天的时间表还空着</p>
      </div>
      <p v-if="data.hint" class="tl-hint">{{ data.hint }}</p>
      <p v-if="shortfallText" class="tl-shortfall">{{ shortfallText }}</p>
    </template>
    <p v-else-if="!data" class="empty">时间表加载中…</p>
  </PaperCard>
</template>
