<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PlanningGoalAdvice } from '../../types'
import GameplayPlanner from './GameplayPlanner.vue'

const props = defineProps<{ goal: PlanningGoalAdvice }>()
const emit = defineEmits<{ openExpedition: [] }>()

const showYosari = ref(false)
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

    <p class="guide-intro">
      预测日期只是照最近习惯往后推。まあ丸把能稳定做的、等活动再做的，以及会花掉小判的玩法分开列给你。
    </p>

    <div class="strategy-list">
      <article class="strategy-card primary-strategy">
        <span class="strategy-mark">稳</span>
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
        <span class="strategy-mark">等</span>
        <div>
          <small>活动开放时 · 集中获取</small>
          <h5>大阪城再集中挖一段</h5>
          <p>开放期间会按你自己的单层实测，换算还要挖多少层、每天安排多少层。</p>
          <p class="strategy-impact">活动没开时不拿旧单产许愿；开了以后，这里会自动变成可执行的层数计划。</p>
        </div>
      </article>

      <article class="strategy-card spending-strategy">
        <span class="strategy-mark">花</span>
        <div>
          <small>当前活动 · 先看目标冲突</small>
          <h5>异去加成值得花多少小判？</h5>
          <p>异去是换碎片的消费方案，不是攒小判的来源。先算参与成本，再决定这期打到哪里。</p>
        </div>
        <button type="button" class="secondary" @click="showYosari = !showYosari">{{ showYosari ? '收起活动算盘' : '算算参与成本' }}</button>
      </article>
    </div>

    <GameplayPlanner v-if="showYosari" class="embedded-gameplay" />
  </section>
</template>

<style scoped>
.koban-guide { margin-top: 16px; padding-top: 16px; border-top: 1px dashed var(--paper-line); }
.koban-guide > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.koban-guide > header span { display: grid; gap: 2px; }
.koban-guide > header small { color: var(--ink-dim); font-size: 11px; }
.koban-guide > header h4 { margin: 0; font-size: 17px; }
.koban-guide > header > b { color: var(--fox-gold-deep); font-size: 13px; }
.guide-intro { max-width: 720px; margin: 7px 0 13px; color: var(--ink-dim); font-size: 12px; line-height: 1.65; }
.strategy-list { display: grid; gap: 8px; }
.strategy-card { display: grid; grid-template-columns: 32px minmax(0, 1fr) auto; align-items: center; gap: 11px; padding: 12px; background: color-mix(in srgb, var(--paper-card) 82%, var(--paper-panel)); border: 1px solid var(--paper-line); border-radius: 10px; }
.strategy-card.primary-strategy { background: color-mix(in srgb, #e9efdf 58%, var(--paper-card)); border-color: color-mix(in srgb, #7f9d68 50%, var(--paper-line)); }
.strategy-card.spending-strategy { background: color-mix(in srgb, #f3e6df 48%, var(--paper-card)); }
.strategy-mark { display: grid; width: 30px; height: 30px; place-items: center; color: var(--fox-gold-deep); background: var(--fox-gold-pale); border-radius: 50%; font-size: 12px; font-weight: 700; }
.strategy-card > div { min-width: 0; }
.strategy-card small { color: var(--ink-dim); font-size: 10px; }
.strategy-card h5 { margin: 2px 0 3px; font-size: 14px; }
.strategy-card p { margin: 0; color: var(--ink-dim); font-size: 11px; line-height: 1.55; }
.strategy-card p b { color: var(--ink); }
.strategy-card .strategy-impact { margin-top: 3px; color: var(--ink); }
.strategy-card button { white-space: nowrap; }
.embedded-gameplay { margin: 10px 0 0; }
@media (max-width: 700px) {
  .strategy-card { grid-template-columns: 32px minmax(0, 1fr); }
  .strategy-card button { grid-column: 2; justify-self: start; }
}
@media (max-width: 480px) {
  .koban-guide > header { align-items: flex-start; flex-direction: column; gap: 4px; }
}
</style>
