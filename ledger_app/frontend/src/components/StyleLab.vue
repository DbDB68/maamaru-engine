<script setup lang="ts">
// 风格试验田：保留明黄拼贴气质，但用真实页面层级验证“随身账房”。
// 只读数据，不写任何东西；数据口径与成绩单一致。
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { PlanningGoalAdvice, PlanningReport, ResourceLedger } from '../types'
import { eventTime, runStatusLabel, runTitle, signed } from './report/reportModel'

type LabView = 'overview' | 'ledger' | 'records' | 'goals'

const ledger = ref<ResourceLedger | null>(null)
const planning = ref<PlanningReport | null>(null)
const runs = ref<any[]>([])
const loading = ref(true)
const error = ref('')
const activeView = ref<LabView>('overview')

const resourceColors: Record<string, string> = {
  木炭: '#ff9f6e', 玉钢: '#a8d8ff', 冷却材: '#ffb3d1', 砥石: '#b8e6a0',
  小判: '#ffd166', 甲州金: '#c9b8ff', 委托符: '#8fe3d0', 加速符: '#f4a988',
}

interface LabCard {
  name: string
  current: number | null
  delta: number | null
  color: string
  daily: number | null
}

const cards = computed<LabCard[]>(() => (ledger.value?.per_resource || []).map(row => ({
  name: row.resource,
  current: row.closing,
  delta: row.total_delta,
  color: resourceColors[row.resource] || '#f3f0e8',
  daily: planning.value?.rates?.[row.resource]?.daily ?? null,
})))

const basicCards = computed(() => ['木炭', '玉钢', '冷却材', '砥石']
  .map(name => cards.value.find(card => card.name === name))
  .filter((card): card is LabCard => Boolean(card)))

const specialCards = computed(() => ['小判', '甲州金', '委托符', '加速符']
  .map(name => cards.value.find(card => card.name === name))
  .filter((card): card is LabCard => Boolean(card)))

const hero = computed(() => cards.value.find(card => card.name === '小判') || null)
const latestRun = computed(() => runs.value[0] || null)
const goals = computed<PlanningGoalAdvice[]>(() =>
  [...(planning.value?.goals || [])]
    .filter(goal => goal.status === 'active' || goal.status === 'behind' || goal.status === 'on_track')
    .slice(0, 3),
)
const leadGoal = computed(() => goals.value[0] || null)
const biggestChange = computed(() => [...cards.value]
  .filter(card => card.delta != null && card.delta !== 0)
  .sort((a, b) => Math.abs(b.delta || 0) - Math.abs(a.delta || 0))[0] || null)

function goalLine(goal: PlanningGoalAdvice): string {
  if (goal.target != null && goal.current != null) {
    const remaining = Math.max(0, goal.target - goal.current)
    if (remaining) return `还差 ${Math.round(remaining).toLocaleString()}`
  }
  if (goal.status === 'on_track') return '照现在速度来得及'
  if (goal.status === 'behind') return '得加把劲'
  return '去看看'
}

function show(view: LabView) {
  activeView.value = view
  document.querySelector('.style-lab')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(async () => {
  try {
    const [ledgerData, planningData, runsData] = await Promise.all([
      api.resourceLedger(7),
      api.planning().catch(() => null),
      api.dataRuns(6).catch(() => ({ schema_version: 1, items: [], has_more: false, next_cursor: null })),
    ])
    ledger.value = ledgerData
    planning.value = planningData
    runs.value = runsData.items || []
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '账房数据没搬动'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="style-lab">
    <div v-if="loading" class="lab-loading">狐之助正在搬账本……</div>
    <p v-else-if="error" class="lab-error">{{ error }}</p>
    <template v-else>
      <Transition name="lab-page" mode="out-in">
        <section v-if="activeView === 'overview'" key="overview" class="lab-view lab-overview">
          <header class="lab-hero">
            <p class="lab-kicker">本丸账房 · 今日总览</p>
            <h1>本丸小金库</h1>
            <div v-if="hero" class="lab-hero-number">
              <strong>{{ hero.current == null ? '—' : hero.current.toLocaleString() }}</strong>
              <span>枚小判</span>
              <em v-if="hero.delta != null" :class="['lab-chip', hero.delta >= 0 ? 'up' : 'down']">近 7 天 {{ signed(hero.delta) }}</em>
            </div>
          </header>

          <div class="lab-briefs" aria-label="今天先看这三件事">
            <article class="lab-brief change">
              <small>近 7 天动静最大</small>
              <strong v-if="biggestChange">{{ biggestChange.name }} {{ signed(biggestChange.delta || 0) }}</strong>
              <strong v-else>家底没有明显变化</strong>
              <span>先说结论，不用翻完八张卡</span>
            </article>
            <article class="lab-brief run">
              <small>最近一次忙活</small>
              <strong v-if="latestRun">{{ runTitle(latestRun) }}</strong>
              <strong v-else>还没有任务记录</strong>
              <span v-if="latestRun">{{ runStatusLabel(latestRun) }} · {{ eventTime(latestRun.started_at) }}</span>
              <span v-else>跑过一次以后，这里会告诉你结果</span>
            </article>
            <article class="lab-brief goal">
              <small>现在盯着的目标</small>
              <strong v-if="leadGoal">{{ leadGoal.resource }}</strong>
              <strong v-else>还没有立目标</strong>
              <span v-if="leadGoal">{{ goalLine(leadGoal) }}</span>
              <span v-else>需要时再立，不催你填表</span>
            </article>
          </div>

          <button class="lab-forward" type="button" @click="show('ledger')">看完整家底 <span>→</span></button>
        </section>

        <section v-else-if="activeView === 'ledger'" key="ledger" class="lab-view">
          <header class="lab-view-head">
            <p>近 7 天账本</p>
            <h2>家底摆在这</h2>
            <span>基础资材看整体，票券和货币单独放。</span>
          </header>

          <div class="lab-resource-grid" aria-label="四项基础资材">
            <article v-for="card in basicCards" :key="card.name" class="lab-resource-card" :style="{ background: card.color }">
              <header><span>{{ card.name }}</span><em v-if="card.delta != null" class="lab-chip dark">{{ signed(card.delta) }}</em></header>
              <strong>{{ card.current == null ? '—' : card.current.toLocaleString() }}</strong>
              <footer v-if="card.daily != null">平常一天约 {{ signed(Math.round(card.daily)) }}</footer>
            </article>
          </div>

          <h3 class="lab-subhead">票券与特别资源</h3>
          <div class="lab-special-grid">
            <article v-for="card in specialCards" :key="card.name" :style="{ '--card-color': card.color }">
              <span>{{ card.name }}</span>
              <strong>{{ card.current == null ? '—' : card.current.toLocaleString() }}</strong>
              <em v-if="card.delta != null">近 7 天 {{ signed(card.delta) }}</em>
            </article>
          </div>
        </section>

        <section v-else-if="activeView === 'records'" key="records" class="lab-view">
          <header class="lab-view-head"><p>任务记录</p><h2>最近忙活</h2><span>先看结果，需要细账再回成绩单。</span></header>
          <div class="lab-records">
            <div class="lab-records-head"><span>{{ runs.length ? `${runs.length} 条` : '还没记录' }}</span></div>
            <ul v-if="runs.length">
              <li v-for="run in runs" :key="run.run_id || run.started_at">
                <span class="lab-record-title">{{ runTitle(run) }}</span>
                <span class="lab-record-meta">{{ run.started_at ? eventTime(run.started_at) : '' }} · {{ runStatusLabel(run) }}</span>
              </li>
            </ul>
            <p v-else class="lab-empty">账本还空着，等它跑几圈就有了</p>
          </div>
        </section>

        <section v-else key="goals" class="lab-view">
          <header class="lab-view-head"><p>活动与家底</p><h2>盯着的目标</h2><span>只展示正在进行的事，不拿空指标占地方。</span></header>
          <div v-if="goals.length" class="lab-goals">
            <article v-for="goal in goals" :key="goal.id" class="lab-goal">
              <small>{{ goal.status === 'behind' ? '需要加把劲' : goal.status === 'on_track' ? '按计划进行' : '正在关注' }}</small>
              <strong>{{ goal.resource }}</strong>
              <span>{{ goalLine(goal) }}</span>
              <em v-if="goal.deadline">截止 {{ goal.deadline }}</em>
            </article>
          </div>
          <div v-else class="lab-no-goal"><strong>眼下没有要追的目标</strong><span>这也是一种好消息。</span></div>
        </section>
      </Transition>

      <nav class="lab-nav" aria-label="试验田导航">
        <button type="button" :class="{ active: activeView === 'overview' }" :aria-current="activeView === 'overview' ? 'page' : undefined" @click="show('overview')">🏠<span>总览</span></button>
        <button type="button" :class="{ active: activeView === 'ledger' }" :aria-current="activeView === 'ledger' ? 'page' : undefined" @click="show('ledger')">📒<span>账本</span></button>
        <button type="button" :class="{ active: activeView === 'records' }" :aria-current="activeView === 'records' ? 'page' : undefined" @click="show('records')">🧾<span>记录</span></button>
        <button type="button" :class="{ active: activeView === 'goals' }" :aria-current="activeView === 'goals' ? 'page' : undefined" @click="show('goals')">🎯<span>目标</span></button>
      </nav>
    </template>
  </div>
</template>

<style scoped>
.style-lab {
  --lab-ink: #1d1a12;
  --lab-yellow: #ffd94d;
  position: relative;
  display: flex;
  flex-direction: column;
  width: min(100%, 620px);
  min-height: 720px;
  margin: 12px auto 0;
  padding: 30px 24px 96px;
  overflow: clip;
  background: var(--lab-yellow);
  border-radius: 30px;
  color: var(--lab-ink);
  font-family: var(--body-font, sans-serif);
}
.lab-loading, .lab-error { margin: 40px 0; text-align: center; font-weight: 700; }
.lab-view { flex: 1; min-width: 0; }
.lab-kicker, .lab-view-head p { margin: 0 0 6px; font-size: 12px; font-weight: 800; letter-spacing: .14em; }
.lab-hero h1, .lab-view-head h2 { margin: 0; font-size: clamp(38px, 9vw, 60px); line-height: 1; font-weight: 900; letter-spacing: -.03em; }
.lab-view-head h2 { font-size: clamp(34px, 8vw, 50px); }
.lab-view-head > span { display: block; margin-top: 10px; font-size: 13px; font-weight: 650; opacity: .68; }
.lab-hero-number { display: flex; align-items: baseline; gap: 8px; margin-top: 22px; flex-wrap: wrap; }
.lab-hero-number strong { font-size: clamp(36px, 9vw, 54px); font-weight: 900; font-variant-numeric: tabular-nums; }
.lab-hero-number span { font-weight: 800; }
.lab-chip { display: inline-block; padding: 4px 11px; border-radius: 999px; background: #fff; color: var(--lab-ink); font-size: 12px; font-weight: 850; font-style: normal; white-space: nowrap; }
.lab-chip.down, .lab-chip.dark { background: rgba(29, 26, 18, .84); color: #fff; }

.lab-briefs { display: grid; margin-top: 30px; }
.lab-brief { position: relative; display: grid; gap: 5px; padding: 18px 20px; border: 2px solid var(--lab-ink); border-radius: 24px; box-shadow: 0 6px 0 rgba(29, 26, 18, .14); }
.lab-brief + .lab-brief { margin-top: -2px; }
.lab-brief.change { z-index: 3; background: #ffb3d1; transform: rotate(-.7deg); }
.lab-brief.run { z-index: 2; background: #a8d8ff; transform: rotate(.7deg); }
.lab-brief.goal { z-index: 1; background: #b8e6a0; transform: rotate(-.4deg); }
.lab-brief small { font-size: 11px; font-weight: 800; opacity: .65; }
.lab-brief strong { font-size: 19px; font-weight: 900; }
.lab-brief span { font-size: 12.5px; font-weight: 650; opacity: .72; }
.lab-forward { width: 100%; margin-top: 22px; padding: 14px 18px; border: 0; border-radius: 18px; background: #fff; color: var(--lab-ink); font-weight: 900; text-align: left; cursor: pointer; }
.lab-forward span { float: right; font-size: 18px; }

.lab-resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; margin-top: 28px; }
.lab-resource-card { min-width: 0; padding: 16px; border: 2px solid var(--lab-ink); border-radius: 22px; box-shadow: 0 5px 0 rgba(29, 26, 18, .14); }
.lab-resource-card:nth-child(odd) { transform: rotate(-.6deg); }
.lab-resource-card:nth-child(even) { transform: rotate(.6deg); }
.lab-resource-card header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.lab-resource-card header > span { font-size: 13px; font-weight: 850; }
.lab-resource-card > strong { display: block; margin-top: 14px; overflow: hidden; font-size: clamp(24px, 6vw, 34px); font-weight: 900; font-variant-numeric: tabular-nums; text-overflow: ellipsis; }
.lab-resource-card footer { margin-top: 4px; font-size: 11.5px; font-weight: 700; opacity: .68; }
.lab-subhead { margin: 30px 0 12px; font-size: 16px; font-weight: 900; }
.lab-special-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.lab-special-grid article { display: grid; gap: 3px; padding: 13px 15px; border-left: 7px solid var(--card-color); border-radius: 16px; background: #fff; }
.lab-special-grid span { font-size: 12px; font-weight: 800; opacity: .65; }
.lab-special-grid strong { font-size: 21px; font-weight: 900; font-variant-numeric: tabular-nums; }
.lab-special-grid em { font-size: 10.5px; font-weight: 700; font-style: normal; opacity: .62; }

.lab-records { margin-top: 26px; padding: 18px; background: #fff; border-radius: 22px; box-shadow: 0 6px 0 rgba(29, 26, 18, .14); }
.lab-records-head { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.lab-records-head span { font-size: 12px; font-weight: 800; opacity: .58; }
.lab-records ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.lab-records li { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 12px 13px; border-radius: 14px; background: #f3f0e8; }
.lab-record-title { font-size: 14px; font-weight: 850; }
.lab-record-meta { font-size: 11px; opacity: .62; white-space: nowrap; }
.lab-empty { margin: 6px 0 2px; font-size: 13px; font-weight: 650; opacity: .65; }

.lab-goals { display: grid; gap: 12px; margin-top: 28px; }
.lab-goal { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; padding: 18px 20px; border-radius: 22px; background: var(--lab-ink); color: #ffd94d; }
.lab-goal small { grid-column: 1 / -1; font-size: 10.5px; font-weight: 800; opacity: .65; }
.lab-goal strong { font-size: 21px; }
.lab-goal span { font-size: 13px; font-weight: 750; }
.lab-goal em { grid-row: 2 / 4; grid-column: 2; align-self: center; font-size: 11px; font-style: normal; opacity: .75; }
.lab-no-goal { display: grid; gap: 6px; margin-top: 28px; padding: 28px; border: 2px dashed var(--lab-ink); border-radius: 22px; text-align: center; }
.lab-no-goal strong { font-size: 18px; }
.lab-no-goal span { font-size: 13px; opacity: .65; }

.lab-nav { position: sticky; z-index: 10; bottom: 14px; display: flex; justify-content: space-around; gap: 4px; margin-top: 30px; padding: 9px 12px; border-radius: 999px; background: var(--lab-ink); box-shadow: 0 10px 24px rgba(29, 26, 18, .35); }
.lab-nav button { display: grid; justify-items: center; gap: 2px; min-width: 58px; padding: 5px 10px; border: 0; border-radius: 999px; background: none; color: #fff4bb; font-size: 17px; cursor: pointer; transition: color .15s ease, background .15s ease, transform .15s ease; }
.lab-nav button:hover, .lab-nav button.active { background: #ffd94d; color: var(--lab-ink); transform: translateY(-1px); }
.lab-nav button span { font-size: 10px; font-weight: 800; }
.lab-page-enter-active, .lab-page-leave-active { transition: opacity .16s ease, transform .16s ease; }
.lab-page-enter-from { opacity: 0; transform: translateX(12px); }
.lab-page-leave-to { opacity: 0; transform: translateX(-8px); }

@media (max-width: 560px) {
  .style-lab { min-height: 680px; margin-top: 0; padding: 24px 16px 84px; border-radius: 24px; }
  .lab-resource-grid { gap: 9px; }
  .lab-resource-card { padding: 14px 12px; }
  .lab-resource-card header { align-items: flex-start; }
  .lab-resource-card .lab-chip { padding: 3px 7px; font-size: 10px; }
  .lab-records { padding: 14px; }
  .lab-records li { align-items: flex-start; flex-direction: column; gap: 3px; }
  .lab-record-meta { white-space: normal; }
  .lab-nav { margin-inline: 2px; }
  .lab-nav button { min-width: 48px; padding-inline: 7px; }
}

@media (prefers-reduced-motion: reduce) {
  .lab-page-enter-active, .lab-page-leave-active, .lab-nav button { transition: none; }
}
</style>
