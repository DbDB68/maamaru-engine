<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PlanningGoalAdvice, PlanningReport } from '../../types'

const props = defineProps<{
  planning: PlanningReport
  budgets: PlanningGoalAdvice[]
}>()
const emit = defineEmits<{ openExpedition: [] }>()

const forgeMode = ref<'normal' | 'ten'>('normal')
const watch = computed(() => forgeMode.value === 'ten'
  ? props.planning.resource_watch?.ten_forge
  : props.planning.resource_watch)
const koban = computed(() => props.planning.koban_watch)
const limitingLabel = computed(() => watch.value?.limiting?.join('、') || '还没看清')

function fmt(value: number | null | undefined) {
  return value == null ? '—' : Math.round(value).toLocaleString()
}
</script>

<template>
  <section class="planning-overview">
    <article class="resource-watch">
      <header>
        <div><small>锻刀资源</small><h3>哪样先不够用</h3></div>
        <div class="forge-modes" role="group" aria-label="锻刀方式">
          <button type="button" :aria-pressed="forgeMode === 'normal'" @click="forgeMode = 'normal'">普通锻刀</button>
          <button v-if="planning.resource_watch?.ten_forge" type="button" :aria-pressed="forgeMode === 'ten'" @click="forgeMode = 'ten'">十连限锻</button>
        </div>
      </header>
      <div v-if="watch?.forge_capacity != null" class="watch-verdict">
        <small>现在最先卡住</small>
        <strong>{{ limitingLabel }}</strong>
        <p>按当前配比，最多还能{{ forgeMode === 'ten' ? '十连锻' : '锻' }} <b>{{ fmt(watch.forge_capacity) }} {{ forgeMode === 'ten' ? '次' : '炉' }}</b>。</p>
      </div>
      <div v-else class="watch-verdict unknown">
        <strong>还缺一次完整盘点</strong>
        <p>材料和符的数量读齐后，才能判断哪样先卡住。</p>
      </div>
      <div class="forge-resources">
        <p v-for="row in watch?.resources || []" :key="row.resource" :class="{ limiting: watch?.limiting.includes(row.resource) }">
          <span>{{ row.resource }}<em v-if="watch?.limiting.includes(row.resource)">短板</em></span>
          <b>{{ fmt(row.current) }}</b>
          <small v-if="row.forge_capacity != null">约 {{ fmt(row.forge_capacity) }} {{ forgeMode === 'ten' ? '次' : '炉' }}</small>
          <small v-else>尚未观察</small>
        </p>
      </div>
      <p class="forge-note">{{ forgeMode === 'ten' ? '每次十连消耗四材料各 10 份、委托符 9 张、加速符 10 张。' : '普通锻刀每炉用委托符 1 张；加速符按实际选择使用。' }}</p>
    </article>

    <article class="koban-watch">
      <header>
        <span class="hakata-seal" aria-hidden="true">博</span>
        <div><small>博多账房</small><h3>小判消耗监督</h3></div>
      </header>
      <blockquote v-if="koban?.current != null">
        账上有 {{ fmt(koban.current) }}，已安排 {{ fmt(koban.reserved) }} 小判；能动用 {{ fmt(koban.available) }}。有余力就继续攒，博多很满意。
      </blockquote>
      <blockquote v-else>等盘点读到小判，咱再把能花的、留好的分开算清楚。</blockquote>
      <div class="koban-numbers">
        <p><small>现有家底</small><b>{{ fmt(koban?.current) }}</b></p>
        <p><small>已留预算</small><b>{{ fmt(koban?.reserved) }}</b></p>
        <p><small>还能动用</small><b>{{ fmt(koban?.available) }}</b></p>
      </div>
      <p class="spending-trace">近 {{ koban?.spending_days || 14 }} 天已记清的支出：<b>{{ fmt(koban?.confirmed_spending) }} 小判</b></p>
      <ul v-if="budgets.length" class="budget-list">
        <li v-for="goal in budgets" :key="goal.id">
          <span><b>{{ goal.event || goal.note || '活动预算' }}</b><small v-if="goal.impact_days">会让攒钱目标推迟约 {{ goal.impact_days }} 天</small></span>
          <strong>{{ fmt(goal.target) }}</strong>
        </li>
      </ul>
      <button type="button" class="secondary" @click="emit('openExpedition')">去安排小判远征</button>
    </article>
  </section>
</template>

<style scoped>
.planning-overview { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr); gap: 10px; }
.planning-overview article { min-width: 0; padding: 17px 18px; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; }
.planning-overview article > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.planning-overview article > header div { display: grid; gap: 2px; }
.planning-overview h3 { margin: 0; font-size: 17px; }
.planning-overview header small { color: var(--fox-gold-deep); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.planning-overview header > span:not(.hakata-seal) { color: var(--ink-dim); font-size: 10px; }
.watch-verdict { margin: 15px 0 12px; }
.watch-verdict small { display: block; color: var(--ink-dim); font-size: 10px; }
.watch-verdict strong { display: block; margin: 2px 0; font-size: 23px; }
.watch-verdict p { margin: 0; color: var(--ink-dim); font-size: 11px; }
.watch-verdict p b { color: var(--ink); }
.watch-verdict.unknown { padding: 7px 0; }
.watch-verdict.unknown strong { font-size: 17px; }
.forge-modes { display: flex; flex-wrap: wrap; gap: 4px; }
.forge-modes button { padding: 4px 7px; border: 1px solid var(--paper-line); border-radius: 6px; background: transparent; color: var(--ink-dim); font-size: 10px; cursor: pointer; }
.forge-modes button[aria-pressed="true"] { border-color: var(--fox-gold-deep); background: var(--fox-gold-pale); color: var(--ink); }
.forge-resources { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--paper-line); border-bottom: 1px solid var(--paper-line); }
.forge-resources p { display: grid; gap: 3px; margin: 0; padding: 10px 9px; border-left: 1px solid var(--paper-line); border-top: 1px solid var(--paper-line); }
.forge-resources p:nth-child(3n+1) { border-left: 0; }
.forge-resources p:nth-child(-n+3) { border-top: 0; }
.forge-resources span { display: flex; align-items: center; justify-content: space-between; gap: 4px; color: var(--ink-dim); font-size: 10px; }
.forge-resources em { padding: 1px 4px; color: #9f3d28; background: #f3e6df; border-radius: 999px; font-size: 10px; font-style: normal; }
.forge-resources b { font-size: 14px; }
.forge-resources small { color: var(--ink-dim); font-size: 10px; }
.forge-resources .limiting { background: color-mix(in srgb, #f3e6df 58%, var(--paper-card)); }
.forge-note { margin: 8px 0 0; color: var(--ink-dim); font-size: 10px; }
.planning-overview .koban-watch { border-left: 5px solid #b78527; }
.planning-overview .koban-watch > header { justify-content: flex-start; }
.hakata-seal { display: grid; flex: 0 0 36px; width: 36px; height: 36px; place-items: center; color: #fffaf0; background: #b78527; border: 2px solid #75510c; border-radius: 50%; box-shadow: inset 0 0 0 2px #dfc06d; font-size: 16px; font-weight: 700; }
.koban-watch blockquote { margin: 13px 0; padding: 9px 11px; color: #5f4a22; background: var(--fox-gold-pale); border: 0; border-left: 3px solid #b78527; font-size: 11px; line-height: 1.6; }
.koban-numbers { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--paper-line); border-radius: 7px; }
.koban-numbers p { display: grid; gap: 3px; margin: 0; padding: 9px; border-left: 1px solid var(--paper-line); }
.koban-numbers p:first-child { border-left: 0; }
.koban-numbers small { color: var(--ink-dim); font-size: 10px; }
.koban-numbers b { font-size: 14px; }
.spending-trace { margin: 10px 0 0; color: var(--ink-dim); font-size: 10px; }
.spending-trace b { color: var(--ink); }
.budget-list { display: grid; gap: 0; margin: 10px 0 0; padding: 0; border-top: 1px solid var(--paper-line); list-style: none; }
.budget-list li { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--paper-line); font-size: 11px; }
.budget-list span { display: grid; gap: 2px; }
.budget-list small { color: var(--ink-dim); font-size: 10px; }
.koban-watch > button { margin-top: 10px; }
@media (max-width: 760px) {
  .planning-overview { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  .planning-overview article { padding: 14px; }
  .forge-resources { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .forge-resources p:nth-child(n) { border-top: 1px solid var(--paper-line); border-left: 1px solid var(--paper-line); }
  .forge-resources p:nth-child(2n+1) { border-left: 0; }
  .forge-resources p:nth-child(-n+2) { border-top: 0; }
  .koban-numbers { grid-template-columns: 1fr; }
  .koban-numbers p { border-top: 1px solid var(--paper-line); border-left: 0; }
  .koban-numbers p:first-child { border-top: 0; }
}
</style>
