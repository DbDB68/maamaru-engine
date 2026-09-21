<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'
import PixelControl from './PixelControl.vue'
import { formatClock, formatDuration, parseRun, parseRuns, scriptLabel } from './runTimeline'
import type { LogEntry, RunEndStatus, StepStatus, TimelineRun, TimelineStep } from './runTimeline'

// 数据与 LogPanel 同一份（SQLite 全量 + SSE 增量），不新开通道；
// run 边界靠 run_id 分组，终态靠 [脚本] 收尾行（见 runTimeline.ts）。
const BUFFER_LIMIT = 3000
const entries = ref<LogEntry[]>([])
const history = ref<any[]>([])
const historyLines = ref<LogEntry[]>([])
const historyNote = ref(false)
const loadingHistoryLines = ref(false)
const pinned = ref<{ runId: string; fromHistory: boolean; script: string } | null>(null)
const openKeys = ref<string[]>([])
const list = ref<HTMLElement | null>(null)
const follow = ref(true)
const clock = ref(Date.now())
let source: EventSource | null = null
let clockTimer = 0
const seen = new Set<number>()

const bufferRuns = computed(() => parseRuns(entries.value))
const latestRun = computed(() => bufferRuns.value[bufferRuns.value.length - 1] || null)

const view = computed<TimelineRun | null>(() => {
  if (!pinned.value) return latestRun.value
  if (pinned.value.fromHistory) {
    if (!historyLines.value.length) return null
    return parseRun(pinned.value.runId, pinned.value.script, historyLines.value)
  }
  return bufferRuns.value.find(run => run.runId === pinned.value!.runId) || null
})

const RUN_STATUS_TEXT: Record<RunEndStatus, string> = {
  completed: '完成', stopped: '已停止', watchdog: '看门狗处决', failed: '翻车',
}

function statusText(status: RunEndStatus | null): string {
  return status ? RUN_STATUS_TEXT[status] : '进行中'
}

const runOptions = computed(() => {
  const options: { runId: string; label: string; fromHistory: boolean; script: string }[] = []
  // 结算记录里有、但明细已滚出缓冲的旧 run（选中后按需按 run_id 拉日志）
  for (const item of history.value) {
    if (!item?.run_id || bufferRuns.value.some(run => run.runId === item.run_id)) continue
    options.push({
      runId: item.run_id,
      label: `${scriptLabel(item.script)} · ${formatClock(item.started_at)} · ${statusText(item.status)}`,
      fromHistory: true,
      script: item.script,
    })
  }
  for (const run of bufferRuns.value) {
    options.push({
      runId: run.runId,
      label: `${scriptLabel(run.script)} · ${formatClock(run.startTs)} · ${run.ended ? statusText(run.endStatus) : '进行中'}`,
      fromHistory: false,
      script: run.script,
    })
  }
  return options.reverse() // 最新在前
})

const headerSubtitle = computed(() => {
  if (!view.value) return '像看快递物流一样看任务怎么跑'
  const run = view.value
  return `${scriptLabel(run.script)} · ${formatClock(run.startTs)} 开始 · ${run.steps.length} 步`
})

function statusIcon(status: StepStatus): string {
  return { ok: '✓', fail: '✗', warn: '⚠', skip: '⏭', info: '●' }[status]
}

function stepMeta(step: TimelineStep): string {
  const parts: string[] = []
  if (step.tag) parts.push(step.tag)
  parts.push(`${formatClock(step.startTs)} 起`)
  parts.push(formatDuration((step.endTs - step.startTs) * 1000))
  return parts.join(' · ')
}

function isOpen(index: number): boolean { return openKeys.value.includes(`${view.value?.runId}:${index}`) }
function toggle(index: number) {
  const key = `${view.value?.runId}:${index}`
  openKeys.value = openKeys.value.includes(key)
    ? openKeys.value.filter(item => item !== key)
    : [...openKeys.value, key]
}

function push(entry: LogEntry) {
  if (seen.has(entry.id)) return
  seen.add(entry.id)
  entries.value.push(entry)
  if (entries.value.length > BUFFER_LIMIT) {
    const dropped = entries.value.shift()
    if (dropped) seen.delete(dropped.id)
  }
}

async function loadHistory() {
  try {
    const data = await api.dataRuns(15)
    history.value = data.items || []
  } catch { /* 结算记录拉不到不挡时间线 */ }
}

async function pickRun(runId: string) {
  historyLines.value = []
  historyNote.value = false
  if (!runId) { pinned.value = null; return }
  const option = runOptions.value.find(item => item.runId === runId)
  if (!option) return
  if (!option.fromHistory) {
    pinned.value = { runId, fromHistory: false, script: option.script }
    return
  }
  pinned.value = { runId, fromHistory: true, script: option.script }
  loadingHistoryLines.value = true
  try {
    const data = await api.logsForRun(runId)
    historyLines.value = (data.logs || []) as LogEntry[]
    historyNote.value = !historyLines.value.length
  } catch { historyNote.value = true } finally { loadingHistoryLines.value = false }
}

async function scrollBottom() {
  await nextTick()
  if (follow.value) list.value?.scrollTo({ top: list.value.scrollHeight })
}

async function load() {
  const data = await api.logs(2000)
  for (const entry of data.logs || []) push(entry as LogEntry)
  await loadHistory()
  scrollBottom()
}

function connect() {
  source = new EventSource('/api/logs/stream')
  source.onmessage = event => {
    if (!event.data) return
    try {
      push(JSON.parse(event.data) as LogEntry)
    } catch { /* 心跳和坏行忽略 */ }
  }
  source.onerror = () => { source?.close(); source = null; window.setTimeout(connect, 3000) }
}

// 步骤行数变化 = 有新进展，跟随模式滚到底
watch(() => view.value?.steps.reduce((total, step) => total + step.lines.length, 0) ?? 0, scrollBottom)

// 正在跟的 run 收尾后，刷新一次结算列表（拿到终态/圈速）
watch(() => view.value?.ended, (ended, was) => { if (ended && !was) loadHistory() })

onMounted(() => {
  load().catch(() => { /* 初始拉取失败就等 SSE 推 */ })
  connect()
  clockTimer = window.setInterval(() => { clock.value = Date.now() }, 1000)
})
onBeforeUnmount(() => { source?.close(); window.clearInterval(clockTimer) })
</script>

<template>
  <section class="run-timeline">
    <PanelHeader title="跑况时间线" :subtitle="headerSubtitle">
      <template #actions>
        <label class="rt-pick">看哪次
          <PixelControl as="select" :model-value="pinned?.runId || ''" @update:model-value="pickRun(String($event))">
            <option value="">跟随最新</option>
            <option v-for="option in runOptions" :key="option.runId" :value="option.runId">{{ option.label }}</option>
          </PixelControl>
        </label>
        <button v-if="pinned" type="button" class="secondary" @click="pickRun('')">回到最新</button>
        <button type="button" class="secondary" :class="{ active: follow }" :aria-pressed="follow" @click="follow = !follow">跟随滚动</button>
      </template>
    </PanelHeader>

    <div v-if="view" class="rt-run">
      <p class="rt-run-head">
        <b>{{ scriptLabel(view.script) }}</b>
        <span>{{ formatClock(view.startTs) }} 开始</span>
        <span v-if="view.ended && view.endTs">跑了 {{ formatDuration((view.endTs - view.startTs) * 1000) }}</span>
        <span v-else>已跑 {{ formatDuration(Math.max(0, clock / 1000 - view.startTs)) }}</span>
        <em class="rt-chip" :class="`is-${view.endStatus || 'running'}`">{{ statusText(view.endStatus) }}</em>
        <span class="rt-count">{{ view.steps.length }} 步 · {{ view.lineCount }} 行日志</span>
      </p>
      <ol ref="list" class="rt-steps">
        <li v-for="(step, index) in view.steps" :key="`${view.runId}:${index}`" class="rt-step" :class="[`is-${step.status}`, { open: isOpen(index) }]">
          <button type="button" class="rt-step-head" :aria-expanded="isOpen(index)" @click="toggle(index)">
            <span class="rt-icon" aria-hidden="true">{{ statusIcon(step.status) }}</span>
            <span class="rt-step-body">
              <strong>{{ step.title }}</strong>
              <small>{{ stepMeta(step) }}</small>
            </span>
            <span class="rt-caret" aria-hidden="true">{{ isOpen(index) ? '−' : '＋' }}</span>
          </button>
          <ol v-if="isOpen(index)" class="rt-lines">
            <li v-for="line in step.lines" :key="line.id" :class="`is-${line.status}`">
              <time>{{ formatClock(line.ts) }}</time><span>{{ line.message }}</span>
            </li>
          </ol>
        </li>
      </ol>
    </div>
    <p v-else-if="pinned?.fromHistory && loadingHistoryLines" class="rt-empty">正在翻这次运行的日志…</p>
    <p v-else-if="pinned?.fromHistory && historyNote" class="rt-empty">这次运行的明细日志已经滚出本地缓冲，只剩结算记录了。下次跑完早点来，就能一步步回看。</p>
    <p v-else class="rt-empty">还没有任务日志。跑一条任务，这里就会出现它的时间线——每步几点开始、跑了多久、成没成，一目了然。</p>
  </section>
</template>

<style scoped>
.run-timeline { min-width: 0; color: var(--ink); }
.run-timeline button { cursor: pointer; font: inherit; }
.rt-pick { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-dim); }
.rt-pick :deep(.pixel-control) { width: clamp(180px, 22vw, 280px); }
.rt-run-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 0 0 12px; font-size: 12px; color: var(--ink-dim); }
.rt-run-head b { font-size: 14px; color: var(--ink); }
.rt-count { margin-left: auto; }
.rt-chip { font-style: normal; font-size: 11px; padding: 1px 8px; border-radius: 99px; border: 1px solid var(--paper-line); color: var(--ink-dim); }
.rt-chip.is-completed { color: #426047; border-color: #42604766; background: #42604712; }
.rt-chip.is-failed, .rt-chip.is-watchdog { color: #9f3d28; border-color: #9f3d2866; background: #9f3d2812; }
.rt-chip.is-stopped { color: var(--fox-gold-deep, #b3781f); border-color: #b3781f66; background: #b3781f12; }
.rt-chip.is-running { color: #2f6f8f; border-color: #2f6f8f66; background: #2f6f8f10; }
.rt-steps { list-style: none; margin: 0; padding: 4px 0 6px; position: relative; max-height: 46vh; overflow-y: auto; }
.rt-steps::before { content: ''; position: absolute; left: 13px; top: 12px; bottom: 12px; width: 2px; background: var(--paper-line); opacity: .7; }
.rt-step { position: relative; padding: 0 0 4px 36px; min-width: 0; }
.rt-icon { position: absolute; left: 0; top: 5px; width: 28px; height: 28px; display: grid; place-items: center; border-radius: 50%; border: 1px solid var(--paper-line); background: var(--paper-card); color: var(--ink-dim); font-size: 12px; font-weight: 700; }
.rt-step.is-ok .rt-icon { color: #426047; border-color: #42604788; background: #42604712; }
.rt-step.is-fail .rt-icon { color: #9f3d28; border-color: #9f3d2888; background: #9f3d2814; }
.rt-step.is-fail .rt-step-body strong { color: #9f3d28; }
.rt-step.is-warn .rt-icon { color: var(--fox-gold-deep, #b3781f); border-color: #b3781f88; background: #b3781f12; }
.rt-step.is-skip .rt-icon { color: var(--ink-dim); }
.rt-step-head { display: flex; align-items: flex-start; gap: 10px; width: 100%; padding: 7px 8px; border: 0; border-radius: 7px; background: transparent; color: var(--ink); text-align: left; }
.rt-step-head:hover { background: var(--paper-panel); }
.rt-step-body { min-width: 0; flex: 1; }
.rt-step-body strong { display: block; font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.rt-step-body small { display: block; font-size: 11px; color: var(--ink-dim); line-height: 1.7; margin-top: 2px; }
.rt-caret { color: var(--ink-dim); font-size: 13px; margin-top: 2px; }
.rt-lines { list-style: none; margin: 2px 0 8px; padding: 8px 10px; border: 1px dashed var(--paper-line); border-radius: 7px; background: var(--paper); display: grid; gap: 4px; max-height: 220px; overflow-y: auto; }
.rt-lines li { display: flex; gap: 10px; font-size: 11px; line-height: 1.7; min-width: 0; }
.rt-lines time { flex-shrink: 0; color: var(--ink-dim); font-variant-numeric: tabular-nums; }
.rt-lines span { min-width: 0; overflow-wrap: anywhere; }
.rt-lines li.is-fail span { color: #9f3d28; }
.rt-lines li.is-warn span { color: var(--fox-gold-deep, #b3781f); }
.rt-lines li.is-ok span { color: #426047; }
.rt-empty { margin: 10px 0 0; padding: 18px 14px; border: 1px dashed var(--paper-line); border-radius: 8px; color: var(--ink-dim); font-size: 12px; line-height: 1.9; text-align: center; }
@media (max-width: 720px) {
  .rt-pick { flex: 1 1 100%; }
  .rt-pick :deep(.pixel-control) { flex: 1; width: auto; }
  .rt-count { width: 100%; margin-left: 0; }
  .rt-step { padding-left: 32px; }
  .rt-lines li { flex-direction: column; gap: 0; }
}
</style>
