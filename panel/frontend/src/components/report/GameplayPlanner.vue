<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
const form = ref({ map_no: 1, mode: 'time', hours_per_day: 2, runs: 100, budget: 50000, free_runs: 0, price: 500, minutes_per_run: '', deadline: '2026-09-10T10:00' })
type Estimate = { campaign: {name: string; source: string}; sample_count: number; seconds_per_run: number | null; speed_source: string; runs: number | null; cost: number | null; hours: number | null; can_finish: boolean | null; remaining_hours: number }
const result = ref<Estimate | null>(null)
const error = ref('')
const loading = ref(false)
watch(form, () => { result.value = null }, { deep: true })
async function calculate() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const response = await fetch('/api/planning/gameplay', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(form.value) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '暂时无法计算')
    result.value = data
    localStorage.setItem('maamaru-yosari-plan', JSON.stringify(form.value))
  } catch (e) { error.value = e instanceof Error ? e.message : '暂时无法计算' }
  finally { loading.value = false }
}
onMounted(() => {
  try { const saved = localStorage.getItem('maamaru-yosari-plan'); if (saved) Object.assign(form.value, JSON.parse(saved)) } catch { /* use defaults */ }
  void calculate()
})
</script>
<template>
  <section class="gameplay-planner">
    <header><h3>按玩法规划 · 异去</h3><p>想打多少、每天打多久，先算时间和小判。</p></header>
    <p class="campaign"><a href="https://www.bilibili.com/read/cv52768115/" target="_blank" rel="noopener noreferrer">宝物碎片掉落率 2 倍</a> · 9 月 3 日 10:00—9 月 10 日 10:00</p>
    <form @submit.prevent="calculate">
      <div class="plan-fields">
        <label>地图<select v-model.number="form.map_no"><option :value="1">异去 1-1</option><option :value="2">异去 1-2</option><option :value="3">异去 1-3</option><option :value="4">异去 1-4</option></select></label>
        <label>规划方式<select v-model="form.mode"><option value="time">按每天可用时间</option><option value="runs">按目标次数</option></select></label>
        <label v-if="form.mode === 'runs'">目标次数<input v-model.number="form.runs" type="number" min="0" step="1" required /></label>
        <label>每天可用小时<input v-model.number="form.hours_per_day" type="number" min="0.01" max="24" step="0.01" required /></label>
        <label>小判预算上限<input v-model.number="form.budget" type="number" min="0" required /></label>
        <label>截止时间（北京时间）<input v-model="form.deadline" type="datetime-local" required /></label>
      </div>
      <details><summary>调整速度和提灯预算</summary><div class="plan-fields">
        <label>每圈分钟（留空用实测）<input v-model="form.minutes_per_run" type="number" min="0.01" max="180" step="0.01" placeholder="自动读取" /></label>
        <label>期间可用的免费次数<input v-model.number="form.free_runs" type="number" min="0" step="1" required /></label>
        <label>每次付费出阵预算（小判）<input v-model.number="form.price" type="number" min="0" required /></label>
      </div><p>免费次数含现有提灯与期间能用上的免费补充，尚未自动读取。默认不计免费次数；500 小判是可调整的预算假设。</p></details>
      <button type="submit" :disabled="loading">{{ loading ? '计算中…' : '计算计划' }}</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="result" aria-live="polite">
      <p v-if="result.seconds_per_run === null">这张地图还没有可用的连续圈样本，请在上方填写每圈分钟。</p>
      <template v-else>
        <div class="plan-results"><span>预计 <strong>{{ result.runs?.toLocaleString() }}</strong> 次</span><span>耗时约 <strong>{{ result.hours?.toFixed(1) }}</strong> 小时</span><span>小判约 <strong>{{ result.cost?.toLocaleString() }}</strong></span></div>
        <p>{{ result.speed_source }} · 每圈约 {{ (result.seconds_per_run / 60).toFixed(1) }} 分钟<span v-if="!form.minutes_per_run"> · {{ result.sample_count }} 个间隔样本</span></p>
        <p v-if="result.remaining_hours <= 0">截止时间已过，请调整计划时间。</p>
        <p v-else-if="!result.can_finish">按当前时间或预算，目标暂时超出安排；可减少次数或增加可用时间、预算。</p>
        <p v-else>在填写的时间和小判预算内可完成。</p>
      </template>
    </div>
    <small>按剩余天数折算每天可用时长；最后不足一天按比例计算。掉落率翻倍不代表必得两倍碎片。本计划仅估算，不会启动出阵。</small>
  </section>
</template>
<style scoped>
.gameplay-planner { margin-bottom: 24px; padding: 18px; border: 1px solid var(--border-color, #b7a5ae); border-radius: 10px; }
h3 { margin: 0; } p { line-height: 1.6; } .campaign { font-size: .9rem; }
.plan-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 14px 0; }
label { display: flex; flex-direction: column; gap: 6px; font-size: .9rem; } input, select { box-sizing: border-box; width: 100%; min-width: 0; padding: 8px; color: inherit; background: var(--bg-card, #fffaf7); border: 1px solid var(--border-color, #b7a5ae); border-radius: 5px; }
button { margin: 12px 0; padding: 8px 18px; } summary { cursor: pointer; } small { display: block; line-height: 1.6; opacity: .8; }
.plan-results { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 14px 0; } strong { font-size: 1.2rem; }
@media(max-width: 480px) { .plan-fields { grid-template-columns: 1fr; } .gameplay-planner { padding: 12px; } }
</style>
