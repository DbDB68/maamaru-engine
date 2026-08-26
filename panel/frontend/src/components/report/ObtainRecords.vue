<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { eventTime, shanghaiDate } from './reportModel'

export interface ObtainRow {
  name: string
  count: number
  sources: Set<string>
  last: number
}

const props = defineProps<{
  rows: ObtainRow[]
  total: number
  rangeLabel: string
  loading: boolean
}>()

const query = ref('')
const shown = ref(12)

const filteredRows = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return props.rows
  return props.rows.filter(row => row.name.toLowerCase().includes(keyword) || [...row.sources].some(source => source.toLowerCase().includes(keyword)))
})
const visibleRows = computed(() => filteredRows.value.slice(0, shown.value))
const groups = computed(() => {
  const result: Array<{ date: string; rows: ObtainRow[] }> = []
  for (const row of visibleRows.value) {
    const date = shanghaiDate(row.last)
    const group = result.find(item => item.date === date)
    if (group) group.rows.push(row)
    else result.push({ date, rows: [row] })
  }
  return result
})
const remaining = computed(() => Math.max(0, filteredRows.value.length - shown.value))

function dateLabel(date: string) {
  const [, month, day] = date.split('-').map(Number)
  return `${month}月${day}日`
}

watch(() => [props.rangeLabel, query.value], () => { shown.value = 12 })
</script>

<template>
  <section class="obtain-records" :class="{ loading }">
    <header class="obtain-head">
      <div>
        <small>入手记录</small>
        <h3>{{ total ? `${total} 振 · ${rows.length} 种` : '还没有新入手' }}</h3>
        <p>{{ rangeLabel }}狐之助认出来的结果</p>
      </div>
      <label class="obtain-search">
        <span>查刀名或来源</span>
        <input v-model="query" type="search" placeholder="例如：博多、大阪城">
      </label>
    </header>

    <div v-if="groups.length" class="obtain-groups">
      <section v-for="group in groups" :key="group.date" class="obtain-day">
        <header><b>{{ dateLabel(group.date) }}</b><span>最近出现</span></header>
        <ul>
          <li v-for="row in group.rows" :key="row.name">
            <span class="obtain-name"><b>{{ row.name }}</b><em v-if="row.count > 1">×{{ row.count }}</em></span>
            <small>{{ [...row.sources].join('、') }}</small>
            <time>{{ eventTime(row.last).split(' ').at(-1) }}</time>
          </li>
        </ul>
      </section>
    </div>
    <div v-else-if="query" class="obtain-empty">没有找到“{{ query }}”。</div>
    <div v-else class="obtain-empty">这个时间段还没有认到新的刀剑男士。</div>

    <button v-if="remaining" type="button" class="secondary obtain-more" @click="shown += 12">再看 {{ Math.min(12, remaining) }} 种</button>
    <p class="obtain-note">记录不等于当前持有，手里有哪些仍以游戏内刀账为准。</p>
  </section>
</template>

<style scoped>
.obtain-records { background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; overflow: hidden; }
.obtain-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; padding: 16px 18px; background: linear-gradient(110deg, var(--fox-gold-pale), var(--paper-card)); border-bottom: 1px solid var(--paper-line); }
.obtain-head > div > small { color: var(--fox-gold-deep); font-weight: 700; letter-spacing: .08em; }
.obtain-head h3 { margin: 2px 0 0; font-size: 22px; }
.obtain-head p { margin: 3px 0 0; color: var(--ink-dim); font-size: 13px; }
.obtain-search { display: grid; gap: 4px; width: min(260px, 42%); color: var(--ink-dim); font-size: 11px; }
.obtain-search input { width: 100%; background: var(--paper-card); }
.obtain-groups { padding: 4px 18px 0; }
.obtain-day { padding: 12px 0 4px; }
.obtain-day + .obtain-day { border-top: 1px dashed var(--paper-line); }
.obtain-day > header { display: flex; align-items: baseline; gap: 8px; margin-bottom: 5px; }
.obtain-day > header b { color: var(--fox-gold-deep); }
.obtain-day > header span { color: var(--ink-dim); font-size: 11px; }
.obtain-day ul { list-style: none; margin: 0; padding: 0; }
.obtain-day li { display: grid; grid-template-columns: minmax(150px, .8fr) minmax(180px, 1fr) auto; align-items: baseline; gap: 12px; padding: 7px 8px; border-radius: 6px; }
.obtain-day li:nth-child(odd) { background: color-mix(in srgb, var(--paper) 64%, transparent); }
.obtain-name { display: flex; align-items: baseline; gap: 7px; min-width: 0; }
.obtain-name b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.obtain-name em { color: var(--fox-gold-deep); font-style: normal; font-weight: 700; }
.obtain-day small { overflow: hidden; color: var(--ink-dim); text-overflow: ellipsis; white-space: nowrap; }
.obtain-day time { color: var(--ink-dim); font-size: 12px; }
.obtain-more { display: block; margin: 12px auto 0; }
.obtain-empty { margin: 18px; padding: 28px 16px; color: var(--ink-dim); background: var(--paper); border: 1px dashed var(--paper-line); border-radius: 10px; text-align: center; }
.obtain-note { margin: 14px 18px 16px; padding-top: 10px; color: var(--ink-dim); border-top: 1px dashed var(--paper-line); font-size: 12px; }
@media (max-width: 620px) {
  .obtain-head { align-items: stretch; flex-direction: column; gap: 12px; padding: 14px; }
  .obtain-search { width: 100%; }
  .obtain-groups { padding-inline: 14px; }
  .obtain-day li { grid-template-columns: minmax(0, 1fr) auto; gap: 3px 10px; padding: 8px 6px; }
  .obtain-day small { grid-column: 1; grid-row: 2; }
  .obtain-day time { grid-column: 2; grid-row: 1 / 3; }
  .obtain-note { margin-inline: 14px; }
}
</style>
