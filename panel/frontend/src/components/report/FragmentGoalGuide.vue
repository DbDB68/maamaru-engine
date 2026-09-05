<script setup lang="ts">
import { computed } from 'vue'
import type { FragmentGuide, FragmentNotes, PlanningGoalAdvice } from '../../types'

const props = defineProps<{
  goal: PlanningGoalAdvice
  guide: FragmentGuide | null
  notes: FragmentNotes | null
}>()

const gap = computed(() => Math.max(0, Number(props.goal.target || 0) - Number(props.goal.current || 0)))
const best = computed(() => props.guide?.best_map || null)
// 加倍活动进行中时按倍率另算一圈期望；数据卡倍率缺失就当 2 倍
const campaignRuns = computed(() => {
  const campaign = props.notes?.campaign
  const rate = props.goal.fragment_rate
  if (!campaign?.active || !rate || !gap.value) return null
  return Math.max(1, Math.ceil(gap.value / (rate * (campaign.rate_multiplier || 2))))
})

function pct(rate: number) {
  const value = rate * 100
  return `${value >= 1 ? Math.round(value) : Math.round(value * 10) / 10}%`
}
</script>

<template>
  <section class="fragment-guide">
    <header>
      <span><small>怎么更接近目标</small><h4>「{{ props.goal.fragment }}」，去哪刷</h4></span>
      <b v-if="gap">还差 {{ gap }} 个</b>
    </header>

    <div class="strategy-list">
      <article v-if="best" class="strategy-card primary-strategy">
        <span class="strategy-mark">刷</span>
        <div>
          <small>异去 · 掉率最高的图</small>
          <h5>刷 {{ best.label }} 最划算</h5>
          <p>这张图每圈约 <b>{{ pct(best.rate) }}</b> 出「{{ props.goal.fragment }}」。
            <template v-if="props.goal.expected_runs">还差 {{ gap }} 个，按这掉率约还要 <b>{{ props.goal.expected_runs }} 圈</b>。</template>
          </p>
          <p v-if="campaignRuns != null && props.notes?.campaign" class="strategy-impact">
            「{{ props.notes.campaign.name }}」进行中，双倍期约 {{ campaignRuns }} 圈就够。
          </p>
          <p v-else-if="props.guide && props.guide.maps.length > 1" class="strategy-impact">
            其余图的掉率比这张低，换图只会更慢。
          </p>
        </div>
      </article>

      <article v-if="props.guide && props.guide.maps.length > 1" class="strategy-card">
        <span class="strategy-mark">比</span>
        <div>
          <small>各图掉率对比</small>
          <ul class="map-rate-list">
            <li v-for="entry in props.guide.maps" :key="entry.map_no">
              <b>{{ entry.label }}</b>：每圈约 {{ pct(entry.rate) }}
            </li>
          </ul>
        </div>
      </article>

      <article v-if="props.notes?.milestones?.length" class="strategy-card">
        <span class="strategy-mark">等</span>
        <div>
          <small>累计圈数 · 顺手拿的</small>
          <h5>打着打着还有里程碑奖励</h5>
          <p><template v-for="(milestone, index) in props.notes.milestones" :key="milestone.runs">
            <template v-if="index">；</template>累计 {{ milestone.runs }} 圈送 {{ milestone.reward }}
          </template>。</p>
        </div>
      </article>

      <p v-if="props.notes?.rate_source" class="rate-source">{{ props.notes.rate_source }}</p>
    </div>
  </section>
</template>

<style scoped>
.fragment-guide { margin-top: 16px; padding-top: 16px; border-top: 1px dashed var(--paper-line); }
.fragment-guide > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.fragment-guide > header span { display: grid; gap: 2px; }
.fragment-guide > header small { color: var(--ink-dim); font-size: 11px; }
.fragment-guide > header h4 { margin: 0; font-size: 17px; }
.fragment-guide > header > b { color: var(--fox-gold-deep); font-size: 13px; }
.strategy-list { display: grid; gap: 8px; margin-top: 12px; }
.strategy-card { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: center; gap: 11px; padding: 12px; background: color-mix(in srgb, var(--paper-card) 82%, var(--paper-panel)); border: 1px solid var(--paper-line); border-radius: 10px; }
.strategy-card.primary-strategy { background: color-mix(in srgb, #e9efdf 58%, var(--paper-card)); border-color: color-mix(in srgb, #7f9d68 50%, var(--paper-line)); }
.strategy-mark { display: grid; width: 30px; height: 30px; place-items: center; color: var(--fox-gold-deep); background: var(--fox-gold-pale); border-radius: 50%; font-size: 12px; font-weight: 700; }
.strategy-card > div { min-width: 0; }
.strategy-card small { color: var(--ink-dim); font-size: 10px; }
.strategy-card h5 { margin: 2px 0 3px; font-size: 14px; }
.strategy-card p { margin: 0; color: var(--ink-dim); font-size: 11px; line-height: 1.55; }
.strategy-card p b { color: var(--ink); }
.strategy-card .strategy-impact { margin-top: 3px; color: var(--ink); }
.map-rate-list { margin: 2px 0 0; padding-left: 16px; color: var(--ink-dim); font-size: 11px; line-height: 1.65; }
.map-rate-list b { color: var(--ink); }
.rate-source { margin: 2px 4px 0; color: var(--ink-dim); font-size: 10px; line-height: 1.5; opacity: 0.8; }
@media (max-width: 480px) {
  .fragment-guide > header { align-items: flex-start; flex-direction: column; gap: 4px; }
}
</style>
