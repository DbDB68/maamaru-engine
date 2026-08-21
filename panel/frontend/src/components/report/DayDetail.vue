<script setup lang="ts">
import { computed } from 'vue'
import type { InventoryGap, LedgerAttribution } from '../../types'
import { attributedStats, categoryLabel, dayLabel, deltaStats, elapsedTime, eventTime, loopTime, runElapsedSeconds, runTitle, scriptNames, signed } from './reportModel'

const props = defineProps<{
  date: string
  resource: string
  totalDelta: number | null
  highlightCategory?: string
  attributions: LedgerAttribution[]
  runs: any[]
  gaps: InventoryGap[]
}>()

const emit = defineEmits<{ close: []; report: [gap: InventoryGap]; 'report-day': [] }>()

const sortedAttributions = computed(() => [...props.attributions].sort((a, b) => a.ts - b.ts))
const attributedTotal = computed(() => props.attributions.reduce((sum, item) => sum + Number(item.delta || 0), 0))
const unexplained = computed(() => props.totalDelta == null ? null : props.totalDelta - attributedTotal.value)

function gapDelta(gap: InventoryGap): string {
  const order = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符']
  return order.filter(name => gap.resource_delta?.[name])
    .map(name => `${name} ${signed(Number(gap.resource_delta![name]))}`).join(' · ')
}
</script>

<template>
  <section class="day-detail" aria-live="polite">
    <header>
      <div>
        <small>{{ date }}</small>
        <h4>{{ dayLabel(date) }} · {{ resource }} {{ signed(totalDelta) }}<template v-if="highlightCategory"> · 看「{{ categoryLabel(highlightCategory) }}」这部分</template></h4>
      </div>
      <button type="button" class="secondary" @click="emit('close')">收起</button>
    </header>

    <p class="day-detail-total">
      狐之助确认 {{ signed(attributedTotal) }}<template v-if="unexplained"> · 还有 <b>{{ signed(unexplained) }}</b> 不知道谁干的</template>
    </p>

    <ul v-if="sortedAttributions.length" class="day-detail-attributions">
      <li v-for="item in sortedAttributions" :key="item.id">
        <time>{{ eventTime(item.ts) }}</time>
        <span><b>{{ item.label || categoryLabel(item.source) }}</b><small>{{ scriptNames[item.script || ''] || item.script || 'まあ丸' }} · {{ resource }} {{ signed(Number(item.delta)) }}</small></span>
      </li>
    </ul>
    <p v-else class="day-detail-empty">这天没有能确认来源的{{ resource }}记录。</p>

    <div v-if="runs.length" class="day-detail-runs">
      <h5>当天狐之助干的活</h5>
      <article v-for="run in runs" :key="run.run_id">
        <time>{{ eventTime(run.started_at) }}</time>
        <span><b>{{ runTitle(run) }}</b><small>{{ elapsedTime(runElapsedSeconds(run)) }}<template v-if="run.average_loop_seconds"> · {{ loopTime(run.average_loop_seconds) }}</template></small></span>
        <em v-if="attributedStats(run) || deltaStats(run)">{{ attributedStats(run) || deltaStats(run) }}</em>
      </article>
    </div>

    <div v-for="gap in gaps" :key="gap.gap_key" class="day-detail-gap">
      <div>
        <strong>🦊 这段家底变化还没人认领</strong>
        <p>{{ gapDelta(gap) }}</p>
        <small>{{ eventTime(gap.started_at) }} → {{ eventTime(gap.ended_at) }}</small>
      </div>
      <button type="button" class="primary" @click="emit('report', gap)">这是我干的，说明一下</button>
    </div>

    <div v-if="!gaps.length && unexplained" class="day-detail-gap">
      <div>
        <strong>🦊 {{ resource }} {{ signed(unexplained) }} 还不知道是谁干的</strong>
        <small>这部分没有赶上库存盘点，只能按天估算；是你自己动的话就说一声。</small>
      </div>
      <button type="button" class="primary" @click="emit('report-day')">这是我干的，说明一下</button>
    </div>
  </section>
</template>

<style scoped>
.day-detail { background: var(--paper); border: 1px solid var(--paper-line); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.day-detail > header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.day-detail h4, .day-detail h5 { margin: 2px 0 0; }
.day-detail small { color: var(--ink-dim); }
.day-detail-total { margin: 0; color: var(--ink-dim); }
.day-detail-total b { color: var(--ink); }
.day-detail-attributions { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.day-detail-attributions li { display: flex; gap: 10px; align-items: baseline; }
.day-detail-attributions time, .day-detail-runs time { color: var(--ink-dim); font-size: 12px; white-space: nowrap; }
.day-detail-attributions span, .day-detail-runs span { display: flex; flex-direction: column; }
.day-detail-runs { display: flex; flex-direction: column; gap: 6px; border-top: 1px dashed var(--paper-line); padding-top: 10px; }
.day-detail-runs article { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.day-detail-runs em { font-style: normal; color: var(--ink-dim); font-size: 12px; }
.day-detail-empty { margin: 0; color: var(--ink-dim); }
.day-detail-gap { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; background: var(--fox-gold-pale); border-radius: 10px; padding: 10px 12px; }
.day-detail-gap p { margin: 2px 0; }
</style>
