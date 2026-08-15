<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const days = ref(7), summary = ref<any>(null), events = ref<any[]>([]), runs = ref<any[]>([]), loading = ref(false), error = ref('')
const eventNames: Record<string, string> = {
  'game_update.detected': '发现游戏更新', 'game_update.recovered': '游戏更新后恢复',
  'osaka.floor_completed': '大阪城完成一圈', 'sortie.completed': '出阵完成',
  'raid.round_completed': '联队战完成一圈', 'pumpkin.sortie_completed': '南瓜活动出阵完成',
  'pumpkin.board_completed': '南瓜活动完成一块板子', 'pumpkin.token_used': '南瓜活动使用更新令牌',
  'repair.queued': '刀剑进入手入', 'repair.skipped': '跳过手入', 'repair.session_completed': '手入完成',
  'repair.summary': '手入小结',
  'practice.result': '演练结束', 'pumpkin.sword_obtained': '南瓜活动获得刀剑',
  'forge.started': '开始锻刀', 'forge.collected': '领取锻刀结果',
  'expedition.dispatched': '远征派遣成功', 'expedition.settled': '远征结算',
  'task_rewards.claimed': '领取任务奖励', 'inventory.captured': '保存库存快照',
}
function countEvents(...types: string[]) { return events.value.filter(item => types.includes(item.event_type)).length }
const rewardClaims = computed(() => countEvents('task_rewards.claimed'))
const sortieCount = computed(() => countEvents('sortie.completed', 'osaka.floor_completed', 'raid.round_completed', 'pumpkin.sortie_completed'))
const expeditions = computed(() => countEvents('expedition.dispatched'))
const practiceWins = computed(() => events.value.filter(item => item.event_type === 'practice.result' && isWin(item.payload)).length)
const practiceTotal = computed(() => countEvents('practice.result'))
const pumpkinBoards = computed(() => countEvents('pumpkin.board_completed'))
const pumpkinTokens = computed(() => countEvents('pumpkin.token_used'))
const estimateHours = ref(6), customHours = ref(6), customEstimate = ref(false)
const timelineEvents = computed(() => {
  const visible: any[] = []
  const repairs = new Map<string, any>()
  const hidden = new Set(['team_record.saved', 'equipment.restored'])
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
    } else if (item.event_type === 'raid.round_completed') {
      add(`raid:${p.difficulty}`, `联队战 ${p.difficulty || '未指定难度'}`, p.triple ? '使用三倍枡' : '')
    } else if (item.event_type === 'pumpkin.sortie_completed') add('pumpkin', '南瓜大作战')
  }
  return [...groups.values()].sort((a, b) => b.count - a.count)
})
function isWin(payload: any) {
  const value = String(payload?.result ?? payload?.outcome ?? '').toLowerCase()
  return value.includes('胜') || value === 'win' || value === 'won'
}
function eventDetail(item: any) {
  const p = item.payload || {}
  if (item.event_type === 'osaka.floor_completed') return p.selected_floor == null ? '未指定层数 · 完成 1 圈' : `${p.selected_floor}F · 完成 1 圈`
  if (item.event_type === 'sortie.completed') return `${p.mode === 'yosari' ? '异去' : '合战场'} ${p.chapter}-${p.map_no} · 完成 1 圈`
  if (item.event_type === 'raid.round_completed') return `难度 ${p.difficulty ?? '未指定'} · ${p.battles ?? 0} 场战斗`
  if (item.event_type === 'pumpkin.sortie_completed') return `第 ${p.sequence ?? '？'} 次出阵`
  if (item.event_type === 'pumpkin.board_completed') return `完成第 ${p.sequence ?? '？'} 块板子`
  if (item.event_type === 'pumpkin.token_used') return `累计使用 ${p.used ?? '？'} 枚`
  if (item.event_type === 'practice.result') return `结果：${p.result ?? p.outcome ?? '已记录'}`
  if (item.event_type === 'expedition.dispatched') return `部队 ${p.team_no ?? '？'} · ${p.map_name || p.map_code || '地图未识别'}`
  if (item.event_type === 'task_rewards.claimed') return `${p.tab || '当前'}页 · 点击一键领取`
  if (item.event_type === 'repair.summary') {
    const queued = p.queued || [], skipped = p.skipped || []
    const repaired = p.sessions ? p.repaired : queued.length
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
function runTitle(run: any) { return run.selected_floor == null ? `未指定层数 · ${run.loops} 圈` : `${run.selected_floor}F · ${run.loops} 圈` }
function runStats(run: any) { return `手入 ${run.repair_sessions} 次 · 加速符 ${run.speedups} 枚 · 补刀装 ${run.equipment_restores} 次` }
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
async function load(nextDays = days.value) {
  days.value = nextDays; loading.value = true
  try {
    const [nextSummary, nextEvents, nextRuns] = await Promise.all([api.dataSummary(nextDays), api.dataEvents(500), api.dataRuns(30)])
    summary.value = nextSummary
    events.value = nextEvents.items.filter(item => item.ts >= Date.now() / 1000 - nextDays * 86400)
    runs.value = nextRuns.items.filter(item => item.script === 'osaka' && item.loops && item.started_at >= Date.now() / 1000 - nextDays * 86400)
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
    <div class="report-stats" :class="{ loading }">
      <article><small>领取任务奖励</small><strong>{{ rewardClaims }} 次</strong><span>按一键领取点击计数</span></article>
      <article><small>出阵完成</small><strong>{{ sortieCount }} 次</strong><span>按确认完成的圈数计数</span></article>
      <article><small>派遣远征</small><strong>{{ expeditions }} 次</strong><span>确认“远征中”后记录</span></article>
      <article><small>演练战绩</small><strong>{{ practiceWins }} / {{ practiceTotal }}</strong><span>胜场 / 已记录场次</span></article>
    </div>
    <div class="report-body">
      <div>
        <section v-if="runs.length" class="report-runs">
          <header><h3>⛏️ 挂机成绩单</h3><small>圈速不含开工与收工盘点</small></header>
          <article v-for="(run, index) in runs.slice(0, 5)" :key="run.run_id" :class="{ featured: index === 0 }">
            <time>{{ eventTime(run.started_at) }}</time>
            <div><strong>{{ runTitle(run) }}</strong>
              <div v-if="index === 0 && run.average_loop_seconds" class="run-estimator">
                <div><small>平均速度</small><b>{{ loopTime(run.average_loop_seconds) }}</b></div>
                <div class="estimate-result"><small>预计完成</small><b>≈ {{ estimatedLoops(run) }} 圈</b></div>
                <div class="estimate-control"><small>预计收益</small><label>挂机时间 <span v-if="!customEstimate">{{ estimateHours }} 小时</span><input v-else v-model.number="customHours" type="number" min="0.5" step="0.5" aria-label="自定义挂机小时数" @input="updateCustom"></label></div>
                <nav aria-label="预计挂机时间"><button v-for="hour in [1, 6, 8]" :key="hour" type="button" :class="{ active: !customEstimate && estimateHours === hour }" @click="chooseHours(hour)">{{ hour }}小时</button><button type="button" :class="{ active: customEstimate }" @click="chooseCustom">自定义</button></nav>
              </div>
              <p v-else>{{ loopTime(run.average_loop_seconds) }}</p><p>{{ runStats(run) }}</p><p v-if="deltaStats(run)" class="run-delta">家底变化：{{ deltaStats(run) }}</p><small v-else-if="!run.has_resource_comparison">这轮没有完整的前后库存快照</small></div>
          </article>
        </section>
        <section class="report-sorties">
          <header><h3>⚔️ 出阵小结</h3><small v-if="pumpkinBoards || pumpkinTokens">南瓜：{{ pumpkinBoards }} 块板子 · {{ pumpkinTokens }} 枚令牌</small></header>
          <div v-if="sortieGroups.length" class="sortie-list"><p v-for="item in sortieGroups" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.count }} 圈</strong><small v-if="item.detail">{{ item.detail }}</small></p></div>
          <p v-else class="report-empty">这个时间段还没有完成的出阵。</p>
        </section>
        <section class="report-events">
          <header><h3>最近发生</h3><small>只展示结构化玩法记录</small></header>
          <div v-if="groupedTimelineEvents.length" class="event-list"><article v-for="item in groupedTimelineEvents.slice(0, 60)" :key="item.id"><time>{{ eventTime(item.ts) }}</time><i aria-hidden="true"></i><div><strong>{{ eventNames[item.event_type] || '本丸记录' }}<em v-if="item.items.length > 1">× {{ item.items.length }}</em></strong><p>{{ eventDetail(item) }}</p><details v-if="item.items.length > 1"><summary>展开 {{ item.items.length }} 条明细</summary><p v-for="child in item.items" :key="child.id"><time>{{ eventTime(child.ts) }}</time>{{ instanceDetail(child) }}</p></details></div></article></div>
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
