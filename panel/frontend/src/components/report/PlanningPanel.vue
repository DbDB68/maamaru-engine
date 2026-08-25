<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../../api'
import type { EventAbacus, EventsCalendar, PlanningReport } from '../../types'
import { resourceNames } from './reportModel'

const planning = ref<PlanningReport | null>(null)
const calendar = ref<EventsCalendar | null>(null)
const loading = ref(false)
const error = ref('')

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
function signedRate(value: number | null | undefined) {
  return value == null ? '—' : `${Math.round(value) >= 0 ? '+' : ''}${Math.round(value).toLocaleString()}`
}

const statusLabel: Record<string, string> = {
  done: '已达成',
  on_track: '进度在线',
  behind: '要加把劲',
  expired: '已到期',
  unknown: '数据不足',
}

// ---- 近期活动（B 站官方公告日历，云服务器每天扒一次） ----

const upcoming = computed(() => {
  const today = localToday()
  return (calendar.value?.announcements || [])
    .filter(item => item.update_date && item.update_date >= today)
    .sort((a, b) => a.update_date!.localeCompare(b.update_date!))
    .slice(0, 4)
})

function shortDate(iso: string | null) {
  if (!iso) return ''
  const [, month, day] = iso.split('-').map(Number)
  return `${month}月${day}日`
}

function goalFromEvent(updateDate: string, eventName: string) {
  formOpen.value = true
  form.value = { ...form.value, deadline: updateDate, note: eventName }
}

// ---- 活动算盘 ----

const estimateInputs = ref<Record<string, string>>({})
const estimateSaving = ref('')
const abacusGoalSaving = ref('')

async function saveEstimate(event: string) {
  estimateSaving.value = event
  try {
    await api.saveEventEstimate(event, Number(estimateInputs.value[event]))
    await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '场均预估保存失败' }
  finally { estimateSaving.value = '' }
}

async function goalFromAbacus(abacus: EventAbacus) {
  const deadline = abacus.end_date || abacus.start_date
  if (!deadline || !abacus.koban_cost) return
  abacusGoalSaving.value = abacus.event
  try {
    const current = planning.value?.current?.['小判'] ?? 0
    await api.addPlanningGoal({
      resource: '小判',
      target: Math.round(current + abacus.koban_cost),
      deadline,
      note: `${abacus.event}门票钱`,
    })
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
    <header>
      <div>
        <h3>攒钱小目标</h3>
        <p v-if="planning">狐之助按最近 {{ planning.rate_window_days }} 天的进出账速度帮你算日子</p>
      </div>
      <button v-if="!formOpen" type="button" class="secondary" @click="formOpen = true">＋ 立个小目标</button>
    </header>
    <p v-if="error" class="planning-error">{{ error }}</p>

    <div v-if="upcoming.length || calendar?.reason" class="planning-events">
      <small class="planning-events-title">
        📣 近期公告（B 站官方号）
        <em v-if="calendar?.stale">日历是旧缓存，服务器暂时联系不上</em>
      </small>
      <p v-if="calendar?.reason && !upcoming.length" class="planning-empty">{{ calendar.reason }}</p>
      <div v-for="item in upcoming" :key="item.title" class="planning-event-row">
        <b>{{ shortDate(item.update_date) }}</b>
        <span class="planning-event-names">
          <template v-for="name in item.events" :key="name">
            <a v-if="item.url" class="planning-event-chip" :href="item.url" target="_blank" rel="noopener" @click.stop>{{ name }}</a>
            <span v-else class="planning-event-chip">{{ name }}</span>
          </template>
        </span>
        <button type="button" class="planning-event-goal" @click="goalFromEvent(item.update_date!, item.events[0] || '')">按这天立目标</button>
      </div>
    </div>

    <div v-for="abacus in planning?.events || []" :key="abacus.event" class="planning-abacus">
      <div class="planning-goal-head">
        <b>🧮 {{ abacus.event }}</b>
        <span v-if="abacus.start_date">{{ shortDate(abacus.start_date) }} 开打<template v-if="abacus.end_date">，{{ shortDate(abacus.end_date) }} 收摊</template></span>
        <em v-if="abacus.keys_source === 'measured'" class="planning-abacus-tag measured">实测场均</em>
        <em v-else-if="abacus.keys_source === 'estimate'" class="planning-abacus-tag">估计场均</em>
      </div>
      <p class="planning-message">🦊 {{ abacus.message }}</p>
      <small v-if="abacus.note">{{ abacus.note }}</small>
      <div class="planning-abacus-actions">
        <label>场均钥匙
          <input v-model="estimateInputs[abacus.event]" type="number" min="1" max="200" step="1" placeholder="填个估计">
        </label>
        <button type="button" class="secondary" :disabled="estimateSaving === abacus.event" @click="saveEstimate(abacus.event)">{{ estimateSaving === abacus.event ? '记账中……' : '记下' }}</button>
        <button v-if="abacus.koban_cost && (abacus.end_date || abacus.start_date)" type="button" :disabled="abacusGoalSaving === abacus.event" @click="goalFromAbacus(abacus)">立成攒钱目标（{{ fmt(abacus.koban_cost) }} 小判）</button>
      </div>
    </div>

    <form v-if="formOpen" class="planning-form" @submit.prevent="saveGoal">
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
      <label>备注（可选）
        <input v-model="form.note" maxlength="50" placeholder="比如：江户城门票钱">
      </label>
      <div class="planning-form-actions">
        <button type="submit" class="primary" :disabled="saving">{{ saving ? '记账中……' : '立目标' }}</button>
        <button type="button" class="secondary" @click="formOpen = false">先不立了</button>
      </div>
    </form>

    <p v-if="planning && !planning.goals.length && !formOpen" class="planning-empty">
      还没立目标。比如「9 月 10 日前攒 30 万小判」——狐之助会盯着每天的进账告诉你来不来得及。
    </p>

    <article v-for="goal in planning?.goals || []" :key="goal.id" class="planning-goal" :class="goal.status">
      <div class="planning-goal-head">
        <b>{{ goal.resource }}</b>
        <span>目标 {{ fmt(goal.target) }}</span>
        <span v-if="goal.note" class="planning-note">{{ goal.note }}</span>
        <em class="planning-status">{{ statusLabel[goal.status] || goal.status }}</em>
        <button type="button" class="planning-delete" title="删掉这个目标" @click="removeGoal(goal.id)">×</button>
      </div>
      <p class="planning-message">🦊 {{ goal.message }}</p>
      <small>
        {{ goal.deadline }} 截止（还剩 {{ goal.days_left }} 天）
        <template v-if="goal.current != null"> · 当前 {{ fmt(goal.current) }}</template>
        <template v-if="goal.rate != null"> · 近日 {{ signedRate(goal.rate) }}/天</template>
        <template v-if="goal.projected != null"> · 到期预计 {{ fmt(goal.projected) }}</template>
      </small>
    </article>
  </section>
</template>

<style scoped>
.planning-panel { background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; padding: 12px 16px; }
.planning-panel > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.planning-panel h3 { margin: 0; }
.planning-panel header p { margin: 2px 0 0; color: var(--ink-dim); font-size: 13px; }
.planning-error { color: #b0492e; }
.planning-events { margin-top: 10px; padding: 8px 12px; background: var(--paper); border: 1px dashed var(--paper-line); border-radius: 10px; }
.planning-events-title { color: var(--ink-dim); }
.planning-events-title em { font-style: normal; color: #b0492e; margin-left: 8px; }
.planning-event-row { display: flex; align-items: baseline; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.planning-event-row > b { color: var(--fox-gold-deep); white-space: nowrap; }
.planning-event-names { display: flex; gap: 6px; flex-wrap: wrap; }
.planning-event-chip { background: var(--fox-gold-pale); border: 1px solid var(--fox-gold); border-radius: 999px; padding: 1px 10px; font-size: 13px; color: var(--ink); text-decoration: none; }
.planning-event-goal { margin-left: auto; border: 1px solid var(--paper-line); background: var(--paper-card); color: var(--ink-dim); border-radius: 999px; padding: 2px 10px; font-size: 12px; cursor: pointer; }
.planning-event-goal:hover { border-color: var(--fox-gold); color: var(--ink); }
.planning-abacus { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--fox-gold); border-radius: 10px; background: var(--paper); }
.planning-abacus small { color: var(--ink-dim); }
.planning-abacus-tag { font-style: normal; font-size: 12px; border: 1px solid var(--paper-line); border-radius: 999px; padding: 1px 10px; color: var(--ink-dim); }
.planning-abacus-tag.measured { color: #4d7a3a; border-color: #4d7a3a; }
.planning-abacus-actions { display: flex; align-items: flex-end; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.planning-abacus-actions label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ink-dim); }
.planning-abacus-actions input { width: 110px; }
.planning-empty { color: var(--ink-dim); font-size: 13px; margin: 10px 0 2px; }
.planning-form { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; padding: 12px; background: var(--paper); border: 1px solid var(--fox-gold); border-radius: 10px; }
.planning-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ink-dim); }
.planning-form input, .planning-form select { min-width: 140px; }
.planning-form-actions { display: flex; gap: 8px; align-items: flex-end; }
.planning-goal { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--paper-line); border-left-width: 4px; border-radius: 10px; background: var(--paper); }
.planning-goal.done { border-left-color: #4d7a3a; }
.planning-goal.on_track { border-left-color: var(--fox-gold); }
.planning-goal.behind { border-left-color: #b0492e; }
.planning-goal.expired, .planning-goal.unknown { border-left-color: var(--paper-line); }
.planning-goal-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.planning-note { color: var(--ink-dim); }
.planning-status { margin-left: auto; font-style: normal; font-size: 12px; border: 1px solid var(--paper-line); border-radius: 999px; padding: 1px 10px; color: var(--ink-dim); }
.planning-goal.done .planning-status { color: #4d7a3a; border-color: #4d7a3a; }
.planning-goal.behind .planning-status { color: #b0492e; border-color: #b0492e; }
.planning-goal.on_track .planning-status { color: var(--fox-gold-deep); border-color: var(--fox-gold); }
.planning-delete { border: 0; background: none; color: var(--ink-dim); font-size: 16px; cursor: pointer; padding: 0 4px; }
.planning-message { margin: 6px 0 4px; }
.planning-goal small { color: var(--ink-dim); }
</style>
