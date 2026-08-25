<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'
import type { PlanningReport } from '../../types'
import { resourceNames } from './reportModel'

const planning = ref<PlanningReport | null>(null)
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

async function load() {
  loading.value = true
  try {
    planning.value = await api.planning()
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
