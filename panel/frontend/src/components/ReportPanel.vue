<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from '../api'
import type { HumanReport, InventoryGap, ManualSession, ResourceLedger } from '../types'
import PanelHeader from './PanelHeader.vue'
import SegmentedControl from './SegmentedControl.vue'
import ResourceChart from './report/ResourceChart.vue'
import DayDetail from './report/DayDetail.vue'
import ReportRecords from './report/ReportRecords.vue'
import PlanningPanel from './report/PlanningPanel.vue'
import { categoryLabel, categoryOf, dayRange, eventTime, resourceColors, resourceNames, shanghaiDate, signed, sourceCategories } from './report/reportModel'
import type { ChartSeries } from './report/reportModel'

const days = ref(7)
const honmaruTab = ref<'report' | 'planning'>('report')
const view = ref<'chart' | 'records'>('chart')
const summary = ref<any>(null)
const ledger = ref<ResourceLedger | null>(null)
const events = ref<any[]>([])
const runs = ref<any[]>([])
const humanReports = ref<HumanReport[]>([])
const manualSessions = ref<ManualSession[]>([])
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
const inventoryFormOpen = ref(false)
const manualActionsOpen = ref(false)
const inventorySaving = ref(false)
const inventoryNotice = ref('')
const inventoryForm = ref<Record<string, number | null | ''>>({})
const manualSessionFormOpen = ref(false)
const manualSessionSaving = ref(false)
const manualSessionForm = ref({ script: 'osaka', loops: 1, started_at: '', ended_at: '', note: '' })
const deletingManualReport = ref<number | null>(null)

const rangeItems = [{ value: 1, label: '24 小时' }, { value: 7, label: '7 天' }, { value: 30, label: '30 天' }]
const honmaruItems = [
  { value: 'report', label: '成绩单' },
  { value: 'planning', label: '规划' },
]
const viewItems = [
  { value: 'chart', label: '概览' },
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
  if (!gain && !cost) {
    const cutoff = Date.now() / 1000 - days.value * 86400
    const manualCount = humanReports.value.filter(report => report.source === 'proactive'
      && Number(report.occurred_at) >= cutoff && report.claimed_delta).length
    return manualCount
      ? `${rangeLabel.value}你手动记了 ${manualCount} 项资源收支；まあ丸还没有能确认来源的自动流水。`
      : `${rangeLabel.value}还没有能确认玩法来源的资源变化。`
  }
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
// 刀剑明细已经归入“全部记录”，成绩单只保留这个时间段的总数。
const swordDropTotal = computed(() => events.value.filter(event => (
  ['sword.obtained', 'forge.collected', 'pumpkin.sword_obtained'].includes(event.event_type)
  && event.payload?.name
)).length)
const manualLoops = computed(() => {
  const cutoff = Date.now() / 1000 - days.value * 86400
  return manualSessions.value.filter(item => item.started_at >= cutoff)
    .reduce((total, item) => total + Number(item.loops || 0), 0)
})

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
const claimedDailyTotals = computed(() => {
  const totals: Record<string, Record<string, number>> = {}
  for (const report of humanReports.value) {
    const resource = String(report.resource || '')
    const delta = Number(report.claimed_delta)
    if (report.source !== 'proactive' || !resourceNames.includes(resource)
        || report.claimed_delta == null || !Number.isFinite(delta) || !delta) continue
    const date = shanghaiDate(Number(report.occurred_at))
    totals[date] ||= {}
    totals[date][resource] = (totals[date][resource] || 0) + delta
  }
  return totals
})
const recentManualReports = computed(() => humanReports.value.filter(report => (
  report.source === 'proactive' && resourceNames.includes(String(report.resource || ''))
  && report.claimed_delta != null && Number.isFinite(Number(report.claimed_delta))
  && Number(report.claimed_delta) !== 0
)).sort((a, b) => Number(b.occurred_at) - Number(a.occurred_at) || b.id - a.id))
const recentManualGroups = computed(() => {
  const groups = new Map<string, HumanReport[]>()
  for (const report of recentManualReports.value) {
    const key = report.group_id || `single:${report.id}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(report)
  }
  return [...groups.entries()].slice(0, 5).map(([key, entries]) => {
    const ordered = [...entries].sort((a, b) => resourceNames.indexOf(String(a.resource)) - resourceNames.indexOf(String(b.resource)))
    return { key, entries: ordered, head: entries[0] }
  })
})

function manualReportTime(timestamp: number) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(timestamp * 1000))
}

function manualReportSource(report: HumanReport) {
  return report.activities?.find(value => !['暂不说明', '记不清了', '没有其他操作'].includes(value)) || '未标来源'
}

function manualGroupAmounts(entries: HumanReport[]) {
  return entries.map(report => `${report.resource} ${signed(Number(report.claimed_delta))}`).join(' · ')
}

function claimWithinUnknown(unknown: number, claim: number): number {
  if (!unknown || !claim || Math.sign(unknown) !== Math.sign(claim)) return 0
  return Math.sign(unknown) * Math.min(Math.abs(unknown), Math.abs(claim))
}

function remainingUnknown(date: string, resource: string): number | null {
  const row = (ledger.value?.daily_series || []).find(item => item.date === date && item.resource === resource)
  if (row?.unattributed_delta == null) return null
  const requested = Number(reportedDailyTotals.value[date]?.[resource] || 0)
    + Number(claimedDailyTotals.value[date]?.[resource] || 0)
  return Number(row.unattributed_delta) - claimWithinUnknown(Number(row.unattributed_delta), requested)
}
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
  chartDates.value.forEach((date, index) => {
    const row = book.daily_series.find(item => item.resource === name && item.date === date)
    if (row?.unattributed_delta != null) {
      const requested = Number(reportedDailyTotals.value[date]?.[name] || 0)
        + Number(claimedDailyTotals.value[date]?.[name] || 0)
      const claimed = claimWithinUnknown(row.unattributed_delta, requested)
      byKey.human[index] += claimed
      byKey.unknown[index] += row.unattributed_delta - claimed
    }
  })
  return sourceCategories.map(cat => ({
    key: cat.key, name: cat.label, color: cat.color,
    values: byKey[cat.key].map(value => value || null),
  }))
})
const dayResourceOverview = computed(() => {
  if (days.value !== 1 || !ledger.value) return []
  const from = Number(ledger.value.window?.from || 0)
  const to = Number(ledger.value.window?.to || Date.now() / 1000)
  return resourceNames.map(resource => {
    const ledgerRow = ledger.value!.per_resource.find(item => item.resource === resource)
    const parts = new Map<string, number>()
    for (const item of ledger.value!.attributions || []) {
      if (item.resource !== resource || item.ts < from || item.ts > to) continue
      const key = categoryOf(item.source)
      parts.set(key, (parts.get(key) || 0) + Number(item.delta || 0))
    }
    const unknown = Number(ledgerRow?.unattributed_delta || 0)
    const requested = humanReports.value.filter(report => (
      report.source === 'proactive' && report.resource === resource
      && Number(report.occurred_at) >= from && Number(report.occurred_at) <= to
    )).reduce((sum, report) => sum + Number(report.claimed_delta || 0), 0)
    const claimed = claimWithinUnknown(unknown, requested)
    if (claimed) parts.set('human', claimed)
    if (unknown - claimed) parts.set('unknown', unknown - claimed)
    return {
      resource, total: ledgerRow?.total_delta ?? null,
      parts: sourceCategories.map(cat => ({ ...cat, label: cat.key === 'human' ? '你记的' : cat.label, value: parts.get(cat.key) || 0 })).filter(item => item.value),
    }
  })
})
const displayedChartDates = computed(() => days.value === 1 ? ['24h'] : chartDates.value)
const displayedChartLabels = computed(() => days.value === 1 ? ['近 24 小时'] : [])
const displayedChartSeries = computed<ChartSeries[]>(() => {
  if (days.value !== 1) return chartSeries.value
  if (mode.value === 'compare') {
    return compareResources.value.map(resource => ({
      key: resource,
      name: resource,
      color: resourceColors[resource] || '#8a7f72',
      values: [dayResourceOverview.value.find(row => row.resource === resource)?.total ?? null],
    }))
  }
  const row = dayResourceOverview.value.find(item => item.resource === selectedResource.value)
  return sourceCategories.map(category => ({
    key: category.key,
    name: category.key === 'human' ? '你记的' : category.label,
    color: category.color,
    values: [row?.parts.find(part => part.key === category.key)?.value || null],
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
    const gap = gapForDay(date, selectedResource.value)
    if (gap) openGapReport(gap)
    else openDayClaim(date, selectedResource.value, remainingUnknown(date, selectedResource.value))
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
function gapForDay(date: string, resource: string) {
  const [start, end] = dayRange(date)
  return unreportedGaps.value.find(gap => gap.started_at < end && gap.ended_at >= start
    && Number(gap.resource_delta?.[resource] || 0) !== 0) || null
}

function latestRecordDate(): string {
  const timestamps = [
    ...runs.value.map(run => Number(run.started_at)),
    ...events.value.map(event => Number(event.ts)),
    ...manualSessions.value.map(item => Number(item.started_at)),
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
  // 盘点、收杂物箱等一次性任务天生没有圈数，也是完整的任务记录。
  for (const item of items) merged.set(item.run_id, item)
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
  const unexplained = remainingUnknown(date, resource)
  const claimedAmount = row?.unattributed_delta == null || unexplained == null
    ? 0
    : Number(row.unattributed_delta) - unexplained
  return {
    date, resource,
    totalDelta: row?.total_delta ?? null,
    claimedAmount,
    unexplained,
    attributions: (ledger.value?.attributions || []).filter(item => item.resource === resource && start <= item.ts && item.ts < end),
    runs: runs.value.filter(run => start <= Number(run.started_at) && Number(run.started_at) < end),
    gaps: unreportedGaps.value.filter(gap => gap.started_at < end && gap.ended_at >= start
      && Number(gap.resource_delta?.[resource] || 0) !== 0),
  }
})

// ---- 审神者报备 ----

const reportMode = ref('')
const reportGap = ref<InventoryGap | null>(null)
const reportSaving = ref(false)
const reportForm = ref<{ activities: string[]; note: string; occurred_at: string; resource: string; claimed_delta: number | null; claim_limit: number | null }>({ activities: [], note: '', occurred_at: '', resource: '', claimed_delta: null, claim_limit: null })
const manualResourceAmounts = ref<Record<string, number | null | ''>>(Object.fromEntries(resourceNames.map(name => [name, null])))
const manualResourceEntries = computed(() => Object.fromEntries(resourceNames.flatMap(name => {
  const value = manualResourceAmounts.value[name]
  if (value == null || value === '') return []
  const amount = Number(value)
  return Number.isFinite(amount) && amount !== 0 ? [[name, amount]] : []
})))
const reportClaimInvalid = computed(() => {
  if (!reportForm.value.resource) return false
  const value = Number(reportForm.value.claimed_delta)
  const limit = Number(reportForm.value.claim_limit)
  if (!Number.isFinite(value) || !value) return true
  if (reportForm.value.claim_limit == null) return false
  return !Number.isFinite(limit) || !limit || Math.sign(value) !== Math.sign(limit) || Math.abs(value) > Math.abs(limit)
})
const reportHasPreciseClaim = computed(() => Boolean(
  reportForm.value.claim_limit == null
    ? Object.keys(manualResourceEntries.value).length
    : reportForm.value.resource && Number.isFinite(Number(reportForm.value.claimed_delta))
      && Number(reportForm.value.claimed_delta) && !reportClaimInvalid.value,
))
const reportSubmitDisabled = computed(() => {
  if (reportSaving.value || reportClaimInvalid.value) return true
  if (!reportGap.value && reportForm.value.claim_limit == null) return !Object.keys(manualResourceEntries.value).length
  return !reportHasPreciseClaim.value && !reportForm.value.activities.length && !reportForm.value.note.trim()
})
const humanActivities = ['领邮箱', '手动领奖', '手动出阵', '锻刀', '手入', '万屋购买', '其他操作']
function localDateTime(timestamp = Date.now()) {
  const date = new Date(timestamp - new Date(timestamp).getTimezoneOffset() * 60000)
  return date.toISOString().slice(0, 16)
}
const reportFormEl = ref<HTMLElement | null>(null)
function scrollToReportForm() {
  void nextTick(() => reportFormEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
}
function openProactiveReport(timestamp?: number, resource = '', claimedDelta: number | null = null) {
  manualActionsOpen.value = false
  inventoryFormOpen.value = false
  reportMode.value = 'proactive'
  reportGap.value = null
  reportForm.value = { activities: [], note: '', occurred_at: localDateTime(timestamp), resource, claimed_delta: claimedDelta, claim_limit: claimedDelta }
  manualResourceAmounts.value = Object.fromEntries(resourceNames.map(name => [name, null]))
  scrollToReportForm()
}
function openDayClaim(date: string, resource: string, unexplained: number | null) {
  const amount = Number(unexplained)
  if (!Number.isFinite(amount) || !amount) return
  openProactiveReport(Math.min(dayRange(date)[1] * 1000 - 1, Date.now()), resource, amount)
}
function openGapReport(gap: InventoryGap) {
  reportMode.value = `gap:${gap.gap_key}`
  reportGap.value = gap
  reportForm.value = { activities: [], note: '', occurred_at: localDateTime(gap.ended_at * 1000), resource: '', claimed_delta: null, claim_limit: null }
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
    const isManualBatch = !reportGap.value && reportForm.value.claim_limit == null
    const claimedPrecisely = Boolean(isManualBatch
      ? Object.keys(manualResourceEntries.value).length
      : !reportGap.value && reportForm.value.resource && reportForm.value.claimed_delta)
    const activities = skip ? ['暂不说明'] : reportForm.value.activities
    const occurred_at = new Date(reportForm.value.occurred_at).getTime() / 1000
    if (isManualBatch) {
      await api.addHumanReportBatch({ occurred_at, activities, note: reportForm.value.note, entries: manualResourceEntries.value })
    } else {
      await api.addHumanReport({
        occurred_at, activities, note: reportForm.value.note,
        source: reportGap.value ? 'gap' : 'proactive',
        gap_key: reportGap.value?.gap_key || null,
        resource: reportGap.value ? null : reportForm.value.resource || null,
        claimed_delta: reportGap.value ? null : reportForm.value.claimed_delta,
      })
    }
    await refreshHumanReports()
    await load(days.value)
    if (claimedPrecisely) {
      highlightCategory.value = 'human'
      inventoryNotice.value = isManualBatch
        ? `已记下 ${Object.keys(manualResourceEntries.value).length} 种资源的收支。`
        : `已记下 ${reportForm.value.resource} ${signed(Number(reportForm.value.claimed_delta))}。`
    }
    reportMode.value = ''; reportGap.value = null
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '审神者报备保存失败' }
  finally { reportSaving.value = false }
}

async function deleteManualReport(report: HumanReport) {
  const group = report.group_id ? recentManualReports.value.filter(item => item.group_id === report.group_id) : [report]
  const label = group.length > 1 ? `这组 ${group.length} 种资源` : `这笔 ${report.resource} ${signed(Number(report.claimed_delta))}`
  if (!window.confirm(`撤销${label}的手账吗？`)) return
  deletingManualReport.value = report.id
  try {
    if (report.group_id) await api.deleteHumanReportGroup(report.group_id)
    else await api.deleteHumanReport(report.id)
    inventoryNotice.value = group.length > 1 ? '这组手账已撤销。' : '这笔手账已撤销。'
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '撤销手账失败' }
  finally { deletingManualReport.value = null }
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

function openInventoryForm() {
  manualActionsOpen.value = false
  reportMode.value = ''
  reportGap.value = null
  inventoryNotice.value = ''
  inventoryForm.value = Object.fromEntries(resourceNames.map(name => [name, null]))
  inventoryFormOpen.value = true
}

function openManualSessionForm() {
  manualActionsOpen.value = false
  inventoryFormOpen.value = false
  reportMode.value = ''
  reportGap.value = null
  const ended = Date.now()
  manualSessionForm.value = {
    script: 'osaka', loops: 1,
    started_at: localDateTime(ended - 60 * 60 * 1000),
    ended_at: localDateTime(ended), note: '',
  }
  manualSessionFormOpen.value = true
}

async function saveManualSession() {
  manualSessionSaving.value = true
  try {
    await api.addManualSession({
      script: manualSessionForm.value.script,
      loops: Number(manualSessionForm.value.loops),
      started_at: new Date(manualSessionForm.value.started_at).getTime() / 1000,
      ended_at: new Date(manualSessionForm.value.ended_at).getTime() / 1000,
      note: manualSessionForm.value.note,
    })
    manualSessionFormOpen.value = false
    inventoryNotice.value = '已记下这段活动；不会算进まあ丸战绩。'
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '手动活动记录失败' }
  finally { manualSessionSaving.value = false }
}

async function saveManualInventory() {
  const resources = Object.fromEntries(resourceNames.flatMap(name => {
    const value = inventoryForm.value[name]
    return value == null || value === '' ? [] : [[name, Number(value)]]
  }))
  if (!Object.keys(resources).length) {
    error.value = '至少填一项家底。'
    return
  }
  inventorySaving.value = true
  try {
    await api.addManualInventory(resources)
    inventoryFormOpen.value = false
    inventoryNotice.value = `已记录 ${Object.keys(resources).length} 项家底。`
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '家底记录失败' }
  finally { inventorySaving.value = false }
}

// ---- 数据加载 ----

async function load(nextDays = days.value) {
  days.value = nextDays; loading.value = true
  try {
    const [nextSummary, nextLedger, nextEvents, nextRuns, nextHuman, nextManualSessions] = await Promise.all([api.dataSummary(nextDays), api.resourceLedger(nextDays), api.dataEvents(1000), api.dataRuns(30), api.humanReports(), api.manualSessions(1000, Date.now() / 1000 - 365 * 86400)])
    summary.value = nextSummary
    ledger.value = nextLedger
    events.value = nextEvents.items.filter(item => item.ts >= Date.now() / 1000 - nextDays * 86400)
    runs.value = nextRuns.items.filter(item => item.started_at >= Date.now() / 1000 - nextDays * 86400)
    hasMoreEvents.value = nextEvents.has_more
    hasMoreRuns.value = nextRuns.has_more
    eventCursor.value = nextEvents.next_cursor
    runCursor.value = nextRuns.next_cursor
    humanReports.value = nextHuman.items
    inventoryGaps.value = nextHuman.inventory_gaps
    manualSessions.value = nextManualSessions.items
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
      mergeRuns(next.items.filter((item: any) => item.started_at >= cutoff))
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
    <PanelHeader variant="page" title="本丸" subtitle="账目和接下来的打算">
      <template #actions>
        <div class="report-toolbar-actions">
          <SegmentedControl class="report-honmaru-switch" :model-value="honmaruTab" :items="honmaruItems" label="本丸页签" @update:model-value="honmaruTab = $event as 'report' | 'planning'" />
        </div>
      </template>
    </PanelHeader>
    <div class="report-content">
      <p v-if="error" class="report-error">{{ error }}</p>

      <div v-if="honmaruTab === 'report'" class="report-context-toolbar">
        <SegmentedControl class="report-view-switch" :model-value="view" :items="viewItems" label="成绩单视图" @update:model-value="switchView($event as 'chart' | 'records')" />
        <SegmentedControl v-if="view === 'chart'" class="report-range-switch" :model-value="days" :items="rangeItems" label="统计时间范围" @update:model-value="load(Number($event))" />
      </div>
      <template v-if="honmaruTab === 'report'">
      <template v-if="view === 'chart'">
        <section class="report-glance" :class="{ loading }">
          <div class="report-glance-copy"><p class="report-glance-lead">🦊 {{ glance }}</p><p>{{ foxSummary }}</p></div>
          <div v-if="swordDropTotal || manualLoops" class="report-glance-chips">
            <span v-if="swordDropTotal" class="obtain">入手 {{ swordDropTotal }} 振</span>
            <span v-if="manualLoops" class="manual">你手动记了 {{ manualLoops }} 圈</span>
          </div>
        </section>

        <button v-if="unreportedGaps.length" type="button" class="report-attention" @click="openGapReport(unreportedGaps[0])">
          <span><b>🦊 有 {{ unreportedGaps.length }} 段家底变化等你认领</b><small>它们没有算进任何一轮挂机收益，说明一下就会染回彩色。</small></span><em>去说明 →</em>
        </button>

        <section class="resource-ledger" :class="{ loading }">
          <header><div><h3>家底概览</h3><p>{{ ledgerDateRange }}的变化</p></div><div class="ledger-actions"><span class="ledger-confidence" :class="confidence.level"><b>{{ confidence.label }}</b></span><button v-if="!inventoryFormOpen && !reportMode" type="button" class="secondary" @click="manualActionsOpen = !manualActionsOpen">＋ 手动记账</button></div></header>
          <div v-if="manualActionsOpen" class="manual-action-picker">
            <button type="button" @click="openProactiveReport()"><b>记一笔收支</b><small>记下自己获得或花掉的资源</small></button>
            <button type="button" @click="openManualSessionForm"><b>补记一段活动</b><small>记玩法、圈数和时间；与まあ丸分开计算</small></button>
            <button type="button" @click="openInventoryForm"><b>更新当前家底</b><small>把游戏里现在的资源数字抄下来</small></button>
          </div>
          <p v-if="inventoryNotice" class="inventory-notice" role="status">✓ {{ inventoryNotice }}</p>
          <section v-if="recentManualGroups.length" class="recent-manual-ledger" aria-labelledby="recent-manual-ledger-title">
            <header><div><h4 id="recent-manual-ledger-title">最近手账</h4><p>这里只列你自己记的收支</p></div><small>最近 {{ recentManualGroups.length }} 组</small></header>
            <ul>
              <li v-for="group in recentManualGroups" :key="group.key">
                <time>{{ manualReportTime(group.head.occurred_at) }}</time>
                <span><b>{{ manualReportSource(group.head) }}<template v-if="group.entries.length > 1"> · {{ group.entries.length }} 种资源</template></b><small>{{ manualGroupAmounts(group.entries) }}<template v-if="group.head.note"> · {{ group.head.note }}</template></small></span>
                <button type="button" :disabled="deletingManualReport === group.head.id" @click="deleteManualReport(group.head)">{{ deletingManualReport === group.head.id ? '撤销中…' : '撤销' }}</button>
              </li>
            </ul>
          </section>
          <form v-if="inventoryFormOpen" class="manual-inventory-form" @submit.prevent="saveManualInventory">
            <header><div><h4>更新当前家底</h4><p>时间自动记为现在；不确定的项目可以留空。</p></div><button type="button" class="inventory-close" aria-label="关闭家底记录" @click="inventoryFormOpen = false">×</button></header>
            <div class="manual-inventory-grid"><label v-for="name in resourceNames" :key="name">{{ name }}<input v-model.number="inventoryForm[name]" type="number" min="0" step="1" inputmode="numeric" placeholder="留空"></label></div>
            <div class="report-form-actions"><button type="submit" class="primary" :disabled="inventorySaving">{{ inventorySaving ? '记录中……' : '记下当前家底' }}</button><button type="button" class="secondary" @click="inventoryFormOpen = false">取消</button></div>
          </form>
          <div class="resource-ledger-grid">
            <article v-for="row in resourceRows" :key="row.name" :class="{ gain: row.delta != null && row.delta > 0, loss: row.delta != null && row.delta < 0 }">
              <small>{{ row.name }}</small><strong>{{ signed(row.delta) }}</strong><span v-if="row.current != null">当前 {{ row.current.toLocaleString() }}</span><span v-else>尚未观察到</span>
            </article>
          </div>
          <details class="ledger-evidence"><summary>查看对账依据</summary><p>{{ confidence.detail }}</p></details>
        </section>

        <form v-if="manualSessionFormOpen" class="manual-session-form" @submit.prevent="saveManualSession">
          <header><div><h4>补记一段活动</h4><p>这里只记你自己打的，不会并进まあ丸完成的圈数。</p></div><button type="button" class="inventory-close" aria-label="关闭手动活动" @click="manualSessionFormOpen = false">×</button></header>
          <div class="manual-session-fields">
            <label>玩法<select v-model="manualSessionForm.script"><option value="osaka">大阪城</option><option value="raid">联队战</option><option value="edocastle">江户城</option><option value="sortie">合战场</option><option value="yosari">异去</option><option value="pumpkin">季节活动</option></select></label>
            <label>圈数<input v-model.number="manualSessionForm.loops" type="number" min="1" max="100000" step="1" required></label>
            <label>开始时间<input v-model="manualSessionForm.started_at" type="datetime-local" required></label>
            <label>结束时间<input v-model="manualSessionForm.ended_at" type="datetime-local" required></label>
            <label class="manual-session-note">备注<input v-model="manualSessionForm.note" maxlength="200" placeholder="可不填"></label>
          </div>
          <div class="report-form-actions"><button type="submit" class="primary" :disabled="manualSessionSaving">{{ manualSessionSaving ? '记录中……' : '记下这段活动' }}</button><button type="button" class="secondary" @click="manualSessionFormOpen = false">取消</button></div>
        </form>

        <form v-if="reportMode" ref="reportFormEl" class="report-form" @submit.prevent="saveHumanReport(false)">
          <header class="report-form-heading"><div><h4>{{ reportGap ? '说明这段差值' : reportForm.claim_limit != null ? '认领这笔变化' : '记一笔收支' }}</h4><p>{{ reportGap ? '说说这期间做过什么，不用硬猜具体数额。' : reportForm.claim_limit != null ? '确认其中有多少是你自己操作造成的。' : '正数是获得，负数是消耗。' }}</p></div><button type="button" class="inventory-close" aria-label="关闭补记" @click="reportMode = ''; reportGap = null">×</button></header>
          <p v-if="reportForm.resource && reportForm.claim_limit != null" class="report-claim-summary"><b>认领这笔：</b>{{ reportForm.resource }} {{ signed(reportForm.claimed_delta) }}</p>
          <template v-if="!reportGap && reportForm.claim_limit == null">
            <fieldset class="multi-resource-entry"><legend>这次有哪些资源变化？</legend><label v-for="name in resourceNames" :key="name">{{ name }}<input v-model.number="manualResourceAmounts[name]" type="number" step="1" placeholder="留空"></label><small>获得填正数，消耗填负数；没有变化的留空。</small></fieldset>
          </template>
          <label v-if="reportForm.resource && reportForm.claim_limit != null">认领数额<input v-model.number="reportForm.claimed_delta" type="number" step="1" :min="Number(reportForm.claim_limit) > 0 ? 1 : reportForm.claim_limit ?? undefined" :max="Number(reportForm.claim_limit) > 0 ? reportForm.claim_limit ?? undefined : -1"><small>最多认领当前灰色部分 {{ signed(reportForm.claim_limit) }}</small></label>
          <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
          <fieldset><legend>{{ reportGap ? '这个时间段你做过什么？' : '顺手标一下来源（可不选）' }}</legend><button v-for="value in [...humanActivities, '记不清了', '没有其他操作']" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
          <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" :placeholder="reportForm.resource ? '可选，资源和数额已经记好了' : '可选，不用写具体资源数字'"></label>
          <div class="report-form-actions"><button type="submit" class="primary" :disabled="reportSubmitDisabled">{{ reportSaving ? '记录中……' : '记下来' }}</button><button type="button" class="secondary" @click="reportMode = ''; reportGap = null">取消</button></div>
        </form>

        <section class="resource-trend">
          <header>
            <div><h3>变化趋势</h3></div>
            <nav v-if="mode === 'single'" aria-label="选择资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: selectedResource === name }" @click="chooseResource(name)">{{ name }}</button></nav>
            <nav v-else aria-label="选择要对比的资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: compareResources.includes(name) }" @click="toggleCompareResource(name)">{{ name }}</button></nav>
            <label class="compare-toggle"><input v-model="mode" type="checkbox" true-value="compare" false-value="single">对比几种资源</label>
          </header>
          <ResourceChart :dates="displayedChartDates" :labels="displayedChartLabels" :series="displayedChartSeries" :stacked="mode === 'single'" :selected-date="selectedDate" :loading="loading" @select="days !== 1 && onChartSelect($event)" />
          <template v-if="days !== 1">
            <DayDetail v-if="dayDetail" v-bind="dayDetail" :highlight-category="highlightCategory" @close="selectedDate = ''; highlightCategory = ''" @report="openGapReport" @report-day="openDayClaim(dayDetail.date, dayDetail.resource, dayDetail.unexplained)" @open-records="selectRecordDate" />
          </template>
        </section>

        <section v-if="unreportedGaps.length" class="inventory-gap-panel" aria-label="库存差值说明">
          <div v-for="gap in unreportedGaps" :key="gap.gap_key" class="inventory-gap-alert"><div><strong>🦊 上次任务和这次开工之间，家底对不上啦</strong><p>{{ gapDelta(gap) }}</p><small>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}。这段差值单独留档，不会算进任何一轮挂机收益。</small></div><button type="button" class="secondary" @click="openGapReport(gap)">这期间做过什么？</button><button type="button" @click="skipGap(gap)">不想说，记差值就好</button></div>
        </section>
      </template>

      <ReportRecords v-if="view === 'records'" :events="events" :runs="runs" :manual-sessions="manualSessions" :selected-date="recordDate" :has-more-events="recordHasMoreEvents" :has-more-runs="recordHasMoreRuns" :loading="recordLoading" :loading-older="loadingOlder" @select-date="selectRecordDate" @load-more="loadOlder" @refresh="refreshRecords" />
      </template>

      <PlanningPanel v-else />
    </div>
  </section>
</template>

<style scoped>
.report-context-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.report-context-toolbar-range { justify-content: flex-end; }
.report-glance { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; padding: 12px 16px; }
.report-glance-lead { margin: 0; font-size: 15px; }
.report-glance-copy { display: grid; gap: 3px; }
.report-glance-copy > p:last-child { margin: 0; color: var(--ink-dim); font-size: 12px; }
.report-glance-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.report-glance-chips span { background: var(--paper); border: 1px solid var(--paper-line); border-radius: 999px; padding: 3px 10px; font-size: 13px; }
.report-glance-chips .gain { color: #4d7a3a; }
.report-glance-chips .loss { color: #b0492e; }
.report-glance-chips .obtain { color: var(--fox-gold-deep); }
.report-glance-chips .manual { color: #536f8a; }
.resource-trend > header { display: flex; flex-direction: column; gap: 10px; margin-bottom: 8px; }
.resource-trend > header h3 { margin: 0; }
.resource-trend > header p { margin: 2px 0 0; color: var(--ink-dim); font-size: 13px; }
.resource-trend nav { display: flex; gap: 6px; flex-wrap: wrap; }
.resource-trend nav button { border: 1px solid var(--paper-line); background: var(--paper-card); color: var(--ink-dim); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.resource-trend nav button.active { background: var(--fox-gold-pale); border-color: var(--fox-gold); color: var(--ink); font-weight: 600; }
.compare-toggle { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-dim); font-size: 13px; }
.ledger-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.manual-action-picker { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; padding: 10px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 10px; }
.manual-action-picker button { display: grid; gap: 3px; padding: 10px 12px; color: var(--ink); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 8px; text-align: left; cursor: pointer; }
.manual-action-picker button:hover { border-color: var(--fox-gold); }
.manual-action-picker small { color: var(--ink-dim); font-size: 11px; line-height: 1.45; }
.manual-session-form { display: grid; gap: 12px; padding: 14px 16px; background: var(--paper-card); border: 1px solid #7d9ab2; border-radius: 12px; }
.manual-session-form > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.manual-session-form h4, .manual-session-form p { margin: 0; }
.manual-session-form header p { margin-top: 3px; color: var(--ink-dim); font-size: 12px; }
.manual-session-fields { display: grid; grid-template-columns: .8fr .55fr 1fr 1fr; gap: 10px; }
.manual-session-fields label { display: grid; gap: 4px; color: var(--ink-dim); font-size: 12px; }
.manual-session-fields input, .manual-session-fields select { width: 100%; min-width: 0; }
.manual-session-fields .manual-session-note { grid-column: 1 / -1; }
.ledger-evidence { margin-top: 8px; color: var(--ink-dim); font-size: 11px; }
.ledger-evidence summary { color: var(--fox-gold-deep); cursor: pointer; }
.ledger-evidence p { margin: 6px 0 0; }
.inventory-notice { margin: 0 0 10px; padding: 8px 10px; color: #426b35; background: #edf5e8; border-radius: 8px; }
.recent-manual-ledger { margin-bottom: 12px; padding: 12px 14px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 10px; }
.recent-manual-ledger > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.recent-manual-ledger h4, .recent-manual-ledger p { margin: 0; }
.recent-manual-ledger header p, .recent-manual-ledger header small { margin-top: 2px; color: var(--ink-dim); font-size: 11px; }
.recent-manual-ledger ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.recent-manual-ledger li { display: grid; grid-template-columns: 88px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 8px 10px; background: var(--paper-card); border-radius: 8px; }
.recent-manual-ledger time { color: var(--ink-dim); font-size: 11px; }
.recent-manual-ledger li span { display: grid; min-width: 0; }
.recent-manual-ledger li span small { overflow: hidden; color: var(--ink-dim); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.recent-manual-ledger li strong { font-variant-numeric: tabular-nums; }
.recent-manual-ledger li strong.gain { color: #47734f; }
.recent-manual-ledger li strong.loss { color: var(--danger); }
.recent-manual-ledger li button { padding: 3px 7px; color: var(--danger); background: transparent; border: 0; font-size: 11px; }
.manual-inventory-form { display: grid; gap: 12px; margin-bottom: 12px; padding: 14px 16px; background: var(--paper-card); border: 1px solid var(--fox-gold); border-radius: 12px; }
.manual-inventory-form > header { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.manual-inventory-form h4, .manual-inventory-form p { margin: 0; }
.manual-inventory-form p { margin-top: 3px; color: var(--ink-dim); font-size: 12px; }
.inventory-close { min-width: 32px; min-height: 32px; padding: 0; color: var(--ink-dim); background: transparent; border: 0; font-size: 20px; }
.manual-inventory-grid { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }
.manual-inventory-grid label { display: grid; gap: 4px; color: var(--ink-dim); font-size: 12px; }
.manual-inventory-grid input { width: 100%; min-width: 0; }
.inventory-gap-panel:empty { display: none; }
.report-form { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding: 14px 16px; background: var(--paper-card); border: 1px solid var(--fox-gold); border-radius: 12px; }
.report-form-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.report-form-heading h4, .report-form-heading p { margin: 0; }
.report-form-heading p { margin-top: 3px; color: var(--ink-dim); font-size: 12px; }
.report-claim-summary { margin: 0; padding: 9px 11px; color: var(--ink); background: var(--fox-gold-pale); border-radius: 8px; }
.report-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ink-dim); }
.report-form input, .report-form select { width: min(320px, 100%); }
.report-form fieldset { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; border: 0; }
.report-form legend { font-size: 13px; color: var(--ink-dim); margin-bottom: 4px; }
.report-form fieldset button { border: 1px solid var(--paper-line); background: var(--paper); color: var(--ink-dim); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.report-form fieldset button.active { background: var(--fox-gold-pale); border-color: var(--fox-gold); color: var(--ink); font-weight: 600; }
.report-form .multi-resource-entry { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 8px; padding: 10px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 9px; }
.report-form .multi-resource-entry legend { grid-column: 1 / -1; }
.report-form .multi-resource-entry label { gap: 3px; }
.report-form .multi-resource-entry input { width: 100%; min-width: 0; }
.report-form .multi-resource-entry > small { grid-column: 1 / -1; color: var(--ink-dim); }
.report-form-actions { display: flex; gap: 8px; }
@media (max-width: 520px) {
  .manual-inventory-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .manual-action-picker { grid-template-columns: 1fr; }
  .manual-session-fields { grid-template-columns: 1fr; }
  .manual-session-fields .manual-session-note { grid-column: 1; }
  .recent-manual-ledger li { grid-template-columns: minmax(0, 1fr) auto; }
  .recent-manual-ledger time { grid-column: 1 / -1; }
  .report-form .multi-resource-entry { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .resource-ledger > header, .ledger-actions { align-items: stretch; flex-direction: column; }
  .report-context-toolbar { align-items: stretch; flex-direction: column; }
  .report-context-toolbar .segmented-control { width: 100%; }
  .report-context-toolbar .segmented-control button { flex: 1 1 0; min-width: 0; padding-inline: 7px; }
}
</style>
