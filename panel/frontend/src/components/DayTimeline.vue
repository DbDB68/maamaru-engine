<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import type { DayRaidPlanBlock, DayTimeline, DayTimelineExpedition } from '../types'
import PaperCard from './PaperCard.vue'

const props = withDefaults(defineProps<{ collapsible?: boolean }>(), {
  collapsible: false,
})

const DAY = 1440
const data = ref<DayTimeline | null>(null)
const expanded = ref(!props.collapsible)
const editing = ref(false)
const saving = ref(false)
const planMessage = ref('')
const expeditionMessage = ref('')
const togglingExpedition = ref('')
const draft = ref<{ time: string; runs: number }[]>([])
let timer: number | undefined

async function load() {
  try {
    data.value = await api.dayTimeline()
  } catch {
    /* 静默失败，下轮轮询再试 */
  }
}

async function toggleExpedition(slot: DayTimelineExpedition) {
  if (!slot.toggleable || togglingExpedition.value) return
  togglingExpedition.value = slot.key
  expeditionMessage.value = ''
  try {
    await api.setDayExpeditionSlot(slot.key, !slot.enabled)
    await load()
    expeditionMessage.value = slot.enabled ? '这班今天跳过；明天仍按原排班。' : '这班今天照常派出。'
  } catch (error) {
    expeditionMessage.value = error instanceof Error ? error.message : '这班没改成，请重试'
    await load()
  } finally {
    togglingExpedition.value = ''
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
  skipped: '今天跳过',
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
  skipped: 'is-skipped',
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

function parseTime(value: string): number | null {
  if (!/^\d{2}:\d{2}$/.test(value)) return null
  const [hour, minute] = value.split(':').map(Number)
  return hour < 24 && minute < 60 ? hour * 60 + minute : null
}

function recommendedBlocks(): DayRaidPlanBlock[] {
  return (data.value?.suggestions || [])
    .filter(block => block.runs != null)
    .map(block => ({ start_min: block.start_min, runs: block.runs! }))
}

function editPlan() {
  const blocks = data.value?.booking?.blocks || recommendedBlocks()
  draft.value = (blocks.length ? blocks : [{ start_min: Math.ceil(nowMin.value), runs: 1 }])
    .map(block => ({ time: fmtMin(block.start_min), runs: block.runs }))
  planMessage.value = ''
  editing.value = true
}

function addBlock() {
  if (draft.value.length >= 2) return
  const last = draft.value[draft.value.length - 1]
  const start = parseTime(last?.time || '') ?? Math.ceil(nowMin.value)
  const pace = data.value?.activity?.seconds_per_loop || 0
  draft.value.push({ time: fmtMin(Math.min(1439, start + Math.ceil((last?.runs || 1) * pace / 60))), runs: 1 })
}

const preview = computed(() => {
  const activity = data.value?.activity
  if (!activity) return { blocks: [] as DayRaidPlanBlock[], issues: ['当前没有可安排的联队战'] }
  const issues: string[] = []
  const blocks: DayRaidPlanBlock[] = []
  const deadline = Math.min(DAY, Math.floor((activity.event_end_at - (data.value?.day_start || 0)) / 60) - 5)
  for (const [index, row] of draft.value.entries()) {
    const start = parseTime(row.time)
    const runs = Number(row.runs)
    if (start == null || !Number.isInteger(runs) || runs < 1 || runs > 99) {
      issues.push(`第${index + 1}段请填写时间和 1–99 圈`)
      continue
    }
    blocks.push({ start_min: start, runs })
    const end = start + Math.ceil(runs * activity.seconds_per_loop / 60)
    if (start < Math.ceil(nowMin.value)) issues.push(`第${index + 1}段的开工时间已经过去`)
    if (end > deadline) issues.push(`第${index + 1}段赶不上今天收摊`)
    const collision = activity.occupied.find(item => start < item.end_min && end > item.start_min)
    if (collision) issues.push(`第${index + 1}段会撞上${collision.label}`)
  }
  if (blocks.reduce((sum, block) => sum + block.runs, 0) > activity.remaining_runs) issues.push('圈数超过本期剩余圈数')
  if (blocks.length === 2) {
    const firstEnd = blocks[0].start_min + Math.ceil(blocks[0].runs * activity.seconds_per_loop / 60)
    if (blocks[0].start_min > blocks[1].start_min) issues.push('请按开工时间排列')
    if (firstEnd > blocks[1].start_min) issues.push('两个时段重叠')
  }
  return { blocks, issues }
})

async function savePlan(blocks: DayRaidPlanBlock[]) {
  saving.value = true
  planMessage.value = ''
  try {
    await api.saveDayRaidPlan(blocks)
    editing.value = false
    await load()
    planMessage.value = '今日安排已记下；到点不会自动开工。'
  } catch (error) {
    planMessage.value = error instanceof Error ? error.message : '保存失败，请重试'
    await load()
  } finally {
    saving.value = false
  }
}

function saveRecommended() {
  const blocks = recommendedBlocks()
  if (blocks.length) void savePlan(blocks)
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
    if (!e.base_enabled) bits.push('排班未启用')
    else if (e.skipped_today) bits.push('今天跳过')
    return {
      key: e.key,
      slot: e,
      minute: e.time_min,
      left: pct(e.time_min),
      width: Math.max(pct(visibleDuration), 0.7),
      cls: [STATE_CLASSES[e.state] ?? 'is-pending',
        !e.enabled ? 'is-expedition-off' : e.state === 'pending' ? 'is-expedition-active' : ''],
      title: bits.join(' · '),
      text: e.map_code,
      rowTitle: `部队${team} · ${e.map_code}`,
      rowDetail: `${durationText(e.duration_min)}远征 · ${!e.base_enabled ? '排班未启用' : stateLabel}`,
      time: fmtMin(e.time_min),
      tone: STATE_CLASSES[e.state] ?? 'is-pending',
      enabled: e.enabled,
    }
  })
})

// 总开关关闭时也保留灰色班次，让玩家先看清原排班。
const displayedExpeditionBlocks = expeditionBlocks

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
    const activityLabel = s.runs != null ? `联队战 ${s.runs} 圈` : '挂机建议'
    const detail = `${s.runs != null ? `${s.runs} 圈 · ` : '挂 '}${durationText(s.duration_min)}${s.note ? ` · ${s.note}` : ''}`
    return {
      key: `suggest-${i}`,
      minute: s.start_min,
      left: pct(s.start_min),
      width: Math.max(pct(Math.max(s.duration_min, 4)), 0.7),
      cls: 'is-suggest',
      title: `${activityLabel} · ${range} · ${durationText(s.duration_min)}${s.note ? ` · ${s.note}` : ''}`,
      text: s.runs != null ? `${s.runs} 圈` : '建议',
      rowTitle: activityLabel,
      rowDetail: `${range} ${detail}`,
      time: fmtMin(s.start_min),
      tone: 'is-suggest',
      current: false,
      durationMin: s.duration_min,
    }
  })
})

const bookingBlocks = computed(() => {
  const activity = data.value?.activity
  if (!activity) return []
  return (data.value?.booking?.blocks || []).map((block, index) => ({
    key: `booked-${index}`,
    left: pct(block.start_min),
    width: Math.max(pct(Math.ceil(block.runs * activity.seconds_per_loop / 60)), 0.7),
    title: `${fmtMin(block.start_min)} 联队战 ${block.runs} 圈（玩家安排，尚未接自动开工）`,
    text: `${block.runs} 圈`,
  }))
})

const shortfallText = computed(() => {
  const shortfall = data.value?.shortfall_seconds
  if (!shortfall || shortfall <= 0) return ''
  const activity = data.value?.activity
  if (activity) return `这张时间表在 24:00 前可安排 ${activity.planned_runs} / ${activity.target_runs} 圈，还差 ${activity.target_runs - activity.planned_runs} 圈排不下。`
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

const totalItemCount = computed(() => displayedExpeditionBlocks.value.length + runBlocks.value.length + suggestionBlocks.value.length)
const hiddenItemCount = computed(() => Math.max(0, totalItemCount.value - compactRows.value.length))
const showDetails = computed(() => !props.collapsible || expanded.value)

const caption = computed(() => {
  const running = runBlocks.value.find((block) => block.current)
  if (running) return `正在跑 ${running.rowTitle}`
  const activity = data.value?.activity
  if (activity) {
    if (!activity.target_runs) return '联队战今天的进度已够，等下一次记账再更新'
    return `联队战接下来建议 ${activity.target_runs} 圈 · 已找到 ${activity.planned_runs} 圈的空窗`
  }
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
            <button v-for="b in displayedExpeditionBlocks" :key="b.key" type="button" class="tl-block tl-expedition-block" :class="b.cls" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title" :aria-label="`${b.time} ${b.rowTitle}，${b.slot.enabled ? '今天照常跑' : '今天不跑'}${b.slot.toggleable ? '，点击切换' : ''}`" :aria-pressed="b.slot.enabled" :disabled="!b.slot.toggleable || !!togglingExpedition" @click="toggleExpedition(b.slot)">{{ b.text }}</button>
            <span v-if="!displayedExpeditionBlocks.length" class="tl-lane-empty">今天没有远征班次</span>
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
          <div v-if="bookingBlocks.length" class="tl-lane">
            <span class="tl-lane-tag">我的安排</span>
            <div v-for="b in bookingBlocks" :key="b.key" class="tl-block is-booked" :class="{ 'is-stale': data.booking?.issues.length }" :style="{ left: b.left + '%', width: b.width + '%' }" :title="b.title">{{ b.text }}</div>
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
      <details v-if="data.expeditions.length" class="tl-expedition-choices" open>
        <summary>今天的远征排班 <small>{{ data.expeditions.filter(item => item.enabled).length }} / {{ data.expeditions.length }} 班照常跑</small></summary>
        <p v-if="!data.expedition_schedule_enabled" class="tl-expedition-note">自动排班总开关未启用；这里先显示原定时间，需在「功能 → 远征排班」开启后才能逐班选择。</p>
        <p v-else class="tl-expedition-note">亮色今天照常跑，灰色今天跳过；只改今天这一班。</p>
        <div class="tl-expedition-list">
          <div v-for="slot in data.expeditions" :key="slot.key" class="tl-expedition-row" :class="{ 'is-off': !slot.enabled }">
            <time>{{ fmtMin(slot.time_min) }}</time>
            <span>部队{{ TEAM_NAMES[slot.team_no] ?? slot.team_no }} · {{ slot.map_code }} <small>{{ !slot.base_enabled ? '排班未启用' : STATE_LABELS[slot.state] ?? slot.state }}</small></span>
            <button v-if="slot.toggleable" type="button" :class="{ 'is-on': slot.enabled }" :aria-pressed="slot.enabled" :disabled="!!togglingExpedition" @click="toggleExpedition(slot)">{{ togglingExpedition === slot.key ? '更改中…' : slot.enabled ? '今天跑' : '今天跳过' }}</button>
            <em v-else>{{ slot.enabled ? slot.planned_at > data.now ? '即将开班' : '已到点或已处理' : slot.skipped_today ? '今天跳过' : '未运行' }}</em>
          </div>
        </div>
        <p v-if="expeditionMessage" class="tl-expedition-message" role="status">{{ expeditionMessage }}</p>
      </details>
      <p v-if="data.hint" class="tl-hint">{{ data.hint }}</p>
      <p v-if="shortfallText" class="tl-shortfall">{{ shortfallText }}</p>
      <section v-if="data.activity || data.booking" class="tl-booking" aria-label="今日联队战安排">
        <div class="tl-booking-head">
          <div>
            <strong>今日联队战</strong>
            <small v-if="data.booking">你安排了 {{ data.booking.blocks.reduce((sum, block) => sum + block.runs, 0) }} 圈 · {{ data.booking.issues.length ? '需要重看' : '只记计划，尚未自动开工' }}</small>
            <small v-else>推荐的空窗可以直接采用，也可以自己挑时间</small>
          </div>
          <div class="tl-booking-actions">
            <button v-if="recommendedBlocks().length && !editing" type="button" :disabled="saving" @click="saveRecommended">按推荐安排</button>
            <button v-if="data.activity && !editing" type="button" :disabled="saving" @click="editPlan">{{ data.booking ? '改安排' : '自己定时间' }}</button>
          </div>
        </div>
        <p v-if="data.booking?.issues.length" class="tl-booking-warning">{{ data.booking.issues.join('；') }}。请重新安排。</p>
        <div v-if="data.booking && !editing" class="tl-booked-list">
          <span v-for="(block, index) in data.booking.blocks" :key="index">{{ fmtMin(block.start_min) }} 开始 · {{ block.runs }} 圈<template v-if="data.activity"> · 预计 {{ fmtMin(block.start_min + Math.ceil(block.runs * data.activity.seconds_per_loop / 60)) }} 收工</template></span>
        </div>
        <div v-if="editing" class="tl-booking-editor">
          <div v-for="(row, index) in draft" :key="index" class="tl-booking-row">
            <label>第{{ index + 1 }}段开始 <input v-model="row.time" type="time" step="60" /></label>
            <label>圈数 <input v-model.number="row.runs" type="number" min="1" max="99" step="1" inputmode="numeric" /></label>
            <span v-if="parseTime(row.time) != null && data.activity">预计 {{ fmtMin(parseTime(row.time)! + Math.ceil(Number(row.runs || 0) * data.activity.seconds_per_loop / 60)) }} 收工</span>
            <button v-if="draft.length > 1" type="button" class="tl-booking-link" @click="draft.splice(index, 1)">移除</button>
          </div>
          <button v-if="draft.length < 2" type="button" class="tl-booking-link" @click="addBlock">＋ 再安排一段</button>
          <p v-if="preview.issues.length" class="tl-booking-warning">{{ preview.issues.join('；') }}</p>
          <div class="tl-booking-actions">
            <button type="button" :disabled="saving || preview.issues.length > 0" @click="savePlan(preview.blocks)">{{ saving ? '保存中…' : '记下今天的安排' }}</button>
            <button type="button" :disabled="saving" @click="editing = false">取消</button>
          </div>
        </div>
        <p v-if="planMessage" class="tl-booking-message" role="status">{{ planMessage }}</p>
      </section>
    </template>
    <p v-else-if="!data" class="empty">时间表加载中…</p>
  </PaperCard>
</template>
