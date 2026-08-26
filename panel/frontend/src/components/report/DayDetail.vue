<script setup lang="ts">
import { computed } from 'vue'
import type { InventoryGap, LedgerAttribution } from '../../types'
import { categoryLabel, dayLabel, eventTime, scriptNames, signed } from './reportModel'

const props = defineProps<{
  date: string
  resource: string
  totalDelta: number | null
  claimedAmount: number
  unexplained: number | null
  highlightCategory?: string
  attributions: LedgerAttribution[]
  runs: any[]
  gaps: InventoryGap[]
}>()

const emit = defineEmits<{ close: []; report: [gap: InventoryGap]; 'report-day': []; 'open-records': [date: string] }>()

const sortedAttributions = computed(() => [...props.attributions].sort((a, b) => a.ts - b.ts))
// 连续相同的归因（同标签同金额，如连续补充提灯）折叠成一条，显示次数与合计
const groupedAttributions = computed(() => {
  const groups: { ts: number; tsEnd: number; label: string; source: string; script: string; delta: number; count: number }[] = []
  for (const item of sortedAttributions.value) {
    const label = item.label || categoryLabel(item.source)
    const script = item.script || ''
    const delta = Number(item.delta || 0)
    const last = groups[groups.length - 1]
    if (last && last.label === label && last.script === script && last.delta === delta) {
      last.count += 1
      last.tsEnd = item.ts
    } else {
      groups.push({ ts: item.ts, tsEnd: item.ts, label, source: item.source, script, delta, count: 1 })
    }
  }
  return groups
})
const attributedTotal = computed(() => props.attributions.reduce((sum, item) => sum + Number(item.delta || 0), 0))

function gapDelta(gap: InventoryGap): string {
  const order = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符']
  return order.filter(name => gap.resource_delta?.[name])
    .map(name => `${name} ${signed(Number(gap.resource_delta![name]))}`).join(' · ')
}

function recordDateLabel(date: string): string {
  const [, month, day] = date.split('-').map(Number)
  return `${month}月${day}日`
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
      狐之助确认 {{ signed(attributedTotal) }}<template v-if="claimedAmount"> · 审神者认领 {{ signed(claimedAmount) }}</template><template v-if="unexplained"> · 还有 <b>{{ signed(unexplained) }}</b> 不知道谁干的</template>
    </p>

    <ul v-if="groupedAttributions.length" class="day-detail-attributions">
      <li v-for="group in groupedAttributions" :key="`${group.ts}:${group.label}`">
        <time>{{ eventTime(group.ts) }}<template v-if="group.count > 1"> → {{ eventTime(group.tsEnd) }}</template></time>
        <span><b>{{ group.label }}<template v-if="group.count > 1"> ×{{ group.count }}</template></b><small>{{ scriptNames[group.script || ''] || group.script || 'まあ丸' }} · {{ resource }} {{ signed(group.delta) }}<template v-if="group.count > 1"> · 共 {{ signed(group.delta * group.count) }}</template></small></span>
      </li>
    </ul>
    <p v-else class="day-detail-empty">这天没有能确认来源的{{ resource }}记录。</p>

    <button v-if="runs.length" type="button" class="day-detail-records" @click="emit('open-records', date)">
      <span>当天共执行 <b>{{ runs.length }}</b> 次任务</span>
      <em>查看 {{ recordDateLabel(date) }}全部记录 →</em>
    </button>

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
.day-detail h4 { margin: 2px 0 0; }
.day-detail small { color: var(--ink-dim); }
.day-detail-total { margin: 0; color: var(--ink-dim); }
.day-detail-total b { color: var(--ink); }
.day-detail-attributions { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.day-detail-attributions li { display: flex; gap: 10px; align-items: baseline; }
.day-detail-attributions time { color: var(--ink-dim); font-size: 12px; white-space: nowrap; }
.day-detail-attributions span { display: flex; flex-direction: column; }
.day-detail-records { display: flex; justify-content: space-between; align-items: center; gap: 12px; width: 100%; padding: 11px 12px; color: var(--ink); background: transparent; border: 0; border-top: 1px dashed var(--paper-line); text-align: left; }
.day-detail-records:hover { color: var(--fox-gold-deep); background: var(--fox-gold-pale); }
.day-detail-records em { color: var(--fox-gold-deep); font-style: normal; white-space: nowrap; }
.day-detail-empty { margin: 0; color: var(--ink-dim); }
.day-detail-gap { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; background: var(--fox-gold-pale); border-radius: 10px; padding: 10px 12px; }
.day-detail-gap p { margin: 2px 0; }
</style>
