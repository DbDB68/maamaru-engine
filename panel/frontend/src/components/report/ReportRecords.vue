<script setup lang="ts">
// 「全部记录」时间线：从旧 ReportPanel 原样迁来，行为保持不变
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import { attributedStats, deltaStats, elapsedTime, eventTime, kobanPerFloorLabel, kobanPerHourLabel, loopTime, runElapsedSeconds, runTitle } from './reportModel'

const props = defineProps<{
  events: any[]
  runs: any[]
  days: number
  hasMoreEvents: boolean
  hasMoreRuns: boolean
  loadingOlder: boolean
}>()

const emit = defineEmits<{ 'load-more': []; refresh: [] }>()

const timelineLimit = ref(20)

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
    const koban = props.events.find((entry: any) => entry.run_id === item.run_id && entry.event_type === 'osaka.koban_session')?.payload?.delta
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
function instanceDetail(item: any) {
  const p = item.payload || {}
  if (item.event_type === 'osaka.floor_completed' && p.completed != null) return `第 ${p.completed} 圈 · ${p.selected_floor == null ? '未指定层数' : `${p.selected_floor}F`}`
  if (item.event_type === 'pumpkin.sortie_completed' && p.sequence != null) return `第 ${p.sequence} 次出阵`
  return eventDetail(item)
}

const timelineEvents = computed(() => {
  const visible: any[] = []
  const repairs = new Map<string, any>()
  const hidden = new Set(['team_record.saved', 'inventory.peek', 'osaka.koban_session'])
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
const unifiedRecords = computed(() => {
  const visibleRunIds = new Set(props.runs.map(run => run.run_id).filter(Boolean))
  const entries = [
    ...props.runs.map(run => ({ kind: 'run' as const, ts: Number(run.started_at), run })),
    ...groupedActivityEvents.value
      .filter(item => !item.run_id || !visibleRunIds.has(item.run_id))
      .map(item => ({ kind: 'activity' as const, ts: Number(item.ts), item })),
  ].sort((a, b) => b.ts - a.ts)
  const groups: Array<{ key: string; label: string; entries: typeof entries }> = []
  for (const entry of entries.slice(0, timelineLimit.value)) {
    const date = new Date(entry.ts * 1000)
    const key = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(date)
    let group = groups[groups.length - 1]
    if (!group || group.key !== key) {
      group = { key, label: new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'short' }).format(date), entries: [] }
      groups.push(group)
    }
    group.entries.push(entry)
  }
  return { total: entries.length, groups }
})
function runActivities(run: any) { return groupedActivityEvents.value.filter(item => item.run_id && item.run_id === run.run_id) }
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

const attachingRun = ref('')
const inventoryNotice = ref<Record<string, string>>({})
const attachError = ref('')
const latestInventoriedRun = computed(() => props.runs.find(run => run.has_before_snapshot))
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
  if (unifiedRecords.value.total > timelineLimit.value) { timelineLimit.value += 20; return }
  pendingBump.value = true
  emit('load-more')
}
watch(() => [props.events.length, props.runs.length], () => {
  if (pendingBump.value) { timelineLimit.value += 20; pendingBump.value = false }
})
watch(() => props.days, () => { timelineLimit.value = 20 })
</script>

<template>
  <section class="unified-history">
    <p v-if="attachError" class="report-error">{{ attachError }}</p>
    <template v-if="unifiedRecords.groups.length">
      <section v-for="group in unifiedRecords.groups" :key="group.key" class="history-day">
        <h3>{{ group.label }}</h3>
        <div class="history-list">
          <template v-for="entry in group.entries" :key="entry.kind === 'run' ? `run:${entry.run.run_id}` : `event:${entry.item.id}`">
            <details v-if="entry.kind === 'run'" class="history-run">
              <summary><time>{{ new Date(entry.ts * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</time><span><b>🦊 {{ runTitle(entry.run) }}</b><small>{{ elapsedTime(runElapsedSeconds(entry.run)) }}<template v-if="entry.run.average_loop_seconds"> · {{ loopTime(entry.run.average_loop_seconds) }}</template></small></span><em>{{ attributedStats(entry.run) || deltaStats(entry.run) || '查看详情' }}</em></summary>
              <div class="run-evidence">
                <p v-if="!hasUpkeep(entry.run)" class="run-upkeep-quiet">本轮无额外养护消耗</p>
                <div v-else class="run-upkeep" aria-label="本轮养护"><span v-if="runRepairTotal(entry.run)">🩹 手入 <b>{{ runRepairTotal(entry.run) }}</b> 振</span><span v-if="runSpeedupTotal(entry.run)">⚡ 加速符 <b>{{ runSpeedupTotal(entry.run) }}</b> 枚</span><span v-if="runEquipmentTotal(entry.run)">🛡️ 补刀装 <b>{{ runEquipmentTotal(entry.run) }}</b> 次</span></div>
                <p v-if="attributedStats(entry.run)" class="run-delta"><small>🦊 已确认收支</small>{{ attributedStats(entry.run) }}</p>
                <p v-if="deltaStats(entry.run)" class="run-delta"><small>📦 库存变化</small>{{ deltaStats(entry.run) }}<span v-if="kobanPerHourLabel(entry.run)">· 小判约 {{ kobanPerHourLabel(entry.run) }} / 小时</span><span v-if="kobanPerFloorLabel(entry.run)">· 平均每层 {{ kobanPerFloorLabel(entry.run) }}</span></p>
                <div v-if="runActivities(entry.run).length" class="run-activities"><p v-for="item in runActivities(entry.run)" :key="item.id"><time>{{ new Date(item.ts * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</time><span><b>{{ activityTitle(item) }}</b><small>{{ activityDetail(item) }}</small></span></p></div>
                <div v-if="!entry.run.has_resource_comparison && canAttachInventory(entry.run)" class="run-inventory-missing"><small>收工盘点没有完成；仅可用挂机结束后、没有其他操作的库存快照补盘。</small><button type="button" class="secondary" :disabled="attachingRun === entry.run.run_id" @click="attachInventory(entry.run)">{{ attachingRun === entry.run.run_id ? '正在补盘……' : '补上最近盘点' }}</button><em v-if="inventoryNotice[entry.run.run_id]">{{ inventoryNotice[entry.run.run_id] }}</em></div>
              </div>
            </details>
            <article v-else class="history-activity"><time>{{ new Date(entry.ts * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</time><span><b>{{ activityTitle(entry.item) }}</b><small>{{ activityDetail(entry.item) }}</small></span><details v-if="entry.item.items.length > 1"><summary>查看 {{ entry.item.items.length }} 条明细</summary><p v-for="child in entry.item.items" :key="child.id"><time>{{ eventTime(child.ts) }}</time>{{ instanceDetail(child) }}</p></details></article>
          </template>
        </div>
      </section>
    </template>
    <p v-else class="report-empty">这个时间段还没有完成的记录。</p>
    <button v-if="unifiedRecords.total > timelineLimit || hasMoreRuns || hasMoreEvents" type="button" class="timeline-more secondary" :disabled="loadingOlder" @click="showMoreRecords">{{ loadingOlder ? '正在翻档案……' : '查看更早记录' }}</button>
  </section>
</template>
