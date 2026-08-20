<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'
import SegmentedControl from './SegmentedControl.vue'

const days = ref(7), reportView = ref<'battle' | 'ledger' | 'records'>('battle'), recordView = ref<'runs' | 'timeline'>('runs'), timelineKind = ref<'activity' | 'system'>('activity'), timelineLimit = ref(20), summary = ref<any>(null), ledger = ref<any>(null), events = ref<any[]>([]), runs = ref<any[]>([]), humanReports = ref<any[]>([]), inventoryGaps = ref<any[]>([]), loading = ref(false), error = ref('')
const resourceNames = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符', '甲州金']
const rangeItems = [{ value: 1, label: '24 小时' }, { value: 7, label: '7 天' }, { value: 30, label: '30 天' }]
const reportViewItems = [
  { value: 'battle', label: '战报', caption: '成绩与最近表现' },
  { value: 'ledger', label: '资源账', caption: '库存、收支与报备' },
  { value: 'records', label: '近期记录', caption: '最近挂机与时间线' },
]
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
    .map((item: any) => {
      const reported = reportedDailyTotals.value[item.date]?.[selectedResource.value] || 0
      return { label: String(item.date || '').slice(5).replace('-', '/'), value: item.total_delta,
        observations: item.observation_count || 0, attributed: item.attributed_delta || 0, reported,
        unattributed: item.unattributed_delta == null ? null : item.unattributed_delta - reported, confidence: item.confidence,
        attributionIds: item.attribution_ids || [], gapIds: item.gap_ids || [] }
    })
  const max = Math.max(1, ...bars.map(bar => Math.abs(bar.value || 0)))
  return bars.map(bar => ({ ...bar,
    mixed: new Set([bar.attributed, bar.reported, bar.unattributed].filter(Boolean).map(Math.sign)).size > 1,
    height: bar.value == null ? 0 : Math.max(4, Math.round(Math.abs(bar.value) / max * 60)) }))
})
const selectedAttributions = computed(() => (ledger.value?.attributions || [])
  .filter((item: any) => item.resource === selectedResource.value))
const hasChartData = computed(() => chartBars.value.some((bar: any) => bar.value != null))
const unreportedGaps = computed(() => inventoryGaps.value.filter(item => !item.reported))
const reportedGapEntries = computed(() => {
  const cutoff = Date.now() / 1000 - days.value * 86400
  return inventoryGaps.value.filter(gap => gap.reported && gap.ended_at >= cutoff).map(gap => ({
    ...gap,
    reports: humanReports.value.filter(report => report.gap_key === gap.gap_key),
  }))
})
function reportExplainsGap(report: any) {
  const nonAnswers = new Set(['暂不说明', '记不清了', '没有其他操作'])
  return Boolean(String(report.note || '').trim()) || (report.activities || []).some((value: string) => !nonAnswers.has(value))
}
const explainedGapEntries = computed(() => reportedGapEntries.value.filter(gap => gap.reports.some(reportExplainsGap)))
const acknowledgedGapEntries = computed(() => reportedGapEntries.value.filter(gap => !gap.reports.some(reportExplainsGap)))
const attributedRows = computed(() => resourceRows.value.filter(row => row.attributed).map(row => `${row.name} ${signed(row.attributed)}`))
function sumGapResources(gaps: any[]) {
  const totals: Record<string, number> = {}
  for (const gap of gaps) for (const [name, value] of Object.entries(gap.resource_delta || {})) totals[name] = (totals[name] || 0) + Number(value || 0)
  return totals
}
const humanPeriodTotals = computed(() => sumGapResources(explainedGapEntries.value))
const acknowledgedTotals = computed(() => sumGapResources(acknowledgedGapEntries.value))
const humanPeriodRows = computed(() => resourceNames.filter(name => humanPeriodTotals.value[name]).map(name => `${name} ${signed(humanPeriodTotals.value[name])}`))
const acknowledgedRows = computed(() => resourceNames.filter(name => acknowledgedTotals.value[name]).map(name => `${name} ${signed(acknowledgedTotals.value[name])}`))
const unexplainedRows = computed(() => resourceRows.value.flatMap(row => {
  if (row.unattributed == null) return []
  const value = row.unattributed - (humanPeriodTotals.value[row.name] || 0) - (acknowledgedTotals.value[row.name] || 0)
  return value ? [`${row.name} ${signed(value)}`] : []
}))
const reportedDailyTotals = computed(() => {
  const totals: Record<string, Record<string, number>> = {}
  for (const gap of explainedGapEntries.value) {
    const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date(gap.ended_at * 1000))
    totals[date] ||= {}
    for (const [name, value] of Object.entries(gap.resource_delta || {})) totals[date][name] = (totals[date][name] || 0) + Number(value || 0)
  }
  return totals
})
const proactiveReports = computed(() => {
  const cutoff = Date.now() / 1000 - days.value * 86400
  return humanReports.value.filter(item => !item.gap_key && item.occurred_at >= cutoff)
})
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
  const hidden = new Set(['team_record.saved', 'inventory.peek', 'osaka.koban_session'])
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
const systemEventTypes = new Set([
  'inventory.captured', 'inventory.peek', 'task_rewards.unconfirmed',
  'game_update.detected', 'game_update.recovered', 'resource.change',
])
function activityGroupKey(item: any) {
  const p = item.payload || {}, run = item.run_id || `minute:${Math.floor(item.ts / 300)}`
  if (item.event_type === 'sortie.completed') return `${run}:sortie:${p.mode}:${p.chapter}:${p.map_no}`
  if (item.event_type === 'sortie.retreated_before_boss') return `${run}:retreat:${p.chapter}:${p.map_no}`
  if (item.event_type === 'osaka.floor_completed') return `${run}:osaka:${p.selected_floor}`
  if (item.event_type === 'practice.result') return `${run}:practice`
  if (item.event_type.startsWith('task_rewards.')) return `${run}:${item.event_type}`
  if (['forge.started', 'forge.collected', 'expedition.dispatched', 'expedition.settled'].includes(item.event_type)) return `${run}:${item.event_type}`
  return `${run}:${item.event_type}:${eventDetail(item)}`
}
const groupedActivityEvents = computed(() => {
  const groups = new Map<string, any>()
  for (const item of timelineEvents.value) {
    if (systemEventTypes.has(item.event_type)) continue
    const key = activityGroupKey(item)
    const found = groups.get(key)
    if (found) { found.items.push(item); found.ts = Math.max(found.ts, item.ts) }
    else groups.set(key, { ...item, items: [item] })
  }
  return [...groups.values()].sort((a, b) => b.ts - a.ts)
})
const groupedSystemEvents = computed(() => {
  const groups = new Map<string, any>()
  for (const item of events.value) {
    if (!systemEventTypes.has(item.event_type) || item.event_type === 'resource.change') continue
    const key = `${item.run_id || `minute:${Math.floor(item.ts / 300)}`}:${item.event_type}`
    const found = groups.get(key)
    if (found) { found.items.push(item); found.ts = Math.max(found.ts, item.ts) }
    else groups.set(key, { ...item, items: [item] })
  }
  return [...groups.values()].sort((a, b) => b.ts - a.ts)
})
const recordViewItems = computed(() => [
  { value: 'runs', label: '挂机轮次', badge: runs.value.length },
  { value: 'timeline', label: '活动时间线', badge: groupedActivityEvents.value.length },
])
const timelineKindItems = computed(() => [
  { value: 'activity', label: '玩家活动', badge: groupedActivityEvents.value.length },
  { value: 'system', label: '系统观察', badge: groupedSystemEvents.value.length },
])
const activeTimeline = computed(() => timelineKind.value === 'activity' ? groupedActivityEvents.value : groupedSystemEvents.value)
function chooseTimelineKind(value: 'activity' | 'system') {
  timelineKind.value = value
  timelineLimit.value = 20
}
function chooseReportView(value: string | number) { reportView.value = value as typeof reportView.value }
function chooseRecordView(value: string | number) { recordView.value = value as typeof recordView.value }
function chooseTimelineSegment(value: string | number) { chooseTimelineKind(value as typeof timelineKind.value) }
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
const latestRun = computed(() => runs.value[0] || null)
const topSorties = computed(() => sortieGroups.value.slice(0, 3))
const kobanRow = computed(() => resourceRows.value.find(row => row.name === '小判'))
const battleSummary = computed(() => {
  if (loading.value) return '狐之助正在整理这段时间的战报……'
  if (!sortieCount.value && !summary.value?.runs?.total) return '还没有足够的成绩，先让小狐狸跑起来吧。'
  const lead = topSorties.value[0]
  return `まあ丸完成了 ${sortieCount.value.toLocaleString()} 次出阵${lead ? `，主要在 ${lead.label} 工作` : ''}。`
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
function activityTitle(item: any) {
  const count = item.items?.length || 1
  if (item.event_type === 'sortie.completed') return `完成出阵 ${count} 次`
  if (item.event_type === 'sortie.retreated_before_boss') return `王点前撤退 ${count} 次`
  if (item.event_type === 'osaka.floor_completed') return `大阪城完成 ${count} 圈`
  if (item.event_type === 'raid.round_completed') return `联队战完成 ${count} 圈`
  if (item.event_type === 'practice.result') return `完成演练 ${count} 场`
  if (item.event_type === 'forge.collected') return `领取锻刀结果 ${count} 次`
  if (item.event_type === 'forge.started') return `开始锻刀 ${count} 炉`
  if (item.event_type === 'expedition.dispatched') return `派遣远征 ${count} 队`
  if (item.event_type === 'expedition.settled') return `领取远征奖励 ${count} 份`
  if (item.event_type === 'task_rewards.claimed') return `领取任务奖励 ${count} 类`
  if (item.event_type === 'task_rewards.none') return `检查任务奖励 ${count} 类`
  if (item.event_type === 'repair.summary') return repairCount(item.payload) ? `手入 ${repairCount(item.payload)} 振` : '检查手入名单'
  if (item.event_type === 'equipment.restored') return `恢复刀装 ${count} 次`
  return eventTitle(item)
}
function activityDetail(item: any) {
  const items = item.items || [item], p = item.payload || {}
  if (item.event_type === 'sortie.completed') return `${p.mode === 'yosari' ? '异去' : '合战场'} ${p.chapter}-${p.map_no} · 共 ${items.length} 圈`
  if (item.event_type === 'sortie.retreated_before_boss') return `合战场 ${p.chapter}-${p.map_no} · 均在王点前返回`
  if (item.event_type === 'osaka.floor_completed') {
    const koban = events.value.find((entry: any) => entry.run_id === item.run_id && entry.event_type === 'osaka.koban_session')?.payload?.delta
    return `${p.selected_floor ?? '？'}F · 共 ${items.length} 圈${Number.isFinite(Number(koban)) ? ` · 小判 ${Number(koban) > 0 ? '+' : ''}${Number(koban).toLocaleString()}` : ''}`
  }
  if (item.event_type === 'practice.result') {
    const wins = items.filter((entry: any) => isWin(entry.payload)).length
    const losses = items.filter((entry: any) => isLoss(entry.payload)).length
    return `${wins} 胜${losses ? ` · ${losses} 负` : ''} · ${items.map((entry: any) => entry.payload?.result).filter(Boolean).join(' / ')}`
  }
  if (item.event_type === 'forge.collected') return `炉位 ${items.map((entry: any) => entry.payload?.slot).filter(Boolean).join('、')}`
  if (item.event_type === 'forge.started') return `已确认点火 · ${items.length} 炉`
  if (item.event_type === 'expedition.dispatched') return items.map((entry: any) => `部队${entry.payload?.team_no ?? '？'} ${entry.payload?.map_name || entry.payload?.map_code || ''}`).join(' · ')
  if (item.event_type === 'expedition.settled') return items.map((entry: any) => entry.payload?.map_name || entry.payload?.header).filter(Boolean).join(' · ') || '奖励已领取'
  if (item.event_type === 'task_rewards.claimed' || item.event_type === 'task_rewards.none') return items.map((entry: any) => entry.payload?.tab || '当前页').join(' / ')
  return eventDetail(item)
}
function systemTitle(item: any) {
  const count = item.items?.length || 1
  if (item.event_type === 'task_rewards.unconfirmed') return `任务奖励检查存在 ${count} 条未确认项`
  if (item.event_type === 'inventory.captured' || item.event_type === 'inventory.peek') return `库存观察已更新${count > 1 ? ` ${count} 次` : ''}`
  if (item.event_type === 'game_update.detected') return '检测到游戏更新'
  if (item.event_type === 'game_update.recovered') return '游戏更新后已恢复'
  return eventTitle(item)
}
function systemDetail(item: any) {
  const items = item.items || [item]
  if (item.event_type === 'task_rewards.unconfirmed') return items.map((entry: any) => entry.payload?.tab || '当前页').join(' / ')
  if (item.event_type === 'inventory.captured' || item.event_type === 'inventory.peek') return '供库存净变化与可信度计算使用'
  return items.map((entry: any) => eventDetail(entry)).join(' · ')
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
function attributedStats(run: any) {
  const order = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符', '甲州金']
  return order.filter(name => run.attributed_resource_delta?.[name])
    .map(name => `${name} ${run.attributed_resource_delta[name] > 0 ? '+' : ''}${run.attributed_resource_delta[name].toLocaleString()}`).join(' · ')
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
function humanReportLabel(report: any) {
  return [...(report.activities || []), report.note].filter(Boolean).join(' · ') || '已报备，未填写说明'
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
    <PanelHeader variant="page" title="本丸成绩单" subtitle="只统计小狐狸帮你完成的事"><template #actions><SegmentedControl :model-value="days" :items="rangeItems" label="统计时间范围" @update:model-value="load(Number($event))" /></template></PanelHeader>
    <div class="report-content">
    <SegmentedControl class="report-views" :model-value="reportView" :items="reportViewItems" label="成绩单视图" variant="wide" @update:model-value="chooseReportView" />
    <p v-if="error" class="report-error">{{ error }}</p>
    <template v-if="reportView === 'battle'">
      <section class="battle-intro">
        <div><span>{{ rangeLabel }}</span><h3>{{ battleSummary }}</h3></div>
        <aside v-if="summary?.runs?.total"><b>🦊 {{ summary.runs.total }} 次任务</b><small>{{ summary.events.total }} 条玩法记录</small></aside><aside v-else><b>🦊 近侍观察</b><small>只记录确认完成的事</small></aside>
      </section>
      <section class="battle-kpis" :class="{ loading }">
        <article><small>⚔️ 出阵完成</small><strong>{{ sortieCount.toLocaleString() }}</strong><span>圈</span><p>{{ topSorties[0]?.label || '等待第一份战绩' }}</p></article>
        <article><small>📋 执行任务</small><strong>{{ summary?.runs?.total || 0 }}</strong><span>次</span><p>狐狸确认完成的任务轮次</p></article>
        <article><small>🎌 演练战绩</small><strong>{{ practiceTotal ? `${practiceWins}胜` : '—' }}</strong><span v-if="practiceTotal">{{ practiceLosses }}负</span><p>{{ practiceCaption() }}</p></article>
        <article :class="{ gain: kobanRow?.attributed != null && kobanRow.attributed > 0, loss: kobanRow?.attributed != null && kobanRow.attributed < 0 }"><small>💰 狐狸确认小判</small><strong>{{ signed(kobanRow?.attributed ?? null) }}</strong><span>枚</span><p>库存净变化 {{ signed(kobanRow?.delta ?? null) }}</p></article>
      </section>
      <button v-if="unreportedGaps.length" type="button" class="report-attention" @click="reportView = 'ledger'">
        <span><b>🦊 有 {{ unreportedGaps.length }} 段库存差值等你说明</b><small>它们没有算进任何一轮挂机收益，处理后提醒会消失。</small></span><em>去看看 →</em>
      </button>
      <div class="battle-grid">
        <section class="latest-battle">
          <header><div><span>最近一轮</span><h3>{{ latestRun ? runTitle(latestRun) : '还没有挂机记录' }}</h3></div><button v-if="latestRun" type="button" class="secondary" @click="reportView = 'records'">查看本轮明细</button></header>
          <template v-if="latestRun">
            <time>{{ eventTime(latestRun.started_at) }}</time>
            <div class="latest-metrics"><p><small>出阵用时</small><strong>{{ elapsedTime(runElapsedSeconds(latestRun)) }}</strong></p><p><small>平均速度</small><strong>{{ loopTime(latestRun.average_loop_seconds) }}</strong></p><p><small>养护</small><strong>{{ latestRun.repair_sessions }} 次手入</strong></p></div>
            <p class="latest-upkeep">加速符 {{ latestRun.speedups }} 枚 · 补刀装 {{ latestRun.equipment_restores }} 次<span v-if="attributedStats(latestRun)"> · 已确认 {{ attributedStats(latestRun) }}</span></p>
            <details v-if="latestRun.average_loop_seconds" class="latest-estimator"><summary>估算挂机收益</summary><div class="run-estimator"><div><small>平均速度</small><b>{{ loopTime(latestRun.average_loop_seconds) }}</b></div><div class="estimate-result"><small>预计完成</small><b>≈ {{ estimatedLoops(latestRun) }} 圈</b></div><div class="estimate-control"><small>预计收益</small><label>挂机时间 <span v-if="!customEstimate">{{ estimateHours }} 小时</span><input v-else v-model.number="customHours" type="number" min="0.5" step="0.5" aria-label="自定义挂机小时数" @input="updateCustom"></label></div><nav aria-label="预计挂机时间"><button v-for="hour in [1, 6, 8]" :key="hour" type="button" :class="{ active: !customEstimate && estimateHours === hour }" @click="chooseHours(hour)">{{ hour }}小时</button><button type="button" :class="{ active: customEstimate }" @click="chooseCustom">自定义</button></nav></div></details>
          </template>
          <p v-else class="report-empty">完成一轮挂机后，这里会展示用时、圈速和养护。</p>
        </section>
        <section class="top-sorties">
          <header><div><span>主力玩法</span><h3>{{ rangeLabel }}出阵排行</h3></div><button type="button" class="secondary" @click="reportView = 'records'">查看全部</button></header>
          <ol v-if="topSorties.length"><li v-for="(item, index) in topSorties" :key="item.label"><i>{{ index + 1 }}</i><span><b>{{ item.label }}</b><small>{{ item.detail || '确认完成' }}</small></span><strong>{{ item.count.toLocaleString() }} 圈</strong></li></ol>
          <p v-else class="report-empty">这段时间还没有完成的出阵。</p>
        </section>
      </div>
      <section class="battle-recent">
        <header><div><span>最新动态</span><h3>最近发生</h3></div><button type="button" class="secondary" @click="reportView = 'records'">打开完整时间线</button></header>
        <div v-if="groupedActivityEvents.length" class="recent-strip"><article v-for="item in groupedActivityEvents.slice(0, 4)" :key="item.id"><time>{{ eventTime(item.ts) }}</time><strong>{{ activityTitle(item) }}</strong><p>{{ activityDetail(item) }}</p></article></div>
        <p v-else class="report-empty">这个时间段还没有完成的主要活动。</p>
      </section>
    </template>
    <section v-if="reportView === 'ledger'" class="resource-ledger" :class="{ loading }">
      <header><div><h3>这段时间家底变了多少</h3><p>按时间范围内第一次和最后一次库存读数计算</p></div><span class="ledger-confidence" :class="confidence.level"><b>{{ confidence.label }}</b>{{ confidence.detail }}</span></header>
      <div class="resource-ledger-grid">
        <article v-for="row in resourceRows" :key="row.name" :class="{ gain: row.delta != null && row.delta > 0, loss: row.delta != null && row.delta < 0 }">
          <small>{{ row.name }}</small><strong>{{ signed(row.delta) }}</strong><span v-if="row.current != null">当前 {{ row.current.toLocaleString() }}</span><span v-else>尚未观察到</span>
        </article>
      </div>
      <p class="fox-summary"><b>狐之助小结</b>{{ foxSummary }}</p>
    </section>
    <section v-if="reportView === 'ledger'" class="ledger-attribution">
      <header><div><h3>这笔账是怎么组成的</h3><p>库存净变化按证据拆开看；人工时段只说明上下文，不冒充狐狸收益。</p></div><small>{{ rangeLabel }}</small></header>
      <div class="ledger-attribution-grid">
        <article class="confirmed"><span>🦊 狐狸确认</span><strong>{{ attributedRows.length ? attributedRows.join(' · ') : '暂无确认收支' }}</strong><p>来自玩法结算、配方消耗或界面读数，可以算进脚本成绩。</p></article>
        <article class="human"><span>📝 审神者已说明</span><strong>{{ humanPeriodRows.length ? humanPeriodRows.join(' · ') : '暂无可对应的库存差值' }}</strong><p v-if="explainedGapEntries.length">{{ explainedGapEntries.length }} 段差值已有具体说明，数字已包含在库存总变化中。</p><p v-else>说明某段人工操作后，对应库存差值会显示在这里。</p></article>
        <article class="acknowledged"><span>👀 看过但未说明</span><strong>{{ acknowledgedRows.length ? acknowledgedRows.join(' · ') : '暂无' }}</strong><p>{{ acknowledgedGapEntries.length ? `${acknowledgedGapEntries.length} 段选择了暂不说明、记不清或没有其他操作。` : '没有仅留档、未提供原因的差值。' }}</p></article>
        <article class="unknown"><span>？ 仍未说明</span><strong>{{ unexplainedRows.length ? unexplainedRows.join(' · ') : '其余变化均已有上下文' }}</strong><p>库存里真实发生、但脚本证据和人工报备都还覆盖不到的部分。</p></article>
      </div>
      <div v-if="reportedGapEntries.length || proactiveReports.length" class="human-context-list">
        <article v-for="gap in reportedGapEntries" :key="gap.gap_key"><time>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}</time><span><b>{{ gap.reports.map(humanReportLabel).join('；') || '已报备' }}</b><small>{{ gapDelta(gap) }}</small></span></article>
        <article v-for="item in proactiveReports" :key="`proactive:${item.id}`"><time>{{ eventTime(item.occurred_at) }}</time><span><b>{{ humanReportLabel(item) }}</b><small>主动报备 · 暂无可对应的库存差值</small></span></article>
      </div>
    </section>
    <section v-if="reportView === 'ledger'" class="resource-trend">
      <header><div><h3>本丸收支</h3><p>柱高是当日库存净变化，柱内颜色表示能够确认的来源</p></div><nav aria-label="选择资源"><button v-for="name in resourceNames" :key="name" type="button" :class="{ active: selectedResource === name }" @click="selectedResource = name">{{ name }}</button></nav></header>
      <div class="chart-legend"><span><i class="attributed"></i>狐狸确认</span><span><i class="reported"></i>审神者已说明</span><span><i class="unattributed"></i>仍未说明</span><small v-if="!selectedAttributions.length">当前范围没有已确认的{{ selectedResource }}来源</small></div>
      <div class="resource-chart" :class="{ empty: !hasChartData }" :style="{ gridTemplateColumns: `repeat(${chartBars.length}, minmax(34px, 1fr))` }">
        <div class="chart-zero" aria-hidden="true"></div>
        <div v-for="bar in chartBars" :key="bar.label" class="chart-column" :title="bar.value == null ? `${bar.label}：读数不足` : `${bar.label}：${selectedResource} ${signed(bar.value)}；狐狸确认 ${signed(bar.attributed)}；审神者已说明 ${signed(bar.reported)}；仍未说明 ${signed(bar.unattributed)}；${bar.observations} 次观察`">
          <span class="chart-value">{{ bar.value == null ? '' : signed(bar.value) }}</span>
          <span v-if="bar.value != null" class="chart-stack" :class="[bar.value >= 0 ? 'positive' : 'negative', { mixed: bar.mixed }]" :style="{ height: `${bar.height}px` }">
            <i v-if="bar.attributed" class="attributed" :style="{ flexGrow: Math.abs(bar.attributed) }"></i>
            <i v-if="bar.reported" class="reported" :style="{ flexGrow: Math.abs(bar.reported) }"></i>
            <i v-if="bar.unattributed" class="unattributed" :style="{ flexGrow: Math.abs(bar.unattributed) }"></i>
          </span>
          <small>{{ bar.label }}</small>
        </div>
        <p v-if="loading">正在整理这段时间的收支……</p>
        <p v-else-if="!hasChartData">同一时间段至少需要两次读数，狐之助再攒一会儿账。</p>
      </div>
    </section>
    <section v-if="reportView === 'ledger' && unreportedGaps.length" class="inventory-gap-panel" aria-label="库存差值提醒">
      <div v-for="gap in unreportedGaps" :key="gap.gap_key" class="inventory-gap-alert"><div><strong>🦊 上次任务和这次开工之间，家底对不上啦</strong><p>{{ gapDelta(gap) }}</p><small>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}。这段差值单独留档，不会算进任何一轮挂机收益。</small></div><button type="button" class="secondary" @click="openGapReport(gap)">这期间做过什么？</button><button type="button" @click="skipGap(gap)">不想说，记差值就好</button></div>
      <form v-if="reportGap" @submit.prevent="saveHumanReport(false)">
        <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
        <fieldset><legend>这个时间段你做过什么？</legend><button v-for="value in [...humanActivities, '记不清了', '没有其他操作']" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
        <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" placeholder="可选，不用写具体资源数字"></label>
        <p>说明只给这段差值加一个上下文，不会改写狐狸账或库存账。</p><button type="submit" class="primary" :disabled="reportSaving || (!reportForm.activities.length && !reportForm.note.trim())">{{ reportSaving ? '记录中……' : '记下来' }}</button>
      </form>
    </section>
    <section v-if="reportView === 'ledger'" class="human-report-panel">
      <header><div><h3>📝 补充人工操作</h3><small>报备会回到上方“账目构成”中，与对应库存差值放在一起看。</small></div><button type="button" class="secondary" @click="openProactiveReport">{{ reportMode === 'proactive' ? '收起' : '主动报备一下' }}</button></header>
      <form v-if="reportMode === 'proactive'" @submit.prevent="saveHumanReport(false)">
        <label>大概时间<input v-model="reportForm.occurred_at" type="datetime-local"></label>
        <fieldset><legend>想给まあ丸报备什么？</legend><button v-for="value in humanActivities" :key="value" type="button" :class="{ active: reportForm.activities.includes(value) }" @click="toggleReportActivity(value)">{{ value }}</button></fieldset>
        <label class="human-report-note">补充说明<input v-model="reportForm.note" maxlength="300" placeholder="可选，不用写具体资源数字"></label>
        <p>报备只作为差值的上下文，不会改写狐狸账或库存账。</p><button type="submit" class="primary" :disabled="reportSaving || (!reportForm.activities.length && !reportForm.note.trim())">{{ reportSaving ? '记录中……' : '记下来' }}</button>
      </form>
      <details v-if="humanReports.length"><summary>查看已有报备（{{ humanReports.length }}）</summary><ul><li v-for="item in humanReports.slice(0, 20)" :key="item.id"><time>{{ eventTime(item.occurred_at) }}</time><span><b>{{ item.activities.join('、') }}</b>{{ item.note }}</span><button type="button" aria-label="删除这条报备" @click="removeHumanReport(item)">×</button></li></ul></details>
    </section>
    <template v-if="reportView === 'records'">
      <section class="records-head">
        <div><span>{{ rangeLabel }}</span><h3>最近的挂机与活动，都能往下追到发生了什么</h3><p>这里最多展示 30 轮挂机和 1000 条事件；更早记录不会在本页无限累积。</p></div>
        <SegmentedControl :model-value="recordView" :items="recordViewItems" label="记录类型" @update:model-value="chooseRecordView" />
      </section>
      <section v-if="recordView === 'runs'" class="run-history">
        <header><div><h3>⛏️ 挂机轮次</h3><small>只列有出阵圈数的任务；其他日课步骤请看活动时间线</small></div><span>最近 {{ runs.length }} / 最多 30 轮</span></header>
        <div v-if="runs.length" class="run-history-list">
          <details v-for="(run, index) in runs" :key="run.run_id" :open="index === 0">
            <summary><time>{{ eventTime(run.started_at) }}</time><span><b>{{ runTitle(run) }}</b><small>{{ elapsedTime(runElapsedSeconds(run)) }} · {{ loopTime(run.average_loop_seconds) }}</small></span><span class="run-cost">手入 {{ run.repair_sessions }} · 符 {{ run.speedups }} · 刀装 {{ run.equipment_restores }}</span><em>{{ attributedStats(run) || deltaStats(run) || '查看详情' }}</em></summary>
            <div class="run-evidence">
              <div class="run-upkeep" aria-label="本轮养护"><small class="ledger-label">🦊 狐狸账</small><span>🩹 手入 <b>{{ run.repair_sessions }}</b> 次</span><span>⚡ 加速符 <b>{{ run.speedups }}</b> 枚</span><span>🛡️ 补刀装 <b>{{ run.equipment_restores }}</b> 次</span></div>
              <p v-if="attributedStats(run)" class="run-delta"><small>🦊 已确认收支 <em>{{ run.resource_change_count }} 笔</em></small>{{ attributedStats(run) }}<span>来自本轮玩法的逐项记录，不依赖库存快照</span></p>
              <p v-if="observedInventory(run)" class="run-delta"><small>👀 途中看到的库存 <em>{{ run.inventory_observation_count }} 次观察</em></small>{{ observedInventory(run) }}<span>只表示最后一次读数，不作为本轮收益</span></p>
              <p v-if="deltaStats(run)" class="run-delta"><small>📦 库存变化 <em v-if="run.after_snapshot_source === 'manual_attach'">手动补盘</em><em v-else-if="run.after_snapshot_source === 'auto_science'">🧪小判实验估算</em></small>{{ deltaStats(run) }}<span v-if="kobanPerHourLabel(run)">· 小判约 {{ kobanPerHourLabel(run) }} / 小时</span><span v-if="kobanPerFloorLabel(run)">· 平均每层 {{ kobanPerFloorLabel(run) }}</span></p>
              <p v-else-if="run.has_resource_comparison" class="run-delta"><small>📦 库存账</small>本轮资源无变化</p>
              <div v-else class="run-inventory-missing"><small v-if="canAttachInventory(run)">收工盘点没有完成。先在首页运行“库存快照”，再把最近结果补到这轮。<strong>仅适合挂机结束后没有其他操作污染的数据。</strong></small><small v-else-if="run.has_before_snapshot && !run.has_after_snapshot">这是较早的挂机记录，不能用现在的库存回填。</small><small v-else-if="attributedStats(run)">这轮没有完整的库存净变化；上方已确认收支仍然有效。</small><small v-else>这轮没有完整库存净变化，也没有记录到资源流水。</small><button v-if="canAttachInventory(run)" type="button" class="secondary" :disabled="attachingRun === run.run_id" @click="attachInventory(run)">{{ attachingRun === run.run_id ? '正在补盘……' : '补上最近盘点' }}</button><em v-if="inventoryNotice[run.run_id]">{{ inventoryNotice[run.run_id] }}</em></div>
            </div>
          </details>
        </div>
        <p v-else class="report-empty">这个时间段还没有挂机记录。</p>
      </section>
      <div v-else class="records-timeline">
        <aside class="records-sorties"><header><h3>⚔️ 出阵分布</h3><small>{{ sortieCount.toLocaleString() }} 圈</small></header><div v-if="sortieGroups.length"><p v-for="item in sortieGroups" :key="`${item.label}:${item.detail}`"><span><b>{{ item.label }}</b><small>{{ item.detail || '确认完成' }}</small></span><strong>{{ item.count }} 圈</strong></p></div><p v-else class="report-empty">暂无出阵。</p></aside>
        <section class="report-events timeline-panel">
          <header><div><h3>{{ timelineKind === 'activity' ? '玩家活动' : '系统观察' }}</h3><small>{{ timelineKind === 'activity' ? '相邻的同类活动已经合并，仍可展开原始明细' : '库存读数、未确认状态与恢复记录，不混入成绩' }}</small></div><span>最近 {{ Math.min(timelineLimit, activeTimeline.length) }} / {{ activeTimeline.length }} 组</span></header>
          <SegmentedControl class="timeline-kinds" :model-value="timelineKind" :items="timelineKindItems" label="时间线内容" @update:model-value="chooseTimelineSegment" />
          <div v-if="timelineKind === 'activity' && groupedActivityEvents.length" class="event-list activity-feed"><article v-for="item in groupedActivityEvents.slice(0, timelineLimit)" :key="item.id"><time>{{ eventTime(item.ts) }}</time><i aria-hidden="true"></i><div><strong>{{ activityTitle(item) }}</strong><p>{{ activityDetail(item) }}</p><details v-if="item.items.length > 1"><summary>查看 {{ item.items.length }} 条明细</summary><p v-for="child in item.items" :key="child.id"><time>{{ eventTime(child.ts) }}</time>{{ instanceDetail(child) }}</p></details></div></article></div>
          <div v-else-if="timelineKind === 'system' && groupedSystemEvents.length" class="system-timeline"><article v-for="item in groupedSystemEvents.slice(0, timelineLimit)" :key="item.id"><time>{{ eventTime(item.ts) }}</time><span><strong>{{ systemTitle(item) }}</strong><small>{{ systemDetail(item) }}</small></span></article></div>
          <p v-else class="report-empty">这个时间段还没有{{ timelineKind === 'activity' ? '完成的主要活动' : '系统观察' }}。</p>
          <button v-if="activeTimeline.length > timelineLimit" type="button" class="timeline-more secondary" @click="timelineLimit += 20">再看 20 组较早记录</button>
        </section>
      </div>
    </template>
    </div>
  </section>
</template>
