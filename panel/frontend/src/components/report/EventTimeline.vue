<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { EventAbacus, EventTimelineCandidate, EventTimelineEntry, EventTimelineReport, PlanningGoalAdvice } from '../../types'

const props = defineProps<{
  timeline: EventTimelineReport | null
  abacuses: EventAbacus[]
  goals: PlanningGoalAdvice[]
  loading?: boolean
  error?: string
  estimateSaving?: string
  goalSaving?: string
}>()

const emit = defineEmits<{
  (event: 'save-estimate', name: string, value: number): void
  (event: 'add-goal', abacus: EventAbacus): void
  (event: 'add-stock-goal', abacus: EventAbacus, target: number): void
}>()

const estimateInputs = ref<Record<string, string>>({})
const targetInputs = ref<Record<string, string>>({})

watch(() => props.abacuses, (items) => {
  for (const item of items) {
    if (item.keys_per_run != null) estimateInputs.value[item.event] = String(item.keys_per_run)
  }
}, { immediate: true })

watch(() => props.goals, (items) => {
  for (const item of items) {
    if (item.event && item.goal_mode === 'stock_target') targetInputs.value[item.event] = String(item.target)
  }
}, { immediate: true })

const abacusByName = computed(() => new Map(props.abacuses.map(item => [item.event, item])))
const goalByEvent = computed(() => new Map(props.goals.filter(item => item.event).map(item => [item.event!, item])))
const activeGroups = computed(() => [
  { key: 'ongoing', title: '正在进行', items: props.timeline?.ongoing || [] },
  { key: 'upcoming', title: '即将开始', items: props.timeline?.upcoming || [] },
].filter(group => group.items.length))
const hasFormalEvents = computed(() => activeGroups.value.length > 0 || Boolean(props.timeline?.later.length))

function fmt(value: number | null | undefined) {
  return value == null ? '—' : Math.round(value).toLocaleString()
}

function parseDate(value: string) {
  return new Date(value.includes('T') ? value : `${value}T00:00:00+08:00`)
}

function shortDate(value: string | null | undefined) {
  if (!value) return '日期待定'
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', timeZone: 'Asia/Shanghai' }).format(parseDate(value))
}

function dateTime(value: string | null, fallback: string | null) {
  if (!value) return shortDate(fallback)
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai',
  }).format(parseDate(value))
}

function clockTime(value: string | null) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai',
  }).format(parseDate(value))
}

function eventRange(entry: EventTimelineEntry) {
  return `${dateTime(entry.start_at, entry.start_date)} → ${dateTime(entry.end_at, entry.end_date)}`
}

function axisMoment(entry: EventTimelineEntry, group: string) {
  if (group === 'ongoing') {
    if (entry.days_left === 0) return '今天结束'
    if (entry.days_left === 1) return '明天结束'
    return entry.days_left == null ? '进行中' : `还剩 ${entry.days_left} 天`
  }
  if (entry.days_until_start === 0) return entry.start_at ? `今天 ${clockTime(entry.start_at)}` : '今天开始'
  if (entry.days_until_start === 1) return entry.start_at ? `明天 ${clockTime(entry.start_at)}` : '明天开始'
  return `${shortDate(entry.start_at || entry.start_date)} 开始`
}

function abacusFor(entry: EventTimelineEntry) {
  return abacusByName.value.get(entry.name)
}

function goalFor(entry: EventTimelineEntry) {
  return goalByEvent.value.get(entry.name)
}

function supportsTokenLearning(entry: EventTimelineEntry) {
  return Boolean(abacusFor(entry)?.keys_total)
}

function experienceLabel(entry: EventTimelineEntry) {
  const source = abacusFor(entry)?.keys_source
  if (source === 'measured') return '本期实测'
  if (source === 'history') return '参考上期'
  if (source === 'estimate') return '临时估计'
  return '第一次参加'
}

function submitEstimate(entry: EventTimelineEntry) {
  const value = Number(estimateInputs.value[entry.name])
  emit('save-estimate', entry.name, value)
}

function submitStockGoal(entry: EventTimelineEntry) {
  const abacus = abacusFor(entry)
  if (abacus) emit('add-stock-goal', abacus, Number(targetInputs.value[entry.name]))
}

function budgetText(entry: EventTimelineEntry) {
  const budget = entry.budget
  if (!budget) return ''
  if (budget.koban_cost === 0) return '免费票够用，不需要额外准备小判。'
  if (budget.sufficient === true) return `预计需要 ${fmt(budget.koban_cost)} 小判，家底已经备齐。`
  if (budget.shortfall != null) return `目前还差 ${fmt(budget.shortfall)} 小判。`
  return budget.message
}

function candidateName(candidate: EventTimelineCandidate) {
  return candidate.name || candidate.section || '未识别活动'
}

function candidateRange(candidate: EventTimelineCandidate) {
  if (!candidate.start_at && !candidate.end_at) return '时间待核对'
  return `${dateTime(candidate.start_at, null)} → ${dateTime(candidate.end_at, null)}`
}
</script>

<template>
  <section class="event-timeline-card">
    <header class="timeline-heading">
      <div>
        <small>活动日程</small>
        <h4>正在进行和即将开始</h4>
      </div>
      <span v-if="timeline?.calendar_stale" class="timeline-stale">日历可能不是最新</span>
    </header>

    <p v-if="error" class="timeline-error">{{ error }}</p>
    <div v-else-if="loading && !timeline" class="timeline-empty">正在整理近期活动……</div>
    <div v-else-if="timeline">
      <div v-if="activeGroups.length" class="timeline-axis">
        <section v-for="group in activeGroups" :key="group.key" class="timeline-group">
          <header class="timeline-group-heading">
            <b>{{ group.title }}</b>
          </header>

          <article v-for="entry in group.items" :key="entry.name" class="timeline-axis-entry" :class="`is-${group.key}`">
            <time>{{ axisMoment(entry, group.key) }}</time>
            <span class="timeline-rail" aria-hidden="true"><i /></span>
            <div class="timeline-event-card">
              <span class="event-mobile-moment">{{ axisMoment(entry, group.key) }}</span>
              <header>
                <div>
                  <span class="event-tags">
                    <span class="event-state">{{ group.key === 'ongoing' ? '进行中' : '即将开始' }}</span>
                    <span v-if="supportsTokenLearning(entry)" class="experience-tag" :class="`source-${abacusFor(entry)?.keys_source || 'new'}`">{{ experienceLabel(entry) }}</span>
                  </span>
                  <h5>{{ entry.name }}</h5>
                </div>
                <span class="event-range">{{ eventRange(entry) }}</span>
              </header>

              <p v-if="abacusFor(entry)?.message || entry.note" class="event-summary">{{ abacusFor(entry)?.message || entry.note }}</p>

              <div v-if="entry.budget && entry.budget.koban_cost != null" class="event-budget" :class="{ ready: entry.budget.sufficient === true || entry.budget.koban_cost === 0 }">
                <span>
                  <small>{{ entry.budget.sufficient === true || entry.budget.koban_cost === 0 ? '活动预算' : '预算缺口' }}</small>
                  <b>{{ entry.budget.sufficient === true || entry.budget.koban_cost === 0 ? '已经备齐' : `${fmt(entry.budget.shortfall)} 小判` }}</b>
                </span>
                <p>{{ budgetText(entry) }}</p>
              </div>

              <div v-if="abacusFor(entry)?.goal_mode === 'stock_target'" class="event-stock-target">
                <div v-if="goalFor(entry)" class="stock-goal-linked">
                  <span><small>已立目标</small><b>{{ fmt(goalFor(entry)?.target) }} {{ goalFor(entry)?.resource }}</b></span>
                  <details>
                    <summary>修改</summary>
                    <div><input v-model="targetInputs[entry.name]" type="number" :min="(abacusFor(entry)?.available_now || 0) + 1" max="100000000" step="10000"><button type="button" class="primary" :disabled="goalSaving === entry.name" @click="submitStockGoal(entry)">{{ goalSaving === entry.name ? '保存中……' : '保存' }}</button></div>
                  </details>
                </div>
                <template v-else>
                  <label>收摊时想把小判攒到多少？
                    <input v-model="targetInputs[entry.name]" type="number" :min="(abacusFor(entry)?.available_now || 0) + 1" max="100000000" step="10000" placeholder="例如 1,000,000">
                  </label>
                  <button type="button" class="primary" :disabled="goalSaving === entry.name" @click="submitStockGoal(entry)">{{ goalSaving === entry.name ? '正在立目标……' : '立为目标' }}</button>
                  <p v-if="abacusFor(entry)?.yield_per_floor" class="stock-yield">最近 {{ fmt(abacusFor(entry)?.yield_sessions) }} 次实测，每层约 {{ fmt(abacusFor(entry)?.yield_per_floor) }} 小判。</p>
                  <p v-else class="stock-yield">还没有单层收益样本；先立目标，挖几层后会自动换算。</p>
                </template>
              </div>

              <div v-else-if="abacusFor(entry)?.keys_total && abacusFor(entry)?.keys_per_run == null" class="event-estimate">
                <label>你一圈通常拿几把钥匙？
                  <input v-model="estimateInputs[entry.name]" type="number" min="1" max="200" step="1" placeholder="填个估计">
                </label>
                <button type="button" class="primary" :disabled="estimateSaving === entry.name" @click="submitEstimate(entry)">{{ estimateSaving === entry.name ? '计算中……' : '帮我算' }}</button>
              </div>

              <div v-else-if="abacusFor(entry)?.koban_cost && entry.budget?.sufficient !== true && entry.budget?.koban_cost !== 0" class="event-actions">
                <span v-if="goalFor(entry)">已加入“当前目标”</span>
                <button v-else type="button" class="primary" :disabled="goalSaving === entry.name" @click="emit('add-goal', abacusFor(entry)!)">{{ goalSaving === entry.name ? '正在立目标……' : '把缺口立成目标' }}</button>
              </div>

              <details v-if="entry.note && entry.note !== abacusFor(entry)?.message">
                <summary>查看活动说明</summary>
                <p>{{ entry.note }}</p>
              </details>
            </div>
          </article>
        </section>
      </div>

      <section v-if="timeline.later.length" class="timeline-later">
        <header><b>稍后</b><span>更远的活动先收成一行</span></header>
        <div class="later-list">
          <article v-for="entry in timeline.later" :key="entry.name">
            <time>{{ shortDate(entry.start_at || entry.start_date) }}</time>
            <b>{{ entry.name }}</b>
            <span>{{ eventRange(entry) }}</span>
          </article>
        </div>
      </section>

      <div v-if="!hasFormalEvents" class="timeline-empty">
        <b>近期没有要开打的活动</b>
        <span>有正式日期后会自动排到这里。</span>
      </div>

      <details v-if="timeline.unverified.length" class="timeline-unverified">
        <summary>
          <span><b>待确认日期</b><small>公告里抓到了 {{ timeline.unverified.length }} 条，还没放上正式时间轴</small></span>
          <em>{{ timeline.unverified.length }}</em>
        </summary>
        <div>
          <a v-for="(candidate, index) in timeline.unverified" :key="`${candidate.name}-${candidate.start_at}-${index}`" :href="candidate.url || undefined" target="_blank" rel="noopener">
            <span><b>{{ candidateName(candidate) }}</b><small>{{ candidate.announcement || '官方公告' }}</small></span>
            <time>{{ candidateRange(candidate) }}</time>
          </a>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.event-timeline-card { padding: 16px 18px; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; }
.timeline-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.timeline-heading small { color: var(--fox-gold-deep); font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.timeline-heading h4 { margin: 2px 0 0; font-size: 16px; }
.timeline-stale { flex: none; padding: 3px 8px; color: #936429; background: var(--fox-gold-pale); border-radius: 999px; font-size: 11px; }
.timeline-error { margin: 12px 0 0; padding: 10px 12px; color: #9f3d28; background: #f9e6df; border-radius: 8px; font-size: 13px; }
.timeline-axis { display: grid; gap: 16px; margin-top: 16px; }
.timeline-group { display: grid; gap: 9px; }
.timeline-group-heading { display: flex; align-items: baseline; gap: 8px; padding-left: 110px; }
.timeline-group-heading b { font-size: 13px; }
.timeline-group-heading span { color: var(--ink-dim); font-size: 11px; }
.timeline-axis-entry { display: grid; grid-template-columns: 84px 18px minmax(0, 1fr); align-items: stretch; }
.timeline-axis-entry > time { padding: 11px 8px 0 0; color: var(--ink-dim); font-size: 11px; font-weight: 700; text-align: right; }
.timeline-rail { position: relative; display: flex; justify-content: center; }
.timeline-rail::after { position: absolute; top: 0; bottom: -10px; width: 1px; background: var(--paper-line); content: ''; }
.timeline-rail i { position: relative; z-index: 1; width: 9px; height: 9px; margin-top: 14px; background: var(--paper-card); border: 2px solid var(--fox-gold); border-radius: 50%; }
.is-ongoing .timeline-rail i { background: #5b813f; border-color: #5b813f; box-shadow: 0 0 0 4px color-mix(in srgb, #5b813f 14%, transparent); }
.timeline-event-card { min-width: 0; padding: 13px 15px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 10px; }
.is-ongoing .timeline-event-card { border-left: 4px solid #5b813f; }
.is-upcoming .timeline-event-card { border-left: 4px solid var(--fox-gold); }
.timeline-event-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.timeline-event-card > header > div { display: grid; gap: 2px; min-width: 0; }
.event-tags { display: flex; align-items: center; gap: 6px; }
.event-state { color: var(--fox-gold-deep); font-size: 10px; font-weight: 700; letter-spacing: .06em; }
.is-ongoing .event-state { color: #4d7137; }
.experience-tag { padding: 1px 6px; color: var(--ink-dim); background: var(--paper-panel); border-radius: 999px; font-size: 9px; font-weight: 700; letter-spacing: .03em; }
.experience-tag.source-measured { color: #426b36; background: color-mix(in srgb, #dcebd6 76%, var(--paper-card)); }
.experience-tag.source-history { color: #805f20; background: var(--fox-gold-pale); }
.experience-tag.source-estimate { color: #765e50; background: color-mix(in srgb, #e9ded4 74%, var(--paper-card)); }
.timeline-event-card h5 { margin: 0; font-size: 16px; }
.event-range { flex: none; color: var(--ink-dim); font-size: 11px; white-space: nowrap; }
.event-mobile-moment { display: none; }
.event-summary { margin: 9px 0 0; color: var(--ink-dim); font-size: 13px; line-height: 1.55; }
.event-budget { display: flex; align-items: center; gap: 14px; margin-top: 11px; padding: 9px 11px; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); border-radius: 8px; }
.event-budget.ready { background: color-mix(in srgb, #dcebd6 72%, var(--paper-card)); }
.event-budget > span { display: grid; flex: 0 0 auto; gap: 1px; min-width: 92px; }
.event-budget small { color: var(--ink-dim); font-size: 10px; }
.event-budget b { color: #9f3d28; font-size: 14px; }
.event-budget.ready b { color: #426b36; }
.event-budget p { margin: 0; color: var(--ink-dim); font-size: 12px; }
.event-estimate { display: flex; align-items: flex-end; gap: 8px; margin-top: 11px; padding: 10px 11px; background: var(--fox-gold-pale); border-radius: 8px; }
.event-estimate label { display: grid; flex: 1 1 auto; gap: 4px; font-size: 12px; }
.event-estimate input { width: min(190px, 100%); background: var(--paper-card); }
.event-stock-target { display: grid; grid-template-columns: minmax(180px, 1fr) auto; align-items: end; gap: 7px 9px; margin-top: 11px; padding: 11px; background: color-mix(in srgb, #dcebd6 62%, var(--paper-card)); border-radius: 8px; }
.event-stock-target label { display: grid; gap: 4px; color: var(--ink); font-size: 12px; font-weight: 700; }
.event-stock-target input { width: min(260px, 100%); background: var(--paper-card); font-weight: 400; }
.event-stock-target .stock-yield { grid-column: 1 / -1; color: var(--ink-dim); font-size: 11px; }
.event-stock-target .stock-yield { margin: 0; }
.stock-goal-linked { display: flex; grid-column: 1 / -1; align-items: center; justify-content: space-between; gap: 12px; }
.stock-goal-linked > span { display: grid; gap: 1px; }
.stock-goal-linked small { color: #426b36; font-size: 10px; font-weight: 700; }
.stock-goal-linked details { margin: 0; }
.stock-goal-linked details[open] { width: min(330px, 100%); }
.stock-goal-linked details > div { display: flex; gap: 7px; margin-top: 6px; }
.stock-goal-linked input { min-width: 0; }
.event-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 11px; }
.event-actions span { color: var(--ink-dim); font-size: 12px; }
.timeline-event-card details { margin-top: 9px; color: var(--ink-dim); font-size: 12px; }
.timeline-event-card summary { color: var(--fox-gold-deep); cursor: pointer; }
.timeline-event-card details p { margin: 6px 0 0; line-height: 1.6; }
.timeline-later { margin-top: 16px; padding-top: 13px; border-top: 1px dashed var(--paper-line); }
.timeline-later > header { display: flex; align-items: baseline; gap: 8px; margin-bottom: 7px; }
.timeline-later > header b { font-size: 13px; }
.timeline-later > header span { color: var(--ink-dim); font-size: 11px; }
.later-list { display: grid; }
.later-list article { display: grid; grid-template-columns: 72px minmax(120px, .7fr) minmax(180px, 1fr); gap: 10px; padding: 8px 10px; border-top: 1px solid color-mix(in srgb, var(--paper-line) 65%, transparent); font-size: 12px; }
.later-list article:first-child { border-top: 0; }
.later-list time, .later-list span { color: var(--ink-dim); }
.timeline-empty { display: grid; gap: 3px; margin-top: 14px; padding: 16px; color: var(--ink-dim); background: var(--paper); border: 1px dashed var(--paper-line); border-radius: 9px; font-size: 13px; }
.timeline-empty b { color: var(--ink); }
.timeline-unverified { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--paper-line); }
.timeline-unverified > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--ink); cursor: pointer; list-style: none; }
.timeline-unverified > summary::-webkit-details-marker { display: none; }
.timeline-unverified > summary > span { display: grid; gap: 2px; }
.timeline-unverified summary small { color: var(--ink-dim); font-size: 11px; font-weight: 400; }
.timeline-unverified summary em { display: grid; place-items: center; width: 24px; height: 24px; color: var(--fox-gold-deep); background: var(--fox-gold-pale); border-radius: 50%; font-size: 11px; font-style: normal; }
.timeline-unverified > div { display: grid; gap: 6px; margin-top: 9px; }
.timeline-unverified a { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 10px; color: var(--ink); background: var(--paper); border-radius: 8px; text-decoration: none; }
.timeline-unverified a:hover { background: var(--fox-gold-pale); }
.timeline-unverified a > span { display: grid; gap: 1px; min-width: 0; }
.timeline-unverified a small, .timeline-unverified a time { color: var(--ink-dim); font-size: 11px; }
.timeline-unverified a time { flex: none; }
@media (max-width: 700px) {
  .event-timeline-card { padding: 14px; }
  .timeline-group-heading { padding-left: 92px; }
  .timeline-axis-entry { grid-template-columns: 67px 16px minmax(0, 1fr); }
  .timeline-event-card > header { flex-direction: column; gap: 5px; }
  .event-range { white-space: normal; }
  .later-list article { grid-template-columns: 62px minmax(0, 1fr); }
  .later-list article span { grid-column: 2; }
}
@media (max-width: 520px) {
  .timeline-heading { flex-direction: column; gap: 7px; }
  .timeline-axis { gap: 14px; }
  .timeline-group-heading { padding-left: 0; }
  .timeline-axis-entry { grid-template-columns: minmax(0, 1fr); }
  .timeline-axis-entry > time, .timeline-rail { display: none; }
  .event-mobile-moment { display: block; margin-bottom: 5px; color: var(--fox-gold-deep); font-size: 11px; font-weight: 700; }
  .is-ongoing .event-mobile-moment { color: #4d7137; }
  .timeline-event-card { padding: 12px; }
  .event-budget, .event-estimate { align-items: stretch; flex-direction: column; }
  .event-estimate input, .event-estimate button, .event-stock-target input, .event-stock-target button { width: 100%; max-width: none; }
  .event-stock-target { grid-template-columns: 1fr; }
  .event-stock-target .stock-yield { grid-column: 1; }
  .stock-goal-linked { align-items: flex-start; flex-direction: column; }
  .stock-goal-linked details, .stock-goal-linked details[open] { width: 100%; }
  .stock-goal-linked details > div { align-items: stretch; flex-direction: column; }
  .event-actions { align-items: stretch; flex-direction: column; }
  .event-actions button { width: 100%; }
  .timeline-unverified a { align-items: flex-start; flex-direction: column; gap: 4px; }
}
</style>
