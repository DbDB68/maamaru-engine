<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../../api'
import PixelControl from '../PixelControl.vue'
import SegmentedControl from '../SegmentedControl.vue'

const emit = defineEmits<{ goalSaved: [] }>()
const form = ref({ map_no: 1, mode: 'time', hours_per_day: 2, runs: 100, budget: 50000, free_runs: '', current_free: 0, price: '', minutes_per_run: '', deadline: '' })
type Estimate = { campaign: {name: string; source: string; start_at: string; end_at: string}; campaign_status: string; deadline: string; price: number; daily_free_runs: number; free_days: number; free_runs: number; free_source: string; sample_count: number; seconds_per_run: number | null; speed_source: string; runs: number | null; cost: number | null; hours: number | null; can_finish: boolean | null; remaining_hours: number }
const result = ref<Estimate | null>(null)
const metadata = ref<Estimate | null>(null)
const error = ref('')
const loading = ref(false)
const saving = ref(false)
const saved = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let revision = 0

const canSave = computed(() => result.value?.cost != null && result.value.cost > 0 && result.value.campaign_status !== '已结束')
const dateText = (value: string) => new Date(value).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false})

watch(form, () => {
  revision++
  saved.value = false
  loading.value = true
  clearTimeout(timer)
  timer = setTimeout(calculate, 450)
}, { deep: true })
onUnmounted(() => { clearTimeout(timer); revision++ })

async function calculate() {
  const requestRevision = revision
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/planning/gameplay', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(form.value) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '暂时无法计算')
    if (requestRevision !== revision) return
    metadata.value = data
    result.value = data
    localStorage.setItem('maamaru-yosari-plan-v2', JSON.stringify(form.value))
  } catch (e) {
    if (requestRevision !== revision) return
    result.value = null
    error.value = e instanceof Error ? e.message : '暂时无法计算'
  } finally {
    if (requestRevision === revision) loading.value = false
  }
}

async function saveGoal() {
  if (!canSave.value) return
  saving.value = true
  error.value = ''
  try {
    await api.addGameplayGoal(form.value)
    saved.value = true
    emit('goalSaved')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '活动预算保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  try { const value = localStorage.getItem('maamaru-yosari-plan-v2'); if (value) Object.assign(form.value, JSON.parse(value)) } catch { /* use defaults */ }
  void calculate()
})
</script>

<template>
  <section class="gameplay-planner">
    <header class="budget-heading">
      <div><span class="eyebrow">活动预算</span><h3>这期异去，准备怎么花</h3></div>
      <span v-if="metadata" class="event-badge">{{ metadata.campaign_status }} · 碎片掉率加成</span>
    </header>
    <p v-if="metadata" class="campaign">{{ metadata.campaign.name }} · 至 {{ dateText(metadata.campaign.end_at) }}</p>

    <div class="budget-result" aria-live="polite" :aria-busy="loading">
      <small v-if="loading">正在按你的方案更新…</small>
      <template v-if="result?.runs != null">
        <div><small>{{ form.mode === 'runs' ? '计划出阵' : '预计能打' }}</small><strong>{{ result.runs.toLocaleString() }}<em> 次</em></strong></div>
        <div><small>需要小判</small><strong>{{ result.cost?.toLocaleString() }}<em> 枚</em></strong></div>
        <div><small>大约用时</small><strong>{{ result.hours?.toFixed(1) }}<em> 小时</em></strong></div>
      </template>
      <template v-else-if="result">
        <div class="missing-pace"><strong>还差这张图的圈速</strong><span>跑过几圈后会自动采用实测，也可以在下方先填一个。</span></div>
      </template>
      <p v-else>{{ error || '正在帮你算这趟出阵…' }}</p>
    </div>

    <div class="budget-decision">
      <p v-if="result?.runs != null">每天 {{ form.hours_per_day }} 小时，最多花 {{ Number(form.budget).toLocaleString() }} 小判。保存后，它会作为一笔独立活动预算，并告诉你会让攒钱目标推迟多久。</p>
      <p v-else>先补一个圈速，才能把这套异去方案保存成活动预算。</p>
      <button type="button" class="primary" :disabled="!canSave || saving" @click="saveGoal">{{ saving ? '正在留预算……' : saved ? '活动预算已更新' : '按这个方案立为活动预算' }}</button>
    </div>
    <p v-if="error" class="planner-error">{{ error }}</p>

    <div class="outing-choice">
      <label>想去哪张图<PixelControl v-model="form.map_no" as="select" numeric><option :value="1">1-1 函馆</option><option :value="2">1-2 会津</option><option :value="3">1-3 宇都宫</option><option :value="4">1-4 鸟羽</option></PixelControl></label>
      <div><span>每天留多少时间</span><SegmentedControl :model-value="form.hours_per_day" @update:model-value="form.hours_per_day = Number($event)" label="每天出阵时间" :items="[{value: 1, label: '1 小时'}, {value: 2, label: '2 小时'}, {value: 3, label: '3 小时'}, {value: 6, label: '6 小时'}]" /></div>
    </div>

    <details class="adjustments"><summary>换个目标，或调整预算</summary>
      <div class="plan-fields">
        <label>怎么计划<PixelControl v-model="form.mode" as="select"><option value="time">看看这段时间能打多少</option><option value="runs">我有想打的次数</option></PixelControl></label>
        <label v-if="form.mode === 'runs'">想打几次<PixelControl v-model="form.runs" type="number" numeric min="0" /></label>
        <label>每天可用小时<PixelControl v-model="form.hours_per_day" type="number" numeric min="0.01" max="24" step="0.5" /></label>
        <label>最多花多少小判<PixelControl v-model="form.budget" type="number" numeric min="0" /></label>
        <label>改个截止时间<PixelControl v-model="form.deadline" type="datetime-local" /><small>留空就跟随本期活动</small></label>
        <label>现在剩几次免费提灯<PixelControl v-model="form.current_free" type="number" numeric min="0" /></label>
      </div>
    </details>
    <details class="adjustments"><summary>这笔账怎么算的</summary>
      <p v-if="metadata">按 {{ metadata.free_runs }} 次免费、付费每次 {{ metadata.price }} 小判估算。免费次数自动计未来完整日，今天剩余由你填写，截止当天暂不计入。</p>
      <p>可用时间按剩余天数折算，碎片掉率加成不代表必得两倍碎片。这里只做计划，不会启动游戏。</p>
      <div class="plan-fields">
        <label>每圈分钟（留空用实测）<PixelControl v-model="form.minutes_per_run" type="number" min="0.01" max="180" step="0.1" /></label>
        <label>手动覆盖免费总次数<PixelControl v-model="form.free_runs" type="number" min="0" /></label>
        <label>手动覆盖单次小判<PixelControl v-model="form.price" type="number" min="0" /></label>
      </div>
      <a v-if="metadata" :href="metadata.campaign.source" target="_blank" rel="noopener noreferrer">查看活动公告 ↗</a>
    </details>
  </section>
</template>

<style scoped>
.gameplay-planner { padding: 18px; background: var(--paper-card); border: 1px solid var(--paper-line); border-left: 5px solid #9b6652; border-radius: 12px; color: var(--ink); }
.budget-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.eyebrow { color: #8d5545; font-size: 11px; font-weight: 700; letter-spacing: .08em; }
h3 { margin: 3px 0 0; font-size: 19px; }
.event-badge { padding: 4px 9px; color: #784738; background: #f1e3dc; border-radius: 999px; font-size: 11px; }
.campaign { margin: 5px 0 15px; color: var(--ink-dim); font-size: 11px; }
.budget-result { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); min-height: 78px; background: var(--paper-panel); border: 1px solid var(--paper-line); border-radius: 8px; }
.budget-result > div { display: grid; align-content: center; gap: 5px; padding: 14px 16px; border-left: 1px solid var(--paper-line); }
.budget-result > div:first-of-type { border-left: 0; }
.budget-result small { color: var(--ink-dim); font-size: 10px; }
.budget-result strong { font-size: clamp(20px, 2.5vw, 27px); font-weight: 650; line-height: 1; }
.budget-result em { color: var(--ink-dim); font-size: 11px; font-style: normal; font-weight: 400; }
.budget-result > small, .budget-result > p { align-self: center; margin: 0; padding: 14px 16px; color: var(--ink-dim); }
.budget-result .missing-pace { grid-column: 1 / -1; border-left: 0; }
.budget-result .missing-pace strong { font-size: 16px; }
.budget-result .missing-pace span { color: var(--ink-dim); font-size: 12px; }
.budget-decision { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 12px 0 16px; }
.budget-decision p { max-width: 680px; margin: 0; color: var(--ink-dim); font-size: 12px; line-height: 1.65; }
.budget-decision button { flex: none; white-space: nowrap; }
.planner-error { margin: -7px 0 14px; color: #9f3d28; font-size: 12px; }
.outing-choice { display: grid; grid-template-columns: 180px minmax(0, 1fr); align-items: end; gap: 18px; padding-top: 14px; border-top: 1px solid var(--paper-line); }
.outing-choice > div { display: grid; gap: 8px; }
.gameplay-planner :deep(.pixel-control) { min-height: 38px; padding: 7px 9px; border: 1px solid var(--paper-line); border-radius: 6px; color: var(--ink); background: var(--paper-card); font: inherit; }
.outing-choice :deep(button) { white-space: nowrap; padding: 9px; }
.outing-choice span, label { font-size: 12px; }
label { display: grid; gap: 6px; }
.adjustments { margin-top: 13px; padding-top: 12px; border-top: 1px solid var(--paper-line); color: var(--ink-dim); font-size: 12px; }
summary { color: var(--fox-gold-deep); cursor: pointer; }
.plan-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin: 16px 0; }
.plan-fields :deep(.pixel-control) { width: 100%; min-width: 0; box-sizing: border-box; }
.adjustments p { line-height: 1.7; }
a { color: inherit; text-underline-offset: 3px; }
@media (max-width: 700px) {
  .budget-decision { align-items: flex-start; flex-direction: column; }
  .outing-choice { grid-template-columns: 1fr; }
}
@media (max-width: 520px) {
  .gameplay-planner { padding: 14px; }
  .budget-result { grid-template-columns: 1fr; }
  .budget-result > div { border-top: 1px solid var(--paper-line); border-left: 0; }
  .budget-result > div:first-of-type { border-top: 0; }
  .budget-decision button { width: 100%; white-space: normal; }
  .plan-fields { grid-template-columns: 1fr; }
}
</style>
