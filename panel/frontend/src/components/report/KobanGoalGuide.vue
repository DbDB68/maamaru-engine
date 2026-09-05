<script setup lang="ts">
import { computed } from 'vue'
import type { PlanningGoalAdvice } from '../../types'

const props = defineProps<{ goal: PlanningGoalAdvice }>()
const emit = defineEmits<{ openExpedition: [] }>()

const expeditionDaily = 6100
const gap = computed(() => Math.max(0, Number(props.goal.target || 0) - Number(props.goal.current || 0)))
const recentDaily = computed(() => Math.max(0, Number(props.goal.rate || 0)))
const expeditionDays = computed(() => gap.value ? Math.ceil(gap.value / expeditionDaily) : 0)
const expeditionHelps = computed(() => recentDaily.value > 0 && recentDaily.value < expeditionDaily)

function fmt(value: number) {
  return Math.round(value).toLocaleString()
}
</script>

<template>
  <section class="koban-guide">
    <header>
      <span><small>怎么更接近目标</small><h4>这笔小判，接下来怎么玩</h4></span>
      <b v-if="gap">还差 {{ fmt(gap) }}</b>
    </header>

    <div class="strategy-list">
      <article class="strategy-card primary-strategy">
        <span class="strategy-mark">远</span>
        <div>
          <small>每天都能做 · 稳定底盘</small>
          <h5>把远征改成小判优先</h5>
          <p>三支部队完整跑完预设排班，计划值约 <b>{{ fmt(expeditionDaily) }} 小判／天</b>。</p>
          <p v-if="expeditionHelps" class="strategy-impact">若能完整执行，单靠这份远征底盘约需 {{ fmt(expeditionDays) }} 天；实际还会受漏班和其他收支影响。</p>
          <p v-else-if="recentDaily >= expeditionDaily" class="strategy-impact">你最近的净进账已经高于这份远征计划值；它适合守住日常，不应再和现有速度重复相加。</p>
          <p v-else class="strategy-impact">这是排班表的计划收入，不是保证到账；启用后，まあ丸会继续按实际库存校正预测。</p>
        </div>
        <button type="button" class="primary" @click="emit('openExpedition')">去安排小判远征</button>
      </article>

      <article class="strategy-card">
        <span class="strategy-mark">城</span>
        <div>
          <small>活动开放时 · 集中获取</small>
          <h5>大阪城再集中挖一段</h5>
          <p>开放期间会按你自己的单层实测，换算还要挖多少层、每天安排多少层。</p>
          <p class="strategy-impact">活动没开时不拿旧单产许愿；开了以后，这里会自动变成可执行的层数计划。</p>
        </div>
      </article>

    </div>
  </section>
</template>

<style scoped>
.koban-guide { margin-top: 16px; padding-top: 16px; border-top: 1px dashed var(--paper-line); }
.koban-guide > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.koban-guide > header span { display: grid; gap: 2px; }
.koban-guide > header small { color: var(--ink-dim); font-size: 11px; }
.koban-guide > header h4 { margin: 0; font-size: 17px; }
.koban-guide > header > b { color: var(--fox-gold-deep); font-size: 13px; }
.strategy-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin-top: 11px; overflow: hidden; background: var(--paper-line); border: 1px solid var(--paper-line); border-radius: 8px; }
.strategy-card { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: start; gap: 10px; padding: 12px 13px; background: var(--paper-card); }
.strategy-card.primary-strategy { grid-template-columns: 32px minmax(0, 1fr) auto; }
.strategy-mark { display: grid; width: 30px; height: 30px; place-items: center; color: var(--fox-gold-deep); border: 1px solid var(--paper-line); border-radius: 50%; font-size: 11px; font-weight: 700; }
.strategy-card > div { min-width: 0; }
.strategy-card small { color: var(--ink-dim); font-size: 10px; }
.strategy-card h5 { margin: 2px 0 3px; font-size: 14px; }
.strategy-card p { margin: 0; color: var(--ink-dim); font-size: 11px; line-height: 1.55; }
.strategy-card p b { color: var(--ink); }
.strategy-card .strategy-impact { margin-top: 3px; color: var(--ink); }
.strategy-card button { white-space: nowrap; }
@media (max-width: 700px) {
  .strategy-list { grid-template-columns: 1fr; }
  .strategy-card, .strategy-card.primary-strategy { grid-template-columns: 32px minmax(0, 1fr); }
  .strategy-card button { grid-column: 2; justify-self: start; }
}
@media (max-width: 480px) {
  .koban-guide > header { align-items: flex-start; flex-direction: column; gap: 4px; }
}
</style>
