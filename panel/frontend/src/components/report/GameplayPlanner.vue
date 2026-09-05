<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import PixelControl from '../PixelControl.vue'
import SegmentedControl from '../SegmentedControl.vue'
const form = ref({ map_no: 1, mode: 'time', hours_per_day: 2, runs: 100, budget: 50000, free_runs: '', current_free: 0, price: '', minutes_per_run: '', deadline: '' })
type Estimate = { campaign: {name: string; source: string; start_at: string; end_at: string}; campaign_status: string; deadline: string; price: number; daily_free_runs: number; free_days: number; free_runs: number; free_source: string; sample_count: number; seconds_per_run: number | null; speed_source: string; runs: number | null; cost: number | null; hours: number | null; can_finish: boolean | null; remaining_hours: number }
const result = ref<Estimate | null>(null)
const metadata = ref<Estimate | null>(null)
const dateText = (value: string) => new Date(value).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false})
const error = ref('')
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let revision = 0
watch(form, () => { revision++; loading.value = true; clearTimeout(timer); timer = setTimeout(calculate, 450) }, { deep: true })
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
  } catch (e) { if (requestRevision !== revision) return; result.value = null; error.value = e instanceof Error ? e.message : '暂时无法计算' }
  finally { if (requestRevision === revision) loading.value = false }
}
onMounted(() => {
  try { const saved = localStorage.getItem('maamaru-yosari-plan-v2'); if (saved) Object.assign(form.value, JSON.parse(saved)) } catch { /* use defaults */ }
  void calculate()
})
</script>
<template>
  <section class="gameplay-planner">
    <header class="outing-heading"><div><span class="eyebrow">下一段出阵打算</span><h3>这几天，去异去走走</h3></div><span v-if="metadata" class="event-badge">{{ metadata.campaign_status }} · 碎片掉率加成</span></header>
    <p v-if="metadata" class="campaign">{{ metadata.campaign.name }}<span> · 至 {{ dateText(metadata.campaign.end_at) }}</span></p>
    <div class="outing-choice">
      <label class="map-choice">想去哪张图<PixelControl v-model="form.map_no" as="select" numeric><option :value="1">1-1 函馆</option><option :value="2">1-2 会津</option><option :value="3">1-3 宇都宫</option><option :value="4">1-4 鸟羽</option></PixelControl></label>
      <div class="time-choice"><span>每天留一点时间</span><SegmentedControl :model-value="form.hours_per_day" @update:model-value="form.hours_per_day = Number($event)" label="每天出阵时间" :items="[{value: 1, label: '1 小时'}, {value: 2, label: '2 小时'}, {value: 3, label: '3 小时'}, {value: 6, label: '6 小时'}]" /></div>
    </div>
    <div class="outing-result" aria-live="polite" :aria-busy="loading">
      <small v-if="loading">正在更新估算…</small>
      <template v-if="result?.runs != null">
        <p class="result-lead">{{ form.mode === 'runs' ? '这次想打' : '照这个节奏，预计能打' }} <strong>{{ result.runs.toLocaleString() }}</strong> 次</p>
        <p>约花 {{ result.hours?.toFixed(1) }} 小时 · 需要 {{ result.cost?.toLocaleString() }} 小判</p>
        <p v-if="result.remaining_hours <= 0" class="notice">截止时间已经过了，调整一下日期再计划吧。</p>
        <p v-else-if="!result.can_finish" class="notice">时间或小判预算还不够，可以在下方调整。</p>
        <small>{{ result.speed_source }} · 每圈约 {{ ((result.seconds_per_run || 0) / 60).toFixed(1) }} 分钟</small>
      </template>
      <template v-else-if="result"><p class="result-lead">还差一点这张图的经验</p><p>跑过几圈后就能用实测速度。现在也可以先估一个：</p><label class="pace-input">每圈大约 <PixelControl v-model="form.minutes_per_run" type="number" min="0.01" max="180" step="0.1" aria-label="每圈大约几分钟" /> 分钟</label></template>
      <p v-else>{{ error || '正在帮你算这趟出阵…' }}</p>
    </div>
    <div class="plan-summary">每天 {{ form.hours_per_day }} 小时 · 最多花 {{ Number(form.budget).toLocaleString() }} 小判 · {{ form.deadline ? '按自定截止时间' : '打到本期活动结束' }}</div>
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
.gameplay-planner { margin-bottom: 28px; padding: 26px; background: var(--paper-card, #fffaf3); border: 1px solid var(--paper-line, #c8bba9); border-radius: 16px; color: var(--ink); }
.outing-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }.eyebrow { font-size:12px; color:var(--ink-dim); } h3 { margin:8px 0 0; font-size:22px; }.event-badge { font-size:12px; padding:6px 10px; background:var(--paper-panel); border-radius:20px; }.campaign { font-size:13px; color:var(--ink-dim); margin:12px 0 24px; }
.outing-choice { display:flex; gap:24px; align-items:end; flex-wrap:wrap; }.map-choice { width:180px; }.gameplay-planner :deep(.pixel-control) { min-height:40px; padding:8px 10px; border:1px solid var(--paper-line); border-radius:6px; color:var(--ink); background:var(--paper-card); font:inherit; }.time-choice { display:grid; gap:8px; }.time-choice :deep(button) { white-space:nowrap; padding:10px 9px; }.time-choice>span, label { font-size:13px; }label { display:grid; gap:8px; }.outing-result { margin:24px 0 14px; padding:22px; border-radius:12px; background:var(--paper-panel); min-height:110px; }.result-lead { font-size:18px; margin:0 0 10px; }.result-lead strong { font-size:36px; font-weight:600; margin:0 5px; }.outing-result p { line-height:1.7; }.outing-result small, small, .plan-summary { color:var(--ink-dim); font-size:12px; }.pace-input { display:flex; align-items:center; gap:8px; }.pace-input :deep(input) { width:90px; }.plan-summary { margin:14px 0 20px; line-height:1.7; }.adjustments { border-top:1px solid var(--paper-line); padding:14px 0; font-size:13px; }.adjustments:last-child { padding-bottom:0; }summary { cursor:pointer; }.plan-fields { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin:18px 0; }.plan-fields :deep(.pixel-control) { width:100%; min-width:0; box-sizing:border-box; }.adjustments p { line-height:1.8; }a { color:inherit; text-underline-offset:3px; }.notice { font-weight:600; }
@media(max-width:600px) { .gameplay-planner { padding:18px 14px; } h3 { font-size:20px; }.outing-choice { gap:18px; }.map-choice,.time-choice { width:100%; }.outing-result { padding:16px; }.plan-fields { grid-template-columns:1fr; } }
</style>
