<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const days = ref(7), summary = ref<any>(null), ledger = ref<any>(null), events = ref<any[]>([]), runs = ref<any[]>([]), humanReports = ref<any[]>([]), inventoryGaps = ref<any[]>([]), loading = ref(false), error = ref('')
const resourceNames = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符', '甲州金']
const selectedResource = ref('小判')
const rangeLabel = computed(() => days.value === 1 ? '近 24 小时' : `近 ${days.value} 天`)
const resourceRows = computed(() => resourceNames.map(name => {
  const row = (ledger.value?.per_resource || []).find((item: any) => item.resource === name)
  return { name, before: row?.opening ?? null, current: row?.closing ?? null,
    delta: row?.total_delta ?? null, attributed: row?.attributed_delta ?? 0,
    unattributed: row?.unattributed_delta ?? null, observations: row?.observation_count ?? 0,
    confidence: row?.confidence || 'low' }
}))
function signed(value: number | null) {
  if (value == null) return '—'
  return `${value > 0 ? '+' : ''}${value.toLocaleString()}`
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
const foxSummary = computed(() => {
  const changed = resourceRows.value.filter(row => row.delta != null && row.delta !== 0)
  if (!changed.length) return `${rangeLabel.value}还没有足够的首末库存读数。狐之助会在挂机途中继续留意家底。`
  const gains = changed.filter(row => row.delta! > 0).sort((a, b) => b.delta! - a.delta!)
  const costs = changed.filter(row => row.delta! < 0).sort((a, b) => a.delta! - b.delta!)
  const parts = [gains.length ? `资源总体有增长，${gains[0].name}${signed(gains[0].delta)}最多` : '资源总体没有增长']
  if (costs.length) parts.push(`${costs[0].name}${signed(costs[0].delta)}是最明显的消耗`)
  const attributed = resourceRows.value.filter(row => row.attributed)
    .sort((a, b) => Math.abs(b.attributed) - Math.abs(a.attributed))[0]
  if (attributed) parts.push(`已确认的${attributed.name}变化为${signed(attributed.attributed)}`)
  return `${rangeLabel.value}观察到${parts.join('；')}。未标明来源的变化可能包含审神者自己的操作。`
})
const chartBars = computed(() => {
  const bars: any[] = (ledger.value?.daily_series || [])
    .filter((item: any) => item.resource === selectedResource.value)
    .map((item: any) => ({
      label: String(item.date || '').slice(5).replace('-', '/'), value: item.total_delta,
      observations: item.observation_count || 0, attributed: item.attributed_delta || 0,
      unattributed: item.unattributed_delta, confidence: item.confidence,
      attributionIds: item.attribution_ids || [], gapIds: item.gap_ids || [],
    }))
  const max = Math.max(1, ...bars.map(bar => Math.abs(bar.value || 0)))
  return bars.map(bar => ({ ...bar,
    mixed: Boolean(bar.attributed && bar.unattributed && Math.sign(bar.attributed) !== Math.sign(bar.unattributed)),
    height: bar.value == null ? 0 : Math.max(4, Math.round(Math.abs(bar.value) / max * 60)) }))
})
const selectedAttributions = computed(() => (ledger.value?.attributions || [])
  .filter((item: any) => item.resource === selectedResource.value))
const hasChartData = computed(() => chartBars.value.some((bar: any) => bar.value != null))
const unreportedGaps = computed(() => inventoryGaps.value.filter(item => !item.reported))
const eventNames: Record<string, string> = {
  'game_update.detected': '发现游戏更新', 'game_update.recovered': '游戏更新后恢复',
  'osaka.floor_completed': '大阪城完成一圈', 'sortie.completed': '出阵完成',
  'sortie.retreated_before_boss': '王点前撤退完成',
  'raid.round_completed': '联队战完成一圈', 'pumpkin.sortie_completed': '南瓜活动出阵完成',
  'pumpkin.board_completed': '南瓜活动完成一块板子', 'pumpkin.token_used': '南瓜活动使用更新令牌',
  'repair.queued': '刀剑进入手入', 'repair.skipped': '跳过手入', 'repair.session_completed': '手入完成',
  'repair.summary': '手入小结',
  'practice.result': '演练结束', 'pumpkin.sword_obtained': '南瓜活动获得刀剑',
  'forge.started': '开始锻刀', 'forge.collected': '领取锻刀结果',
  'expedition.dispatched': '远征派遣成功', 'expedition.settled': '远征结算',
  'task_rewards.claimed': '领取任务奖励', 'task_rewards.none': '任务奖励已清空',
  'task_rewards.unconfirmed': '任务奖励状态未确认', 'inventory.captured': '保存库存快照',
}
const scriptNames: Record<string, string> = {
  osaka: '大阪城', sortie: '合战场', yosari: '异去', raid: '联队战',
  pumpkin: '南瓜大作战', daily: '一键日课',
}
function countEvents(...types: string[]) { return events.value.filter(item => types.includes(item.event_type)).length }
const rewardClaims = computed(() => countEvents('task_rewards.claimed'))
const sortieCount = computed(() => countEvents('sortie.completed', 'sortie.retreated_before_boss', 'osaka.floor_completed', 'raid.round_completed', 'pumpkin.sortie_completed'))
const expeditions = computed(() => countEvents('expedition.dispatched'))
const practiceWins = computed(() => events.value.filter(item => item.event_type === 'practice.result' && isWin(item.payload)).length)
const practiceLosses = computed(() => events.value.filter(item => item.event_type === 'practice.result' && isLoss(item.payload)).length)
const practiceTotal = computed(() => countEvents('practice.result'))
const practiceUnknown = computed(() => Math.max(0, practiceTotal.value - practiceWins.value - practiceLosses.value))
const pumpkinBoards = computed(() => countEvents('pumpkin.board_completed'))
const pumpkinTokens = computed(() => countEvents('pumpkin.token_used'))
const estimateHours = ref(6), customHours = ref(6), customEstimate = ref(false)
const timelineEvents = computed(() => {
  const visible: any[] = []
  const repairs = new Map<string, any>()
  const hidden = new Set(['team_record.saved', 'equipment.restored', 'inventory.peek'])
  for (const item of events.value) {
    if (hidden.has(item.event_type)) continue
    if (!item.event_type.startsWith('repair.')) {
      visible.push(item)
      continue
    }
    const key = item.run_id || `minute:${Math.floor(item.ts / 60)}`
    let group = repairs.get(key)
    if (!group) {
      group = { id: `repair:${key}`, ts: item.ts, run_id: item.run_id, event_type: 'repair.summary', payload: { queued: [], skipped: [], repaired: 0, speedups: 0, sessions: 0 } }
      repairs.set(key, group)
    }
    group.ts = Math.max(group.ts, item.ts)
    if (item.event_type === 'repair.queued') group.payload.queued.push(item.payload || {})
    else if (item.event_type === 'repair.skipped') group.payload.skipped.push(item.payload || {})
    else if (item.event_type === 'repair.session_completed') {
      group.payload.sessions += 1
      group.payload.repaired += Number(item.payload?.repaired ?? item.payload?.count ?? 0)
      group.payload.speedups += Number(item.payload?.speedups ?? 0)
    }
  }
  return [...visible, ...repairs.values()].sort((a, b) => b.ts - a.ts)
})
const groupedTimelineEvents = computed(() => {
  const groups = new Map<string, any>()
  for (const item of timelineEvents.value) {
    const key = `${item.run_id || 'standalone'}:${item.event_type}:${eventDetail(item)}`
    const found = groups.get(key)
    if (found) found.items.push(item)
    else groups.set(key, { ...item, items: [item] })
  }
  return [...groups.values()].sort((a, b) => b.ts - a.ts)
})
const sortieGroups = computed(() => {
  const groups = new Map<string, { label: string; count: number; detail: string }>()
  const add = (key: string, label: string, detail = '') => {
    const found = groups.get(key)
    if (found) found.count += 1
    else groups.set(key, { label, count: 1, detail })
  }
  for (const item of events.value) {
    const p = item.payload || {}
    if (item.event_type === 'osaka.floor_completed') {
      const floor = p.selected_floor == null ? '未指定层数' : `${p.selected_floor}F`
      add(`osaka:${floor}`, `大阪城 ${floor}`)
    } else if (item.event_type === 'sortie.completed') {
      const place = p.mode === 'yosari' ? `异去 ${p.chapter}-${p.map_no}` : `合战场 ${p.chapter}-${p.map_no}`
      add(`sortie:${p.mode}:${p.chapter}:${p.map_no}`, place)
    } else if (item.event_type === 'sortie.retreated_before_boss') {
      add(`sortie-retreat:${p.chapter}:${p.map_no}`, `合战场 ${p.chapter}-${p.map_no}`, '王点前撤退')
    } else if (item.event_type === 'raid.round_completed') {
      add(`raid:${p.difficulty}`, `联队战 ${p.difficulty || '未指定难度'}`, p.triple ? '使用三倍枡' : '')
    } else if (item.event_type === 'pumpkin.sortie_completed') add('pumpkin', '南瓜大作战')
  }
  return [...groups.values()].sort((a, b) => b.count - a.count)
})
function isWin(payload: any) {
  const value = String(payload?.result ?? payload?.outcome ?? '').toLowerCase()
  return value.includes('胜') || value.startsWith('win') || value === 'won'
}
function isLoss(payload: any) {
  const value = String(payload?.result ?? payload?.outcome ?? '').toLowerCase()
  return value.includes('败') || value.startsWith('lose') || value === 'lost'
}
function practiceHeadline() {
  if (!practiceTotal.value) return '—'
  if (practiceUnknown.value === practiceTotal.value) return `${practiceTotal.value} 场待确认`
  return `${practiceWins.value} 胜 / ${practiceLosses.value} 负`
}
function practiceCaption() {
  if (!practiceTotal.value) return '还没有可确认的演练记录'
  return practiceUnknown.value ? `另有 ${practiceUnknown.value} 场结果未识别` : `已确认 ${practiceTotal.value} 场结果`
}
function repairCount(payload: any) {
  const queued = payload?.queued || []
  return payload?.sessions ? Number(payload.repaired || 0) : queued.length
}
function eventTitle(item: any) {
  return item.event_type === 'repair.summary' && repairCount(item.payload) === 0
    ? '手入误报'
    : (eventNames[item.event_type] || '本丸记录')
}
function eventDetail(item: any) {
  const p = item.payload || {}
  if (item.event_type === 'osaka.floor_completed') return p.selected_floor == null ? '未指定层数 · 完成 1 圈' : `${p.selected_floor}F · 完成 1 圈`
  if (item.event_type === 'sortie.completed') return `${p.mode === 'yosari' ? '异去' : '合战场'} ${p.chapter}-${p.map_no} · 完成 1 圈`
  if (item.event_type === 'sortie.retreated_before_boss') return `合战场 ${p.chapter}-${p.map_no} · 王点前主动返回本丸`
  if (item.event_type === 'raid.round_completed') return `难度 ${p.difficulty ?? '未指定'} · ${p.battles ?? 0} 场战斗`
  if (item.event_type === 'pumpkin.sortie_completed') return `第 ${p.sequence ?? '？'} 次出阵`
  if (item.event_type === 'pumpkin.board_completed') return `完成第 ${p.sequence ?? '？'} 块板子`
  if (item.event_type === 'pumpkin.token_used') return `累计使用 ${p.used ?? '？'} 枚`
  if (item.event_type === 'practice.result') return `结果：${p.result ?? p.outcome ?? '已记录'}`
  if (item.event_type === 'expedition.dispatched') return `部队 ${p.team_no ?? '？'} · ${p.map_name || p.map_code || '地图未识别'}`
  if (item.event_type === 'task_rewards.claimed') return `${p.tab || '当前'}页 · 已确认领取后按钮变灰`
  if (item.event_type === 'task_rewards.none') return `${p.tab || '当前'}页 · 没有可领取奖励`
  if (item.event_type === 'task_rewards.unconfirmed') return `${p.tab || '当前'}页 · ${p.stage === 'after_click' ? '点击后未确认到账' : '按钮状态未识别，不计成绩'}`
  if (item.event_type === 'repair.summary') {
    const queued = p.queued || [], skipped = p.skipped || []
    const repaired = repairCount(p)
    if (repaired === 0) {
      const evidence = skipped.length ? `（名单保护跳过 ${skipped.length} 振）` : ''
      return `麻麻露眼花认错伤势了，九十度鞠躬私密马赛 🙇${evidence}`
    }
    const parts = [`安排手入 ${repaired} 振`]
    const speedups = p.speedups || queued.filter((entry: any) => entry.speedup).length
    if (speedups) parts.push(`加速 ${speedups} 振`)
    if (skipped.length) parts.push(`名单保护跳过 ${skipped.length} 振`)
    return parts.join(' · ')
  }
  if (item.event_type === 'pumpkin.sword_obtained') return p.name || p.sword_name || '获得刀剑已记录'
  if (item.event_type === 'repair.session_completed') return p.repaired != null ? `完成 ${p.repaired} 振` : '本轮手入结束'
  return '本丸记录'
}
function eventTime(ts: number) { return new Date(ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
function loopTime(seconds: number | null) {
  if (!seconds) return '圈速积累中'
  const value = Math.round(seconds)
  return `${Math.floor(value / 60)}分${String(value % 60).padStart(2, '0')}秒/圈`
}
function elapsedTime(seconds: number | null) {
  if (seconds == null || seconds < 0) return '用时未记录'
  const minutes = Math.max(0, Math.round(seconds / 60))
  const hours = Math.floor(minutes / 60), rest = minutes % 60
  return hours ? `${hours}小时${rest ? `${rest}分` : ''}` : `${rest}分钟`
}
function runElapsedSeconds(run: any) {
  const precise = Number(run.play_duration_seconds)
  if (Number.isFinite(precise) && precise >= 0) return precise
  const fallback = Number(run.duration_seconds)
  return Number.isFinite(fallback) && fallback >= 0 ? fallback : null
}
function runTitle(run: any) {
  const name = scriptNames[run.script] || '挂机任务'
  if (run.script === 'osaka' && run.selected_floor != null) return `大阪城 ${run.selected_floor}F · ${run.loops} 圈`
  return `${name} · ${run.loops} 圈`
}
function chooseHours(value: number) { estimateHours.value = value; customHours.value = value; customEstimate.value = false }
function chooseCustom() { customEstimate.value = true; estimateHours.value = Math.max(.5, Number(customHours.value) || 1) }
function updateCustom() { estimateHours.value = Math.max(.5, Number(customHours.value) || 1) }
function estimatedLoops(run: any) { return run.average_loop_seconds ? Math.floor(estimateHours.value * 3600 / run.average_loop_seconds) : null }
function instanceDetail(item: any) {
  const p = item.payload || {}
  if (item.event_type === 'osaka.floor_completed' && p.completed != null) return `第 ${p.completed} 圈 · ${p.selected_floor == null ? '未指定层数' : `${p.selected_floor}F`}`
  if (item.event_type === 'pumpkin.sortie_completed' && p.sequence != null) return `第 ${p.sequence} 次出阵`
  return eventDetail(item)
}
function deltaStats(run: any) {
  const order = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符']
  return order.filter(name => run.resource_delta?.[name]).map(name => `${name} ${run.resource_delta[name] > 0 ? '+' : ''}${run.resource_delta[name].toLocaleString()}`).join(' · ')
}
function observedInventory(run: any) {
  const order = ['木炭', '玉钢', '冷却材', '砥石', '小判']
  const observed = run.inventory_observation || {}
  return order.filter(name => Number.isFinite(Number(observed[name])))
    .map(name => `${name} ${Number(observed[name]).toLocaleString()}`).join(' · ')
}
function kobanPerHour(run: any) {
  const koban = Number(run.resource_delta?.['小判'])
  const seconds = Number(runElapsedSeconds(run))
  return Number.isFinite(koban) && seconds > 0 ? Math.round(koban * 3600 / seconds) : null
}
function kobanPerHourLabel(run: any) {
  const value = kobanPerHour(run)
  return value == null ? '' : value.toLocaleString()
}
function kobanPerFloorLabel(run: any) {
  const ks = run.koban_session
  if (!ks || !ks.floors) return ''
  const delta = Number(ks.after) - Number(ks.before)
  if (!Number.isFinite(delta)) return ''
  return `${(delta / ks.floors).toFixed(1)} 小判`
}
const attachingRun = ref('')
const inventoryNotice = ref<Record<string, string>>({})
const latestInventoriedRun = computed(() => runs.value.find(run => run.has_before_snapshot))
function canAttachInventory(run: any) {
  return latestInventoriedRun.value?.run_id === run.run_id && !run.has_after_snapshot
}
async function attachInventory(run: any) {
  const confirmed = window.confirm(
    '补盘会把“最近库存快照”当作这轮的收工数据。\n\n'
    + '只有在挂机结束后没有领邮件、领奖、锻刀、手入、购买或其他人工操作时，差值才可信。\n\n'
    + '确定这份快照没有被其他操作污染吗？',
  )
  if (!confirmed) return
  attachingRun.value = run.run_id
  inventoryNotice.value = { ...inventoryNotice.value, [run.run_id]: '' }
  try {
    await api.attachRunInventory(run.run_id)
    await load(days.value)
  } catch (cause) {
    inventoryNotice.value = { ...inventoryNotice.value, [run.run_id]: cause instanceof Error ? cause.message : '补盘失败' }
  } finally { attachingRun.value = '' }
}
const reportMode = ref('')
const reportGap = ref<any>(null)
const reportSaving = ref(false)
const reportForm = ref<{ activities: string[]; note: string; occurred_at: string }>({ activities: [], note: '', occurred_at: '' })
const humanActivities = ['领邮箱', '手动领奖', '手动出阵', '锻刀', '手入', '万屋购买', '其他操作']
function localDateTime(timestamp = Date.now()) {
  const date = new Date(timestamp - new Date(timestamp).getTimezoneOffset() * 60000)
  return date.toISOString().slice(0, 16)
}
function openProactiveReport() {
  reportMode.value = reportMode.value === 'proactive' ? '' : 'proactive'
  reportGap.value = null
  reportForm.value = { activities: [], note: '', occurred_at: localDateTime() }
}
function openGapReport(gap: any) {
  reportMode.value = `gap:${gap.gap_key}`
  reportGap.value = gap
  reportForm.value = { activities: [], note: '', occurred_at: localDateTime(gap.ended_at * 1000) }
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
    reportMode.value = ''; reportGap.value = null
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '审神者报备保存失败' }
  finally { reportSaving.value = false }
}
async function skipGap(gap: any) {
  openGapReport(gap)
  await saveHumanReport(true)
}
async function removeHumanReport(item: any) {
  if (!window.confirm('确定删除这条审神者报备吗？狐狸账和库存账不会受影响。')) return
  try {
    await api.deleteHumanReport(item.id); await refreshHumanReports()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '审神者报备删除失败' }
}
function gapDelta(gap: any) {
  const order = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符']
  return order.filter(name => gap.resource_delta?.[name]).map(name => `${name} ${gap.resource_delta[name] > 0 ? '+' : ''}${gap.resource_delta[name].toLocaleString()}`).join(' · ')
}
async function load(nextDays = days.value) {
  days.value = nextDays; loading.value = true
  try {
    const [nextSummary, nextLedger, nextEvents, nextRuns, nextHuman] = await Promise.all([api.dataSummary(nextDays), api.resourceLedger(nextDays), api.dataEvents(1000), api.dataRuns(30), api.humanReports()])
    summary.value = nextSummary
    ledger.value = nextLedger
    events.value = nextEvents.items.filter(item => item.ts >= Date.now() / 1000 - nextDays * 86400)
    runs.value = nextRuns.items.filter(item => item.loops && item.started_at >= Date.now() / 1000 - nextDays * 86400)
    humanReports.value = nextHuman.items
    inventoryGaps.value = nextHuman.inventory_gaps
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '成绩单读取失败' }
  finally { loading.value = false }
}
onMounted(() => load())
</script>

<template>
  <section class="report-panel">
    <header class="report-head">
      <div><h2>📜 本丸成绩单</h2><p>只统计小狐狸帮你完成的事</p></div>
      <div class="report-ranges" aria-label="统计时间范围"><button v-for="value in [1, 7, 30]" :key="value" type="button" :class="{ active: days === value }" @click="load(value)">{{ value === 1 ? '24 小时' : `${value} 天` }}</button></div>
    </header>
    <p v-if="error" class="report-error">{{ error }}</p>
    <section class="resource-ledger" :class="{ loading }">
      <header><div><h3>这段时间家底变了多少</h3><p>按时间范围内第一次和最后一次库存读数计算</p></div><span class="ledger-confidence" :class="confidence.level"><b>{{ confidence.label }}</b>{{ confidence.detail }}</span></header>
      <div class="resource-ledger-grid">
        <article v-for="row in resourceRows" :key="row.name" :class="{ gain: row.delta != null && row.delta > 0, loss: row.delta != null && row.delta < 0 }">
          <small>{{ row.name }}</small><strong>{{ signed(row.delta) }}</strong><span v-if="row.current != null">当前 {{ row.current.toLocaleString() }}</span><span v-else>尚未观察到</span>
        </article>
      </div>
      <p class="fox-summary"><b>狐之助小结</b>{{ foxSummary }}</p>
    </section>
    <section class="resource-trend">
      <header><div><h3>本丸收支</h3><p>柱高是当日库存净变化，柱内颜色表示能够确认的来源</p></div><nav aria-label="选择资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: selectedResource === name }" @click="selectedResource = name">{{ name }}</button></nav></header>
      <div class="chart-legend"><span><i class="attributed"></i>已确认来源</span><span><i class="unattributed"></i>尚未归因</span><small v-if="!selectedAttributions.length">当前范围没有已确认的{{ selectedResource }}来源</small></div>
      <div class="resource-chart" :class="{ empty: !hasChartData }" :style="{ gridTemplateColumns: `repeat(${chartBars.length}, minmax(34px, 1fr))` }">
        <div class="chart-zero" aria-hidden="true"></div>
        <div v-for="bar in chartBars" :key="bar.label" class="chart-column" :title="bar.value == null ? `${bar.label}：读数不足` : `${bar.label}：${selectedResource} ${signed(bar.value)}；已归因 ${signed(bar.attributed)}；未归因 ${signed(bar.unattributed)}；${bar.observations} 次观察`">
          <span class="chart-value">{{ bar.value == null ? '' : signed(bar.value) }}</span>
          <span v-if="bar.value != null" class="chart-stack" :class="[bar.value >= 0 ? 'positive' : 'negative', { mixed: bar.mixed }]" :style="{ height: `${bar.height}px` }">
            <i v-if="bar.attributed" class="attributed" :style="{ flexGrow: Math.abs(bar.attributed) }"></i>
            <i v-if="bar.unattributed" class="unattributed" :style="{ flexGrow: Math.abs(bar.unattributed) }"></i>
          </span>
          <small>{{ bar.label }}</small>
        </div>
        <p v-if="loading">正在整理这段时间的收支……</p>
        <p v-else-if="!hasChartData">同一时间段至少需要两次读数，狐之助再攒一会儿账。</p>
      </div>
    </section>
    <section class="weekly-activity"><header><h3>活动小结</h3><small>{{ rangeLabel }}</small></header><div class="report-stats" :class="{ loading }">
      <article><small>领取任务奖励</small><strong>{{ rewardClaims }} 次</strong><span>确认领取后按钮变灰才计数</span></article>
      <article><small>出阵完成</small><strong>{{ sortieCount }} 次</strong><span>按确认完成的圈数计数</span></article>
      <article><small>派遣远征</small><strong>{{ expeditions }} 次</strong><span>确认“远征中”后记录</span></article>
      <article><small>演练战绩</small><strong>{{ practiceHeadline() }}</strong><span>{{ practiceCaption() }}</span></article>
    </div></section>
    <section v-if="unreportedGaps.length" class="inventory-gap-panel" aria-label="库存差值提醒">
      <div v-for="gap in unreportedGaps" :key="gap.gap_key" class="inventory-gap-alert"><div><strong>🦊 上次任务和这次开工之间，家底对不上啦</strong><p>{{ gapDelta(gap) }}</p><small>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}。这段差值单独留档，不会算进任何一轮挂机收益。</small></div><button type="button" class="secondary" @click="openGapReport(gap)">这期间做过什么？</button><button type="button" @click="skipGap(gap)">不想说，记差值就好</button></div>
      <form v-if="reportGap" @submit.prevent="saveHumanReport(false)">
        <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
        <fieldset><legend>这个时间段你做过什么？</legend><button v-for="value in [...humanActivities, '记不清了', '没有其他操作']" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
        <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" placeholder="可选，不用写具体资源数字"></label>
        <p>说明只给这段差值加一个上下文，不会改写狐狸账或库存账。</p><button type="submit" class="primary" :disabled="reportSaving || (!reportForm.activities.length && !reportForm.note.trim())">{{ reportSaving ? '记录中……' : '记下来' }}</button>
      </form>
    </section>
    <section class="human-report-panel">
      <header><div><h3>📝 审神者报备</h3><small>你只说做过什么，具体数字交给库存盘点。</small></div><button type="button" class="secondary" @click="openProactiveReport">{{ reportMode === 'proactive' ? '收起' : '主动报备一下' }}</button></header>
      <form v-if="reportMode === 'proactive'" @submit.prevent="saveHumanReport(false)">
        <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
        <fieldset><legend>想给まあ丸报备什么？</legend><button v-for="value in humanActivities" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
        <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" placeholder="可选，不用写具体资源数字"></label>
        <p>报备只作为差值的上下文，不会改写狐狸账或库存账。</p><button type="submit" class="primary" :disabled="reportSaving || (!reportForm.activities.length && !reportForm.note.trim())">{{ reportSaving ? '记录中……' : '记下来' }}</button>
      </form>
      <details v-if="humanReports.length"><summary>查看已有报备（{{ humanReports.length }}）</summary><ul><li v-for="item in humanReports.slice(0, 20)" :key="item.id"><time>{{ eventTime(item.occurred_at) }}</time><span><b>{{ item.activities.join('、') }}</b>{{ item.note }}</span><button type="button" aria-label="删除这条报备" @click="removeHumanReport(item)">×</button></li></ul></details>
    </section>
    <div class="report-body">
      <div>
        <section v-if="runs.length" class="report-runs">
          <header><h3>⛏️ 挂机成绩单</h3><small>圈速按相邻出阵间隔计算</small></header>
          <article v-for="(run, index) in runs.slice(0, 5)" :key="run.run_id" :class="{ featured: index === 0 }">
            <time>{{ eventTime(run.started_at) }}</time>
            <div><strong>{{ runTitle(run) }}</strong>
              <p class="run-duration">出阵用时 <b>{{ elapsedTime(runElapsedSeconds(run)) }}</b><small>{{ run.play_duration_seconds != null ? '从开工到最后一圈完成' : '旧记录按整轮任务用时估算' }}</small></p>
              <div v-if="index === 0 && run.average_loop_seconds" class="run-estimator">
                <div><small>平均速度</small><b>{{ loopTime(run.average_loop_seconds) }}</b></div>
                <div class="estimate-result"><small>预计完成</small><b>≈ {{ estimatedLoops(run) }} 圈</b></div>
                <div class="estimate-control"><small>预计收益</small><label>挂机时间 <span v-if="!customEstimate">{{ estimateHours }} 小时</span><input v-else v-model.number="customHours" type="number" min="0.5" step="0.5" aria-label="自定义挂机小时数" @input="updateCustom"></label></div>
                <nav aria-label="预计挂机时间"><button v-for="hour in [1, 6, 8]" :key="hour" type="button" :class="{ active: !customEstimate && estimateHours === hour }" @click="chooseHours(hour)">{{ hour }}小时</button><button type="button" :class="{ active: customEstimate }" @click="chooseCustom">自定义</button></nav>
              </div>
              <p v-else>{{ loopTime(run.average_loop_seconds) }}</p>
              <div class="run-upkeep" aria-label="本轮养护"><small class="ledger-label">🦊 狐狸账</small><span>🩹 手入 <b>{{ run.repair_sessions }}</b> 次</span><span>⚡ 加速符 <b>{{ run.speedups }}</b> 枚</span><span>🛡️ 补刀装 <b>{{ run.equipment_restores }}</b> 次</span></div>
              <p v-if="observedInventory(run)" class="run-delta"><small>👀 途中看到的库存 <em>{{ run.inventory_observation_count }} 次观察</em></small>{{ observedInventory(run) }}<span>只表示最后一次读数，不作为本轮收益</span></p>
              <p v-if="deltaStats(run)" class="run-delta"><small>📦 库存变化 <em v-if="run.after_snapshot_source === 'manual_attach'">手动补盘</em><em v-else-if="run.after_snapshot_source === 'auto_science'">🧪小判实验估算</em></small>{{ deltaStats(run) }}<span v-if="kobanPerHourLabel(run)">· 小判约 {{ kobanPerHourLabel(run) }} / 小时</span><span v-if="kobanPerFloorLabel(run)">· 平均每层 {{ kobanPerFloorLabel(run) }}</span></p>
              <p v-else-if="run.has_resource_comparison" class="run-delta"><small>📦 库存账</small>本轮资源无变化<span v-if="run.after_snapshot_source === 'manual_attach'">（手动补盘）</span><span v-else-if="run.after_snapshot_source === 'auto_science'">（🧪小判实验）</span></p>
              <div v-else class="run-inventory-missing">
                <small v-if="canAttachInventory(run)">收工盘点没有完成。先在首页运行“库存快照”，再把最近结果补到这轮。<strong>仅适合挂机结束后没有其他操作污染的数据。</strong></small>
                <small v-else-if="run.has_before_snapshot && !run.has_after_snapshot">这是较早的挂机记录，不能用现在的库存回填，以免把中间的变化算错轮次。</small>
                <small v-else>这轮没有完整的前后库存快照，无法计算变化。</small>
                <button v-if="canAttachInventory(run)" type="button" class="secondary" :disabled="attachingRun === run.run_id" @click="attachInventory(run)">{{ attachingRun === run.run_id ? '正在补盘……' : '补上最近盘点' }}</button>
                <em v-if="inventoryNotice[run.run_id]">{{ inventoryNotice[run.run_id] }}</em>
              </div>
            </div>
          </article>
        </section>
        <section class="report-sorties">
          <header><h3>⚔️ 出阵小结</h3><small v-if="pumpkinBoards || pumpkinTokens">南瓜：{{ pumpkinBoards }} 块板子 · {{ pumpkinTokens }} 枚令牌</small></header>
          <div v-if="sortieGroups.length" class="sortie-list"><p v-for="item in sortieGroups" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.count }} 圈</strong><small v-if="item.detail">{{ item.detail }}</small></p></div>
          <p v-else class="report-empty">这个时间段还没有完成的出阵。</p>
        </section>
        <section class="report-events">
          <header><h3>最近发生</h3><small>只展示结构化玩法记录</small></header>
          <div v-if="groupedTimelineEvents.length" class="event-list"><article v-for="item in groupedTimelineEvents.slice(0, 60)" :key="item.id"><time>{{ eventTime(item.ts) }}</time><i aria-hidden="true"></i><div><strong>{{ eventTitle(item) }}<em v-if="item.items.length > 1">× {{ item.items.length }}</em></strong><p>{{ eventDetail(item) }}</p><details v-if="item.items.length > 1"><summary>展开 {{ item.items.length }} 条明细</summary><p v-for="child in item.items" :key="child.id"><time>{{ eventTime(child.ts) }}</time>{{ instanceDetail(child) }}</p></details></div></article></div>
          <p v-else class="report-empty">这个时间段还没有玩法记录。新任务运行后，就会从这里开始积累。</p>
        </section>
      </div>
      <aside class="report-observation">
        <h3>🦊 近侍观察</h3>
        <p v-if="summary?.runs?.total">这段时间共执行 {{ summary.runs.total }} 次任务，留下 {{ summary.events.total }} 条玩法记录。只说能够确认的事，不把猜测当成绩。</p>
        <p v-else>还没有足够数据。小狐狸先认真记账，积累一阵再来写周报。</p>
        <small>智能建议将在数据积累稳定后开放，并始终注明依据。</small>
      </aside>
    </div>
  </section>
</template>
