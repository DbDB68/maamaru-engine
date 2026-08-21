<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from '../api'
import type { HumanReport, InventoryGap, ResourceLedger } from '../types'
import PanelHeader from './PanelHeader.vue'
import SegmentedControl from './SegmentedControl.vue'
import ResourceChart from './report/ResourceChart.vue'
import DayDetail from './report/DayDetail.vue'
import ReportRecords from './report/ReportRecords.vue'
import { categoryOf, dayRange, eventTime, resourceColors, resourceNames, shanghaiDate, signed, sourceCategories } from './report/reportModel'
import type { ChartSeries } from './report/reportModel'

const days = ref(7)
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

const mode = ref<'single' | 'compare'>('single')
const selectedResource = ref('小判')
const compareResources = ref(['小判', '加速符'])
const selectedDate = ref('')
const highlightCategory = ref('')

const rangeItems = [{ value: 1, label: '24 小时' }, { value: 7, label: '7 天' }, { value: 30, label: '30 天' }, { value: 365, label: '1 年' }]
const viewItems = [
  { value: 'chart', label: '资源对账图', caption: '涨跌都归到干活的人头上' },
  { value: 'records', label: '全部记录', caption: '按时间翻本丸档案' },
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
  const gains = changed.filter(row => row.delta! > 0).sort((a, b) => b.delta! - a.delta!)
  const costs = changed.filter(row => row.delta! < 0).sort((a, b) => a.delta! - b.delta!)
  const parts = [gains.length ? `资源总体有增长，${gains[0].name}${signed(gains[0].delta)}最多` : '资源总体没有增长']
  if (costs.length) parts.push(`${costs[0].name}${signed(costs[0].delta)}是最明显的消耗`)
  return `${rangeLabel.value}观察到${parts.join('；')}。点柱子可以看到每一笔是谁干的。`
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
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '成绩单读取失败' }
  finally { loading.value = false }
}
async function loadOlder() {
  if (loadingOlder.value) return
  loadingOlder.value = true
  try {
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
onMounted(() => load())
</script>

<template>
  <section class="report-panel">
    <PanelHeader variant="page" title="本丸成绩单" subtitle="资源涨跌都归到干活的人头上"><template #actions><SegmentedControl :model-value="days" :items="rangeItems" label="统计时间范围" @update:model-value="load(Number($event))" /></template></PanelHeader>
    <div class="report-content">
      <SegmentedControl class="report-views" :model-value="view" :items="viewItems" label="成绩单视图" variant="wide" @update:model-value="view = $event as 'chart' | 'records'" />
      <p v-if="error" class="report-error">{{ error }}</p>

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
            <div><h3>资源为什么增长或减少</h3><p>{{ mode === 'single' ? '柱子按来源染色，灰色是还没认领的；点一天看明细' : '对比模式：最多 4 种资源放一起，看谁涨谁跌' }}</p></div>
            <nav v-if="mode === 'single'" aria-label="选择资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: selectedResource === name }" @click="chooseResource(name)">{{ name }}</button></nav>
            <nav v-else aria-label="选择要对比的资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: compareResources.includes(name) }" @click="toggleCompareResource(name)">{{ name }}</button></nav>
            <label class="compare-toggle"><input v-model="mode" type="checkbox" true-value="compare" false-value="single">对比几种资源</label>
          </header>
          <ResourceChart :dates="chartDates" :series="chartSeries" :stacked="mode === 'single'" :selected-date="selectedDate" :loading="loading" @select="onChartSelect" />
          <DayDetail v-if="dayDetail" v-bind="dayDetail" :highlight-category="highlightCategory" @close="selectedDate = ''; highlightCategory = ''" @report="openGapReport" @report-day="openProactiveReport(dayRange(dayDetail.date)[1] * 1000)" />
          <form v-if="reportMode" ref="reportFormEl" class="report-form" @submit.prevent="saveHumanReport(false)">
            <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
            <fieldset><legend>这个时间段你做过什么？</legend><button v-for="value in [...humanActivities, '记不清了', '没有其他操作']" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
            <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" placeholder="可选，不用写具体资源数字"></label>
            <div class="report-form-actions"><button type="submit" class="primary" :disabled="reportSaving || (!reportForm.activities.length && !reportForm.note.trim())">{{ reportSaving ? '记录中……' : '记下来' }}</button><button type="button" class="secondary" @click="reportMode = ''; reportGap = null">先不说了</button></div>
          </form>
        </section>

        <section class="resource-ledger" :class="{ loading }">
          <header><div><h3>这段时间家底变了多少</h3><p>按时间范围内第一次和最后一次库存读数计算</p></div><span class="ledger-confidence" :class="confidence.level"><b>{{ confidence.label }}</b>{{ confidence.detail }}</span></header>
          <div class="resource-ledger-grid">
            <article v-for="row in resourceRows" :key="row.name" :class="{ gain: row.delta != null && row.delta > 0, loss: row.delta != null && row.delta < 0 }">
              <small>{{ row.name }}</small><strong>{{ signed(row.delta) }}</strong><span v-if="row.current != null">当前 {{ row.current.toLocaleString() }}</span><span v-else>尚未观察到</span>
            </article>
          </div>
          <p class="fox-summary"><b>狐之助小结</b>{{ foxSummary }}</p>
        </section>

        <section v-if="unreportedGaps.length || !reportMode" class="inventory-gap-panel" aria-label="库存差值说明">
          <div v-for="gap in unreportedGaps" :key="gap.gap_key" class="inventory-gap-alert"><div><strong>🦊 上次任务和这次开工之间，家底对不上啦</strong><p>{{ gapDelta(gap) }}</p><small>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}。这段差值单独留档，不会算进任何一轮挂机收益。</small></div><button type="button" class="secondary" @click="openGapReport(gap)">这期间做过什么？</button><button type="button" @click="skipGap(gap)">不想说，记差值就好</button></div>
          <button v-if="!reportMode" type="button" class="secondary report-proactive" @click="openProactiveReport()">我自己动了家底，主动报备一笔</button>
        </section>
      </template>

      <ReportRecords v-if="view === 'records'" :events="events" :runs="runs" :days="days" :has-more-events="hasMoreEvents" :has-more-runs="hasMoreRuns" :loading-older="loadingOlder" @load-more="loadOlder" @refresh="load(days)" />
    </div>
  </section>
</template>

<style scoped>
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
.inventory-gap-panel:empty { display: none; }
.report-form { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding: 14px 16px; background: var(--paper-card); border: 1px solid var(--fox-gold); border-radius: 12px; }
.report-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ink-dim); }
.report-form input { max-width: 260px; }
.report-form fieldset { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; border: 0; }
.report-form legend { font-size: 13px; color: var(--ink-dim); margin-bottom: 4px; }
.report-form fieldset button { border: 1px solid var(--paper-line); background: var(--paper); color: var(--ink-dim); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.report-form fieldset button.active { background: var(--fox-gold-pale); border-color: var(--fox-gold); color: var(--ink); font-weight: 600; }
.report-form-actions { display: flex; gap: 8px; }
</style>
