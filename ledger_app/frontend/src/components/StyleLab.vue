<script setup lang="ts">
// 风格试验田：明黄大色块 + 堆叠卡片 + 胶囊导航的账房新皮肤试验。
// 只读数据，不写任何东西；数据口径与成绩单一致。
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { PlanningGoalAdvice, PlanningReport, ResourceLedger } from '../types'
import { eventTime, runStatusLabel, runTitle, signed } from './report/reportModel'

const ledger = ref<ResourceLedger | null>(null)
const planning = ref<PlanningReport | null>(null)
const runs = ref<any[]>([])
const loading = ref(true)
const error = ref('')

// 糖果色卡池：参考稿的橙/蓝/粉/绿轮着来，跟资源含义解耦，纯看风格
const cardPalette = ['#ff9f6e', '#a8d8ff', '#ffb3d1', '#b8e6a0', '#ffd166', '#c9b8ff', '#8fe3d0', '#f4a988']

interface LabCard {
  name: string
  current: number | null
  delta: number | null
  color: string
  daily: number | null
}

const cards = computed<LabCard[]>(() => {
  const rows = ledger.value?.per_resource || []
  return rows.map((row, index) => ({
    name: row.resource,
    current: row.closing,
    delta: row.total_delta,
    color: cardPalette[index % cardPalette.length],
    daily: planning.value?.rates?.[row.resource]?.daily ?? null,
  }))
})

const hero = computed(() => cards.value.find(card => card.name === '小判') || null)

const goals = computed<PlanningGoalAdvice[]>(() =>
  [...(planning.value?.goals || [])]
    .filter(goal => goal.status === 'active' || goal.status === 'behind' || goal.status === 'on_track')
    .slice(0, 3),
)

function goalLine(goal: PlanningGoalAdvice): string {
  if (goal.target != null && goal.current != null) {
    const remaining = Math.max(0, goal.target - goal.current)
    if (remaining) return `还差 ${Math.round(remaining).toLocaleString()}`
  }
  if (goal.status === 'on_track') return '照现在速度来得及'
  if (goal.status === 'behind') return '得加把劲'
  return '去看看'
}

function scrollTo(section: string) {
  document.getElementById(`lab-${section}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
      <!-- 大标题区：参考稿的超大粗黑字 -->
      <section id="lab-hero" class="lab-hero">
        <p class="lab-kicker">本丸账房 · 试验田</p>
        <h1 class="lab-headline">看看咱<br>小金库</h1>
        <div v-if="hero" class="lab-hero-number">
          <strong>{{ hero.current == null ? '—' : hero.current.toLocaleString() }}</strong>
          <span>枚小判</span>
          <em v-if="hero.delta != null" :class="['lab-chip', hero.delta >= 0 ? 'up' : 'down']">
            近 7 天 {{ signed(hero.delta) }}
          </em>
        </div>
      </section>

      <!-- 资源色卡堆叠：每张卡微微歪一点，像一沓便签 -->
      <section id="lab-cards" class="lab-stack" aria-label="资源总览">
        <article
          v-for="(card, index) in cards"
          :key="card.name"
          class="lab-card"
          :style="{ background: card.color, '--tilt': `${index % 2 ? 1.2 : -1.2}deg` }"
        >
          <header>
            <span class="lab-card-name">{{ card.name }}</span>
            <span v-if="card.delta != null" :class="['lab-chip dark', card.delta >= 0 ? 'up' : 'down']">
              {{ signed(card.delta) }}
            </span>
          </header>
          <strong class="lab-card-number">{{ card.current == null ? '—' : card.current.toLocaleString() }}</strong>
          <footer v-if="card.daily != null">平常一天约 {{ signed(Math.round(card.daily)) }}</footer>
        </article>
      </section>

      <!-- 最近记录：参考稿里 "Events with Friends" 那种列表卡 -->
      <section id="lab-records" class="lab-records">
        <header class="lab-records-head">
          <h2>最近忙活</h2>
          <span>{{ runs.length ? `${runs.length} 条` : '还没记录' }}</span>
        </header>
        <ul v-if="runs.length">
          <li v-for="run in runs" :key="run.run_id || run.started_at">
            <span class="lab-record-title">{{ runTitle(run) }}</span>
            <span class="lab-record-meta">{{ run.started_at ? eventTime(run.started_at) : '' }} · {{ runStatusLabel(run) }}</span>
          </li>
        </ul>
        <p v-else class="lab-empty">账本还空着，等它跑几圈就有了</p>
      </section>

      <!-- 目标小卡 -->
      <section v-if="goals.length" id="lab-goals" class="lab-goals">
        <h2>盯着的目标</h2>
        <div class="lab-goal-row">
          <article v-for="goal in goals" :key="goal.id" class="lab-goal">
            <strong>{{ goal.resource }}</strong>
            <span>{{ goalLine(goal) }}</span>
          </article>
        </div>
      </section>

      <!-- 胶囊导航 -->
      <nav class="lab-nav" aria-label="试验田导航">
        <button type="button" @click="scrollTo('hero')">🏠<span>总览</span></button>
        <button type="button" @click="scrollTo('cards')">📒<span>账本</span></button>
        <button type="button" @click="scrollTo('records')">🧾<span>记录</span></button>
        <button v-if="goals.length" type="button" @click="scrollTo('goals')">🎯<span>目标</span></button>
      </nav>
    </template>
  </div>
</template>

<style scoped>
.style-lab {
  --lab-ink: #1d1a12;
  --lab-yellow: #ffd94d;
  position: relative;
  margin: 12px auto 0;
  max-width: 520px;
  padding: 28px 20px 96px;
  background: var(--lab-yellow);
  border-radius: 28px;
  color: var(--lab-ink);
  font-family: var(--body-font, sans-serif);
}

.lab-loading,
.lab-error {
  margin: 40px 0;
  text-align: center;
  font-weight: 700;
}

/* ── 大标题 ── */
.lab-kicker {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .12em;
}
.lab-headline {
  margin: 0 0 20px;
  font-size: clamp(44px, 11vw, 64px);
  line-height: 1.02;
  font-weight: 900;
  letter-spacing: .01em;
}
.lab-hero-number {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.lab-hero-number strong {
  font-size: clamp(36px, 9vw, 52px);
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}
.lab-hero-number span { font-weight: 700; }

.lab-chip {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 800;
  font-style: normal;
  background: #fff;
  color: var(--lab-ink);
}
.lab-chip.down { background: var(--lab-ink); color: #ffd94d; }
.lab-chip.dark { background: rgba(0, 0, 0, .72); color: #fff; }

/* ── 堆叠色卡 ── */
.lab-stack {
  display: grid;
  gap: 14px;
  margin-top: 26px;
}
.lab-card {
  padding: 18px 20px 14px;
  border-radius: 22px;
  transform: rotate(var(--tilt, 0deg));
  box-shadow: 0 6px 0 rgba(29, 26, 18, .14);
  transition: transform .18s ease;
}
.lab-card:hover { transform: rotate(0deg) translateY(-3px); }
.lab-card header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.lab-card-name { font-weight: 800; font-size: 15px; }
.lab-card-number {
  display: block;
  font-size: 34px;
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}
.lab-card footer {
  margin-top: 4px;
  font-size: 12.5px;
  font-weight: 600;
  opacity: .75;
}

/* ── 最近记录列表卡 ── */
.lab-records {
  margin-top: 26px;
  padding: 18px 20px;
  background: #fff;
  border-radius: 22px;
  box-shadow: 0 6px 0 rgba(29, 26, 18, .14);
}
.lab-records-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 10px;
}
.lab-records-head h2,
.lab-goals h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 900;
}
.lab-records-head span { font-size: 12.5px; font-weight: 700; opacity: .6; }
.lab-records ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 4px;
}
.lab-records li {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  padding: 10px 12px;
  background: #f3f0e8;
  border-radius: 14px;
}
.lab-record-title { font-weight: 800; font-size: 14px; }
.lab-record-meta { font-size: 12px; opacity: .65; white-space: nowrap; }
.lab-empty { margin: 6px 0 2px; font-size: 13.5px; font-weight: 600; opacity: .65; }

/* ── 目标 ── */
.lab-goals { margin-top: 26px; }
.lab-goal-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.lab-goal {
  padding: 14px 16px;
  background: var(--lab-ink);
  color: #ffd94d;
  border-radius: 18px;
  display: grid;
  gap: 4px;
}
.lab-goal strong { font-size: 15px; }
.lab-goal span { font-size: 12.5px; opacity: .85; }

/* ── 胶囊导航 ── */
.lab-nav {
  position: sticky;
  bottom: 14px;
  margin-top: 30px;
  display: flex;
  justify-content: space-around;
  gap: 4px;
  padding: 10px 14px;
  background: var(--lab-ink);
  border-radius: 999px;
  box-shadow: 0 10px 24px rgba(29, 26, 18, .35);
}
.lab-nav button {
  display: grid;
  justify-items: center;
  gap: 2px;
  border: 0;
  background: none;
  color: #ffd94d;
  font-size: 18px;
  cursor: pointer;
  padding: 2px 10px;
  border-radius: 999px;
  transition: background .15s ease;
}
.lab-nav button:hover { background: rgba(255, 217, 77, .16); }
.lab-nav button span { font-size: 10.5px; font-weight: 700; }

@media (prefers-reduced-motion: reduce) {
  .lab-card,
  .lab-nav button { transition: none; }
  .lab-card:hover { transform: rotate(var(--tilt, 0deg)); }
}
</style>
