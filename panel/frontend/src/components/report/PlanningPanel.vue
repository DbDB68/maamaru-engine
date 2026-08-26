<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../../api'
import type { EventAbacus, EventsCalendar, PlanningGoalAdvice, PlanningReport } from '../../types'
import { resourceNames } from './reportModel'

const planning = ref<PlanningReport | null>(null)
const calendar = ref<EventsCalendar | null>(null)
const loading = ref(false)
const error = ref('')

const formOpen = ref(false)
const formEvent = ref('')
const saving = ref(false)
const form = ref({ resource: '小判', target: 100000, deadline: '', note: '' })

function localToday() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

function fmt(value: number | null | undefined) {
  return value == null ? '—' : Math.round(value).toLocaleString()
}

function shortDate(iso: string | null) {
  if (!iso) return ''
  const [, month, day] = iso.split('-').map(Number)
  return `${month}月${day}日`
}

const statusLabel: Record<string, string> = {
  done: '已达成',
  on_track: '来得及',
  behind: '要加把劲',
  expired: '已到期',
  unknown: '数据不足',
}

const upcoming = computed(() => {
  const today = localToday()
  return (calendar.value?.announcements || [])
    .filter(item => item.update_date && item.update_date >= today)
    .sort((a, b) => a.update_date!.localeCompare(b.update_date!))
    .slice(0, 4)
})
const featuredAnnouncement = computed(() => upcoming.value[0] || null)
const actionableEvents = computed(() => (planning.value?.events || []).filter(item => item.start_date || item.end_date || item.keys_total > 0))
const waitingEvents = computed(() => (planning.value?.events || []).filter(item => !item.start_date && !item.end_date && item.keys_total <= 0))
const eventGoalNames = computed(() => new Set(
  (planning.value?.goals || [])
    .filter(goal => goal.kind === 'event' && goal.event)
    .map(goal => String(goal.event)),
))

function eventDate(abacus: EventAbacus) {
  if (abacus.start_date && abacus.end_date) return `${shortDate(abacus.start_date)}开打 · ${shortDate(abacus.end_date)}收摊`
  if (abacus.start_date) return `${shortDate(abacus.start_date)}开打`
  if (abacus.end_date) return `${shortDate(abacus.end_date)}前结束`
  return '日期待公告'
}

function goalHeadline(goal: PlanningGoalAdvice) {
  if (goal.status === 'done') return `已经攒够 ${fmt(goal.target)} ${goal.resource}`
  if (goal.status === 'on_track') return '照现在的速度来得及'
  if (goal.status === 'expired') return '这个目标已经到期'
  if (goal.status === 'unknown') return '还缺一些库存记录'
  if (goal.shortfall != null) return `还差 ${fmt(goal.shortfall)} ${goal.resource}`
  return '需要再加把劲'
}

function goalAction(goal: PlanningGoalAdvice) {
  if (goal.status === 'behind' && goal.extra_daily != null) {
    const floors = goal.resource === '小判' && goal.extra_floors != null ? `，约合每天多挖 ${fmt(goal.extra_floors)} 层大阪城` : ''
    return `接下来每天还需多攒 ${fmt(goal.extra_daily)} ${goal.resource}${floors}`
  }
  if (goal.status === 'on_track') return '保持最近的进账速度即可。'
  if (goal.status === 'done') return '目标已经完成，可以放心开打。'
  return ''
}

function planFromEvent(eventName: string) {
  formOpen.value = true
  formEvent.value = eventName
  form.value = { ...form.value, deadline: '', note: eventName }
}

const estimateInputs = ref<Record<string, string>>({})
const estimateSaving = ref('')
const abacusGoalSaving = ref('')

async function saveEstimate(event: string) {
  const value = Number(estimateInputs.value[event])
  if (!Number.isFinite(value) || value <= 0) {
    error.value = '先填一个大于 0 的场均钥匙数。'
    return
  }
  estimateSaving.value = event
  try {
    await api.saveEventEstimate(event, value)
    await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '场均预估保存失败' }
  finally { estimateSaving.value = '' }
}

async function goalFromAbacus(abacus: EventAbacus) {
  if (!abacus.koban_cost) return
  abacusGoalSaving.value = abacus.event
  try {
    await api.addEventGoal(abacus.event)
    await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '目标保存失败' }
  finally { abacusGoalSaving.value = '' }
}

async function load() {
  loading.value = true
  try {
    const [nextPlanning, nextCalendar] = await Promise.all([api.planning(), api.events()])
    planning.value = nextPlanning
    calendar.value = nextCalendar
    for (const abacus of nextPlanning.events || []) {
      if (abacus.keys_per_run != null) estimateInputs.value[abacus.event] = String(abacus.keys_per_run)
    }
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '规划建议读取失败' }
  finally { loading.value = false }
}

function openCustomForm() {
  formOpen.value = true
  formEvent.value = ''
  form.value = { ...form.value, note: '' }
}

async function saveGoal() {
  saving.value = true
  try {
    await api.addPlanningGoal({
      resource: form.value.resource,
      target: Number(form.value.target),
      deadline: form.value.deadline,
      note: form.value.note,
    })
    formOpen.value = false
    formEvent.value = ''
    form.value = { resource: '小判', target: 100000, deadline: '', note: '' }
    await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '目标保存失败' }
  finally { saving.value = false }
}

async function removeGoal(id: number) {
  try {
    await api.deletePlanningGoal(id)
    await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '目标删除失败' }
}

onMounted(load)
</script>

<template>
  <section class="planning-panel" :class="{ loading }">
    <header class="planning-hero">
      <div>
        <small>规划</small>
        <h3>接下来要准备什么</h3>
        <p>先看差多少，再决定要不要加把劲。</p>
      </div>
      <button v-if="!formOpen" type="button" class="secondary" @click="openCustomForm">＋ 自定目标</button>
    </header>

    <p v-if="error" class="planning-error">{{ error }}</p>

    <aside v-if="featuredAnnouncement" class="planning-news">
      <span>
        <small>官方公告 · {{ shortDate(featuredAnnouncement.update_date) }}</small>
        <b>{{ featuredAnnouncement.events.join('、') }}</b>
      </span>
      <div>
        <a v-if="featuredAnnouncement.url" :href="featuredAnnouncement.url" target="_blank" rel="noopener">查看公告</a>
        <button type="button" class="secondary" @click="planFromEvent(featuredAnnouncement.events[0] || '')">按活动准备</button>
      </div>
    </aside>
    <p v-else-if="calendar?.reason" class="planning-muted">{{ calendar.reason }}</p>

    <form v-if="formOpen" class="planning-form" @submit.prevent="saveGoal">
      <header>
        <div><h4>{{ formEvent ? `为「${formEvent}」做准备` : '自定目标' }}</h4><p>{{ formEvent ? '资源最好在活动开打前备齐。' : '给自己定一个明确的数量和日期。' }}</p></div>
        <button type="button" class="planning-close" aria-label="关闭目标表单" @click="formOpen = false; formEvent = ''">×</button>
      </header>
      <div class="planning-form-fields">
        <label>攒什么
          <select v-model="form.resource">
            <option v-for="name in resourceNames" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <label>目标数量
          <input v-model.number="form.target" type="number" min="0" step="1000" required>
        </label>
        <label>截止日期
          <input v-model="form.deadline" type="date" :min="localToday()" required>
        </label>
        <label>备注
          <input v-model="form.note" maxlength="50" placeholder="可不填">
        </label>
      </div>
      <div class="planning-form-actions">
        <button type="submit" class="primary" :disabled="saving">{{ saving ? '记账中……' : '立下目标' }}</button>
        <button type="button" class="secondary" @click="formOpen = false; formEvent = ''">取消</button>
      </div>
    </form>

    <section class="planning-section planning-goals-section">
      <header>
        <div><h4>我的目标</h4><p>最需要你做决定的事放在最前面。</p></div>
      </header>
      <div v-if="planning?.goals.length" class="planning-goal-list">
        <article v-for="goal in planning.goals" :key="goal.id" class="planning-goal" :class="goal.status">
          <header>
            <span><b>{{ goal.note || `${goal.resource}目标` }}</b><small>{{ goal.kind === 'event' ? '活动预算' : '手动目标' }} · {{ goal.deadline }} 截止</small></span>
            <em>{{ statusLabel[goal.status] || goal.status }}</em>
            <button type="button" class="planning-delete" title="删掉这个目标" @click="removeGoal(goal.id)">×</button>
          </header>
          <strong class="planning-goal-result">{{ goalHeadline(goal) }}</strong>
          <p v-if="goalAction(goal)" class="planning-next-action">{{ goalAction(goal) }}</p>
          <div class="planning-goal-metrics">
            <span><small>当前</small><b>{{ fmt(goal.current) }}</b></span>
            <span><small>目标</small><b>{{ fmt(goal.target) }}</b></span>
            <span><small>还剩</small><b>{{ Math.max(0, goal.days_left) }} 天</b></span>
            <span><small>到期预计</small><b>{{ fmt(goal.projected) }}</b></span>
          </div>
          <details>
            <summary>查看预测依据</summary>
            <p>{{ goal.message }}</p>
          </details>
        </article>
      </div>
      <div v-else class="planning-empty-state">
        <b>还没有目标</b>
        <span>立一个之后，这里会直接告诉你来不来得及。</span>
        <button type="button" class="secondary" @click="openCustomForm">＋ 立个目标</button>
      </div>
    </section>

    <section class="planning-section planning-events-section">
      <header>
        <div><h4>活动准备</h4><p>只展示现在能算、也值得你动手的活动。</p></div>
      </header>

      <article v-for="abacus in actionableEvents" :key="abacus.event" class="planning-event-card">
        <header>
          <span><small>近期活动</small><b>{{ abacus.event }}</b></span>
          <em>{{ eventDate(abacus) }}</em>
        </header>
        <p class="planning-event-result">{{ abacus.message }}</p>
        <div v-if="abacus.keys_total || abacus.runs_needed || abacus.koban_cost" class="planning-event-metrics">
          <span v-if="abacus.keys_total"><small>总目标</small><b>{{ fmt(abacus.keys_total) }} 把钥匙</b></span>
          <span v-if="abacus.runs_needed"><small>预计要跑</small><b>{{ fmt(abacus.runs_needed) }} 圈</b></span>
          <span v-if="abacus.koban_cost != null"><small>预计买票</small><b>{{ fmt(abacus.koban_cost) }} 小判</b></span>
          <span v-if="abacus.available_now != null"><small>现有小判</small><b>{{ fmt(abacus.available_now) }}</b></span>
          <span v-if="abacus.shortfall != null"><small>还差</small><b>{{ fmt(abacus.shortfall) }} 小判</b></span>
        </div>
        <div v-if="abacus.keys_total > 0 && abacus.keys_per_run == null" class="planning-question">
          <label>你一圈通常拿几把钥匙？
            <input v-model="estimateInputs[abacus.event]" type="number" min="1" max="200" step="1" placeholder="填个估计">
          </label>
          <button type="button" class="primary" :disabled="estimateSaving === abacus.event" @click="saveEstimate(abacus.event)">{{ estimateSaving === abacus.event ? '计算中……' : '帮我算' }}</button>
        </div>
        <div v-else-if="abacus.koban_cost && abacus.sufficient === true" class="planning-budget-state ready">
          <b>小判已经备齐</b><span>活动预算 {{ fmt(abacus.koban_cost) }}，不用再立目标。</span>
        </div>
        <div v-else-if="abacus.koban_cost && eventGoalNames.has(abacus.event)" class="planning-budget-state">
          <b>已加入我的目标</b><span v-if="abacus.shortfall != null">目前还差 {{ fmt(abacus.shortfall) }} 小判。</span>
        </div>
        <button v-else-if="abacus.koban_cost && (abacus.start_date || abacus.end_date)" type="button" class="primary planning-event-goal" :disabled="abacusGoalSaving === abacus.event" @click="goalFromAbacus(abacus)">{{ abacusGoalSaving === abacus.event ? '正在立目标……' : abacus.shortfall != null ? `还差 ${fmt(abacus.shortfall)} 小判，立成目标` : `把 ${fmt(abacus.koban_cost)} 小判设为目标` }}</button>
        <details v-if="abacus.note">
          <summary>怎么算的</summary>
          <p>{{ abacus.note }}</p>
        </details>
      </article>

      <div v-for="abacus in waitingEvents" :key="abacus.event" class="planning-waiting-event">
        <b>{{ abacus.event }}</b><span>日期待公告，暂不参与规划</span>
      </div>
    </section>
  </section>
</template>

<style scoped>
.planning-panel { display: grid; gap: 12px; }
.planning-hero { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 18px; background: linear-gradient(110deg, var(--fox-gold-pale), var(--paper-card)); border: 1px solid var(--paper-line); border-left: 4px solid var(--fox-gold); border-radius: 12px; }
.planning-hero small { color: var(--fox-gold-deep); font-weight: 700; letter-spacing: .08em; }
.planning-hero h3 { margin: 2px 0 0; font-size: 20px; }
.planning-hero p, .planning-section > header p, .planning-form header p { margin: 3px 0 0; color: var(--ink-dim); font-size: 13px; }
.planning-error { margin: 0; padding: 10px 12px; color: #9f3d28; background: #f9e6df; border: 1px solid #d6a394; border-radius: 10px; }
.planning-news { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 10px 14px; background: var(--paper-card); border: 1px dashed var(--paper-line); border-radius: 10px; }
.planning-news > span { display: grid; gap: 2px; min-width: 0; }
.planning-news small { color: var(--ink-dim); }
.planning-news b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.planning-news > div { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.planning-news a { color: var(--fox-gold-deep); font-size: 13px; }
.planning-muted { margin: 0; color: var(--ink-dim); font-size: 13px; }
.planning-section, .planning-form { padding: 16px 18px; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; }
.planning-section > header, .planning-form > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.planning-section h4, .planning-form h4 { margin: 0; font-size: 16px; }
.planning-close { padding: 0 5px; color: var(--ink-dim); background: transparent; border: 0; font-size: 20px; cursor: pointer; }
.planning-form-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.planning-form label, .planning-question label { display: grid; gap: 5px; color: var(--ink-dim); font-size: 12px; }
.planning-form input, .planning-form select, .planning-question input { width: 100%; min-width: 0; }
.planning-form-actions { display: flex; gap: 8px; margin-top: 12px; }
.planning-goal-list { display: grid; gap: 10px; margin-top: 12px; }
.planning-goal { padding: 14px 16px; background: var(--paper); border: 1px solid var(--paper-line); border-left: 5px solid var(--paper-line); border-radius: 10px; }
.planning-goal.done { border-left-color: #4d7a3a; }
.planning-goal.on_track { border-left-color: var(--fox-gold); }
.planning-goal.behind { border-left-color: #b0492e; }
.planning-goal > header { display: flex; align-items: flex-start; gap: 8px; }
.planning-goal > header > span { display: grid; gap: 1px; min-width: 0; }
.planning-goal > header small { color: var(--ink-dim); font-size: 11px; }
.planning-goal > header em { margin-left: auto; padding: 2px 9px; color: var(--ink-dim); border: 1px solid var(--paper-line); border-radius: 999px; font-size: 11px; font-style: normal; white-space: nowrap; }
.planning-goal.behind > header em { color: #9f3d28; border-color: #c98673; }
.planning-goal.on_track > header em { color: var(--fox-gold-deep); border-color: var(--fox-gold); }
.planning-delete { padding: 0 3px; color: var(--ink-dim); background: transparent; border: 0; font-size: 17px; cursor: pointer; }
.planning-goal-result { display: block; margin-top: 13px; font-size: clamp(22px, 3vw, 30px); line-height: 1.1; }
.planning-next-action { margin: 7px 0 0; color: #9f3d28; }
.planning-goal-metrics, .planning-event-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 14px; border: 1px solid var(--paper-line); }
.planning-goal-metrics span, .planning-event-metrics span { display: grid; gap: 3px; min-width: 0; padding: 9px 11px; border-left: 1px solid var(--paper-line); }
.planning-goal-metrics span:first-child, .planning-event-metrics span:first-child { border-left: 0; }
.planning-goal-metrics small, .planning-event-metrics small { color: var(--ink-dim); font-size: 11px; }
.planning-goal-metrics b, .planning-event-metrics b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.planning-panel details { margin-top: 10px; color: var(--ink-dim); font-size: 12px; }
.planning-panel summary { color: var(--fox-gold-deep); cursor: pointer; }
.planning-panel details p { margin: 7px 0 0; line-height: 1.6; }
.planning-empty-state { display: grid; justify-items: start; gap: 5px; margin-top: 12px; padding: 18px; color: var(--ink-dim); background: var(--paper); border: 1px dashed var(--paper-line); border-radius: 10px; }
.planning-empty-state b { color: var(--ink); }
.planning-empty-state button { margin-top: 5px; }
.planning-events-section { display: grid; gap: 10px; }
.planning-event-card { padding: 14px 16px; background: var(--paper); border: 1px solid var(--fox-gold); border-radius: 10px; }
.planning-event-card > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.planning-event-card > header span { display: grid; gap: 2px; }
.planning-event-card > header small { color: var(--fox-gold-deep); font-size: 11px; font-weight: 700; }
.planning-event-card > header b { font-size: 16px; }
.planning-event-card > header em { color: var(--ink-dim); font-size: 12px; font-style: normal; white-space: nowrap; }
.planning-event-result { margin: 12px 0 0; font-size: 15px; line-height: 1.65; }
.planning-event-metrics { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
.planning-question { display: flex; align-items: flex-end; gap: 8px; margin-top: 12px; padding: 11px 12px; background: var(--fox-gold-pale); border-radius: 8px; }
.planning-question label { flex: 1 1 180px; color: var(--ink); font-size: 13px; }
.planning-question input { max-width: 180px; background: var(--paper-card); }
.planning-event-goal { margin-top: 12px; }
.planning-budget-state { display: flex; align-items: baseline; gap: 8px; margin-top: 12px; padding: 10px 12px; color: var(--ink-dim); background: var(--fox-gold-pale); border-radius: 8px; }
.planning-budget-state b { color: var(--ink); }
.planning-budget-state.ready { background: color-mix(in srgb, #dcebd6 72%, var(--paper-card)); }
.planning-budget-state.ready b { color: #426b36; }
.planning-waiting-event { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 12px; color: var(--ink-dim); border-top: 1px dashed var(--paper-line); }
.planning-waiting-event b { color: var(--ink); }
@media (max-width: 700px) {
  .planning-form-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .planning-goal-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .planning-goal-metrics span:nth-child(odd) { border-left: 0; }
  .planning-goal-metrics span:nth-child(n+3) { border-top: 1px solid var(--paper-line); }
}
@media (max-width: 520px) {
  .planning-hero { align-items: flex-start; padding: 14px; }
  .planning-hero h3 { font-size: 18px; }
  .planning-hero p { max-width: 210px; }
  .planning-news { align-items: flex-start; flex-direction: column; }
  .planning-news > span { width: 100%; }
  .planning-news > div { justify-content: space-between; width: 100%; }
  .planning-section, .planning-form { padding: 14px; }
  .planning-form-fields { grid-template-columns: 1fr; }
  .planning-event-card > header { align-items: flex-start; flex-direction: column; gap: 4px; }
  .planning-event-metrics { grid-template-columns: 1fr; }
  .planning-event-metrics span { border-top: 1px solid var(--paper-line); border-left: 0; }
  .planning-event-metrics span:first-child { border-top: 0; }
  .planning-question { align-items: stretch; flex-direction: column; }
  .planning-question label { flex: none; }
  .planning-question label, .planning-question input, .planning-question button { width: 100%; max-width: none; }
  .planning-waiting-event { align-items: flex-start; flex-direction: column; gap: 2px; }
}
</style>
