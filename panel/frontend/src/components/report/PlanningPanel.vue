<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from '../../api'
import type { EventAbacus, EventTimelineReport, PlanningGoalAdvice, PlanningReport } from '../../types'
import { resourceNames } from './reportModel'
import EventTimeline from './EventTimeline.vue'

const planning = ref<PlanningReport | null>(null)
const timeline = ref<EventTimelineReport | null>(null)
const loading = ref(false)
const error = ref('')
const timelineError = ref('')
const goalNotice = ref('')

const formOpen = ref(false)
const saving = ref(false)
const form = ref({ resource: '小判', target: 100000, deadline: '', note: '' })

function localToday() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

function fmt(value: number | null | undefined) {
  return value == null ? '—' : Math.round(value).toLocaleString()
}

function goalDeadline(goal: PlanningGoalAdvice) {
  if (!goal.deadline_at) return goal.deadline
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
    hour12: false, timeZone: 'Asia/Shanghai',
  }).format(new Date(goal.deadline_at))
}

const statusLabel: Record<string, string> = {
  done: '已达成',
  on_track: '来得及',
  behind: '要加把劲',
  active: '进行中',
  expired: '已到期',
  unknown: '数据不足',
}

const eventGoalNames = computed(() => (
  (planning.value?.goals || [])
    .filter(goal => goal.kind === 'event' && goal.event)
    .map(goal => String(goal.event))
))

function goalHeadline(goal: PlanningGoalAdvice) {
  if (goal.status === 'done') return `已经攒够 ${fmt(goal.target)} ${goal.resource}`
  if (goal.status === 'on_track') return '照现在的速度来得及'
  if (goal.status === 'expired') return '这个目标已经到期'
  if (goal.status === 'unknown' && goal.goal_mode === 'stock_target' && goal.shortfall != null) return `还差 ${fmt(goal.shortfall)} ${goal.resource}`
  if (goal.status === 'unknown') return '还缺一些库存记录'
  if (goal.status === 'active' && goal.shortfall != null) return `还差 ${fmt(goal.shortfall)} ${goal.resource}`
  if (goal.shortfall != null) return `还差 ${fmt(goal.shortfall)} ${goal.resource}`
  return '需要再加把劲'
}

function goalAction(goal: PlanningGoalAdvice) {
  if (goal.goal_mode === 'stock_target' && goal.status === 'active' && goal.floors_needed != null) {
    return `结束前还要挖约 ${fmt(goal.floors_needed)} 层，按剩余时间约每天 ${fmt(goal.floors_per_day)} 层。`
  }
  if (goal.goal_mode === 'stock_target' && goal.status === 'unknown') return '再挖几层，单层收益稳定后会自动换算。'
  if (goal.status === 'behind' && goal.extra_daily != null) {
    const floors = goal.resource === '小判' && goal.extra_floors != null ? `，约合每天多挖 ${fmt(goal.extra_floors)} 层大阪城` : ''
    return `接下来每天还需多攒 ${fmt(goal.extra_daily)} ${goal.resource}${floors}`
  }
  if (goal.status === 'on_track') return '保持最近的进账速度即可。'
  if (goal.status === 'done') return '目标已经完成，可以放心开打。'
  return ''
}

const estimateSaving = ref('')
const abacusGoalSaving = ref('')

async function saveEstimate(event: string, value: number) {
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
  goalNotice.value = ''
  abacusGoalSaving.value = abacus.event
  try {
    await api.addEventGoal(abacus.event)
    await load()
    goalNotice.value = `「${abacus.event}」目标已保存。`
    await scrollToElement('.planning-success')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '目标保存失败' }
  finally { abacusGoalSaving.value = '' }
}

async function goalFromStockTarget(abacus: EventAbacus, target: number) {
  goalNotice.value = ''
  if (!Number.isFinite(target) || target <= 0) {
    error.value = '先填一个想攒到的小判数。'
    return
  }
  if (abacus.available_now != null && target <= abacus.available_now) {
    error.value = '目标得比现有小判多一点。'
    return
  }
  abacusGoalSaving.value = abacus.event
  try {
    await api.addEventGoal(abacus.event, target)
    await load()
    goalNotice.value = `「${abacus.event}」目标已保存。`
    await scrollToElement('.planning-success')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '目标保存失败' }
  finally { abacusGoalSaving.value = '' }
}

async function load() {
  loading.value = true
  try {
    const [planningResult, timelineResult] = await Promise.allSettled([api.planning(), api.eventsTimeline()])
    if (planningResult.status === 'fulfilled') {
      planning.value = planningResult.value
      error.value = ''
    } else {
      error.value = planningResult.reason instanceof Error ? planningResult.reason.message : '规划建议读取失败'
    }
    if (timelineResult.status === 'fulfilled') {
      timeline.value = timelineResult.value
      timelineError.value = ''
    } else {
      timelineError.value = timelineResult.reason instanceof Error ? timelineResult.reason.message : '近期活动读取失败'
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '规划建议读取失败' }
  finally { loading.value = false }
}

async function scrollToElement(selector: string) {
  await nextTick()
  const element = document.querySelector(selector)
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  element?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
}

async function openCustomForm() {
  goalNotice.value = ''
  formOpen.value = true
  form.value = { ...form.value, note: '' }
  await scrollToElement('.planning-form')
}

async function saveGoal() {
  goalNotice.value = ''
  saving.value = true
  try {
    await api.addPlanningGoal({
      resource: form.value.resource,
      target: Number(form.value.target),
      deadline: form.value.deadline,
      note: form.value.note,
    })
    formOpen.value = false
    form.value = { resource: '小判', target: 100000, deadline: '', note: '' }
    await load()
    goalNotice.value = '目标已保存。'
    await scrollToElement('.planning-success')
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
    <p v-if="goalNotice" class="planning-success" role="status">✓ {{ goalNotice }}</p>

    <form v-if="formOpen" class="planning-form" @submit.prevent="saveGoal">
      <header>
        <div><h4>自定目标</h4><p>给自己定一个明确的数量和日期。</p></div>
        <button type="button" class="planning-close" aria-label="关闭目标表单" @click="formOpen = false">×</button>
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
        <button type="button" class="secondary" @click="formOpen = false">取消</button>
      </div>
    </form>

    <section v-if="planning?.goals.length" class="planning-section planning-goals-section">
      <header>
        <div><h4>我的目标</h4><p>最需要你做决定的事放在最前面。</p></div>
      </header>
      <div class="planning-goal-list">
        <article v-for="goal in planning.goals" :key="goal.id" class="planning-goal" :class="goal.status">
          <header>
            <span><b>{{ goal.note || `${goal.resource}目标` }}</b><small>{{ goal.goal_mode === 'stock_target' ? '活动目标' : goal.kind === 'event' ? '活动预算' : '手动目标' }} · {{ goalDeadline(goal) }} 截止</small></span>
            <em>{{ statusLabel[goal.status] || goal.status }}</em>
            <button type="button" class="planning-delete" title="删掉这个目标" @click="removeGoal(goal.id)">×</button>
          </header>
          <strong class="planning-goal-result">{{ goalHeadline(goal) }}</strong>
          <p v-if="goalAction(goal)" class="planning-next-action">{{ goalAction(goal) }}</p>
          <div class="planning-goal-metrics">
            <span><small>当前</small><b>{{ fmt(goal.current) }}</b></span>
            <span><small>目标</small><b>{{ fmt(goal.target) }}</b></span>
            <span><small>还剩</small><b>{{ Math.max(0, goal.days_left) }} 天</b></span>
            <span><small>{{ goal.goal_mode === 'stock_target' ? '还需挖' : '到期预计' }}</small><b>{{ goal.goal_mode === 'stock_target' ? goal.floors_needed == null ? '待实测' : `${fmt(goal.floors_needed)} 层` : fmt(goal.projected) }}</b></span>
          </div>
          <details>
            <summary>查看预测依据</summary>
            <p>{{ goal.message }}</p>
          </details>
        </article>
      </div>
    </section>

    <EventTimeline
      id="event-timeline"
      :timeline="timeline"
      :abacuses="planning?.events || []"
      :goal-names="eventGoalNames"
      :loading="loading"
      :error="timelineError"
      :estimate-saving="estimateSaving"
      :goal-saving="abacusGoalSaving"
      @save-estimate="saveEstimate"
      @add-goal="goalFromAbacus"
      @add-stock-goal="goalFromStockTarget"
    />

  </section>
</template>

<style scoped>
.planning-panel { display: grid; gap: 12px; }
.planning-hero { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 18px; background: linear-gradient(110deg, var(--fox-gold-pale), var(--paper-card)); border: 1px solid var(--paper-line); border-left: 4px solid var(--fox-gold); border-radius: 12px; }
.planning-hero small { color: var(--fox-gold-deep); font-weight: 700; letter-spacing: .08em; }
.planning-hero h3 { margin: 2px 0 0; font-size: 20px; }
.planning-hero p, .planning-section > header p, .planning-form header p { margin: 3px 0 0; color: var(--ink-dim); font-size: 13px; }
.planning-error { margin: 0; padding: 10px 12px; color: #9f3d28; background: #f9e6df; border: 1px solid #d6a394; border-radius: 10px; }
.planning-success { margin: 0; padding: 9px 12px; color: #426b36; background: color-mix(in srgb, #dcebd6 72%, var(--paper-card)); border: 1px solid #a8c59c; border-radius: 10px; font-size: 13px; font-weight: 700; }
.planning-section, .planning-form { padding: 16px 18px; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; }
.planning-section > header, .planning-form > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.planning-section h4, .planning-form h4 { margin: 0; font-size: 16px; }
.planning-close { padding: 0 5px; color: var(--ink-dim); background: transparent; border: 0; font-size: 20px; cursor: pointer; }
.planning-form-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.planning-form label { display: grid; gap: 5px; color: var(--ink-dim); font-size: 12px; }
.planning-form input, .planning-form select { width: 100%; min-width: 0; }
.planning-form-actions { display: flex; gap: 8px; margin-top: 12px; }
.planning-goal-list { display: grid; gap: 10px; margin-top: 12px; }
.planning-goals-section { scroll-margin-top: 12px; }
.planning-goal { padding: 14px 16px; background: var(--paper); border: 1px solid var(--paper-line); border-left: 5px solid var(--paper-line); border-radius: 10px; }
.planning-goal.done { border-left-color: #4d7a3a; }
.planning-goal.on_track { border-left-color: var(--fox-gold); }
.planning-goal.behind { border-left-color: #b0492e; }
.planning-goal.active { border-left-color: #5b813f; }
.planning-goal > header { display: flex; align-items: flex-start; gap: 8px; }
.planning-goal > header > span { display: grid; gap: 1px; min-width: 0; }
.planning-goal > header small { color: var(--ink-dim); font-size: 11px; }
.planning-goal > header em { margin-left: auto; padding: 2px 9px; color: var(--ink-dim); border: 1px solid var(--paper-line); border-radius: 999px; font-size: 11px; font-style: normal; white-space: nowrap; }
.planning-goal.behind > header em { color: #9f3d28; border-color: #c98673; }
.planning-goal.on_track > header em { color: var(--fox-gold-deep); border-color: var(--fox-gold); }
.planning-goal.active > header em { color: #426b36; border-color: #77a164; }
.planning-delete { padding: 0 3px; color: var(--ink-dim); background: transparent; border: 0; font-size: 17px; cursor: pointer; }
.planning-goal-result { display: block; margin-top: 13px; font-size: clamp(22px, 3vw, 30px); line-height: 1.1; }
.planning-next-action { margin: 7px 0 0; color: #9f3d28; }
.planning-goal-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 14px; border: 1px solid var(--paper-line); }
.planning-goal-metrics span { display: grid; gap: 3px; min-width: 0; padding: 9px 11px; border-left: 1px solid var(--paper-line); }
.planning-goal-metrics span:first-child { border-left: 0; }
.planning-goal-metrics small { color: var(--ink-dim); font-size: 11px; }
.planning-goal-metrics b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.planning-panel details { margin-top: 10px; color: var(--ink-dim); font-size: 12px; }
.planning-panel summary { color: var(--fox-gold-deep); cursor: pointer; }
.planning-panel details p { margin: 7px 0 0; line-height: 1.6; }
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
  .planning-section, .planning-form { padding: 14px; }
  .planning-form-fields { grid-template-columns: 1fr; }
}
</style>
