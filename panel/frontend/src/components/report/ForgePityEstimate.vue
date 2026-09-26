<script setup lang="ts">
import { computed } from 'vue'
import type { PlanningReport } from '../../types'
import { FORGE_POINT_OPTIONS, forgePityEstimate } from './forgePity'
import { forgePityDraft as draft } from './forgePityDraft'

const props = defineProps<{
  tenForge: NonNullable<NonNullable<PlanningReport['resource_watch']>['ten_forge']>
}>()

const estimate = computed(() => draft.currentPoints !== '' && draft.targetPoints !== ''
  ? forgePityEstimate(Number(draft.currentPoints), Number(draft.targetPoints), draft.talisman, props.tenForge.resources)
  : null)
const recipe = computed(() => ['木炭', '玉钢', '冷却材', '砥石']
  .map(name => props.tenForge.resources.find(row => row.resource === name)?.per_forge)
  .map(cost => cost == null ? '?' : fmt(cost / 10))
  .join('/'))

function fmt(value: number) { return value.toLocaleString() }
function clearDraft() {
  draft.currentPoints = ''
  draft.targetPoints = ''
  draft.talisman = 'none'
}
</script>

<template>
  <details class="forge-pity">
    <summary>按显现积分算限锻保底</summary>
    <p class="intro">填本期游戏里看到的积分和保底线。当前按 {{ recipe }} 配方试算，请核对本期指定配方与积分规则；出货可以提前收手。</p>
    <div class="pity-fields">
      <label>当前显现积分
        <input v-model="draft.currentPoints" type="number" min="0" max="1000000" step="1" placeholder="游戏里看到的数">
      </label>
      <label>本期保底积分
        <input v-model="draft.targetPoints" type="number" min="1" max="1000000" step="1" placeholder="例如 5000">
      </label>
      <label>每锻使用的御札
        <select v-model="draft.talisman">
          <option v-for="option in FORGE_POINT_OPTIONS" :key="option.key" :value="option.key">{{ option.label }}</option>
        </select>
      </label>
    </div>
    <p v-if="draft.currentPoints === '' || draft.targetPoints === ''" class="pity-hint">积分填齐后，再按十连整批算材料。</p>
    <p v-else-if="!estimate" class="pity-hint">积分要填 0 以上的整数，保底线须大于 0。</p>
    <template v-else>
      <p class="pity-result" v-if="estimate.batches === 0">已达到填写的保底积分，不需要再为这条线准备十连。</p>
      <template v-else>
        <p class="pity-result">还差 <b>{{ fmt(estimate.remainingPoints) }} 点</b>；按每次十连 {{ estimate.pointsPerTen }} 点，还需 <b>{{ estimate.batches }} 次十连</b>（{{ estimate.swords }} 把）。</p>
        <div class="pity-costs">
          <p v-for="row in estimate.costs" :key="row.resource" :class="{ short: row.shortfall != null && row.shortfall > 0 }">
            <span>{{ row.resource }}<b>需 {{ fmt(row.required) }}</b></span>
            <small v-if="row.shortfall == null">库存未读到，差额待确认</small>
            <small v-else-if="row.shortfall > 0">还差 {{ fmt(row.shortfall) }}</small>
            <small v-else>现有库存够用</small>
          </p>
        </div>
        <p v-if="estimate.talismans" class="pity-hint">还需御札 {{ fmt(estimate.talismans) }} 张；まあ丸尚未记录御札库存，请另行核对。</p>
        <p v-if="estimate.trackedCostsCovered" class="pity-hint">已记录的六项资源够这轮试算；刀位、御札和本期配方仍要在游戏里核对。</p>
      </template>
    </template>
    <p class="pity-disclaimer">这只是保底预算，不会自动改锻刀次数或替你点火。数字仅在本次面板会话保留，换期限锻请重新核对。</p>
    <button type="button" class="clear-draft" @click="clearDraft">清空试算</button>
  </details>
</template>

<style scoped>
.forge-pity { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--paper-line); }
.forge-pity summary { color: var(--fox-gold-deep); font-size: 11px; font-weight: 700; cursor: pointer; }
.forge-pity .intro, .pity-hint, .pity-disclaimer { margin: 8px 0 0; color: var(--ink-dim); font-size: 10px; line-height: 1.5; }
.pity-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
.pity-fields label { display: grid; min-width: 0; gap: 3px; color: var(--ink-dim); font-size: 10px; }
.pity-fields input, .pity-fields select { box-sizing: border-box; width: 100%; min-width: 0; padding: 6px; border: 1px solid var(--paper-line); border-radius: 5px; background: var(--paper-card); color: var(--ink); font: inherit; }
.pity-result { margin: 12px 0 8px; font-size: 12px; line-height: 1.5; }
.pity-costs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; }
.pity-costs p { display: grid; gap: 3px; margin: 0; padding: 7px; border: 1px solid var(--paper-line); border-radius: 5px; font-size: 10px; }
.pity-costs span { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 3px; }
.pity-costs small { color: var(--ink-dim); }
.pity-costs .short { border-color: #d8a99d; background: #f8eeea; }
.pity-costs .short small { color: #9f3d28; }
.clear-draft { margin-top: 8px; padding: 3px 0; border: 0; background: transparent; color: var(--fox-gold-deep); font-size: 10px; cursor: pointer; }
@media (max-width: 760px) { .pity-fields, .pity-costs { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .pity-fields, .pity-costs { grid-template-columns: 1fr; } }
</style>
