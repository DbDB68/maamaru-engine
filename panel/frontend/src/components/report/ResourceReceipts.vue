<script setup lang="ts">
import { computed } from 'vue'
import type { LedgerAttribution } from '../../types'
import { eventTime, signed, recordOrigin, categoryLabel, categoryOf, shanghaiDate } from './reportModel'
const props = defineProps<{ receipts: LedgerAttribution[] }>()
const days = computed(() => {
  const entries = new Map<string, { ts: number; title: string; origin: string; resources: Record<string, number> }>()
  for (const row of [...props.receipts].sort((a, b) => b.ts - a.ts)) {
    const title = row.source.startsWith('unknown') || row.confidence === 'unresolved' ? '来源未确认'
      : (row.label || categoryLabel(categoryOf(row.source))).split(` ${row.resource} `)[0]
    const origin = recordOrigin(row)
    const key = `${row.ts}:${row.source}:${title}:${origin}`
    const entry = entries.get(key) || { ts: row.ts, title, origin, resources: {} }
    entry.resources[row.resource] = (entry.resources[row.resource] || 0) + row.delta
    entries.set(key, entry)
  }
  const grouped = new Map<string, typeof entries extends Map<string, infer T> ? T[] : never>()
  for (const entry of entries.values()) {
    const date = shanghaiDate(entry.ts)
    grouped.set(date, [...(grouped.get(date) || []), entry])
  }
  return [...grouped].map(([date, rows]) => ({ date, rows }))
})
</script>
<template>
  <section class="receipts" aria-label="资源收支">
    <p v-if="!days.length">这段时间还没有资源收支记录。</p>
    <section v-for="day in days" :key="day.date">
      <h3>{{ day.date }}</h3>
      <details v-for="(row, index) in day.rows" :key="`${row.ts}:${index}`">
        <summary class="receipt-row"><time>{{ eventTime(row.ts).split(' ').at(-1) }}</time><b>{{ row.title }}</b><span class="receipt-amounts"><strong v-for="(delta, resource) in row.resources" :key="resource" :class="{ loss: delta < 0 }">{{ resource }} {{ signed(delta) }}</strong></span></summary>
        <p>{{ row.origin }}</p>
      </details>
    </section>
  </section>
</template>
<style scoped>
.receipts { background: var(--paper-card); padding: 20px; }
h3 { margin: 12px 0; font-size: 15px; }
.receipt-row { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 12px 0; border-top: 1px solid var(--border-light, #ddd3c5); }
time, small, p { color: var(--ink-dim); font-size: 12px; }
small { display: block; margin-top: 4px; }
.receipt-amounts { display: flex; gap: 8px 16px; flex-wrap: wrap; justify-content: flex-end; }
summary { cursor: pointer; }
strong { color: #527b3d; }
strong.loss { color: #a2513e; }
.receipt-row span { overflow-wrap: anywhere; }
@media (max-width: 600px) { .receipts { padding: 14px; } .receipt-row { grid-template-columns: 48px minmax(0, 1fr); } .receipt-amounts { grid-column: 2; justify-content: flex-start; } }
</style>
