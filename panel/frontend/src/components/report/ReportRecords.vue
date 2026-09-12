<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import DatePicker from 'primevue/datepicker'
import Timeline from 'primevue/timeline'
import { api } from '../../api'
import type { ManualSession } from '../../types'
import { attributedStats, deltaStats, elapsedTime, eventTime, kobanPerFloorLabel, kobanPerHourLabel, loopTime, obtainSourceLabel, runElapsedSeconds, runStatusLabel, runTitle, shanghaiDate } from './reportModel'

const props = defineProps<{
  events: any[]
  runs: any[]
  manualSessions: ManualSession[]
  selectedDate: string
  highlightRunId?: string
  hasMoreEvents: boolean
  hasMoreRuns: boolean
  loading: boolean
  loadingOlder: boolean
}>()

const emit = defineEmits<{ 'load-more': []; refresh: []; 'select-date': [date: string] }>()

const timelineLimit = ref(20)
const deletingManual = ref(0)

const eventNames: Record<string, string> = {
  'game_update.detected': '发现游戏更新', 'game_update.recovered': '游戏更新后恢复',
  'network.recovered': '断线自动恢复',
  'osaka.floor_completed': '大阪城完成一圈', 'edocastle.run_completed': '江户城完成一圈', 'hanafuda.run_completed': '秘宝之里完成一圈', 'sortie.completed': '出阵完成',
  'sortie.retreated_before_boss': '王点前撤退完成', 'sortie.interrupted': '出阵中断',
  'raid.round_completed': '联队战完成一圈', 'pumpkin.sortie_completed': '南瓜活动出阵完成',
  'pumpkin.board_completed': '南瓜活动完成一块板子', 'pumpkin.token_used': '南瓜活动使用更新令牌',
  'repair.queued': '刀剑进入手入', 'repair.skipped': '跳过手入', 'repair.session_completed': '手入完成',
  'repair.summary': '手入小结',
  'practice.result': '演练结束', 'pumpkin.sword_obtained': '南瓜活动获得刀剑',
  'forge.started': '开始锻刀', 'forge.collected': '领取锻刀结果',
  'expedition.dispatched': '远征派遣成功', 'expedition.settled': '远征结算',
  'task_rewards.claimed': '领取任务奖励', 'task_rewards.none': '任务奖励已清空',
  'task_rewards.unconfirmed': '任务奖励状态未确认', 'inventory.captured': '保存库存快照',
  'sword.obtained': '刀剑男士来本丸', 'naihanka.gains': '内番收工',
  'dismantle.completed': '刀解完成', 'equipment.restored': '恢复刀装',
  'ticket.refilled': '补充活动手形', 'yosari.ticket_refilled': '补充异去提灯',
  'yosari.fragments': '记录异去碎片', 'sword_inventory.completed': '刀帐盘点完成',
}

function hanafudaDifficulty(value: unknown) {
  return ({ 1: '易', 2: '普', 3: '难', 4: '超难' } as Record<number, string>)[Number(value)] || '未指定'
}

function isWin(payload: any) {
  const value = String(payload?.result ?? payload?.outcome ?? '').toLowerCase()
  return value.includes('胜') || value.startsWith('win') || value === 'won'
}
function isLoss(payload: any) {
  const value = String(payload?.result ?? payload?.outcome ?? '').toLowerCase()
  return value.includes('败') || value.startsWith('lose') || value === 'lost'
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
  if (item.event_type === 'edocastle.run_completed') return `带回 ${Number(p.keys || 0).toLocaleString()} 把钥匙`
  if (item.event_type === 'hanafuda.run_completed') {
    const tama = p.tama == null ? '玉数没读出来' : `带回 ${Number(p.tama).toLocaleString()} 个玉`
    return `难度·${hanafudaDifficulty(p.difficulty)} · 部队${p.team_no ?? '未指定'} · ${tama}`
  }
  if (item.event_type === 'sortie.completed') return `${p.mode === 'yosari' ? '异去' : '合战场'} ${p.chapter}-${p.map_no} · 完成 1 圈`
  if (item.event_type === 'sortie.retreated_before_boss') return `合战场 ${p.chapter}-${p.map_no} · 王点前主动返回本丸`
  if (item.event_type === 'sortie.interrupted') return `${p.mode === 'yosari' ? '异去' : '合战场'} ${p.chapter}-${p.map_no} · 中断（${interruptReasonLabel(p.interrupt_reason)}）`
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
  if (item.event_type === 'sword.obtained') {
    const src = obtainSourceLabel(p.source)
    return `【${p.name || '认不出是谁'}】${src ? ` · ${src}` : ''}`
  }
  if (item.event_type === 'naihanka.gains') {
    const gains = p.gains || []
    if (!gains.length) return '收工了，没人 +1（都喂满金框了？）'
    const head = p.source === 'diff' ? '数值比对发现' : '报告屏确认'
    return `${head}：${gains.map((g: any) => `【${g.name}】${g.stat}+1`).join('、')}`
  }
  if (item.event_type === 'dismantle.completed') return p.sword ? `刀解【${p.sword}】` : '刀解结果已记录'
  if (item.event_type === 'equipment.restored') return `恢复第 ${p.record_no ?? '？'} 套编队记录的刀装`
  if (item.event_type === 'ticket.refilled') return `${p.source || '活动'} · ${p.ticket_price ? `使用 ${Number(p.ticket_price).toLocaleString()} 小判补充 1 枚` : '补充 1 枚'}`
  if (item.event_type === 'yosari.ticket_refilled') return `${p.item || '归城提灯'}补充完成${Number.isFinite(Number(p.delta)) ? ` · 小判 ${Number(p.delta).toLocaleString()}` : ''}`
  if (item.event_type === 'yosari.fragments') {
    const gained = Object.values(p.gained || {}).reduce((sum: number, value: any) => sum + Number(value || 0), 0)
    return gained ? `${p.map_no ?? '？'}图 · 本圈新增 ${gained} 枚碎片` : `${p.map_no ?? '？'}图 · 碎片数量已记录`
  }
  if (item.event_type === 'sword_inventory.completed') {
    const owned = p.owned == null ? '' : `（所持 ${p.owned}${p.missing ? `，缺 ${p.missing}` : ''}）`
    return `认出 ${p.count ?? '？'} 把刀${owned}`
  }
  if (item.event_type === 'network.recovered') {
    return p.mode === 'resumed' ? '断线后接回战斗，继续干活'
      : p.mode === 'home' ? '断线重登后回到本丸，那一仗作废' : '断线后自动恢复'
  }
  return '本丸记录'
}
function activityTitle(item: any) {
  const count = item.items?.length || 1
  if (item.event_type === 'sortie.completed') return `完成出阵 ${count} 次`
  if (item.event_type === 'sortie.retreated_before_boss') return `王点前撤退 ${count} 次`
  if (item.event_type === 'osaka.floor_completed') return `大阪城完成 ${count} 圈`
  if (item.event_type === 'edocastle.run_completed') return `江户城完成 ${count} 圈`
  if (item.event_type === 'hanafuda.run_completed') return `秘宝之里完成 ${count} 圈`
  if (item.event_type === 'raid.round_completed') return `联队战完成 ${count} 圈`
  if (item.event_type === 'practice.result') return `完成演练 ${count} 场`
  if (item.event_type === 'forge.collected') return `领取锻刀结果 ${count} 次`
  if (item.event_type === 'forge.started') return `开始锻刀 ${count} 炉`
  if (item.event_type === 'expedition.dispatched') return `派遣远征 ${count} 队`
  if (item.event_type === 'expedition.settled') return `领取远征奖励 ${count} 份`
  if (item.event_type === 'task_rewards.claimed') return `领取任务奖励 ${count} 类`
  if (item.event_type === 'task_rewards.none') return `检查任务奖励 ${count} 类`
  if (item.event_type === 'sword.obtained') return `刀剑男士来本丸 ${count} 位`
  if (item.event_type === 'naihanka.gains') return `内番收工 ${count} 次`
  if (item.event_type === 'repair.summary') return repairCount(item.payload) ? `手入 ${repairCount(item.payload)} 振` : '检查手入名单'
  if (item.event_type === 'equipment.restored') return `恢复刀装 ${count} 次`
  return eventTitle(item)
}
function activityDetail(item: any) {
  const items = item.items || [item], p = item.payload || {}
  if (item.event_type === 'sortie.completed') return `${p.mode === 'yosari' ? '异去' : '合战场'} ${p.chapter}-${p.map_no} · 共 ${items.length} 圈`
  if (item.event_type === 'sortie.retreated_before_boss') return `合战场 ${p.chapter}-${p.map_no} · 均在王点前返回`
  if (item.event_type === 'osaka.floor_completed') {
    const koban = props.events.find((entry: any) => entry.run_id === item.run_id && entry.event_type === 'osaka.koban_session')?.payload?.delta
    return `${p.selected_floor ?? '？'}F · 共 ${items.length} 圈${Number.isFinite(Number(koban)) ? ` · 小判 ${Number(koban) > 0 ? '+' : ''}${Number(koban).toLocaleString()}` : ''}`
  }
  if (item.event_type === 'edocastle.run_completed') {
    const keys = items.reduce((total: number, entry: any) => total + Number(entry.payload?.keys || 0), 0)
    return `共带回 ${keys.toLocaleString()} 把钥匙`
  }
  if (item.event_type === 'hanafuda.run_completed') {
    const known = items.filter((entry: any) => entry.payload?.tama != null)
    const tama = known.reduce((total: number, entry: any) => total + Number(entry.payload.tama || 0), 0)
    return `难度·${hanafudaDifficulty(p.difficulty)} · 部队${p.team_no ?? '未指定'} · ${known.length === items.length ? `共带回 ${tama.toLocaleString()} 个玉` : `${known.length}/${items.length} 圈读到玉数，共 ${tama.toLocaleString()} 个`}`
  }
  if (item.event_type === 'practice.result') {
    const wins = items.filter((entry: any) => isWin(entry.payload)).length
    const losses = items.filter((entry: any) => isLoss(entry.payload)).length
    return `${wins} 胜${losses ? ` · ${losses} 负` : ''} · ${items.map((entry: any) => entry.payload?.result).filter(Boolean).join(' / ')}`
  }
  if (item.event_type === 'forge.collected') {
    const names = items.map((entry: any) => entry.payload?.name).filter(Boolean)
    return names.length ? names.map((name: string) => `【${name}】`).join('、') : `共 ${items.length} 炉（没认出是谁）`
  }
  if (item.event_type === 'forge.started') {
    const durations = items.map((entry: any) => entry.payload?.duration).filter(Boolean)
    return `已确认点火 · ${items.length} 炉${durations.length ? `（${durations.join('、')}）` : ''}`
  }
  if (item.event_type === 'expedition.dispatched') return items.map((entry: any) => `部队${entry.payload?.team_no ?? '？'} ${entry.payload?.map_name || entry.payload?.map_code || ''}`).join(' · ')
  if (item.event_type === 'expedition.settled') return items.map((entry: any) => entry.payload?.map_name || entry.payload?.header).filter(Boolean).join(' · ') || '奖励已领取'
  if (item.event_type === 'task_rewards.claimed' || item.event_type === 'task_rewards.none') return items.map((entry: any) => entry.payload?.tab || '当前页').join(' / ')
  if (item.event_type === 'sword.obtained') return items.map((entry: any) => `【${entry.payload?.name || '认不出是谁'}】`).join('、')
  return eventDetail(item)
}
function instanceDetail(item: any) {
  const p = item.payload || {}
  if (item.event_type === 'osaka.floor_completed' && p.completed != null) return `第 ${p.completed} 圈 · ${p.selected_floor == null ? '未指定层数' : `${p.selected_floor}F`}`
  if (item.event_type === 'edocastle.run_completed') return `第 ${p.run_no ?? '？'} 圈 · ${Number(p.keys || 0).toLocaleString()} 把钥匙`
  if (item.event_type === 'hanafuda.run_completed') return `第 ${p.run_no ?? '？'} 圈 · ${p.tama == null ? '玉数没读出来' : `${Number(p.tama).toLocaleString()} 个玉`}`
  if (item.event_type === 'pumpkin.sortie_completed' && p.sequence != null) return `第 ${p.sequence} 次出阵`
  if (item.event_type === 'forge.collected') {
    const parts = []
    if (p.name) parts.push(`【${p.name}】`)
    if (p.duration) parts.push(`${p.duration} 炉`)
    return parts.length ? parts.join(' · ') : '没认出是谁'
  }
  if (item.event_type === 'forge.started' && (p.duration || p.slot != null)) {
    return [p.duration, p.slot != null ? `炉位 ${p.slot}` : ''].filter(Boolean).join(' · ')
  }
  return eventDetail(item)
}

// ---- 逐圈事实：服务端已把 loop_started 和结束事件配好对 ----
const sortieEventTypes = new Set(['sortie.loop_started', 'sortie.completed', 'sortie.retreated_before_boss', 'sortie.interrupted'])
function runLoopRecords(run: any) {
  return Array.isArray(run?.loop_records) ? run.loop_records : []
}
const loopModeNames: Record<string, string> = { yosari: '异去', sortie: '合战场' }
const interruptReasonNames: Record<string, string> = {
  auto_march_stopped: '自动行军停止', heavy_injury_warning: '重伤行军警告',
  field_injury_threshold: '伤势达到手入阈值', monitor_timeout: '监控超时',
  heavy_injury_denied_return_failed: '重伤点否后没能返回本丸',
  auto_march_stopped_return_failed: '自动行军停止后没能返回本丸',
  field_injury_return_failed: '伤势返回本丸失败',
}
function interruptReasonLabel(reason: unknown) {
  const key = String(reason || '')
  return interruptReasonNames[key] || (key ? `原因 ${key}` : '原因未记录')
}
const dropReasonNames: Record<string, string> = {
  auto_march_skips_obtain_animation: '委托行军跳过获得动画',
  observation_lost: '观察中断', recognizer_error: '认人流程异常',
}
function loopOutcomeLabel(loop: any) {
  if (loop.end_type === 'sortie.completed') return '完成'
  if (loop.end_type === 'sortie.retreated_before_boss') return '王点前撤退'
  if (loop.end_type === 'sortie.interrupted') return '中断'
  return '结果未知'
}
function loopSeconds(seconds: unknown) {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value <= 0) return ''
  const total = Math.round(value)  // 先舍入再拆：59.6 是 1分00秒，不是 0分00秒
  return `${Math.floor(total / 60)}分${String(total % 60).padStart(2, '0')}秒`
}
function loopHeadline(loop: any) {
  const place = `${loopModeNames[loop.mode] || loop.mode || '出阵'} ${loop.chapter}-${loop.map_no}`
  const no = loop.sequence == null ? '' : ` · 第 ${loop.sequence} 圈`
  const retry = Number(loop.attempt) > 1 ? ` · 第 ${Number(loop.attempt)} 次出发` : ''
  return `${place}${no}${retry}`
}
function loopDetail(loop: any) {
  const parts = [loopOutcomeLabel(loop)]
  const seconds = loopSeconds(loop.duration_seconds)
  parts.push(seconds ? `耗时 ${seconds}` : '耗时没读出来')
  parts.push(loop.battle_count != null ? `${loop.battle_count} 场战斗` : '战斗数没读出来')
  if (loop.march_mode === 'delegated') parts.push('委托行军')
  else if (loop.march_mode === 'script') parts.push('脚本行军')
  if (loop.end_type === 'sortie.interrupted' && loop.interrupt_reason) parts.push(interruptReasonLabel(loop.interrupt_reason))
  if (loop.drop_observation === 'recognized') parts.push(loop.drops_recognized ? `掉落已识别 ${loop.drops_recognized} 把` : '掉落已识别')
  else if (loop.drop_observation === 'confirmed_none') parts.push('确认无掉落')
  else if (loop.drop_observation === 'not_observed') parts.push(`未观察掉落（${dropReasonNames[loop.drop_observation_reason] || '原因未记录'}）`)
  else parts.push('未观察掉落（没有观察数据）')
  return parts.join(' · ')
}

const timelineEvents = computed(() => {
  const visible: any[] = []
  const repairs = new Map<string, any>()
  // loop_started 是逐圈事实的起点标记，成绩单按配对后的逐圈明细展示，
  // 绝不裸奔成「本丸记录」；结束事件照常单独可见（跨日游离行用）。
  const hidden = new Set(['team_record.saved', 'inventory.peek', 'osaka.koban_session', 'sortie.loop_started'])
  for (const item of props.events) {
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
  'network.recovered',
])
function activityGroupKey(item: any) {
  const p = item.payload || {}, day = shanghaiDate(Number(item.ts))
  const run = item.run_id || `minute:${Math.floor(item.ts / 300)}`
  // 同一轮可能跨零点；先按上海日期切开，避免第二天的成绩被吞回开工日。
  const prefix = `${day}:${run}`
  if (item.event_type === 'sortie.completed') return `${prefix}:sortie:${p.mode}:${p.chapter}:${p.map_no}`
  if (item.event_type === 'sortie.retreated_before_boss') return `${prefix}:retreat:${p.chapter}:${p.map_no}`
  if (item.event_type === 'osaka.floor_completed') return `${prefix}:osaka:${p.selected_floor}`
  if (item.event_type === 'edocastle.run_completed') return `${prefix}:edocastle`
  if (item.event_type === 'practice.result') return `${prefix}:practice`
  if (item.event_type.startsWith('task_rewards.')) return `${prefix}:${item.event_type}`
  if (['forge.started', 'forge.collected', 'expedition.dispatched', 'expedition.settled'].includes(item.event_type)) return `${prefix}:${item.event_type}`
  return `${prefix}:${item.event_type}:${eventDetail(item)}`
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
const allRecords = computed(() => {
  const runsById = new Map(props.runs.filter(run => run.run_id).map(run => [run.run_id, run]))
  return [
    ...props.runs.map(run => ({ kind: 'run' as const, ts: Number(run.started_at), run })),
    ...props.manualSessions.map(session => ({ kind: 'manual' as const, ts: Number(session.started_at), session })),
    ...groupedActivityEvents.value
      .filter(item => {
        if (!item.run_id) return true
        const run = runsById.get(item.run_id)
        // 开工日的活动收进任务卡；跨日部分在实际发生日单独出现。
        return !run || shanghaiDate(Number(run.started_at)) !== shanghaiDate(Number(item.ts))
      })
      .map(item => ({ kind: 'activity' as const, ts: Number(item.ts), item })),
  ].sort((a, b) => b.ts - a.ts)
})
const selectedRecords = computed(() => allRecords.value.filter(entry => shanghaiDate(entry.ts) === props.selectedDate))
const visibleRecords = computed(() => {
  const visible = selectedRecords.value.slice(0, timelineLimit.value)
  if (!props.highlightRunId || visible.some(entry => entry.kind === 'run' && entry.run.run_id === props.highlightRunId)) return visible
  const highlighted = selectedRecords.value.find(entry => entry.kind === 'run' && entry.run.run_id === props.highlightRunId)
  return highlighted ? [...visible, highlighted].sort((left, right) => right.ts - left.ts) : visible
})
const selectedRunCount = computed(() => selectedRecords.value.filter(entry => entry.kind === 'run').length)
const selectedManualCount = computed(() => selectedRecords.value.filter(entry => entry.kind === 'manual').length)
const selectedActivityCount = computed(() => selectedRecords.value.filter(entry => entry.kind === 'activity').length)
const recordCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const entry of allRecords.value) {
    const date = shanghaiDate(entry.ts)
    counts.set(date, (counts.get(date) || 0) + 1)
  }
  return counts
})
const calendarDate = computed({
  get: () => new Date(`${props.selectedDate}T12:00:00+08:00`),
  set: (value: Date | null) => value && emit('select-date', shanghaiDate(value.getTime() / 1000)),
})
const minDate = computed(() => new Date((Date.now() / 1000 - 365 * 86400) * 1000))
const maxDate = computed(() => new Date())
const selectedDateLabel = computed(() => new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'long',
}).format(new Date(`${props.selectedDate}T12:00:00+08:00`)))

function calendarDayKey(date: { year: number; month: number; day: number }): string {
  return `${date.year}-${String(date.month + 1).padStart(2, '0')}-${String(date.day).padStart(2, '0')}`
}
function recordKey(entry: any): string {
  if (entry.kind === 'run') return `run:${entry.run.run_id}`
  if (entry.kind === 'manual') return `manual:${entry.session.id}`
  return `event:${entry.item.id}`
}
function recordTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
function runActivities(run: any) {
  const startDay = shanghaiDate(Number(run.started_at))
  return groupedActivityEvents.value.filter(item => (
    item.run_id && item.run_id === run.run_id && shanghaiDate(Number(item.ts)) === startDay
    // 逐圈明细已接管出阵圈事件的展示，任务卡里不再重复列一遍
    && !(runLoopRecords(run).length && sortieEventTypes.has(item.event_type))
  ))
}
function runRepairTotal(run: any) {
  const activityTotal = runActivities(run).filter(item => item.event_type === 'repair.summary')
    .reduce((total, item) => total + repairCount(item.payload), 0)
  return Math.max(Number(run.repair_sessions || 0), activityTotal)
}
function runSpeedupTotal(run: any) {
  const activityTotal = runActivities(run).filter(item => item.event_type === 'repair.summary')
    .reduce((total, item) => total + Number(item.payload?.speedups || item.payload?.queued?.filter((entry: any) => entry.speedup).length || 0), 0)
  return Math.max(Number(run.speedups || 0), activityTotal)
}
function runEquipmentTotal(run: any) {
  const activityTotal = runActivities(run).filter(item => item.event_type === 'equipment.restored')
    .reduce((total, item) => total + Number(item.items?.length || 1), 0)
  return Math.max(Number(run.equipment_restores || 0), activityTotal)
}
function hasUpkeep(run: any) { return Boolean(runRepairTotal(run) || runSpeedupTotal(run) || runEquipmentTotal(run)) }

async function deleteManualSession(session: ManualSession) {
  if (!window.confirm(`删掉这条“${session.activity} ${session.loops} 圈”的手动记录吗？`)) return
  deletingManual.value = session.id
  try {
    await api.deleteManualSession(session.id)
    emit('refresh')
  } catch (cause) {
    attachError.value = cause instanceof Error ? cause.message : '手动记录删除失败'
  } finally { deletingManual.value = 0 }
}

const deletingRun = ref('')
async function deleteRun(run: any) {
  if (!window.confirm(`删掉这条“${runTitle(run)}”的任务记录吗？它名下的成绩明细会一起消失。`)) return
  deletingRun.value = run.run_id
  try {
    await api.deleteRun(run.run_id)
    emit('refresh')
  } catch (cause) {
    attachError.value = cause instanceof Error ? cause.message : '任务记录删除失败'
  } finally { deletingRun.value = '' }
}

const attachingRun = ref('')
const inventoryNotice = ref<Record<string, string>>({})
const attachError = ref('')
const latestInventoriedRun = computed(() => props.runs.find(run => Number(run.loops) > 0 && run.has_before_snapshot))
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
    emit('refresh')
  } catch (cause) {
    inventoryNotice.value = { ...inventoryNotice.value, [run.run_id]: cause instanceof Error ? cause.message : '补盘失败' }
  } finally { attachingRun.value = '' }
}

const pendingBump = ref(false)
function showMoreRecords() {
  if (selectedRecords.value.length > timelineLimit.value) { timelineLimit.value += 20; return }
  pendingBump.value = true
  emit('load-more')
}
watch(() => [props.events.length, props.runs.length], () => {
  if (pendingBump.value) { timelineLimit.value += 20; pendingBump.value = false }
})
watch(() => props.selectedDate, () => { timelineLimit.value = 20 })
</script>

<template>
  <section class="records-browser">
    <aside class="records-calendar-panel">
      <header><h3>按日期查看</h3></header>
      <DatePicker v-model="calendarDate" class="records-calendar" inline :min-date="minDate" :max-date="maxDate" :show-other-months="false">
        <template #date="slotProps">
          <span class="calendar-day" :class="{ recorded: recordCounts.has(calendarDayKey(slotProps.date)) }">
            {{ slotProps.date.day }}<i v-if="recordCounts.has(calendarDayKey(slotProps.date))" aria-hidden="true" />
          </span>
        </template>
      </DatePicker>
      <DatePicker v-model="calendarDate" class="records-date-picker-mobile" :min-date="minDate" :max-date="maxDate" show-icon fluid date-format="yy年mm月dd日" />
    </aside>

    <section class="records-day">
      <header class="records-day-header">
        <div><small>{{ selectedDate }}</small><h3>{{ selectedDateLabel }}</h3></div>
        <p><b>{{ selectedRunCount }}</b> 次まあ丸任务<template v-if="selectedManualCount"> · 你手动 {{ selectedManualCount }} 段</template><template v-if="selectedActivityCount"> · {{ selectedActivityCount }} 条单独记录</template></p>
      </header>
      <p v-if="attachError" class="report-error">{{ attachError }}</p>
      <p v-if="loading" class="report-empty">狐之助正在翻这一天的档案……</p>
      <Timeline v-else-if="visibleRecords.length" :value="visibleRecords" align="left" class="day-timeline">
        <template #opposite="slotProps"><time>{{ recordTime(slotProps.item.ts) }}</time></template>
        <template #marker="slotProps"><span class="record-marker" :class="slotProps.item.kind">{{ slotProps.item.kind === 'run' ? '🦊' : slotProps.item.kind === 'manual' ? '你' : '·' }}</span></template>
        <template #content="slotProps">
          <details v-if="slotProps.item.kind === 'run'" :id="`run-${slotProps.item.run.run_id}`" :key="recordKey(slotProps.item)" class="record-run" :class="{ 'record-run-highlight': slotProps.item.run.run_id === highlightRunId }" :open="slotProps.item.run.run_id === highlightRunId">
            <summary><span><b>{{ runTitle(slotProps.item.run) }}</b><small>{{ runStatusLabel(slotProps.item.run) }} · {{ elapsedTime(runElapsedSeconds(slotProps.item.run)) }}<template v-if="slotProps.item.run.average_loop_seconds && slotProps.item.run.loop_pace_unified !== false"> · {{ loopTime(slotProps.item.run.average_loop_seconds) }}</template></small></span><em>{{ attributedStats(slotProps.item.run) || deltaStats(slotProps.item.run) || '查看详情' }}</em></summary>
            <div class="run-evidence">
              <p v-if="Number(slotProps.item.run.loops) > 0 && !hasUpkeep(slotProps.item.run)" class="run-upkeep-quiet">本轮无额外养护消耗</p>
              <div v-if="hasUpkeep(slotProps.item.run)" class="run-upkeep" aria-label="本轮养护"><span v-if="runRepairTotal(slotProps.item.run)">🩹 手入 <b>{{ runRepairTotal(slotProps.item.run) }}</b> 振</span><span v-if="runSpeedupTotal(slotProps.item.run)">⚡ 加速符 <b>{{ runSpeedupTotal(slotProps.item.run) }}</b> 枚</span><span v-if="runEquipmentTotal(slotProps.item.run)">🛡️ 补刀装 <b>{{ runEquipmentTotal(slotProps.item.run) }}</b> 次</span></div>
              <p v-if="attributedStats(slotProps.item.run)" class="run-delta"><small>🦊 已确认收支</small>{{ attributedStats(slotProps.item.run) }}</p>
              <p v-if="deltaStats(slotProps.item.run)" class="run-delta"><small>📦 库存变化</small>{{ deltaStats(slotProps.item.run) }}<span v-if="kobanPerHourLabel(slotProps.item.run)">· 小判约 {{ kobanPerHourLabel(slotProps.item.run) }} / 小时</span><span v-if="kobanPerFloorLabel(slotProps.item.run)">· 平均每层 {{ kobanPerFloorLabel(slotProps.item.run) }}</span></p>
              <div v-if="runLoopRecords(slotProps.item.run).length" class="run-activities run-loops"><p v-for="(loop, index) in runLoopRecords(slotProps.item.run)" :key="`loop-${index}`"><time>{{ recordTime(loop.ended_at || loop.started_at || 0) }}</time><span><b>{{ loopHeadline(loop) }}</b><small>{{ loopDetail(loop) }}</small></span></p></div>
              <div v-if="runActivities(slotProps.item.run).length" class="run-activities"><p v-for="item in runActivities(slotProps.item.run)" :key="item.id"><time>{{ recordTime(item.ts) }}</time><span><b>{{ activityTitle(item) }}</b><small>{{ activityDetail(item) }}</small></span></p></div>
              <p v-else-if="!attributedStats(slotProps.item.run) && !deltaStats(slotProps.item.run)" class="run-upkeep-quiet">这次任务没有额外成绩明细。</p>
              <div v-if="!slotProps.item.run.has_resource_comparison && canAttachInventory(slotProps.item.run)" class="run-inventory-missing"><small>收工盘点没有完成；仅可用挂机结束后、没有其他操作的库存快照补盘。</small><button type="button" class="secondary" :disabled="attachingRun === slotProps.item.run.run_id" @click="attachInventory(slotProps.item.run)">{{ attachingRun === slotProps.item.run.run_id ? '正在补盘……' : '补上最近盘点' }}</button><em v-if="inventoryNotice[slotProps.item.run.run_id]">{{ inventoryNotice[slotProps.item.run.run_id] }}</em></div>
              <div class="run-actions"><button type="button" class="run-delete" :disabled="deletingRun === slotProps.item.run.run_id" @click="deleteRun(slotProps.item.run)">{{ deletingRun === slotProps.item.run.run_id ? '删除中…' : '删除这条记录' }}</button></div>
            </div>
          </details>
          <article v-else-if="slotProps.item.kind === 'manual'" :key="recordKey(slotProps.item)" class="record-manual">
            <span><small>审神者手动</small><b>{{ slotProps.item.session.activity }} {{ slotProps.item.session.loops }} 圈</b><em>{{ elapsedTime(slotProps.item.session.duration_seconds) }} · {{ loopTime(slotProps.item.session.average_loop_seconds) }}</em><p v-if="slotProps.item.session.note">{{ slotProps.item.session.note }}</p></span>
            <button type="button" :disabled="deletingManual === slotProps.item.session.id" @click="deleteManualSession(slotProps.item.session)">{{ deletingManual === slotProps.item.session.id ? '删除中…' : '删除' }}</button>
          </article>
          <article v-else :key="recordKey(slotProps.item)" class="record-activity"><span><b>{{ activityTitle(slotProps.item.item) }}</b><small>{{ activityDetail(slotProps.item.item) }}</small></span><details v-if="slotProps.item.item.items.length > 1"><summary>查看 {{ slotProps.item.item.items.length }} 条明细</summary><p v-for="child in slotProps.item.item.items" :key="child.id"><time>{{ eventTime(child.ts) }}</time>{{ instanceDetail(child) }}</p></details></article>
        </template>
      </Timeline>
      <p v-else class="report-empty">这一天还没有完成的任务记录。</p>
      <button v-if="selectedRecords.length > timelineLimit || hasMoreRuns || hasMoreEvents" type="button" class="timeline-more secondary" :disabled="loadingOlder" @click="showMoreRecords">{{ loadingOlder ? '正在翻当天档案……' : '查看当天更早记录' }}</button>
    </section>
  </section>
</template>

<style scoped>
.records-browser { display: grid; grid-template-columns: 248px minmax(0, 1fr); gap: 12px; align-items: start; }
.records-calendar-panel, .records-day { min-width: 0; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; }
.records-calendar-panel { position: sticky; top: 0; padding: 14px; }
.records-calendar-panel header h3 { margin: 0; }
.records-date-picker-mobile { display: none; }
.records-day { padding: 0 16px 16px; }
.records-day-header { display: flex; justify-content: space-between; align-items: end; gap: 14px; padding: 14px 0 12px; border-bottom: 1px solid var(--paper-line); }
.records-day-header small { color: var(--ink-dim); }
.records-day-header h3, .records-day-header p { margin: 0; }
.records-day-header p { color: var(--ink-dim); font-size: 12px; }
.records-day-header p b { color: var(--fox-gold-deep); font-size: 18px; }
.calendar-day { position: relative; display: grid; width: 100%; height: 100%; place-items: center; }
.calendar-day i { position: absolute; right: 1px; bottom: 1px; width: 4px; height: 4px; border-radius: 50%; background: var(--fox-gold); }
.record-marker { display: grid; width: 28px; height: 28px; place-items: center; border: 2px solid var(--paper-card); border-radius: 50%; color: var(--ink-dim); background: var(--paper-panel); box-shadow: 0 0 0 1px var(--paper-line); font-size: 15px; }
.record-marker.run { color: var(--ink); background: var(--fox-gold-pale); box-shadow: 0 0 0 1px var(--fox-gold); }
.record-marker.manual { color: #315875; background: #e6eef4; box-shadow: 0 0 0 1px #7d9ab2; font-size: 11px; font-weight: 700; }
.record-run, .record-activity { min-width: 0; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 10px; }
.record-run-highlight { border-color: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 12%, transparent); }
.record-manual { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 11px 12px; background: color-mix(in srgb, #e6eef4 70%, var(--paper)); border: 1px solid #a9bccb; border-radius: 10px; }
.record-manual > span { display: grid; gap: 2px; min-width: 0; }
.record-manual small, .record-manual em, .record-manual p { color: var(--ink-dim); font-size: 11px; font-style: normal; }
.record-manual b { font-size: 14px; }
.record-manual p { margin: 3px 0 0; }
.record-manual > button { flex: none; padding: 3px 7px; color: var(--danger); background: transparent; border: 0; cursor: pointer; }
.record-run > summary { display: grid; grid-template-columns: minmax(0, 1fr) auto 18px; align-items: center; gap: 10px; padding: 11px 12px; cursor: pointer; list-style: none; }
.record-run > summary::-webkit-details-marker { display: none; }
.record-run > summary::after { content: '＋'; color: var(--fox-gold-deep); font-size: 16px; }
.record-run[open] > summary { background: var(--fox-gold-pale); border-radius: 9px 9px 0 0; }
.record-run[open] > summary::after { content: '−'; }
.record-run summary > span, .record-activity > span { display: grid; gap: 2px; min-width: 0; }
.record-run summary small, .record-activity small { color: var(--ink-dim); font-size: 11px; }
.record-run summary > em { overflow: hidden; color: var(--fox-gold-deep); font-size: 11px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.record-activity { padding: 11px 12px; }
.run-actions { display: flex; justify-content: flex-end; margin-top: 8px; }
.run-delete { padding: 3px 7px; color: var(--danger); background: transparent; border: 0; cursor: pointer; font-size: 11px; }
.record-activity > details summary { margin-top: 7px; color: var(--fox-gold-deep); cursor: pointer; font-size: 11px; }
.record-activity > details p { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 8px; margin: 6px 0 0; color: var(--ink-dim); font-size: 11px; }
.record-activity > details time { white-space: nowrap; }
.report-empty { padding: 28px 12px; text-align: center; }
:deep(.records-calendar.p-datepicker) { width: 100%; margin-top: 10px; color: var(--ink); background: transparent; border: 0; box-shadow: none; }
:deep(.records-calendar .p-datepicker-panel) { width: 100%; padding: 0; background: transparent; border: 0; box-shadow: none; }
:deep(.records-calendar .p-datepicker-header) { padding-inline: 2px; background: transparent; border: 0; }
:deep(.records-calendar .p-datepicker-day-view) { width: 100%; font-size: 12px; }
:deep(.records-calendar .p-datepicker-day-view) { table-layout: fixed; }
:deep(.records-calendar .p-datepicker-day-view th),
:deep(.records-calendar .p-datepicker-day-view td) { padding: 2px 0; }
:deep(.records-calendar .p-datepicker-day) { width: 27px; height: 27px; border-radius: 8px; }
:deep(.records-calendar .p-datepicker-day-selected) { color: var(--ink); background: var(--fox-gold-pale); outline: 1px solid var(--fox-gold); }
:deep(.records-calendar .p-datepicker-today > .p-datepicker-day) { color: var(--fox-gold-deep); font-weight: 700; }
:deep(.day-timeline) { margin-top: 14px; }
:deep(.day-timeline .p-timeline-event-opposite) { flex: 0 0 54px; padding: 7px 0 0; color: var(--ink-dim); font-size: 11px; text-align: left; }
:deep(.day-timeline .p-timeline-event-separator) { flex: 0 0 36px; }
:deep(.day-timeline .p-timeline-event-content) { min-width: 0; padding: 0 0 13px 8px; }
:deep(.day-timeline .p-timeline-event-connector) { background: var(--paper-line); }
:global(body[data-theme='pixel']) .records-calendar-panel,
:global(body[data-theme='pixel']) .records-day,
:global(body[data-theme='pixel']) .record-run,
:global(body[data-theme='pixel']) .record-activity { border-width: 2px; border-color: #1a3055; border-radius: 0; box-shadow: 3px 3px 0 #c8bea5; }

@media (max-width: 720px) {
  .records-browser { grid-template-columns: 1fr; }
  .records-calendar-panel { position: static; padding: 12px; }
  .records-calendar-panel header, .records-calendar { display: none; }
  .records-date-picker-mobile { display: flex; }
  .records-day { padding-inline: 12px; }
  .records-day-header { align-items: flex-start; }
  .record-run > summary { grid-template-columns: minmax(0, 1fr) 18px; }
  .record-run summary > em { grid-column: 1; }
  .record-run summary::after { grid-column: 2; grid-row: 1 / 3; }
  :deep(.day-timeline .p-timeline-event-opposite) { flex-basis: 45px; }
  :deep(.day-timeline .p-timeline-event-separator) { flex-basis: 30px; }
}
</style>
