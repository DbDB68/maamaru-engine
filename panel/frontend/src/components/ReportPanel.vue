<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from '../api'
import type { HumanReport, InventoryGap, ResourceLedger } from '../types'
import PanelHeader from './PanelHeader.vue'
import SegmentedControl from './SegmentedControl.vue'
import ResourceChart from './report/ResourceChart.vue'
import DayDetail from './report/DayDetail.vue'
import ReportRecords from './report/ReportRecords.vue'
import PlanningPanel from './report/PlanningPanel.vue'
import ObtainRecords from './report/ObtainRecords.vue'
import { categoryLabel, categoryOf, dayRange, eventTime, obtainSourceLabel, resourceColors, resourceNames, shanghaiDate, signed, sourceCategories } from './report/reportModel'
import type { ChartSeries } from './report/reportModel'

const days = ref(7)
const honmaruTab = ref<'report' | 'obtains' | 'planning'>('report')
const view = ref<'chart' | 'records'>('chart')
const summary = ref<any>(null)
const ledger = ref<ResourceLedger | null>(null)
const events = ref<any[]>([])
const runs = ref<any[]>([])
const humanReports = ref<HumanReport[]>([])
const inventoryGaps = ref<InventoryGap[]>([])
const loading = ref(false)
const loadingOlder = ref(false)
const error = ref('')
const hasMoreEvents = ref(false), hasMoreRuns = ref(false)
const eventCursor = ref<number | null>(null), runCursor = ref<number | null>(null)
const recordDate = ref('')
const recordLoading = ref(false)
const recordHasMoreEvents = ref(false), recordHasMoreRuns = ref(false)
const recordEventCursor = ref<number | null>(null), recordRunCursor = ref<number | null>(null)

const mode = ref<'single' | 'compare'>('single')
const selectedResource = ref('小判')
const compareResources = ref(['小判', '加速符'])
const selectedDate = ref('')
const highlightCategory = ref('')

const rangeItems = [{ value: 1, label: '24 小时' }, { value: 7, label: '7 天' }, { value: 30, label: '30 天' }]
const honmaruItems = [
  { value: 'report', label: '成绩单' },
  { value: 'obtains', label: '入手' },
  { value: 'planning', label: '规划' },
]
const viewItems = [
  { value: 'chart', label: '资源对账图' },
  { value: 'records', label: '全部记录' },
]
const rangeLabel = computed(() => days.value === 1 ? '近 24 小时' : days.value === 365 ? '近 1 年' : `近 ${days.value} 天`)

// ---- 库存总账 ----

const resourceRows = computed(() => resourceNames.map(name => {
  const row = (ledger.value?.per_resource || []).find(item => item.resource === name)
  return { name, before: row?.opening ?? null, current: row?.closing ?? null,
    delta: row?.total_delta ?? null, attributed: row?.attributed_delta ?? 0,
    unattributed: row?.unattributed_delta ?? null, observations: row?.observation_count ?? 0,
    confidence: row?.confidence || 'low' }
}))
const confidence = computed(() => {
  if (loading.value) return { level: 'empty', label: '正在对账', detail: '狐之助正在整理库存记录' }
  const rows = resourceRows.value.filter(row => row.delta != null)
  if (!rows.length) return { level: 'empty', label: '无法计算', detail: '这个时间段还没有可比较的库存读数' }
  const levels = rows.map(row => row.confidence)
  const count = Math.max(...rows.map(row => row.observations))
  const gaps = ledger.value?.gaps?.length || 0
  if (levels.every(level => level === 'high')) return { level: 'good', label: '账目完整', detail: `${count} 次库存观察，证据链完整` }
  if (levels.some(level => level === 'low')) return { level: 'rough', label: '仅供参考', detail: `${count} 次库存观察${gaps ? `，另有 ${gaps} 段数据缺口` : ''}` }
  return { level: 'fair', label: '基本可信', detail: `${count} 次库存观察${gaps ? `，另有 ${gaps} 段变化无法完整归因` : ''}` }
})
const foxSummary = computed(() => {
  const changed = resourceRows.value.filter(row => row.delta != null && row.delta !== 0)
  if (!changed.length) return `${rangeLabel.value}还没有足够的首末库存读数。狐之助会在挂机途中继续留意家底。`
  const totals = new Map<string, { source: string; resource: string; delta: number }>()
  for (const item of ledger.value?.attributions || []) {
    const source = categoryOf(item.source)
    if (source === 'unknown' || source === 'human') continue
    const key = `${source}:${item.resource}`
    const found = totals.get(key) || { source, resource: item.resource, delta: 0 }
    found.delta += Number(item.delta || 0)
    totals.set(key, found)
  }
  const entries = [...totals.values()].filter(item => item.delta)
  const gain = entries.filter(item => item.delta > 0).sort((a, b) => b.delta - a.delta)[0]
  const cost = entries.filter(item => item.delta < 0).sort((a, b) => a.delta - b.delta)[0]
  if (!gain && !cost) return `${rangeLabel.value}还没有能确认玩法来源的资源变化。`
  const parts: string[] = []
  if (gain) parts.push(`从${categoryLabel(gain.source)}获得的${gain.resource}最多（${signed(gain.delta)}）`)
  if (cost) parts.push(`${categoryLabel(cost.source)}消耗的${cost.resource}最多（${signed(cost.delta)}）`)
  return `${rangeLabel.value}，${parts.join('；')}。`
})

// ---- 顶部小结：这段时间狐之助干啥了 ----

function isWin(payload: any) {
  const value = String(payload?.result ?? payload?.outcome ?? '').toLowerCase()
  return value.includes('胜') || value.startsWith('win') || value === 'won'
}
function isLoss(payload: any) {
  const value = String(payload?.result ?? payload?.outcome ?? '').toLowerCase()
  return value.includes('败') || value.startsWith('lose') || value === 'lost'
}
function summaryEventCount(...types: string[]) { return types.reduce((total, type) => total + Number(summary.value?.events?.by_type?.[type] || 0), 0) }
const sortieCount = computed(() => Number(summary.value?.activity?.sorties ?? summaryEventCount('sortie.completed')))
const practiceWins = computed(() => Number(summary.value?.activity?.practice?.wins ?? 0))
const practiceLosses = computed(() => Number(summary.value?.activity?.practice?.losses ?? 0))
const practiceTotal = computed(() => Number(summary.value?.activity?.practice?.total ?? 0))
const topSortie = computed(() => (summary.value?.activity?.sortie_groups || [])[0]?.label || '')
const glance = computed(() => {
  if (loading.value) return '狐之助正在清点这段时间干了多少活……'
  const total = Number(summary.value?.runs?.total || 0)
  if (!total && !sortieCount.value) return `${rangeLabel.value}还没有跑过任务，先让小狐狸跑起来吧。`
  const parts = [`${rangeLabel.value}狐之助跑了 ${total} 次任务`]
  if (sortieCount.value) parts.push(`出阵 ${sortieCount.value.toLocaleString()} 圈${topSortie.value ? `，主要在${topSortie.value}` : ''}`)
  if (practiceTotal.value) parts.push(`演练 ${practiceWins.value} 胜 ${practiceLosses.value} 负`)
  return `${parts.join('，')}。`
})
const glanceResources = computed(() => resourceRows.value
  .filter(row => row.delta != null && row.delta !== 0)
  .sort((a, b) => Math.abs(b.delta!) - Math.abs(a.delta!))
  .slice(0, 4))

// ---- 刀剑进账（掉落结果）：sword.obtained + 锻刀/南瓜的认人记录，按名字聚合 ----

const swordDrops = computed(() => {
  const rows = new Map<string, { name: string; count: number; sources: Set<string>; last: number }>()
  const push = (ts: number, name: string, source: string) => {
    const row = rows.get(name) || { name, count: 0, sources: new Set<string>(), last: 0 }
    row.count += 1
    row.sources.add(source)
    row.last = Math.max(row.last, ts)
    rows.set(name, row)
  }
  for (const event of events.value) {
    const payload = event.payload || {}
    if (event.event_type === 'sword.obtained' && payload.name) push(event.ts, payload.name, obtainSourceLabel(payload.source) || '出阵掉落')
    else if (event.event_type === 'forge.collected' && payload.name) push(event.ts, payload.name, '锻刀')
    else if (event.event_type === 'pumpkin.sword_obtained' && payload.name) push(event.ts, payload.name, '南瓜大作战')
  }
  return [...rows.values()].sort((a, b) => b.last - a.last)
})
const swordDropTotal = computed(() => swordDrops.value.reduce((total, row) => total + row.count, 0))

// ---- 图表数据 ----

const unreportedGaps = computed(() => inventoryGaps.value.filter(item => !item.reported))
function reportExplainsGap(report: HumanReport) {
  const nonAnswers = new Set(['暂不说明', '记不清了', '没有其他操作'])
  return Boolean(String(report.note || '').trim()) || (report.activities || []).some(value => !nonAnswers.has(value))
}
const reportedDailyTotals = computed(() => {
  const cutoff = Date.now() / 1000 - days.value * 86400
  const totals: Record<string, Record<string, number>> = {}
  for (const gap of inventoryGaps.value) {
    if (!gap.reported || gap.ended_at < cutoff) continue
    const reports = humanReports.value.filter(report => report.gap_key === gap.gap_key)
    if (!reports.some(reportExplainsGap)) continue
    const date = shanghaiDate(gap.ended_at)
    totals[date] ||= {}
    for (const [name, value] of Object.entries(gap.resource_delta || {})) totals[date][name] = (totals[date][name] || 0) + Number(value || 0)
  }
  return totals
})

const chartDates = computed(() => {
  const names = mode.value === 'single' ? [selectedResource.value] : compareResources.value
  const dates = new Set<string>()
  for (const item of ledger.value?.daily_series || []) {
    if (names.includes(item.resource) && item.total_delta != null) dates.add(item.date)
  }
  // 有些天只有确认来源、没有成对的库存读数（比如挂机跨午夜），也不能丢
  for (const attr of ledger.value?.attributions || []) {
    if (names.includes(attr.resource)) dates.add(shanghaiDate(attr.ts))
  }
  return [...dates].sort()
})
const ledgerDateRange = computed(() => {
  if (!chartDates.value.length) return '暂无日期范围'
  const label = (date: string) => {
    const [, month, day] = date.split('-').map(Number)
    return `${month}月${day}日`
  }
  return `${label(chartDates.value[0])}至${label(chartDates.value[chartDates.value.length - 1])}`
})
const chartSeries = computed<ChartSeries[]>(() => {
  const book = ledger.value
  if (!book) return []
  if (mode.value === 'compare') {
    return compareResources.value.map(name => ({
      key: name, name, color: resourceColors[name] || '#8a7f72',
      values: chartDates.value.map(date =>
        book.daily_series.find(item => item.resource === name && item.date === date)?.total_delta ?? null),
    }))
  }
  const name = selectedResource.value
  const dayIndex = new Map(chartDates.value.map((date, index) => [date, index]))
  const byKey: Record<string, number[]> = {}
  for (const cat of sourceCategories) byKey[cat.key] = chartDates.value.map(() => 0)
  for (const attr of book.attributions || []) {
    if (attr.resource !== name) continue
    const index = dayIndex.get(shanghaiDate(attr.ts))
    if (index != null) byKey[categoryOf(attr.source)][index] += Number(attr.delta || 0)
  }
  for (const [date, resources] of Object.entries(reportedDailyTotals.value)) {
    const index = dayIndex.get(date)
    const value = resources[name]
    if (index != null && value) byKey.human[index] += value
  }
  chartDates.value.forEach((date, index) => {
    const row = book.daily_series.find(item => item.resource === name && item.date === date)
    if (row?.unattributed_delta != null) byKey.unknown[index] += row.unattributed_delta - (byKey.human[index] || 0)
  })
  return sourceCategories.map(cat => ({
    key: cat.key, name: cat.label, color: cat.color,
    values: byKey[cat.key].map(value => value || null),
  }))
})

function toggleCompareResource(name: string) {
  if (compareResources.value.includes(name)) {
    if (compareResources.value.length > 1) compareResources.value = compareResources.value.filter(item => item !== name)
  } else if (compareResources.value.length < 4) compareResources.value = [...compareResources.value, name]
}
function chooseResource(name: string) {
  selectedResource.value = name
  highlightCategory.value = ''
}
function onChartSelect({ date, key }: { date: string; key: string }) {
  if (mode.value === 'single' && key === 'unknown') {
    // 点灰色 = 认领这部分：展开当天明细，并直接弹报备框
    selectedDate.value = date
    highlightCategory.value = key
    const gap = gapForDay(date)
    if (gap) openGapReport(gap)
    else openProactiveReport(dayRange(date)[1] * 1000)
    return
  }
  if (mode.value === 'compare' && resourceNames.includes(key)) selectedResource.value = key
  if (selectedDate.value === date && highlightCategory.value === key) {
    selectedDate.value = ''
    highlightCategory.value = ''
    return
  }
  selectedDate.value = date
  highlightCategory.value = mode.value === 'single' ? key : ''
}
function gapForDay(date: string) {
  const [start, end] = dayRange(date)
  return unreportedGaps.value.find(gap => gap.started_at < end && gap.ended_at >= start) || null
}

function latestRecordDate(): string {
  const timestamps = [
    ...runs.value.map(run => Number(run.started_at)),
    ...events.value.map(event => Number(event.ts)),
  ].filter(Number.isFinite)
  return timestamps.length ? shanghaiDate(Math.max(...timestamps)) : shanghaiDate(Date.now() / 1000)
}

function mergeEvents(items: any[]) {
  const merged = new Map(events.value.map(item => [item.id, item]))
  for (const item of items) merged.set(item.id, item)
  events.value = [...merged.values()].sort((a, b) => b.ts - a.ts)
}

function mergeRuns(items: any[]) {
  const merged = new Map(runs.value.map(item => [item.run_id, item]))
  for (const item of items.filter(run => run.loops)) merged.set(item.run_id, item)
  runs.value = [...merged.values()].sort((a, b) => b.started_at - a.started_at)
}

async function loadRecordDay(date: string) {
  recordLoading.value = true
  try {
    const [start, end] = dayRange(date)
    const [nextEvents, nextRuns] = await Promise.all([
      api.dataEvents(1000, undefined, start, end),
      api.dataRuns(100, undefined, start, end),
    ])
    mergeEvents(nextEvents.items)
    mergeRuns(nextRuns.items)
    recordHasMoreEvents.value = nextEvents.has_more
    recordHasMoreRuns.value = nextRuns.has_more
    recordEventCursor.value = nextEvents.next_cursor
    recordRunCursor.value = nextRuns.next_cursor
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '当天记录读取失败' }
  finally { recordLoading.value = false }
}

function selectRecordDate(date: string) {
  recordDate.value = date
  view.value = 'records'
  void loadRecordDay(date)
}

function switchView(nextView: 'chart' | 'records') {
  view.value = nextView
  if (nextView !== 'records') return
  const date = recordDate.value || latestRecordDate()
  recordDate.value = date
  void loadRecordDay(date)
}
const dayDetail = computed(() => {
  const date = selectedDate.value
  if (!date) return null
  const [start, end] = dayRange(date)
  const resource = selectedResource.value
  const row = (ledger.value?.daily_series || []).find(item => item.date === date && item.resource === resource)
  return {
    date, resource,
    totalDelta: row?.total_delta ?? null,
    attributions: (ledger.value?.attributions || []).filter(item => item.resource === resource && start <= item.ts && item.ts < end),
    runs: runs.value.filter(run => start <= Number(run.started_at) && Number(run.started_at) < end),
    gaps: unreportedGaps.value.filter(gap => gap.started_at < end && gap.ended_at >= start),
  }
})

// ---- 审神者报备 ----

const reportMode = ref('')
const reportGap = ref<InventoryGap | null>(null)
const reportSaving = ref(false)
const reportForm = ref<{ activities: string[]; note: string; occurred_at: string }>({ activities: [], note: '', occurred_at: '' })
const humanActivities = ['领邮箱', '手动领奖', '手动出阵', '锻刀', '手入', '万屋购买', '其他操作']
function localDateTime(timestamp = Date.now()) {
  const date = new Date(timestamp - new Date(timestamp).getTimezoneOffset() * 60000)
  return date.toISOString().slice(0, 16)
}
const reportFormEl = ref<HTMLElement | null>(null)
function scrollToReportForm() {
  void nextTick(() => reportFormEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
}
function openProactiveReport(timestamp?: number) {
  reportMode.value = 'proactive'
  reportGap.value = null
  reportForm.value = { activities: [], note: '', occurred_at: localDateTime(timestamp) }
  scrollToReportForm()
}
function openGapReport(gap: InventoryGap) {
  reportMode.value = `gap:${gap.gap_key}`
  reportGap.value = gap
  reportForm.value = { activities: [], note: '', occurred_at: localDateTime(gap.ended_at * 1000) }
  scrollToReportForm()
}
function toggleReportActivity(value: string) {
  const clean = '没有其他操作'
  const current = reportForm.value.activities
  if (current.includes(value)) reportForm.value.activities = current.filter(item => item !== value)
  else if (value === clean) reportForm.value.activities = [clean]
  else reportForm.value.activities = [...current.filter(item => item !== clean), value]
}
async function refreshHumanReports() {
  const result = await api.humanReports()
  humanReports.value = result.items
  inventoryGaps.value = result.inventory_gaps
}
async function saveHumanReport(skip = false) {
  reportSaving.value = true
  try {
    const activities = skip ? ['暂不说明'] : reportForm.value.activities
    await api.addHumanReport({
      occurred_at: new Date(reportForm.value.occurred_at).getTime() / 1000,
      activities,
      note: reportForm.value.note,
      source: reportGap.value ? 'gap' : 'proactive',
      gap_key: reportGap.value?.gap_key || null,
    })
    await refreshHumanReports()
    await load(days.value)
    reportMode.value = ''; reportGap.value = null
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '审神者报备保存失败' }
  finally { reportSaving.value = false }
}
async function skipGap(gap: InventoryGap) {
  openGapReport(gap)
  await saveHumanReport(true)
}
function gapDelta(gap: InventoryGap) {
  const order = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符']
  return order.filter(name => gap.resource_delta?.[name])
    .map(name => `${name} ${signed(Number(gap.resource_delta![name]))}`).join(' · ')
}

// ---- 数据加载 ----

async function load(nextDays = days.value) {
  days.value = nextDays; loading.value = true
  try {
    const [nextSummary, nextLedger, nextEvents, nextRuns, nextHuman] = await Promise.all([api.dataSummary(nextDays), api.resourceLedger(nextDays), api.dataEvents(1000), api.dataRuns(30), api.humanReports()])
    summary.value = nextSummary
    ledger.value = nextLedger
    events.value = nextEvents.items.filter(item => item.ts >= Date.now() / 1000 - nextDays * 86400)
    runs.value = nextRuns.items.filter(item => item.loops && item.started_at >= Date.now() / 1000 - nextDays * 86400)
    hasMoreEvents.value = nextEvents.has_more
    hasMoreRuns.value = nextRuns.has_more
    eventCursor.value = nextEvents.next_cursor
    runCursor.value = nextRuns.next_cursor
    humanReports.value = nextHuman.items
    inventoryGaps.value = nextHuman.inventory_gaps
    if (!recordDate.value) recordDate.value = latestRecordDate()
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '成绩单读取失败' }
  finally { loading.value = false }
}
async function loadOlder() {
  if (loadingOlder.value) return
  loadingOlder.value = true
  try {
    if (view.value === 'records' && recordDate.value) {
      const [start, end] = dayRange(recordDate.value)
      const requests: Promise<any>[] = []
      if (recordHasMoreEvents.value) requests.push(api.dataEvents(1000, recordEventCursor.value ?? undefined, start, end).then(next => {
        mergeEvents(next.items)
        recordEventCursor.value = next.next_cursor
        recordHasMoreEvents.value = next.has_more
      }))
      if (recordHasMoreRuns.value) requests.push(api.dataRuns(100, recordRunCursor.value ?? undefined, start, end).then(next => {
        mergeRuns(next.items)
        recordRunCursor.value = next.next_cursor
        recordHasMoreRuns.value = next.has_more
      }))
      await Promise.all(requests)
      return
    }
    const cutoff = Date.now() / 1000 - days.value * 86400
    const requests: Promise<any>[] = []
    if (hasMoreEvents.value) requests.push(api.dataEvents(1000, eventCursor.value ?? undefined).then(next => {
      events.value.push(...next.items.filter((item: any) => item.ts >= cutoff))
      eventCursor.value = next.next_cursor
      hasMoreEvents.value = next.has_more && next.items.some((item: any) => item.ts >= cutoff)
    }))
    if (hasMoreRuns.value) requests.push(api.dataRuns(30, runCursor.value ?? undefined).then(next => {
      runs.value.push(...next.items.filter((item: any) => item.loops && item.started_at >= cutoff))
      runCursor.value = next.next_cursor
      hasMoreRuns.value = next.has_more && next.items.some((item: any) => item.started_at >= cutoff)
    }))
    await Promise.all(requests)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '较早记录读取失败' }
  finally { loadingOlder.value = false }
}

async function refreshRecords() {
  await load(days.value)
  if (recordDate.value) await loadRecordDay(recordDate.value)
}
onMounted(() => load())
</script>

<template>
  <section class="report-panel">
    <PanelHeader variant="page" title="本丸" subtitle="账目、入手与接下来的打算">
      <template #actions>
        <div class="report-toolbar-actions">
          <SegmentedControl class="report-honmaru-switch" :model-value="honmaruTab" :items="honmaruItems" label="本丸页签" @update:model-value="honmaruTab = $event as 'report' | 'obtains' | 'planning'" />
        </div>
      </template>
    </PanelHeader>
    <div class="report-content">
      <p v-if="error" class="report-error">{{ error }}</p>

      <div v-if="honmaruTab === 'report'" class="report-context-toolbar">
        <SegmentedControl class="report-view-switch" :model-value="view" :items="viewItems" label="成绩单视图" @update:model-value="switchView($event as 'chart' | 'records')" />
        <SegmentedControl v-if="view === 'chart'" class="report-range-switch" :model-value="days" :items="rangeItems" label="统计时间范围" @update:model-value="load(Number($event))" />
      </div>
      <div v-else-if="honmaruTab === 'obtains'" class="report-context-toolbar report-context-toolbar-range">
        <SegmentedControl class="report-range-switch" :model-value="days" :items="rangeItems" label="统计时间范围" @update:model-value="load(Number($event))" />
      </div>

      <template v-if="honmaruTab === 'report'">
      <template v-if="view === 'chart'">
        <section class="report-glance" :class="{ loading }">
          <p class="report-glance-lead">🦊 {{ glance }}</p>
          <div v-if="glanceResources.length" class="report-glance-chips">
            <span v-for="row in glanceResources" :key="row.name" :class="{ gain: row.delta! > 0, loss: row.delta! < 0 }">{{ row.name }} {{ signed(row.delta) }}</span>
          </div>
        </section>

        <button v-if="unreportedGaps.length" type="button" class="report-attention" @click="openGapReport(unreportedGaps[0])">
          <span><b>🦊 有 {{ unreportedGaps.length }} 段家底变化等你认领</b><small>它们没有算进任何一轮挂机收益，说明一下就会染回彩色。</small></span><em>去说明 →</em>
        </button>

        <section class="resource-trend">
          <header>
            <div><h3>资源统计</h3></div>
            <nav v-if="mode === 'single'" aria-label="选择资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: selectedResource === name }" @click="chooseResource(name)">{{ name }}</button></nav>
            <nav v-else aria-label="选择要对比的资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: compareResources.includes(name) }" @click="toggleCompareResource(name)">{{ name }}</button></nav>
            <label class="compare-toggle"><input v-model="mode" type="checkbox" true-value="compare" false-value="single">对比几种资源</label>
          </header>
          <ResourceChart :dates="chartDates" :series="chartSeries" :stacked="mode === 'single'" :selected-date="selectedDate" :loading="loading" @select="onChartSelect" />
          <DayDetail v-if="dayDetail" v-bind="dayDetail" :highlight-category="highlightCategory" @close="selectedDate = ''; highlightCategory = ''" @report="openGapReport" @report-day="openProactiveReport(dayRange(dayDetail.date)[1] * 1000)" @open-records="selectRecordDate" />
          <form v-if="reportMode" ref="reportFormEl" class="report-form" @submit.prevent="saveHumanReport(false)">
            <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
            <fieldset><legend>这个时间段你做过什么？</legend><button v-for="value in [...humanActivities, '记不清了', '没有其他操作']" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
            <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" placeholder="可选，不用写具体资源数字"></label>
            <div class="report-form-actions"><button type="submit" class="primary" :disabled="reportSaving || (!reportForm.activities.length && !reportForm.note.trim())">{{ reportSaving ? '记录中……' : '记下来' }}</button><button type="button" class="secondary" @click="reportMode = ''; reportGap = null">先不说了</button></div>
          </form>
        </section>

        <section class="resource-ledger" :class="{ loading }">
          <header><div><h3>资源变化</h3><p>{{ ledgerDateRange }}</p></div><span class="ledger-confidence" :class="confidence.level"><b>{{ confidence.label }}</b>{{ confidence.detail }}</span></header>
          <div class="resource-ledger-grid">
            <article v-for="row in resourceRows" :key="row.name" :class="{ gain: row.delta != null && row.delta > 0, loss: row.delta != null && row.delta < 0 }">
              <small>{{ row.name }}</small><strong>{{ signed(row.delta) }}</strong><span v-if="row.current != null">当前 {{ row.current.toLocaleString() }}</span><span v-else>尚未观察到</span>
            </article>
          </div>
          <p class="fox-summary"><b>狐之助小结</b>{{ foxSummary }}</p>
        </section>

        <button v-if="swordDropTotal" type="button" class="report-obtains-link" @click="honmaruTab = 'obtains'">
          <b>🗡️ {{ rangeLabel }}收获 {{ swordDropTotal }} 振</b><em>查看入手记录 →</em>
        </button>

        <section v-if="unreportedGaps.length || !reportMode" class="inventory-gap-panel" aria-label="库存差值说明">
          <div v-for="gap in unreportedGaps" :key="gap.gap_key" class="inventory-gap-alert"><div><strong>🦊 上次任务和这次开工之间，家底对不上啦</strong><p>{{ gapDelta(gap) }}</p><small>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}。这段差值单独留档，不会算进任何一轮挂机收益。</small></div><button type="button" class="secondary" @click="openGapReport(gap)">这期间做过什么？</button><button type="button" @click="skipGap(gap)">不想说，记差值就好</button></div>
          <button v-if="!reportMode" type="button" class="secondary report-proactive" @click="openProactiveReport()">我自己动了家底，主动报备一笔</button>
        </section>
      </template>

      <ReportRecords v-if="view === 'records'" :events="events" :runs="runs" :selected-date="recordDate" :has-more-events="recordHasMoreEvents" :has-more-runs="recordHasMoreRuns" :loading="recordLoading" :loading-older="loadingOlder" @select-date="selectRecordDate" @load-more="loadOlder" @refresh="refreshRecords" />
      </template>

      <ObtainRecords v-else-if="honmaruTab === 'obtains'" :rows="swordDrops" :total="swordDropTotal" :range-label="rangeLabel" :loading="loading" />

      <PlanningPanel v-else />
    </div>
  </section>
</template>

<style scoped>
.report-context-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.report-context-toolbar-range { justify-content: flex-end; }
.report-glance { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; padding: 12px 16px; }
.report-glance-lead { margin: 0; font-size: 15px; }
.report-glance-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.report-glance-chips span { background: var(--paper); border: 1px solid var(--paper-line); border-radius: 999px; padding: 3px 10px; font-size: 13px; }
.report-glance-chips .gain { color: #4d7a3a; }
.report-glance-chips .loss { color: #b0492e; }
.resource-trend > header { display: flex; flex-direction: column; gap: 10px; margin-bottom: 8px; }
.resource-trend > header h3 { margin: 0; }
.resource-trend > header p { margin: 2px 0 0; color: var(--ink-dim); font-size: 13px; }
.resource-trend nav { display: flex; gap: 6px; flex-wrap: wrap; }
.resource-trend nav button { border: 1px solid var(--paper-line); background: var(--paper-card); color: var(--ink-dim); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.resource-trend nav button.active { background: var(--fox-gold-pale); border-color: var(--fox-gold); color: var(--ink); font-weight: 600; }
.compare-toggle { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-dim); font-size: 13px; }
.report-proactive { align-self: flex-start; }
.report-obtains-link { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; padding: 12px 16px; cursor: pointer; color: var(--ink); font-size: 14px; }
.report-obtains-link:hover { border-color: var(--fox-gold); }
.report-obtains-link em { font-style: normal; color: var(--fox-gold-deep); white-space: nowrap; }
.inventory-gap-panel:empty { display: none; }
.report-form { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding: 14px 16px; background: var(--paper-card); border: 1px solid var(--fox-gold); border-radius: 12px; }
.report-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ink-dim); }
.report-form input { max-width: 260px; }
.report-form fieldset { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; border: 0; }
.report-form legend { font-size: 13px; color: var(--ink-dim); margin-bottom: 4px; }
.report-form fieldset button { border: 1px solid var(--paper-line); background: var(--paper); color: var(--ink-dim); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.report-form fieldset button.active { background: var(--fox-gold-pale); border-color: var(--fox-gold); color: var(--ink); font-weight: 600; }
.report-form-actions { display: flex; gap: 8px; }
@media (max-width: 520px) {
  .report-context-toolbar { align-items: stretch; flex-direction: column; }
  .report-context-toolbar .segmented-control { width: 100%; }
  .report-context-toolbar .segmented-control button { flex: 1 1 0; min-width: 0; padding-inline: 7px; }
}
</style>
