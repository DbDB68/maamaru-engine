<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from '../api'
import type { HumanReport, InventoryGap, LedgerImportPreview, LedgerOnboarding, ManualInventory, ManualSession, PlanningGoalAdvice, PlanningReport, ResourceLedger } from '../types'
import PanelHeader from './PanelHeader.vue'
import SegmentedControl from './SegmentedControl.vue'
import ResourceChart from './report/ResourceChart.vue'
import DayDetail from './report/DayDetail.vue'
import ReportRecords from './report/ReportRecords.vue'
import PlanningPanel from './report/PlanningPanel.vue'
import { categoryLabel, categoryOf, dayRange, eventTime, resourceColors, resourceNames, scriptNames, shanghaiDate, signed, sourceCategories } from './report/reportModel'
import type { ChartSeries } from './report/reportModel'

const emit = defineEmits<{ 'open-wishlist': []; 'open-expedition': [] }>()
const props = defineProps<{ initialSection?: 'report' | 'records' | 'planning' }>()

const days = ref(7)
const honmaruTab = ref<'report' | 'planning'>(props.initialSection === 'planning' ? 'planning' : 'report')
const view = ref<'chart' | 'records'>(props.initialSection === 'records' ? 'records' : 'chart')
const summary = ref<any>(null)
const ledger = ref<ResourceLedger | null>(null)
const planning = ref<PlanningReport | null>(null)
const events = ref<any[]>([])
const runs = ref<any[]>([])
const humanReports = ref<HumanReport[]>([])
const manualSessions = ref<ManualSession[]>([])
const manualInventories = ref<ManualInventory[]>([])
const inventoryGaps = ref<InventoryGap[]>([])
const loading = ref(false)
const loadingOlder = ref(false)
const error = ref('')
const hasMoreEvents = ref(false), hasMoreRuns = ref(false)
const eventCursor = ref<number | null>(null), runCursor = ref<number | null>(null)
const recordDate = ref('')
const recordHighlightRunId = ref('')
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
const inventoryObservedAt = ref('')
const editingInventoryId = ref<number | null>(null)
const manualSessionFormOpen = ref(false)
const manualSessionSaving = ref(false)
const manualSessionForm = ref({ script: 'osaka', loops: 1, started_at: '', ended_at: '', note: '' })
const editingManualSessionId = ref<number | null>(null)
const editingManualReport = ref<{ groupId?: string; reportId?: number } | null>(null)
const handLedgerExpanded = ref(false)
const manualEntryBusy = ref('')
const ledgerTransferOpen = ref(false)
const ledgerTransferBusy = ref('')
const ledgerImportInput = ref<HTMLInputElement | null>(null)
const ledgerImportPreview = ref<LedgerImportPreview | null>(null)
const acceptLedgerConflicts = ref(false)
const ledgerTransferNotice = ref('')
const ledgerOnboarding = ref<LedgerOnboarding | null>(null)
const ledgerOnboardingBusy = ref('')
const planningPanelRef = ref<{ openCustomForm: () => Promise<void> } | null>(null)
const swordWishlist = ref<string[]>([])
const failedRun = ref<any | null>(null)

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

const goalStatusRank: Record<PlanningGoalAdvice['status'], number> = {
  active: 0, behind: 0, on_track: 1, unknown: 2, done: 3, expired: 4,
}

function goalForResource(resource: string) {
  return [...(planning.value?.goals || [])]
    .filter(goal => goal.resource === resource && (goal.kind || 'resource') === 'resource')
    .sort((left, right) => goalStatusRank[left.status] - goalStatusRank[right.status])[0] || null
}

const resourceRows = computed(() => resourceNames.map(name => {
  const row = (ledger.value?.per_resource || []).find(item => item.resource === name)
  const rate = planning.value?.rates?.[name]
  return { name, before: row?.opening ?? null, current: row?.closing ?? null,
    delta: row?.total_delta ?? null, attributed: row?.attributed_delta ?? 0,
    unattributed: row?.unattributed_delta ?? null, observations: row?.observation_count ?? 0,
    confidence: row?.confidence || 'low', rate: rate?.daily ?? null,
    rateDays: rate?.days_observed ?? 0, goal: goalForResource(name) }
}))
const rateWindowLabel = computed(() => `近 ${planning.value?.rate_window_days || 14} 天平常日均`)

function goalSummary(goal: PlanningGoalAdvice) {
  if (goal.status === 'done') return '目标已经达成'
  if (goal.goal_mode === 'deadline_target' && goal.projected != null) {
    return `到期预计 ${Math.round(goal.projected).toLocaleString()}`
  }
  if (goal.target != null && goal.current != null) {
    const remaining = Math.max(0, goal.target - goal.current)
    if (remaining) return `还差 ${Math.round(remaining).toLocaleString()}`
  }
  if (goal.shortfall != null && goal.shortfall > 0) return `预计还差 ${Math.round(goal.shortfall).toLocaleString()}`
  if (goal.status === 'on_track') return '照现在速度来得及'
  if (goal.status === 'behind') return '需要再加把劲'
  return '查看目标进度'
}

function shortGoalDate(value: string | null | undefined) {
  const match = String(value || '').match(/^\d{4}-(\d{2})-(\d{2})/)
  return match ? `${Number(match[1])}/${Number(match[2])}` : ''
}

function goalMeta(goal: PlanningGoalAdvice) {
  if (goal.goal_mode === 'amount_target' && goal.estimated_deadline) return `预计 ${shortGoalDate(goal.estimated_deadline)}`
  if (goal.deadline) return `${shortGoalDate(goal.deadline)} 截止`
  return '规划'
}

async function openPlanning() {
  honmaruTab.value = 'planning'
  await nextTick()
  document.querySelector('.report-panel')?.scrollIntoView({ block: 'start' })
}

async function beginLedgerOnboarding() {
  ledgerOnboardingBusy.value = 'inventory'
  try {
    ledgerOnboarding.value = await api.updateLedgerOnboarding('start')
    openInventoryForm()
    await nextTick()
    document.querySelector('.manual-inventory-form')?.scrollIntoView({ block: 'start' })
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '首次设置没能开始' }
  finally { ledgerOnboardingBusy.value = '' }
}

function openOnboardingImport() {
  ledgerTransferOpen.value = true
  chooseLedgerImport()
  void nextTick().then(() => document.querySelector('.ledger-transfer')?.scrollIntoView({ block: 'start' }))
}

async function advanceLedgerOnboarding(step: 2 | 3) {
  ledgerOnboardingBusy.value = `step-${step}`
  try {
    ledgerOnboarding.value = await api.updateLedgerOnboarding('advance', step)
    if (step === 3) {
      honmaruTab.value = 'planning'
      await nextTick()
      document.querySelector('.ledger-onboarding-goal')?.scrollIntoView({ block: 'start' })
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '首次设置进度保存失败' }
  finally { ledgerOnboardingBusy.value = '' }
}

async function openOnboardingGoal() {
  honmaruTab.value = 'planning'
  await nextTick()
  await planningPanelRef.value?.openCustomForm()
}

async function finishLedgerOnboarding() {
  if (!ledgerOnboarding.value?.visible || ledgerOnboarding.value.step !== 3) return
  ledgerOnboardingBusy.value = 'complete'
  try {
    ledgerOnboarding.value = await api.updateLedgerOnboarding('complete')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '首次设置完成状态保存失败' }
  finally { ledgerOnboardingBusy.value = '' }
}

async function dismissLedgerOnboarding() {
  ledgerOnboardingBusy.value = 'dismiss'
  try {
    ledgerOnboarding.value = await api.updateLedgerOnboarding('dismiss')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '首次设置状态保存失败' }
  finally { ledgerOnboardingBusy.value = '' }
}
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
const topSortie = computed(() => {
  const group = (summary.value?.activity?.sortie_groups || [])[0]
  if (!group) return ''
  if (group.label) return String(group.label)
  if (group.event_type === 'edocastle.run_completed') return '江户城'
  if (group.event_type === 'osaka.floor_completed') return '大阪城'
  if (group.event_type === 'raid.round_completed') return '联队战'
  if (group.event_type === 'pumpkin.sortie_completed') return '南瓜大作战'
  if (group.event_type === 'sortie.completed') return scriptNames[group.payload?.mode] || '合战场'
  if (group.event_type === 'sortie.retreated_before_boss') return '合战场'
  return ''
})
type ReportInsight = {
  key: string
  title: string
  detail: string
  tone: 'plain' | 'gain' | 'cost' | 'alert' | 'goal'
  score: number
  resource?: string
  date?: string
  runId?: string
  target?: 'chart' | 'planning' | 'records'
}

const sourceLeaders = computed(() => {
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
  return {
    gain: entries.filter(item => item.delta > 0).sort((a, b) => b.delta - a.delta)[0] || null,
    cost: entries.filter(item => item.delta < 0).sort((a, b) => a.delta - b.delta)[0] || null,
  }
})

const anomalyInsight = computed<ReportInsight | null>(() => {
  const candidates: Array<{ resource: string; date: string; delta: number; ratio: number }> = []
  for (const resource of resourceNames) {
    const rows = (ledger.value?.daily_series || []).filter(item => item.resource === resource
      && item.total_delta != null && Number(item.total_delta) !== 0)
    if (rows.length < 3) continue
    const ordered = [...rows].sort((left, right) => Math.abs(Number(right.total_delta)) - Math.abs(Number(left.total_delta)))
    const peak = ordered[0]
    const baseline = ordered.slice(1).reduce((sum, item) => sum + Math.abs(Number(item.total_delta)), 0) / (ordered.length - 1)
    if (!baseline) continue
    const ratio = Math.abs(Number(peak.total_delta)) / baseline
    if (ratio >= 2) candidates.push({ resource, date: peak.date, delta: Number(peak.total_delta), ratio })
  }
  const peak = candidates.sort((left, right) => right.ratio - left.ratio)[0]
  if (!peak) return null
  const sourceTotals = new Map<string, number>()
  for (const item of ledger.value?.attributions || []) {
    if (item.resource !== peak.resource || shanghaiDate(item.ts) !== peak.date || Math.sign(Number(item.delta)) !== Math.sign(peak.delta)) continue
    const source = categoryOf(item.source)
    if (source === 'unknown') continue
    sourceTotals.set(source, (sourceTotals.get(source) || 0) + Math.abs(Number(item.delta || 0)))
  }
  const source = [...sourceTotals].sort((left, right) => right[1] - left[1])[0]?.[0]
  const date = peak.date.slice(5).replace('-', '/')
  return {
    key: `anomaly:${peak.resource}:${peak.date}`, tone: 'alert', score: 82,
    title: `${date} 的${peak.resource}变化最突出`,
    detail: `${signed(peak.delta)}，是其余有记录日平均幅度的 ${peak.ratio.toFixed(1)} 倍${source ? `，主要来自${categoryLabel(source)}` : ''}。`,
    resource: peak.resource, date: peak.date, target: 'chart',
  }
})

const swordObtainedEvents = computed(() => events.value.filter(event => (
  ['sword.obtained', 'forge.collected', 'pumpkin.sword_obtained'].includes(event.event_type)
  && event.payload?.name
)))
// 刀剑明细仍归入“全部记录”；心愿命中只额外点名，不重新铺完整刀名列表。
const swordDropTotal = computed(() => swordObtainedEvents.value.length)
const wishlistHits = computed(() => {
  const wanted = new Set(swordWishlist.value)
  const hits = new Map<string, number>()
  for (const event of swordObtainedEvents.value) {
    const name = String(event.payload?.name || '').trim()
    if (wanted.has(name)) hits.set(name, (hits.get(name) || 0) + 1)
  }
  return [...hits].map(([name, count]) => ({ name, count }))
})
const wishlistHitTotal = computed(() => wishlistHits.value.reduce((total, item) => total + item.count, 0))
function wishlistNames(limit = 3) {
  const names = wishlistHits.value.map(item => item.name)
  return names.length > limit ? `${names.slice(0, limit).join('、')}等 ${names.length} 把` : names.join('、')
}
const wishlistFooter = computed(() => wishlistHits.value
  .map(item => `${item.name}${item.count > 1 ? ` ×${item.count}` : ''}`).join('、'))

const reportInsights = computed<ReportInsight[]>(() => {
  if (loading.value) return [{ key: 'loading', tone: 'plain', score: 1, title: '狐之助正在看账', detail: '稍等一下，马上挑出最值得说的事情。' }]
  const items: ReportInsight[] = []
  if (wishlistHitTotal.value) items.push({
    key: `wishlist:${wishlistHits.value.map(item => `${item.name}:${item.count}`).join('|')}`,
    tone: 'gain', score: 120, target: 'records',
    title: `🎉 心愿刀到账：${wishlistNames()}`,
    detail: `这段时间命中 ${wishlistHitTotal.value} 振，完整入手记录已经替你收好。`,
  })
  const completed = Number(summary.value?.runs?.by_status?.completed || 0)
  const failed = Number(summary.value?.runs?.by_status?.failed || 0)
  if (failed) items.push({ key: 'failed-runs', tone: 'alert', score: 98,
    title: `${rangeLabel.value}有 ${failed} 次任务没顺利收工`, detail: '已经停止继续操作；点开会带你到最近一次翻车记录。', target: 'records',
    date: failedRun.value ? shanghaiDate(Number(failedRun.value.started_at)) : undefined,
    runId: failedRun.value?.run_id })
  if (completed || sortieCount.value) {
    const details = []
    if (sortieCount.value) details.push(`出阵 ${sortieCount.value.toLocaleString()} 圈${topSortie.value ? `，主要在${topSortie.value}` : ''}`)
    if (practiceTotal.value) details.push(`演练 ${practiceWins.value} 胜 ${practiceLosses.value} 负`)
    items.push({ key: 'activity', tone: 'plain', score: 90,
      title: completed > 0
        ? `${rangeLabel.value}完成 ${completed} 次任务`
        : `${rangeLabel.value}留下 ${sortieCount.value.toLocaleString()} 次出阵记录`,
      detail: details.join('；') || '任务记录已经整理完成。' })
  }

  const goal = [...(planning.value?.goals || [])]
    .filter(item => (item.kind || 'resource') !== 'event' && ['behind', 'on_track', 'active', 'done'].includes(item.status))
    .sort((left, right) => goalStatusRank[left.status] - goalStatusRank[right.status])[0]
  if (goal) {
    const urgent = goal.status === 'behind'
    items.push({ key: `goal:${goal.id}`, tone: urgent ? 'alert' : 'goal', score: urgent ? 100 : 64,
      title: urgent ? `${goal.resource}目标需要加把劲` : `${goal.resource}目标${goal.status === 'done' ? '已经达成' : '进展正常'}`,
      detail: goal.message || goalSummary(goal), target: 'planning' })
  }

  if (anomalyInsight.value) items.push(anomalyInsight.value)
  const gain = sourceLeaders.value.gain
  if (gain) items.push({ key: `gain:${gain.source}:${gain.resource}`, tone: 'gain', score: 72,
    title: `${gain.resource}是这段时间的进账冠军`,
    detail: `从${categoryLabel(gain.source)}确认获得 ${signed(gain.delta)}。`, resource: gain.resource, target: 'chart' })
  const cost = sourceLeaders.value.cost
  if (cost) items.push({ key: `cost:${cost.source}:${cost.resource}`, tone: 'cost', score: 68,
    title: `最大支出是${cost.resource}`, detail: `${categoryLabel(cost.source)}消耗 ${signed(cost.delta)}。`, resource: cost.resource, target: 'chart' })

  if (!items.length) items.push({ key: 'empty', tone: 'plain', score: 1,
    title: '这段时间还没有足够的账', detail: '再跑几次任务或补一次家底，狐之助就能开始替你挑重点。' })
  return items.sort((left, right) => right.score - left.score).slice(0, 3)
})

const insightHeading = computed(() => days.value === 7 ? '本周本丸小结' : `${rangeLabel.value}本丸小结`)

function insightToneLabel(tone: ReportInsight['tone']) {
  return { plain: '记', gain: '得', cost: '用', alert: '留意', goal: '目标' }[tone]
}

async function followInsight(insight: ReportInsight) {
  if (insight.target === 'planning') return openPlanning()
  if (insight.target === 'records') {
    if (!insight.date) return switchView('records')
    recordHighlightRunId.value = insight.runId || ''
    recordDate.value = insight.date
    view.value = 'records'
    await loadRecordDay(insight.date)
    await nextTick()
    if (insight.runId) document.getElementById(`run-${insight.runId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  if (insight.target === 'chart' && insight.resource) {
    mode.value = 'single'
    chooseResource(insight.resource)
    if (insight.date) selectedDate.value = insight.date
    await nextTick()
    document.querySelector('.resource-trend')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
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
  return [...groups.entries()].map(([key, entries]) => {
    const ordered = [...entries].sort((a, b) => resourceNames.indexOf(String(a.resource)) - resourceNames.indexOf(String(b.resource)))
    return { key, entries: ordered, head: entries[0] }
  })
})

type HandLedgerEntry =
  | { kind: 'resource'; key: string; at: number; entries: HumanReport[]; head: HumanReport }
  | { kind: 'inventory'; key: string; at: number; item: ManualInventory }
  | { kind: 'session'; key: string; at: number; item: ManualSession }

const handLedgerEntries = computed<HandLedgerEntry[]>(() => [
  ...recentManualGroups.value.map(({ key: groupKey, ...group }) => ({
    kind: 'resource' as const, key: `resource:${groupKey}`,
    at: Number(group.head.occurred_at), ...group,
  })),
  ...manualInventories.value.map(item => ({
    kind: 'inventory' as const, key: `inventory:${item.id}`, at: Number(item.ts), item,
  })),
  ...manualSessions.value.map(item => ({
    kind: 'session' as const, key: `session:${item.id}`, at: Number(item.started_at), item,
  })),
].sort((a, b) => b.at - a.at))
const displayedHandLedgerEntries = computed(() => handLedgerExpanded.value
  ? handLedgerEntries.value : handLedgerEntries.value.slice(0, 3))

function inventoryAmounts(item: ManualInventory) {
  return resourceNames.filter(name => item.resources?.[name] != null)
    .map(name => `${name} ${Number(item.resources[name]).toLocaleString()}`).join(' · ')
}

function handEntryTitle(entry: HandLedgerEntry) {
  if (entry.kind === 'resource') return manualReportSource(entry.head)
  if (entry.kind === 'inventory') return '家底盘点'
  return `${entry.item.activity} · ${entry.item.loops} 圈`
}

function handEntryDetail(entry: HandLedgerEntry) {
  if (entry.kind === 'resource') {
    const note = entry.head.note ? ` · ${entry.head.note}` : ''
    return `${manualGroupAmounts(entry.entries)}${note}`
  }
  if (entry.kind === 'inventory') return inventoryAmounts(entry.item)
  const minutes = Math.max(1, Math.round(Number(entry.item.duration_seconds) / 60))
  return `用时 ${minutes} 分钟${entry.item.note ? ` · ${entry.item.note}` : ''}`
}

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
const dayChartResources = computed(() => resourceNames.filter(resource => resource !== '甲州金'))
const displayedChartDates = computed(() => days.value === 1 ? dayChartResources.value : chartDates.value)
const displayedChartLabels = computed(() => days.value === 1 ? dayChartResources.value : [])
const displayedChartSeries = computed<ChartSeries[]>(() => {
  if (days.value !== 1) return chartSeries.value
  return sourceCategories.map(category => ({
    key: category.key,
    name: category.key === 'human' ? '你记的' : category.label,
    color: category.color,
    values: dayChartResources.value.map(resource => {
      const row = dayResourceOverview.value.find(item => item.resource === resource)
      return row?.parts.find(part => part.key === category.key)?.value || null
    }),
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
  recordHighlightRunId.value = ''
  recordDate.value = date
  view.value = 'records'
  void loadRecordDay(date)
}

function switchView(nextView: 'chart' | 'records') {
  recordHighlightRunId.value = ''
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
    manualReports: recentManualReports.value.filter(report => report.resource === resource
      && start <= Number(report.occurred_at) && Number(report.occurred_at) < end),
    manualSessions: manualSessions.value.filter(item => Number(item.started_at) < end && Number(item.ended_at) >= start),
    gaps: unreportedGaps.value.filter(gap => gap.started_at < end && gap.ended_at >= start
      && Number(gap.resource_delta?.[resource] || 0) !== 0),
  }
})

// ---- 手动补账 ----

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
  manualSessionFormOpen.value = false
  editingManualReport.value = null
  reportMode.value = 'proactive'
  reportGap.value = null
  reportForm.value = { activities: [], note: '', occurred_at: localDateTime(timestamp), resource, claimed_delta: claimedDelta, claim_limit: claimedDelta }
  manualResourceAmounts.value = Object.fromEntries(resourceNames.map(name => [name, null]))
  scrollToReportForm()
}
function editManualReport(entry: Extract<HandLedgerEntry, { kind: 'resource' }>) {
  manualActionsOpen.value = false
  inventoryFormOpen.value = false
  manualSessionFormOpen.value = false
  reportMode.value = 'proactive-edit'
  reportGap.value = null
  editingManualReport.value = entry.head.group_id
    ? { groupId: entry.head.group_id } : { reportId: entry.head.id }
  reportForm.value = {
    activities: [...(entry.head.activities || [])], note: entry.head.note || '',
    occurred_at: localDateTime(entry.at * 1000), resource: '',
    claimed_delta: null, claim_limit: null,
  }
  manualResourceAmounts.value = Object.fromEntries(resourceNames.map(name => {
    const report = entry.entries.find(item => item.resource === name)
    return [name, report?.claimed_delta ?? null]
  }))
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
      const payload = { occurred_at, activities, note: reportForm.value.note, entries: manualResourceEntries.value }
      if (editingManualReport.value?.groupId) {
        await api.updateHumanReportGroup(editingManualReport.value.groupId, payload)
      } else if (editingManualReport.value?.reportId) {
        const entries = Object.entries(manualResourceEntries.value)
        if (entries.length !== 1) throw new Error('这条旧手账一次只能保留一种资源；要记多种请另记一笔。')
        await api.updateHumanReport(editingManualReport.value.reportId, {
          occurred_at, activities, note: reportForm.value.note,
          resource: entries[0][0], claimed_delta: entries[0][1],
        })
      } else {
        await api.addHumanReportBatch(payload)
      }
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
        ? `${editingManualReport.value ? '已修改' : '已记下'} ${Object.keys(manualResourceEntries.value).length} 种资源的收支。`
        : `已记下 ${reportForm.value.resource} ${signed(Number(reportForm.value.claimed_delta))}。`
    }
    reportMode.value = ''; reportGap.value = null; editingManualReport.value = null
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '手动补账保存失败' }
  finally { reportSaving.value = false }
}

async function deleteManualReport(entry: Extract<HandLedgerEntry, { kind: 'resource' }>) {
  const report = entry.head
  const group = entry.entries
  const label = group.length > 1 ? `这组 ${group.length} 种资源` : `这笔 ${report.resource} ${signed(Number(report.claimed_delta))}`
  if (!window.confirm(`撤销${label}的手账吗？`)) return
  manualEntryBusy.value = entry.key
  try {
    if (report.group_id) await api.deleteHumanReportGroup(report.group_id)
    else await api.deleteHumanReport(report.id)
    inventoryNotice.value = group.length > 1 ? '这组手账已撤销。' : '这笔手账已撤销。'
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '撤销手账失败' }
  finally { manualEntryBusy.value = '' }
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
  manualSessionFormOpen.value = false
  editingInventoryId.value = null
  inventoryNotice.value = ''
  inventoryForm.value = Object.fromEntries(resourceNames.map(name => [name, null]))
  inventoryObservedAt.value = localDateTime()
  inventoryFormOpen.value = true
}

function editManualInventory(item: ManualInventory) {
  manualActionsOpen.value = false
  reportMode.value = ''
  reportGap.value = null
  manualSessionFormOpen.value = false
  editingInventoryId.value = item.id
  inventoryForm.value = Object.fromEntries(resourceNames.map(name => [name, item.resources?.[name] ?? null]))
  inventoryObservedAt.value = localDateTime(item.ts * 1000)
  inventoryFormOpen.value = true
}

function openManualSessionForm() {
  manualActionsOpen.value = false
  inventoryFormOpen.value = false
  reportMode.value = ''
  reportGap.value = null
  editingManualSessionId.value = null
  const ended = Date.now()
  manualSessionForm.value = {
    script: 'osaka', loops: 1,
    started_at: localDateTime(ended - 60 * 60 * 1000),
    ended_at: localDateTime(ended), note: '',
  }
  manualSessionFormOpen.value = true
}

function editManualSession(item: ManualSession) {
  manualActionsOpen.value = false
  inventoryFormOpen.value = false
  reportMode.value = ''
  reportGap.value = null
  editingManualSessionId.value = item.id
  manualSessionForm.value = {
    script: item.script, loops: item.loops,
    started_at: localDateTime(item.started_at * 1000),
    ended_at: localDateTime(item.ended_at * 1000), note: item.note || '',
  }
  manualSessionFormOpen.value = true
}

async function saveManualSession() {
  manualSessionSaving.value = true
  try {
    const payload = {
      script: manualSessionForm.value.script,
      loops: Number(manualSessionForm.value.loops),
      started_at: new Date(manualSessionForm.value.started_at).getTime() / 1000,
      ended_at: new Date(manualSessionForm.value.ended_at).getTime() / 1000,
      note: manualSessionForm.value.note,
    }
    if (editingManualSessionId.value) await api.updateManualSession(editingManualSessionId.value, payload)
    else await api.addManualSession(payload)
    manualSessionFormOpen.value = false
    inventoryNotice.value = editingManualSessionId.value
      ? '这段手动活动已修改。' : '已记下这段活动；不会算进まあ丸战绩。'
    editingManualSessionId.value = null
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
    const observedAt = new Date(inventoryObservedAt.value).getTime() / 1000
    if (editingInventoryId.value) await api.updateManualInventory(editingInventoryId.value, resources, observedAt)
    else await api.addManualInventory(resources, observedAt)
    inventoryFormOpen.value = false
    inventoryNotice.value = `${editingInventoryId.value ? '已修改' : '已记录'} ${Object.keys(resources).length} 项家底。`
    editingInventoryId.value = null
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '家底记录失败' }
  finally { inventorySaving.value = false }
}

async function deleteManualInventoryEntry(entry: Extract<HandLedgerEntry, { kind: 'inventory' }>) {
  if (!window.confirm('撤销这次手动家底盘点吗？撤销后账房会按前后记录重新计算。')) return
  manualEntryBusy.value = entry.key
  try {
    await api.deleteManualInventory(entry.item.id)
    inventoryNotice.value = '这次手动家底盘点已撤销。'
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '撤销家底记录失败' }
  finally { manualEntryBusy.value = '' }
}

async function deleteManualSessionEntry(entry: Extract<HandLedgerEntry, { kind: 'session' }>) {
  if (!window.confirm(`撤销这段${entry.item.activity}手动活动吗？`)) return
  manualEntryBusy.value = entry.key
  try {
    await api.deleteManualSession(entry.item.id)
    inventoryNotice.value = '这段手动活动已撤销。'
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '撤销手动活动失败' }
  finally { manualEntryBusy.value = '' }
}

async function downloadLedger(format: 'xlsx' | 'csv') {
  ledgerTransferBusy.value = `export-${format}`
  ledgerTransferNotice.value = ''
  try {
    const result = await api.ledgerExport(format)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = result.filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    ledgerTransferNotice.value = format === 'xlsx'
      ? '账本已导出：完整流水、当前家底和每日汇总都在里面。'
      : '完整流水 CSV 已导出。'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '账本导出失败' }
  finally { ledgerTransferBusy.value = '' }
}

function chooseLedgerImport() {
  ledgerImportInput.value?.click()
}

async function previewLedgerFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  ledgerTransferBusy.value = 'preview'
  ledgerTransferNotice.value = ''
  ledgerImportPreview.value = null
  acceptLedgerConflicts.value = false
  try {
    ledgerImportPreview.value = await api.previewLedgerImport(file)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '旧账预览失败' }
  finally { ledgerTransferBusy.value = '' }
}

async function importLedgerPreview() {
  const preview = ledgerImportPreview.value
  if (!preview) return
  ledgerTransferBusy.value = 'apply'
  ledgerTransferNotice.value = ''
  try {
    const result = await api.applyLedgerImport(preview.preview_id, acceptLedgerConflicts.value)
    ledgerTransferNotice.value = result.imported
      ? `已导入 ${result.imported} 条手动记录，写入前备份已保存。`
      : '没有需要写入的新记录，账本未改动。'
    ledgerImportPreview.value = null
    acceptLedgerConflicts.value = false
    if (ledgerOnboarding.value?.visible && ledgerOnboarding.value.step === 2) {
      try {
        ledgerOnboarding.value = await api.updateLedgerOnboarding('advance', 3)
        honmaruTab.value = 'planning'
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : '旧账已导入，但首次设置进度保存失败'
      }
    }
    await load(days.value)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '旧账导入失败' }
  finally { ledgerTransferBusy.value = '' }
}

// ---- 数据加载 ----

async function load(nextDays = days.value) {
  days.value = nextDays; loading.value = true
  try {
    const rangeStartedAt = Date.now() / 1000 - nextDays * 86400
    const [nextSummary, nextLedger, nextEvents, nextRuns, nextFailedRuns, nextHuman, nextManualSessions, nextManualInventory, nextPlanning, nextOnboarding, nextLists] = await Promise.all([api.dataSummary(nextDays), api.resourceLedger(nextDays), api.dataEvents(1000), api.dataRuns(30), api.dataRuns(1, undefined, rangeStartedAt, undefined, 'failed'), api.humanReports(), api.manualSessions(1000, Date.now() / 1000 - 365 * 86400), api.manualInventory(500), api.planning().catch(() => null), api.ledgerOnboarding().catch(() => null), api.configLists().catch((): Record<string, string[]> => ({}))])
    summary.value = nextSummary
    ledger.value = nextLedger
    planning.value = nextPlanning
    failedRun.value = nextFailedRuns.items[0] || null
    events.value = nextEvents.items.filter(item => item.ts >= Date.now() / 1000 - nextDays * 86400)
    runs.value = nextRuns.items.filter(item => item.started_at >= Date.now() / 1000 - nextDays * 86400)
    hasMoreEvents.value = nextEvents.has_more
    hasMoreRuns.value = nextRuns.has_more
    eventCursor.value = nextEvents.next_cursor
    runCursor.value = nextRuns.next_cursor
    humanReports.value = nextHuman.items
    inventoryGaps.value = nextHuman.inventory_gaps
    manualSessions.value = nextManualSessions.items
    manualInventories.value = nextManualInventory.items
    ledgerOnboarding.value = nextOnboarding
    swordWishlist.value = nextLists.sword_wishlist || []
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
onMounted(async () => {
  await load()
  if (view.value === 'records' && recordDate.value) await loadRecordDay(recordDate.value)
})
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
        <section class="report-glance" :class="{ loading }" aria-labelledby="report-insight-title">
          <header>
            <div><small>狐之助从账里圈出的三笔</small><h2 id="report-insight-title">{{ insightHeading }}</h2></div>
            <span>{{ rangeLabel }} · 回看</span>
          </header>
          <ol class="report-insight-list">
            <li v-for="(insight, index) in reportInsights" :key="insight.key" :class="[insight.tone, { lead: index === 0 }]">
              <i>{{ insightToneLabel(insight.tone) }}</i><div><strong>{{ insight.title }}</strong><p>{{ insight.detail }}</p></div>
              <button v-if="insight.target" type="button" @click="followInsight(insight)">{{ insight.target === 'planning' ? '看规划' : insight.target === 'records' ? '看记录' : '看证据' }} →</button>
            </li>
          </ol>
          <footer v-if="swordDropTotal || manualLoops || swordWishlist.length">
            <span v-if="swordDropTotal" class="obtain">入手 {{ swordDropTotal }} 振</span>
            <span v-if="wishlistHitTotal" class="wishlist">🎯 心愿命中 {{ wishlistFooter }}</span>
            <button v-if="swordDropTotal || swordWishlist.length" type="button" class="wishlist-manage" @click="emit('open-wishlist')">{{ swordWishlist.length ? `心愿名单 ${swordWishlist.length} 把` : '＋ 设置心愿刀' }} →</button>
            <span v-if="manualLoops" class="manual">你手动记了 {{ manualLoops }} 圈</span>
          </footer>
        </section>

        <button v-if="unreportedGaps.length" type="button" class="report-attention" @click="openGapReport(unreportedGaps[0])">
          <span><b>🦊 有 {{ unreportedGaps.length }} 段家底变化等你认领</b><small>它们没有算进任何一轮挂机收益，说明一下就会染回彩色。</small></span><em>去说明 →</em>
        </button>

        <section v-if="ledgerOnboarding?.visible" class="ledger-onboarding" aria-labelledby="ledger-onboarding-title">
          <header>
            <div><small>第一次使用 · {{ ledgerOnboarding.step }}/3</small><h3 id="ledger-onboarding-title">把账房安顿好</h3></div>
            <button type="button" :disabled="!!ledgerOnboardingBusy" @click="dismissLedgerOnboarding">不需要引导</button>
          </header>
          <ol aria-label="首次设置进度">
            <li :class="{ active: ledgerOnboarding.step === 1, done: ledgerOnboarding.step > 1 }"><span>1</span>抄家底</li>
            <li :class="{ active: ledgerOnboarding.step === 2, done: ledgerOnboarding.step > 2 }"><span>2</span>带旧账</li>
            <li :class="{ active: ledgerOnboarding.step === 3 }"><span>3</span>立目标</li>
          </ol>
          <div v-if="ledgerOnboarding.step === 1" class="ledger-onboarding-copy">
            <div><b>先抄一次现在的家底</b><p>打开游戏看一眼资源数字；不确定的项目可以留空，以后随时能改。</p></div>
            <button type="button" class="primary" :disabled="ledgerOnboardingBusy === 'inventory'" @click="beginLedgerOnboarding">{{ ledgerOnboardingBusy === 'inventory' ? '正在准备……' : '抄下当前家底' }}</button>
          </div>
          <div v-else-if="ledgerOnboarding.step === 2" class="ledger-onboarding-copy">
            <div><b>有旧表就顺手带回来</b><p>导入前只做预览，不会碰刚抄好的家底；没有旧账直接下一步。</p></div>
            <div class="ledger-onboarding-actions"><button type="button" class="primary" @click="openOnboardingImport">选旧账预览</button><button type="button" class="secondary" :disabled="ledgerOnboardingBusy === 'step-3'" @click="advanceLedgerOnboarding(3)">没有旧账，下一步</button></div>
          </div>
          <div v-else class="ledger-onboarding-copy">
            <div><b>最后立一个真正想盯的目标</b><p>让账房替你算还差多少；暂时没想法也可以直接完成。</p></div>
            <div class="ledger-onboarding-actions"><button type="button" class="primary" @click="openOnboardingGoal">去规划立目标</button><button type="button" class="secondary" :disabled="ledgerOnboardingBusy === 'complete'" @click="finishLedgerOnboarding">暂时不立，完成设置</button></div>
          </div>
        </section>

        <section class="resource-ledger" :class="{ loading }">
          <header><div><h3>家底概览</h3><p>{{ ledgerDateRange }}的变化</p></div><div class="ledger-actions"><span class="ledger-confidence" :class="confidence.level"><b>{{ confidence.label }}</b></span><button type="button" class="secondary" @click="ledgerTransferOpen = !ledgerTransferOpen">账本进出</button><button v-if="!inventoryFormOpen && !reportMode" type="button" class="secondary" @click="manualActionsOpen = !manualActionsOpen">＋ 手动记账</button></div></header>
          <section v-if="ledgerTransferOpen" class="ledger-transfer" aria-labelledby="ledger-transfer-title">
            <header><div><h4 id="ledger-transfer-title">带走或带回账本</h4><p>自动流水只导出；导入只增加你的手动记录。</p></div><button type="button" class="inventory-close" aria-label="关闭账本进出" @click="ledgerTransferOpen = false">×</button></header>
            <div class="ledger-export-actions">
              <button type="button" class="primary" :disabled="!!ledgerTransferBusy" @click="downloadLedger('xlsx')">{{ ledgerTransferBusy === 'export-xlsx' ? '正在整理……' : '导出 Excel 账本' }}</button>
              <button type="button" class="secondary" :disabled="!!ledgerTransferBusy" @click="downloadLedger('csv')">{{ ledgerTransferBusy === 'export-csv' ? '正在整理……' : '导出流水 CSV' }}</button>
              <button type="button" class="secondary" :disabled="!!ledgerTransferBusy" @click="chooseLedgerImport">{{ ledgerTransferBusy === 'preview' ? '正在看旧账……' : '选旧账预览' }}</button>
            </div>
            <p class="ledger-transfer-tip">Excel 会带上完整流水、当前家底、每日汇总和一张“可再次导入”表。旧账真正写入前会自动备份。</p>
            <p v-if="ledgerTransferNotice" class="inventory-notice" role="status">✓ {{ ledgerTransferNotice }}</p>
            <section v-if="ledgerImportPreview" class="ledger-import-preview">
              <header><div><h5>{{ ledgerImportPreview.filename }}</h5><p>这里还没有改动账本。</p></div><button type="button" @click="ledgerImportPreview = null; acceptLedgerConflicts = false">取消预览</button></header>
              <div class="ledger-preview-counts">
                <span class="new"><b>{{ ledgerImportPreview.counts.new }}</b>条可导入</span>
                <span><b>{{ ledgerImportPreview.counts.duplicate }}</b>条重复会跳过</span>
                <span :class="{ conflict: ledgerImportPreview.counts.conflict }"><b>{{ ledgerImportPreview.counts.conflict }}</b>条冲突</span>
                <span v-if="ledgerImportPreview.counts.invalid || ledgerImportPreview.counts.ignored"><b>{{ ledgerImportPreview.counts.invalid + ledgerImportPreview.counts.ignored }}</b>条不写入</span>
              </div>
              <ul v-if="ledgerImportPreview.items.length" class="ledger-preview-list">
                <li v-for="item in ledgerImportPreview.items.slice(0, 8)" :key="`${item.row}:${item.summary}`" :class="item.status"><span>第 {{ item.row }} 行 · {{ item.summary }}</span><em>{{ item.detail }}</em></li>
              </ul>
              <details v-if="ledgerImportPreview.issues.length"><summary>查看 {{ ledgerImportPreview.issues.length }} 条忽略/无法识别的内容</summary><ul><li v-for="issue in ledgerImportPreview.issues.slice(0, 20)" :key="`${issue.row}:${issue.reason}`">第 {{ issue.row }} 行：{{ issue.reason }}</li></ul></details>
              <label v-if="ledgerImportPreview.counts.conflict" class="ledger-conflict-confirm"><input v-model="acceptLedgerConflicts" type="checkbox">我已检查冲突，仍要把这些行作为手动记录导入</label>
              <button type="button" class="primary" :disabled="ledgerTransferBusy === 'apply' || (!ledgerImportPreview.counts.new && !acceptLedgerConflicts) || (!!ledgerImportPreview.counts.conflict && !acceptLedgerConflicts)" @click="importLedgerPreview">{{ ledgerTransferBusy === 'apply' ? '正在备份并导入……' : '备份后导入' }}</button>
            </section>
          </section>
          <input ref="ledgerImportInput" class="ledger-file-input" type="file" accept=".xlsx,.csv" @change="previewLedgerFile">
          <div v-if="manualActionsOpen" class="manual-action-picker">
            <button type="button" @click="openProactiveReport()"><b>记一笔收支</b><small>记下自己获得或花掉的资源</small></button>
            <button type="button" @click="openManualSessionForm"><b>补记一段活动</b><small>记玩法、圈数和时间；与まあ丸分开计算</small></button>
            <button type="button" @click="openInventoryForm"><b>更新当前家底</b><small>把游戏里现在的资源数字抄下来</small></button>
          </div>
          <p v-if="inventoryNotice" class="inventory-notice" role="status">✓ {{ inventoryNotice }}</p>
          <section v-if="handLedgerEntries.length" class="recent-manual-ledger" aria-labelledby="recent-manual-ledger-title">
            <header><div><h4 id="recent-manual-ledger-title">我的手账</h4><p>你自己记的收支、家底和活动都在这里</p></div><button v-if="handLedgerEntries.length > 3" type="button" class="hand-ledger-toggle" @click="handLedgerExpanded = !handLedgerExpanded">{{ handLedgerExpanded ? '收起' : `查看全部 ${handLedgerEntries.length} 条` }}</button></header>
            <ul>
              <li v-for="entry in displayedHandLedgerEntries" :key="entry.key">
                <time>{{ manualReportTime(entry.at) }}</time>
                <span><b><em class="hand-entry-kind">{{ entry.kind === 'resource' ? '收支' : entry.kind === 'inventory' ? '家底' : '活动' }}</em>{{ handEntryTitle(entry) }}</b><small>{{ handEntryDetail(entry) }}</small></span>
                <div class="hand-entry-actions">
                  <button v-if="entry.kind === 'resource'" type="button" :disabled="manualEntryBusy === entry.key" @click="editManualReport(entry)">修改</button>
                  <button v-else-if="entry.kind === 'inventory'" type="button" :disabled="manualEntryBusy === entry.key" @click="editManualInventory(entry.item)">修改</button>
                  <button v-else type="button" :disabled="manualEntryBusy === entry.key" @click="editManualSession(entry.item)">修改</button>
                  <button v-if="entry.kind === 'resource'" type="button" class="danger" :disabled="manualEntryBusy === entry.key" @click="deleteManualReport(entry)">{{ manualEntryBusy === entry.key ? '处理中…' : '撤销' }}</button>
                  <button v-else-if="entry.kind === 'inventory'" type="button" class="danger" :disabled="manualEntryBusy === entry.key" @click="deleteManualInventoryEntry(entry)">{{ manualEntryBusy === entry.key ? '处理中…' : '撤销' }}</button>
                  <button v-else type="button" class="danger" :disabled="manualEntryBusy === entry.key" @click="deleteManualSessionEntry(entry)">{{ manualEntryBusy === entry.key ? '处理中…' : '撤销' }}</button>
                </div>
              </li>
            </ul>
          </section>
          <form v-if="inventoryFormOpen" class="manual-inventory-form" @submit.prevent="saveManualInventory">
            <header><div><h4>{{ editingInventoryId ? '修改家底记录' : '更新当前家底' }}</h4><p>不确定的项目可以留空，修改后会重新计算前后账目。</p></div><button type="button" class="inventory-close" aria-label="关闭家底记录" @click="inventoryFormOpen = false; editingInventoryId = null">×</button></header>
            <label class="manual-inventory-time">记录时间<input v-model="inventoryObservedAt" type="datetime-local" required></label>
            <div class="manual-inventory-grid"><label v-for="name in resourceNames" :key="name">{{ name }}<input v-model.number="inventoryForm[name]" type="number" min="0" step="1" inputmode="numeric" placeholder="留空"></label></div>
            <div class="report-form-actions"><button type="submit" class="primary" :disabled="inventorySaving">{{ inventorySaving ? '保存中……' : editingInventoryId ? '保存修改' : '记下当前家底' }}</button><button type="button" class="secondary" @click="inventoryFormOpen = false; editingInventoryId = null">取消</button></div>
          </form>
          <div class="resource-ledger-grid">
            <article v-for="row in resourceRows" :key="row.name" :class="{ gain: row.delta != null && row.delta > 0, loss: row.delta != null && row.delta < 0 }">
              <small>{{ row.name }}</small><strong>{{ signed(row.delta) }}</strong><span v-if="row.current != null">当前 {{ row.current.toLocaleString() }}</span><span v-else>尚未观察到</span>
              <span v-if="row.rate != null" class="resource-rate" :title="`按最近 ${planning?.rate_window_days || 14} 天里 ${row.rateDays} 个有完整记录的平常日计算`">{{ rateWindowLabel }} {{ signed(Math.round(row.rate)) }}/日</span>
              <button v-if="row.goal" type="button" class="resource-goal-link" :title="`去规划查看${row.name}目标`" @click="openPlanning"><span>{{ goalSummary(row.goal) }}</span><em>{{ goalMeta(row.goal) }} →</em></button>
            </article>
          </div>
          <details class="ledger-evidence"><summary>查看对账依据</summary><p>{{ confidence.detail }}</p></details>
        </section>

        <form v-if="manualSessionFormOpen" class="manual-session-form" @submit.prevent="saveManualSession">
          <header><div><h4>{{ editingManualSessionId ? '修改手动活动' : '补记一段活动' }}</h4><p>这里只记你自己打的，不会并进まあ丸完成的圈数。</p></div><button type="button" class="inventory-close" aria-label="关闭手动活动" @click="manualSessionFormOpen = false; editingManualSessionId = null">×</button></header>
          <div class="manual-session-fields">
            <label>玩法<select v-model="manualSessionForm.script"><option value="osaka">大阪城</option><option value="raid">联队战</option><option value="edocastle">江户城</option><option value="sortie">合战场</option><option value="yosari">异去</option><option value="pumpkin">季节活动</option></select></label>
            <label>圈数<input v-model.number="manualSessionForm.loops" type="number" min="1" max="100000" step="1" required></label>
            <label>开始时间<input v-model="manualSessionForm.started_at" type="datetime-local" required></label>
            <label>结束时间<input v-model="manualSessionForm.ended_at" type="datetime-local" required></label>
            <label class="manual-session-note">备注<input v-model="manualSessionForm.note" maxlength="200" placeholder="可不填"></label>
          </div>
          <div class="report-form-actions"><button type="submit" class="primary" :disabled="manualSessionSaving">{{ manualSessionSaving ? '保存中……' : editingManualSessionId ? '保存修改' : '记下这段活动' }}</button><button type="button" class="secondary" @click="manualSessionFormOpen = false; editingManualSessionId = null">取消</button></div>
        </form>

        <form v-if="reportMode" ref="reportFormEl" class="report-form" @submit.prevent="saveHumanReport(false)">
          <header class="report-form-heading"><div><h4>{{ reportGap ? '补上这段账' : editingManualReport ? '修改手动收支' : reportForm.claim_limit != null ? '补上这笔账' : '记一笔收支' }}</h4><p>{{ reportGap ? '只记你能确定的；具体数额不用硬猜。' : reportForm.claim_limit != null ? '账房已经列出当天线索；想不起来也可以如实记下。' : '正数是获得，负数是消耗。' }}</p></div><button type="button" class="inventory-close" aria-label="关闭补记" @click="reportMode = ''; reportGap = null; editingManualReport = null">×</button></header>
          <p v-if="reportForm.resource && reportForm.claim_limit != null" class="report-claim-summary"><b>待补：</b>{{ reportForm.resource }} {{ signed(reportForm.claimed_delta) }}</p>
          <template v-if="!reportGap && reportForm.claim_limit == null">
            <fieldset class="multi-resource-entry"><legend>这次有哪些资源变化？</legend><label v-for="name in resourceNames" :key="name">{{ name }}<input v-model.number="manualResourceAmounts[name]" type="number" step="1" placeholder="留空"></label><small>获得填正数，消耗填负数；没有变化的留空。</small></fieldset>
          </template>
          <label v-if="reportForm.resource && reportForm.claim_limit != null">其中有多少是这次操作<input v-model.number="reportForm.claimed_delta" type="number" step="1" :min="Number(reportForm.claim_limit) > 0 ? 1 : reportForm.claim_limit ?? undefined" :max="Number(reportForm.claim_limit) > 0 ? reportForm.claim_limit ?? undefined : -1"><small>最多补到当前没对上的 {{ signed(reportForm.claim_limit) }}</small></label>
          <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
          <fieldset><legend>{{ reportGap || reportForm.claim_limit != null ? '你记得它来自哪里？' : '顺手标一下来源（可不选）' }}</legend><button v-for="value in [...humanActivities, '记不清了', ...(reportGap ? ['没有其他操作'] : [])]" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
          <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" :placeholder="reportForm.resource ? '可选，资源和数额已经记好了' : '可选，不用写具体资源数字'"></label>
          <div class="report-form-actions"><button type="submit" class="primary" :disabled="reportSubmitDisabled">{{ reportSaving ? '保存中……' : editingManualReport ? '保存修改' : '记下来' }}</button><button type="button" class="secondary" @click="reportMode = ''; reportGap = null; editingManualReport = null">取消</button></div>
        </form>

        <section class="resource-trend">
          <header>
            <div><h3>{{ days === 1 ? '24 小时收支' : '变化趋势' }}</h3></div>
            <nav v-if="days !== 1 && mode === 'single'" aria-label="选择资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: selectedResource === name }" @click="chooseResource(name)">{{ name }}</button></nav>
            <nav v-else-if="days !== 1" aria-label="选择要对比的资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: compareResources.includes(name) }" @click="toggleCompareResource(name)">{{ name }}</button></nav>
            <label v-if="days !== 1" class="compare-toggle"><input v-model="mode" type="checkbox" true-value="compare" false-value="single">对比几种资源</label>
          </header>
          <p v-if="anomalyInsight && (mode === 'compare' ? compareResources.includes(anomalyInsight.resource || '') : selectedResource === anomalyInsight.resource)" class="trend-callout">🦊 {{ anomalyInsight.detail }}</p>
          <ResourceChart :dates="displayedChartDates" :labels="displayedChartLabels" :series="displayedChartSeries" :stacked="days === 1 || mode === 'single'" :selected-date="selectedDate" :loading="loading" @select="days !== 1 && onChartSelect($event)" />
          <template v-if="days !== 1">
            <DayDetail v-if="dayDetail" v-bind="dayDetail" :highlight-category="highlightCategory" @close="selectedDate = ''; highlightCategory = ''" @report="openGapReport" @report-day="openDayClaim(dayDetail.date, dayDetail.resource, dayDetail.unexplained)" @open-records="selectRecordDate" />
          </template>
        </section>

        <section v-if="unreportedGaps.length" class="inventory-gap-panel" aria-label="库存差值说明">
          <div v-for="gap in unreportedGaps" :key="gap.gap_key" class="inventory-gap-alert"><div><strong>🦊 上次任务和这次开工之间，家底对不上啦</strong><p>{{ gapDelta(gap) }}</p><small>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}。这段差值单独留档，不会算进任何一轮挂机收益。</small></div><button type="button" class="secondary" @click="openGapReport(gap)">这期间做过什么？</button><button type="button" @click="skipGap(gap)">不想说，记差值就好</button></div>
        </section>
      </template>

      <ReportRecords v-if="view === 'records'" :events="events" :runs="runs" :manual-sessions="manualSessions" :selected-date="recordDate" :highlight-run-id="recordHighlightRunId" :has-more-events="recordHasMoreEvents" :has-more-runs="recordHasMoreRuns" :loading="recordLoading" :loading-older="loadingOlder" @select-date="selectRecordDate" @load-more="loadOlder" @refresh="refreshRecords" />
      </template>

      <template v-else>
        <section v-if="ledgerOnboarding?.visible && ledgerOnboarding.step === 3" class="ledger-onboarding ledger-onboarding-goal" aria-labelledby="ledger-onboarding-goal-title">
          <header><div><small>第一次使用 · 3/3</small><h3 id="ledger-onboarding-goal-title">最后，立一个真正想盯的目标</h3></div></header>
          <ol aria-label="首次设置进度"><li class="done"><span>1</span>抄家底</li><li class="done"><span>2</span>带旧账</li><li class="active"><span>3</span>立目标</li></ol>
          <div class="ledger-onboarding-copy"><div><b>让账房替你盯结果</b><p>可以选“攒到多少”或“到哪一天”；暂时没想法也可以直接完成。</p></div><div class="ledger-onboarding-actions"><button type="button" class="primary" @click="openOnboardingGoal">立一个目标</button><button type="button" class="secondary" :disabled="ledgerOnboardingBusy === 'complete'" @click="finishLedgerOnboarding">暂时不立，完成设置</button></div></div>
        </section>
        <PlanningPanel ref="planningPanelRef" @goal-saved="finishLedgerOnboarding" @open-expedition="emit('open-expedition')" />
      </template>
    </div>
  </section>
</template>

<style scoped>
.report-context-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.report-context-toolbar-range { justify-content: flex-end; }
.ledger-onboarding { display: grid; gap: 13px; padding: 16px 18px; background: linear-gradient(130deg, color-mix(in srgb, var(--fox-gold-pale) 62%, var(--paper-card)), var(--paper-card) 72%); border: 1px solid var(--fox-gold); border-radius: 12px; }
.ledger-onboarding > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ledger-onboarding h3, .ledger-onboarding p { margin: 0; }
.ledger-onboarding header small { display: block; margin-bottom: 2px; color: var(--fox-gold-deep); font-size: 11px; font-weight: 700; }
.ledger-onboarding > header > button { padding: 3px 5px; color: var(--ink-dim); background: transparent; border: 0; font-size: 11px; cursor: pointer; }
.ledger-onboarding ol { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 0; list-style: none; }
.ledger-onboarding ol li { display: flex; align-items: center; gap: 6px; padding: 7px 9px; color: var(--ink-dim); background: color-mix(in srgb, var(--paper-card) 82%, transparent); border: 1px solid var(--paper-line); border-radius: 999px; font-size: 11px; }
.ledger-onboarding ol span { display: grid; place-items: center; width: 18px; height: 18px; flex: 0 0 auto; background: var(--paper); border-radius: 50%; font-variant-numeric: tabular-nums; }
.ledger-onboarding ol li.active { color: var(--ink); border-color: var(--fox-gold); font-weight: 700; }
.ledger-onboarding ol li.active span { color: #fff; background: var(--fox-gold-deep); }
.ledger-onboarding ol li.done { color: #426b36; border-color: #9bb68f; }
.ledger-onboarding ol li.done span { color: #fff; background: #5b813f; }
.ledger-onboarding-copy { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding-top: 1px; }
.ledger-onboarding-copy > div:first-child { display: grid; gap: 3px; }
.ledger-onboarding-copy b { font-size: 14px; }
.ledger-onboarding-copy p { color: var(--ink-dim); font-size: 12px; line-height: 1.55; }
.ledger-onboarding-actions { display: flex; flex: 0 0 auto; gap: 8px; }
.ledger-onboarding-goal { margin-bottom: 12px; }
.report-glance { position: relative; display: grid; gap: 14px; overflow: hidden; padding: 17px 19px 15px; background: var(--paper-card); border: 1px solid var(--paper-line); border-left: 5px solid color-mix(in srgb, var(--fox-gold-deep) 72%, var(--ink)); box-shadow: 4px 4px 0 color-mix(in srgb, var(--paper-line) 48%, transparent); }
.report-glance > header { display: flex; align-items: end; justify-content: space-between; gap: 18px; }
.report-glance > header small { display: block; margin-bottom: 3px; color: var(--fox-gold-deep); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.report-glance > header h2 { margin: 0; font-size: clamp(19px, 2.3vw, 25px); line-height: 1.2; }
.report-glance > header > span { padding-bottom: 2px; color: var(--ink-dim); border-bottom: 1px solid var(--paper-line); font-size: 10px; letter-spacing: .04em; }
.report-insight-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; padding: 0; border-top: 1px solid var(--paper-line); border-bottom: 1px solid var(--paper-line); list-style: none; }
.report-insight-list li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 10px; min-width: 0; padding: 12px 10px; border-left: 3px solid transparent; }
.report-insight-list li:not(.lead) { border-top: 1px solid var(--paper-line); }
.report-insight-list li:not(.lead):last-child { border-left-color: var(--paper-line); }
.report-insight-list li.lead { grid-column: 1 / -1; padding: 14px 10px 15px; }
.report-insight-list li > i { min-width: 27px; padding: 3px 5px; color: var(--ink-dim); background: var(--paper-panel); border: 1px solid var(--paper-line); font-size: 10px; font-style: normal; font-weight: 700; text-align: center; }
.report-insight-list li > div { display: grid; gap: 3px; min-width: 0; }
.report-insight-list strong { font-size: 13px; line-height: 1.4; }
.report-insight-list .lead strong { font-size: clamp(16px, 2vw, 19px); }
.report-insight-list p { margin: 0; color: var(--ink-dim); font-size: 11px; line-height: 1.55; }
.report-insight-list button { align-self: center; padding: 4px 6px; color: var(--fox-gold-deep); background: transparent; border: 0; border-bottom: 1px solid var(--fox-gold); font-size: 10px; white-space: nowrap; cursor: pointer; }
.report-insight-list li.gain > i { color: #47734f; border-color: #91ad8f; }
.report-insight-list li.cost > i { color: #8d4c3e; border-color: #c79d91; }
.report-insight-list li.alert > i { color: var(--danger); border-color: #c99589; }
.report-insight-list li.goal > i { color: #806115; border-color: var(--fox-gold); }
.report-glance > footer { display: flex; gap: 8px; flex-wrap: wrap; }
.report-glance > footer span { padding: 2px 0; color: var(--ink-dim); border-bottom: 1px dotted var(--paper-line); font-size: 11px; }
.report-glance > footer .obtain { color: var(--fox-gold-deep); }
.report-glance > footer .wishlist { color: #7a4b16; border-color: var(--fox-gold); font-weight: 700; }
.report-glance > footer .wishlist-manage { padding: 2px 3px; color: var(--fox-gold-deep); background: transparent; border: 0; border-bottom: 1px dashed var(--fox-gold); font-size: 11px; }
.report-glance > footer .wishlist-manage:hover { color: var(--ink); }
.report-glance > footer .manual { color: #536f8a; }
.trend-callout { margin: 0 0 8px; padding: 8px 10px; color: var(--ink); background: var(--fox-gold-pale); border-left: 3px solid var(--fox-gold); font-size: 12px; line-height: 1.5; }
.resource-trend > header { display: flex; flex-direction: column; gap: 10px; margin-bottom: 8px; }
.resource-trend > header h3 { margin: 0; }
.resource-trend > header p { margin: 2px 0 0; color: var(--ink-dim); font-size: 13px; }
.resource-trend nav { display: flex; gap: 6px; flex-wrap: wrap; }
.resource-trend nav button { border: 1px solid var(--paper-line); background: var(--paper-card); color: var(--ink-dim); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.resource-trend nav button.active { background: var(--fox-gold-pale); border-color: var(--fox-gold); color: var(--ink); font-weight: 600; }
@media (max-width: 520px) {
  .report-glance { padding: 15px 13px; }
  .report-glance > header { align-items: flex-start; flex-direction: column; gap: 4px; }
  .report-insight-list { grid-template-columns: 1fr; }
  .report-insight-list li { grid-template-columns: auto minmax(0, 1fr); gap: 8px; }
  .report-insight-list li.lead { grid-column: auto; }
  .report-insight-list li:not(.lead):last-child { border-left-color: transparent; }
  .report-insight-list li > button { grid-column: 2; justify-self: start; min-height: 28px; padding: 0; }
}
.compare-toggle { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-dim); font-size: 13px; }
.ledger-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.ledger-transfer { display: grid; gap: 12px; margin-bottom: 12px; padding: 14px 16px; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; }
.ledger-transfer > header, .ledger-import-preview > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ledger-transfer h4, .ledger-transfer h5, .ledger-transfer p { margin: 0; }
.ledger-transfer header p { margin-top: 3px; color: var(--ink-dim); font-size: 12px; }
.ledger-export-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.ledger-file-input { display: none; }
.ledger-transfer-tip { color: var(--ink-dim); font-size: 12px; line-height: 1.55; }
.ledger-import-preview { display: grid; gap: 10px; padding: 12px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 10px; }
.ledger-import-preview > header button { flex: 0 0 auto; padding: 4px 8px; color: var(--ink-dim); background: transparent; border: 0; cursor: pointer; }
.ledger-preview-counts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.ledger-preview-counts span { display: grid; gap: 1px; padding: 8px 9px; color: var(--ink-dim); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 8px; font-size: 11px; }
.ledger-preview-counts b { color: var(--ink); font-size: 18px; line-height: 1.1; }
.ledger-preview-counts .new { border-color: #9bb68f; }
.ledger-preview-counts .new b { color: #47734f; }
.ledger-preview-counts .conflict { border-color: #c99082; }
.ledger-preview-counts .conflict b { color: var(--danger); }
.ledger-preview-list { display: grid; gap: 5px; margin: 0; padding: 0; list-style: none; }
.ledger-preview-list li { display: grid; grid-template-columns: minmax(0, 1fr) minmax(160px, .8fr); gap: 10px; padding: 7px 9px; background: var(--paper-card); border-left: 3px solid #9bb68f; border-radius: 7px; font-size: 11px; }
.ledger-preview-list li span { min-width: 0; overflow-wrap: anywhere; }
.ledger-preview-list li em { color: var(--ink-dim); font-style: normal; overflow-wrap: anywhere; }
.ledger-preview-list li.duplicate { opacity: .7; border-left-color: var(--paper-line); }
.ledger-preview-list li.conflict { border-left-color: var(--danger); }
.ledger-import-preview details { color: var(--ink-dim); font-size: 11px; }
.ledger-import-preview details summary { color: var(--fox-gold-deep); cursor: pointer; }
.ledger-import-preview details ul { margin: 7px 0 0; padding-left: 20px; }
.ledger-conflict-confirm { display: flex; align-items: flex-start; gap: 7px; padding: 9px 10px; color: var(--danger); background: color-mix(in srgb, var(--paper-card) 78%, #f1d4cc); border-radius: 8px; font-size: 12px; line-height: 1.5; }
.ledger-conflict-confirm input { flex: 0 0 auto; margin-top: 2px; }
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
.hand-ledger-toggle { padding: 3px 7px; color: var(--fox-gold-deep); background: transparent; border: 0; font-size: 11px; cursor: pointer; }
.recent-manual-ledger ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.recent-manual-ledger li { display: grid; grid-template-columns: 88px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 8px 10px; background: var(--paper-card); border-radius: 8px; }
.recent-manual-ledger time { color: var(--ink-dim); font-size: 11px; }
.recent-manual-ledger li span { display: grid; min-width: 0; }
.recent-manual-ledger li span b { display: flex; align-items: center; gap: 6px; }
.recent-manual-ledger li span small { overflow: hidden; color: var(--ink-dim); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.recent-manual-ledger li strong { font-variant-numeric: tabular-nums; }
.recent-manual-ledger li strong.gain { color: #47734f; }
.recent-manual-ledger li strong.loss { color: var(--danger); }
.hand-entry-kind { padding: 1px 5px; color: #536f8a; background: #edf2f6; border-radius: 4px; font-size: 10px; font-style: normal; font-weight: 500; }
.hand-entry-actions { display: flex; align-items: center; gap: 2px; }
.hand-entry-actions button { padding: 3px 6px; color: var(--fox-gold-deep); background: transparent; border: 0; font-size: 11px; cursor: pointer; }
.hand-entry-actions button.danger { color: var(--danger); }
.resource-ledger-grid .resource-rate { margin-top: 5px; color: var(--fox-gold-deep); line-height: 1.35; }
.resource-goal-link { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; margin-top: 7px; padding: 5px 7px; color: var(--ink); background: var(--fox-gold-pale); border: 0; border-left: 3px solid var(--fox-gold); text-align: left; cursor: pointer; }
.resource-goal-link span { color: var(--ink); line-height: 1.35; }
.resource-goal-link em { flex: 0 0 auto; color: var(--fox-gold-deep); font-size: 10px; font-style: normal; white-space: nowrap; }
.resource-goal-link:hover { background: color-mix(in srgb, var(--fox-gold-pale) 70%, var(--paper-card)); }
.manual-inventory-form { display: grid; gap: 12px; margin-bottom: 12px; padding: 14px 16px; background: var(--paper-card); border: 1px solid var(--fox-gold); border-radius: 12px; }
.manual-inventory-form > header { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.manual-inventory-form h4, .manual-inventory-form p { margin: 0; }
.manual-inventory-form p { margin-top: 3px; color: var(--ink-dim); font-size: 12px; }
.manual-inventory-time { display: grid; grid-template-columns: auto minmax(180px, 320px); align-items: center; gap: 10px; color: var(--ink-dim); font-size: 12px; }
.manual-inventory-time input { width: 100%; min-width: 0; }
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
  .ledger-onboarding { padding: 14px; }
  .ledger-onboarding ol { gap: 5px; }
  .ledger-onboarding ol li { justify-content: center; padding: 6px 4px; }
  .ledger-onboarding-copy { align-items: stretch; flex-direction: column; gap: 11px; }
  .ledger-onboarding-actions { display: grid; }
  .ledger-onboarding-copy > button, .ledger-onboarding-actions button { width: 100%; }
  .ledger-export-actions { display: grid; }
  .ledger-export-actions button { width: 100%; }
  .ledger-preview-counts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ledger-preview-list li { grid-template-columns: 1fr; gap: 3px; }
  .manual-inventory-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .manual-action-picker { grid-template-columns: 1fr; }
  .manual-session-fields { grid-template-columns: 1fr; }
  .manual-session-fields .manual-session-note { grid-column: 1; }
  .recent-manual-ledger li { grid-template-columns: minmax(0, 1fr) auto; }
  .recent-manual-ledger time { grid-column: 1 / -1; }
  .recent-manual-ledger li span small { white-space: normal; }
  .manual-inventory-time { grid-template-columns: 1fr; }
  .resource-goal-link { align-items: flex-start; flex-direction: column; gap: 2px; }
  .resource-goal-link span, .resource-goal-link em { white-space: nowrap; }
  .report-form .multi-resource-entry { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .resource-ledger > header, .ledger-actions { align-items: stretch; flex-direction: column; }
  .report-context-toolbar { align-items: stretch; flex-direction: column; }
  .report-context-toolbar .segmented-control { width: 100%; }
  .report-context-toolbar .segmented-control button { flex: 1 1 0; min-width: 0; padding-inline: 7px; }
}
</style>
