<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../../api'
import type { SwordInventoryRow, SwordInventorySnapshot } from '../../types'

interface SwordGroup { name: string; rows: SwordInventoryRow[] }

const snapshot = ref<SwordInventorySnapshot | null>(null)
const loading = ref(true)
const error = ref('')
const query = ref('')
const shown = ref(36)

const groups = computed<SwordGroup[]>(() => {
  const grouped = new Map<string, SwordInventoryRow[]>()
  for (const sword of snapshot.value?.swords || []) {
    const rows = grouped.get(sword.name_zh) || []
    rows.push(sword)
    grouped.set(sword.name_zh, rows)
  }
  return [...grouped].map(([name, rows]) => ({ name, rows }))
})

const filteredGroups = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase('zh-CN')
  return needle ? groups.value.filter(group => group.name.toLocaleLowerCase('zh-CN').includes(needle)) : groups.value
})
const visibleGroups = computed(() => filteredGroups.value.slice(0, shown.value))
const duplicateKinds = computed(() => groups.value.filter(group => group.rows.length > 1).length)
const scannedCount = computed(() => snapshot.value?.swords.length || 0)
const missingCount = computed(() => snapshot.value?.missing == null
  ? Math.max(0, Number(snapshot.value?.owned || 0) - scannedCount.value)
  : Math.max(0, snapshot.value.missing))

function fmt(value: number | null | undefined) {
  return value == null ? '—' : Math.round(value).toLocaleString()
}

function capturedAt(value: number) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value * 1000))
}

function statEntries(row: SwordInventoryRow) {
  return Object.entries(row.stats || {}).filter((entry): entry is [string, number] => typeof entry[1] === 'number')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    snapshot.value = (await api.swordInventory()).snapshot
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '刀帐没有翻开'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="sword-inventory">
    <header class="sword-heading">
      <div>
        <small>刀帐盘点</small>
        <h2>所持刀剑</h2>
        <p>一振一行地收好，同名刀也不会被合并。</p>
      </div>
      <button type="button" :disabled="loading" @click="load">{{ loading ? '正在翻帐……' : '重新翻帐' }}</button>
    </header>

    <p v-if="error" class="sword-error">{{ error }}</p>
    <div v-else-if="loading && !snapshot" class="sword-empty">正在整理最近一次盘点……</div>
    <div v-else-if="!snapshot" class="sword-empty">
      <b>还没有所持刀剑记录</b>
      <span>先运行一次“刀帐盘点”，狐之助就会把结果放到这里。</span>
    </div>
    <template v-else>
      <section class="sword-summary" :class="{ incomplete: missingCount > 0 }">
        <div class="sword-count"><small>所持</small><b>{{ fmt(snapshot.owned ?? scannedCount) }}<i v-if="snapshot.capacity != null"> / {{ fmt(snapshot.capacity) }}</i></b></div>
        <div><small>认清</small><b>{{ fmt(scannedCount) }} 振</b></div>
        <div><small>刀名</small><b>{{ fmt(groups.length) }} 种</b></div>
        <div><small>有同伴的刀名</small><b>{{ fmt(duplicateKinds) }} 种</b></div>
        <p>
          <template v-if="missingCount">这次还有 {{ fmt(missingCount) }} 振没认清，下面只展示已经确认的结果。</template>
          <template v-else>这次盘点已经和游戏里的所持数对上。</template>
          <time>{{ capturedAt(snapshot.captured_at) }}</time>
        </p>
      </section>

      <label class="sword-search">
        <span>找一振刀</span>
        <input v-model="query" type="search" placeholder="输入刀名" @input="shown = 36">
        <em>{{ filteredGroups.length }} 种</em>
      </label>

      <div v-if="visibleGroups.length" class="sword-list">
        <details v-for="group in visibleGroups" :key="group.name" class="sword-group">
          <summary>
            <span><b>{{ group.name }}</b><small v-if="group.rows.length > 1">同名 {{ group.rows.length }} 振</small></span>
            <span class="sword-glance">最高 Lv.{{ Math.max(...group.rows.map(row => row.level || 0)) || '—' }}</span>
          </summary>
          <ol>
            <li v-for="(row, index) in group.rows" :key="`${row.sword_id}-${index}`">
              <header>
                <b>{{ group.rows.length > 1 ? `第 ${index + 1} 振` : group.name }}</b>
                <span>Lv.{{ fmt(row.level) }} · 乱舞 Lv.{{ fmt(row.tou_level) }}</span>
              </header>
              <div class="sword-vitals">
                <span><small>生存</small>{{ fmt(row.survival) }} / {{ fmt(row.survival_max) }}</span>
                <span><small>疲劳</small>{{ fmt(row.fatigue) }} / {{ fmt(row.fatigue_max) }}</span>
                <span v-if="row.kiwame_date"><small>显现</small>{{ row.kiwame_date }}</span>
              </div>
              <div v-if="statEntries(row).length" class="sword-stats">
                <span v-for="[name, value] in statEntries(row)" :key="name"><small>{{ name }}</small>{{ value }}</span>
              </div>
            </li>
          </ol>
        </details>
      </div>
      <p v-else class="sword-empty">没有找到这个刀名。</p>
      <button v-if="shown < filteredGroups.length" type="button" class="show-more" @click="shown += 36">再看一些（还有 {{ filteredGroups.length - shown }} 种）</button>
    </template>
  </section>
</template>

<style scoped>
.sword-inventory { display: grid; gap: 13px; }
.sword-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 17px 19px; background: var(--paper-card); border: 1px solid var(--paper-line); border-left: 5px solid color-mix(in srgb, var(--fox-gold-deep) 72%, var(--ink)); box-shadow: 4px 4px 0 color-mix(in srgb, var(--paper-line) 48%, transparent); }
.sword-heading small { color: var(--fox-gold-deep); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.sword-heading h2 { margin: 2px 0 0; font-size: clamp(19px, 2.3vw, 25px); }
.sword-heading p { margin: 4px 0 0; color: var(--ink-dim); font-size: 12px; }
.sword-heading button, .show-more { padding: 7px 12px; color: var(--fox-gold-deep); background: var(--paper); border: 1px solid var(--paper-line); border-radius: 8px; cursor: pointer; }
.sword-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 12px; overflow: hidden; }
.sword-summary > div { display: grid; gap: 3px; padding: 13px 15px; border-left: 1px solid var(--paper-line); }
.sword-summary > div:first-child { border-left: 0; }
.sword-summary small { color: var(--ink-dim); font-size: 10px; }
.sword-summary b { font-size: 18px; font-variant-numeric: tabular-nums; }
.sword-summary b i { color: var(--ink-dim); font-size: 12px; font-style: normal; font-weight: 500; }
.sword-summary > p { display: flex; grid-column: 1 / -1; justify-content: space-between; gap: 12px; margin: 0; padding: 9px 15px; color: #426b36; background: color-mix(in srgb, #dcebd6 70%, var(--paper-card)); border-top: 1px solid var(--paper-line); font-size: 11px; }
.sword-summary.incomplete > p { color: #9f3d28; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); }
.sword-summary time { color: var(--ink-dim); white-space: nowrap; }
.sword-search { display: grid; grid-template-columns: auto minmax(150px, 340px) auto 1fr; align-items: center; gap: 9px; padding: 10px 13px; color: var(--ink-dim); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 10px; font-size: 12px; }
.sword-search input { width: 100%; min-width: 0; }
.sword-search em { font-style: normal; white-space: nowrap; }
.sword-list { display: grid; gap: 7px; }
.sword-group { background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 10px; overflow: hidden; }
.sword-group > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 14px; cursor: pointer; list-style: none; }
.sword-group > summary::-webkit-details-marker { display: none; }
.sword-group > summary::before { width: 5px; height: 22px; flex: 0 0 auto; background: var(--fox-gold); border-radius: 999px; content: ''; }
.sword-group > summary > span:first-of-type { display: flex; flex: 1 1 auto; align-items: baseline; gap: 8px; }
.sword-group summary small, .sword-glance { color: var(--ink-dim); font-size: 11px; }
.sword-group ol { display: grid; gap: 7px; margin: 0; padding: 0 10px 10px; list-style: none; }
.sword-group li { display: grid; gap: 8px; padding: 11px 12px; background: var(--paper); border-top: 1px solid var(--paper-line); }
.sword-group li header { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
.sword-group li header span { color: var(--ink-dim); }
.sword-vitals, .sword-stats { display: flex; flex-wrap: wrap; gap: 6px; }
.sword-vitals span, .sword-stats span { display: flex; gap: 4px; padding: 3px 7px; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 6px; font-size: 11px; font-variant-numeric: tabular-nums; }
.sword-vitals small, .sword-stats small { color: var(--ink-dim); }
.sword-error, .sword-empty { display: grid; gap: 3px; margin: 0; padding: 18px; color: var(--ink-dim); background: var(--paper-card); border: 1px dashed var(--paper-line); border-radius: 10px; font-size: 13px; }
.sword-error { color: #9f3d28; }
.show-more { justify-self: center; }
@media (max-width: 620px) {
  .sword-heading { align-items: stretch; flex-direction: column; padding: 15px 14px; }
  .sword-heading button { width: 100%; }
  .sword-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sword-summary > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--paper-line); }
  .sword-summary > div:nth-child(4) { border-top: 1px solid var(--paper-line); }
  .sword-summary > p { align-items: flex-start; flex-direction: column; gap: 3px; }
  .sword-search { grid-template-columns: 1fr auto; }
  .sword-search span { grid-column: 1 / -1; }
  .sword-group li header { align-items: flex-start; flex-direction: column; gap: 3px; }
}
</style>
