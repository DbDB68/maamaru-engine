<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PaperCard from './PaperCard.vue'
import PanelHeader from './PanelHeader.vue'
import PixelControl from './PixelControl.vue'
import SegmentedControl from './SegmentedControl.vue'
import type { SwordAnnotationBody, SwordArchiveAttentionItem, SwordArchiveEntry, SwordArchiveResponse } from '../types'
import {
  ARCHIVE_ALL_TYPES,
  SWORD_TYPE_OPTIONS,
  archiveFormLabel,
  archiveName,
  attentionReasonTexts,
  attentionTarget,
  duplicateOrdinals,
  filterArchiveEntries,
  formConfirmBody,
  keeperBody,
  levelConfirmBody,
  parseLevelInput,
  sortArchiveEntries,
} from '../archive'

// 刀帐档案：整本刀帐 + 玩家确认过的固定档案。编号/筛选/请求体全在
// archive.ts，这里只做展示和递请求；写操作成功后整页重新翻档（数据量小，
// 不做局部 patch）。布局一条中轴线：三块同宽对齐，卡片铺满容器。

const data = ref<SwordArchiveResponse | null>(null)
const loading = ref(true)
const error = ref('')
const saving = ref(false)
const query = ref('')
const swordType = ref<string>(ARCHIVE_ALL_TYPES)
// 每条「等级没读出来」的等级草稿，按 attentionKey 各自独立绑定，互不串行
const levelDrafts = ref<Record<string, string>>({})

const done = computed(() => Boolean(data.value?.done))
const summary = computed(() => data.value?.summary || null)
const entries = computed(() => data.value?.entries || [])
const attention = computed(() => data.value?.attention || [])

const sortedEntries = computed(() => sortArchiveEntries(entries.value))
const ordinals = computed(() => duplicateOrdinals(entries.value))
const visibleEntries = computed(() => filterArchiveEntries(sortedEntries.value, query.value, swordType.value))

const typeItems = computed(() => [
  { value: ARCHIVE_ALL_TYPES, label: ARCHIVE_ALL_TYPES, badge: entries.value.length },
  ...SWORD_TYPE_OPTIONS.map(type => ({
    value: type as string,
    label: type,
    badge: entries.value.filter(entry => entry.sword_type === type).length,
  })),
])

const overviewSubtitle = computed(() => {
  if (!data.value) return '整本刀帐 + 你确认过的固定档案'
  const parts = [`档案时间 ${data.value.observed_at ? fmtTime(data.value.observed_at) : '—'}`]
  if (data.value.snapshot_id != null) parts.push(`第 ${data.value.snapshot_id} 号盘点`)
  return parts.join(' · ')
})

function fmtTime(value: number) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value * 1000))
}

function entryOf(observationId: string | null): SwordArchiveEntry | null {
  if (observationId == null) return null
  return entries.value.find(entry => entry.observation_id === observationId) || null
}

// stale 条目没有 observation_id（标注对不上任何行），key 用指纹兜底
function attentionKey(item: SwordArchiveAttentionItem): string {
  return item.observation_id || `stale:${item.sword_catalog_id || '?'}:${item.kiwame_date || '?'}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.swordArchive()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '刀帐档案没有翻开'
  } finally {
    loading.value = false
  }
}

async function annotate(body: SwordAnnotationBody): Promise<boolean> {
  if (saving.value) return false
  saving.value = true
  error.value = ''
  try {
    await api.saveSwordAnnotation(body)
    await load()
    return true
  } catch (cause) {
    error.value = cause instanceof Error ? `这次没能记下：${cause.message}` : '这次没能记下，请重试'
    return false
  } finally {
    saving.value = false
  }
}

// 等你拿主意：是极 / 是普通 / 是要练的刀。旧标注从同 observation_id
// 的档案行里找回来，改一位、其余原样带回。
function confirmAttention(item: SwordArchiveAttentionItem, form: 'kiwame' | 'normal') {
  annotate(formConfirmBody(attentionTarget(item), form, entryOf(item.observation_id)?.human))
}
function keepAttention(item: SwordArchiveAttentionItem) {
  annotate(keeperBody(attentionTarget(item), true, entryOf(item.observation_id)?.human))
}

// 等级没读出来的条目：填 1~99 的整数才给递，记下成功就清掉这行的草稿
async function confirmLevel(item: SwordArchiveAttentionItem) {
  const key = attentionKey(item)
  const parsed = parseLevelInput(levelDrafts.value[key] || '')
  const body = parsed == null
    ? null
    : levelConfirmBody(attentionTarget(item), parsed, entryOf(item.observation_id)?.human)
  if (!body) {
    error.value = '等级要填 1～99 的整数，才能记下。'
    return
  }
  if (await annotate(body)) {
    const drafts = { ...levelDrafts.value }
    delete drafts[key]
    levelDrafts.value = drafts
  }
}

function toggleKeeper(entry: SwordArchiveEntry) {
  annotate(keeperBody(entry, !(entry.human?.keeper ?? false), entry.human))
}

onMounted(load)
</script>

<template>
  <section class="archive-panel">
    <PaperCard variant="task" tag="section">
      <PanelHeader title="刀帐档案" :subtitle="overviewSubtitle" variant="embedded">
        <template #actions>
          <button type="button" class="secondary" :disabled="loading" @click="load">{{ loading ? '正在翻档……' : '刷新档案' }}</button>
        </template>
      </PanelHeader>
      <div v-if="summary" class="archive-summary">
        <div><small>共</small><b>{{ summary.total }} 振</b></div>
        <div><small>你确认过</small><b>{{ summary.human_confirmed }} 振</b></div>
        <div><small>要练的刀</small><b>{{ summary.keepers }} 振</b></div>
        <div class="archive-summary-attention"><small>等你拿主意</small><b>{{ summary.attention_count }} 条</b></div>
      </div>
      <p v-if="!done && data" class="archive-notice">
        这份档案还不可信{{ data.reason ? `：${data.reason}` : '' }}。先去「配置 → 后勤配置 → 刀帐盘点」跑一次完整盘点，认清了再来对档案。
      </p>
    </PaperCard>

    <p v-if="error" class="archive-error" role="alert">{{ error }}</p>
    <div v-else-if="loading && !data" class="archive-empty">正在翻刀帐……</div>

    <template v-else-if="data">
      <PaperCard variant="task" tag="section" class="archive-attention">
        <h3 class="archive-sub">等你拿主意 · {{ attention.length }} 条</h3>
        <p v-if="!attention.length" class="archive-clean">现在没有要你拿主意的条目，刀帐清清爽爽。</p>
        <ul v-else class="archive-attention-list">
          <li v-for="item in attention" :key="attentionKey(item)" class="archive-attention-row">
            <div class="archive-row-head">
              <b>{{ item.name_zh || '没认出名字' }}</b>
              <small v-if="item.observation_id && ordinals.get(item.observation_id)">第 {{ ordinals.get(item.observation_id) }} 振</small>
              <span class="archive-facts">
                <template v-if="item.level != null">Lv.{{ item.level }}</template>
                <template v-if="item.kiwame_date"> · 显现 {{ item.kiwame_date }}</template>
              </span>
            </div>
            <div class="archive-badges">
              <i v-for="text in attentionReasonTexts(item.reasons)" :key="text" class="archive-reason">{{ text }}</i>
              <i v-for="hint in item.hints" :key="hint" class="archive-hint">{{ hint }}</i>
            </div>
            <div class="archive-actions">
              <button type="button" class="secondary" :disabled="saving" @click="confirmAttention(item, 'kiwame')">是极</button>
              <button type="button" class="secondary" :disabled="saving" @click="confirmAttention(item, 'normal')">是普通</button>
              <button type="button" class="secondary" :disabled="saving" @click="keepAttention(item)">是要练的刀</button>
            </div>
            <div v-if="item.reasons.includes('level_unknown')" class="archive-level">
              <PixelControl
                v-model="levelDrafts[attentionKey(item)]"
                type="number"
                :min="1"
                :max="99"
                placeholder="等级"
                aria-label="填等级（1 到 99）"
                @keyup.enter="confirmLevel(item)"
              />
              <button
                type="button"
                class="secondary"
                :disabled="saving || parseLevelInput(levelDrafts[attentionKey(item)] || '') == null"
                @click="confirmLevel(item)"
              >记下等级</button>
              <small v-if="(levelDrafts[attentionKey(item)] || '').trim() && parseLevelInput(levelDrafts[attentionKey(item)] || '') == null" class="archive-level-bad">要填 1～99 的整数</small>
            </div>
          </li>
        </ul>
      </PaperCard>

      <PaperCard variant="task" tag="section" class="archive-book">
        <h3 class="archive-sub">整本刀帐 · {{ entries.length }} 振</h3>
        <div class="archive-toolbar">
          <PixelControl v-model="query" type="search" placeholder="输入刀名找一找" aria-label="搜索刀名" />
          <em>{{ visibleEntries.length }} 振</em>
        </div>
        <SegmentedControl v-model="swordType" :items="typeItems" label="按刀种筛选" variant="wide" />
        <ul v-if="visibleEntries.length" class="archive-list">
          <li v-for="entry in visibleEntries" :key="entry.observation_id" class="archive-entry">
            <div class="archive-entry-name">
              <b>{{ archiveName(entry) }}</b>
              <small v-if="ordinals.get(entry.observation_id)">第 {{ ordinals.get(entry.observation_id) }} 振</small>
              <i v-if="entry.human?.form" class="archive-confirmed">你确认过</i>
              <i v-if="entry.human?.stale" class="archive-stale">待复核</i>
            </div>
            <div class="archive-entry-facts">
              <i class="archive-form" :class="entry.form_status" :title="(entry.form_evidence || []).join('；')">{{ archiveFormLabel(entry) }}</i>
              <span>Lv.{{ entry.level ?? '—' }}<i v-if="entry.human?.level != null" class="archive-confirmed archive-level-tag" title="机器没读出来，这个等级是你填的">你填的</i></span>
              <span>乱舞 Lv.{{ entry.tou_level ?? '—' }}</span>
              <span>显现 {{ entry.kiwame_date || '—' }}</span>
              <i v-for="hint in entry.hints" :key="hint" class="archive-hint">{{ hint }}</i>
            </div>
            <button
              type="button"
              class="archive-keeper"
              :class="{ active: entry.human?.keeper }"
              :aria-pressed="Boolean(entry.human?.keeper)"
              :disabled="saving"
              title="点了就是要练的刀，再点取消"
              @click="toggleKeeper(entry)"
            >{{ entry.human?.keeper ? '要练 ✓' : '要练' }}</button>
          </li>
        </ul>
        <p v-else class="archive-clean">没有找到这样的刀。</p>
      </PaperCard>
    </template>
  </section>
</template>

<style scoped>
/* 一条中轴线：三块卡片铺满同一容器。全局 task-card 的 max-width 和
   margin:0 auto 都要关掉——网格里 auto 外边距会打断拉伸，卡片会缩成
   内容宽悬在中间（编队页"东一块西一块"就是这么来的）。 */
.archive-panel { display: grid; gap: 13px; align-content: start; }
.archive-panel :deep(.task-card) { max-width: none; margin: 0; }
.archive-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.archive-summary > div { display: grid; gap: 3px; padding: 13px 16px; border-left: 1px solid var(--paper-line); }
.archive-summary > div:first-child { border-left: 0; }
.archive-summary small { color: var(--ink-dim); font-size: 10px; }
.archive-summary b { font-size: 18px; font-variant-numeric: tabular-nums; }
.archive-summary-attention b { color: #9f3d28; }
.archive-notice { margin: 12px 16px 14px; padding: 10px 13px; color: #9f3d28; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); border: 1px solid #d8a195; border-radius: 8px; font-size: 12px; }
.archive-error { margin: 0; padding: 12px 14px; color: #9f3d28; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); border: 1px solid #d8a195; border-radius: 9px; font-size: 12px; }
.archive-sub { margin: 2px 0 10px; color: var(--ink-dim); font-size: 12px; letter-spacing: .06em; }
.archive-clean { margin: 0; padding: 14px; color: var(--ink-dim); background: var(--paper); border: 1px dashed var(--paper-line); border-radius: 9px; font-size: 12px; text-align: center; }
.archive-empty { display: grid; gap: 3px; margin: 0; padding: 18px; color: var(--ink-dim); background: var(--paper-card); border: 1px dashed var(--paper-line); border-radius: 10px; font-size: 13px; }

/* 「等你拿主意」是全页最显眼的一块：金框压边，逐条列清理由和指认按钮。 */
.archive-attention { border-left: 5px solid var(--fox-gold-deep); }
.archive-attention-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.archive-attention-row { display: grid; gap: 8px; padding: 11px 13px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 9px; }
.archive-row-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; font-size: 13px; }
.archive-row-head small { color: var(--fox-gold-deep); font-size: 11px; }
.archive-facts { color: var(--ink-dim); font-size: 11px; font-variant-numeric: tabular-nums; }
.archive-badges { display: flex; flex-wrap: wrap; gap: 5px; }
.archive-reason { padding: 2px 8px; color: #7a5312; background: color-mix(in srgb, #f4e8cf 75%, var(--paper-card)); border: 1px solid #d9bd84; border-radius: 999px; font-size: 10px; font-style: normal; }
.archive-hint { padding: 2px 8px; color: var(--ink-dim); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 999px; font-size: 10px; font-style: normal; }
.archive-actions { display: flex; flex-wrap: wrap; gap: 7px; }
.archive-actions button { min-height: 30px; padding: 4px 13px; font-size: 12px; }
/* 等级填写照操作组的风格排：行内 flex 自然换行，不把行撑歪 */
.archive-level { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.archive-level :deep(.pixel-control) { width: 96px; min-height: 30px; padding: 4px 9px; color: var(--ink); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 8px; font: inherit; font-variant-numeric: tabular-nums; }
.archive-level button { min-height: 30px; padding: 4px 13px; font-size: 12px; }
.archive-level-bad { color: #9f3d28; font-size: 11px; }

.archive-toolbar { display: grid; grid-template-columns: minmax(170px, 330px) auto 1fr; align-items: center; gap: 10px; margin-bottom: 10px; color: var(--ink-dim); font-size: 12px; }
.archive-toolbar :deep(.pixel-control) { width: 100%; min-height: 36px; padding: 7px 10px; color: var(--ink); background: var(--paper); border: 1px solid var(--paper-line); border-radius: 8px; font: inherit; }
.archive-toolbar em { font-style: normal; white-space: nowrap; }
.archive-list { display: grid; gap: 7px; margin: 12px 0 0; padding: 0; list-style: none; }
/* 列表长就内部限高滚动，且全页只此一层内滚；窄屏取消内滚整页滚动。 */
@media (min-width: 901px) {
  .archive-list { max-height: 620px; overflow: auto; padding-right: 4px; }
}
.archive-entry { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 2fr) auto; gap: 6px 12px; align-items: center; padding: 9px 12px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 9px; font-size: 12px; }
.archive-entry-name { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; min-width: 0; }
.archive-entry-name b { font-size: 13px; }
.archive-entry-name small { color: var(--fox-gold-deep); font-size: 10px; }
.archive-confirmed { padding: 1px 7px; color: #426b36; background: color-mix(in srgb, #dcebd6 72%, var(--paper-card)); border: 1px solid #b2caa8; border-radius: 999px; font-size: 10px; font-style: normal; }
.archive-level-tag { margin-left: 5px; }
.archive-stale { padding: 1px 7px; color: #9f3d28; background: color-mix(in srgb, #f4dfd7 70%, var(--paper-card)); border: 1px solid #d8a195; border-radius: 999px; font-size: 10px; font-style: normal; }
.archive-entry-facts { display: flex; flex-wrap: wrap; align-items: center; gap: 5px 10px; color: var(--ink-dim); font-variant-numeric: tabular-nums; }
.archive-form { padding: 2px 8px; color: var(--ink); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 999px; font-size: 10px; font-style: normal; }
.archive-form.kiwame { color: #8a5a18; border-color: color-mix(in srgb, var(--fox-gold) 65%, var(--paper-line)); }
.archive-form.ambiguous { color: #9f3d28; border-color: #d8a195; }
.archive-keeper { min-height: 30px; padding: 4px 13px; color: var(--ink-dim); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 999px; font-size: 12px; }
.archive-keeper.active { color: #75560b; background: var(--fox-gold-pale); border-color: var(--fox-gold); font-weight: 700; }

@media (max-width: 900px) {
  .archive-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .archive-summary > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--paper-line); }
  .archive-summary > div:nth-child(4) { border-top: 1px solid var(--paper-line); }
  .archive-toolbar { grid-template-columns: 1fr auto; }
  .archive-entry { grid-template-columns: 1fr; }
  .archive-keeper { justify-self: start; }
}
@media (prefers-reduced-motion: reduce) {
  .archive-keeper, .archive-actions button { transition: none; }
}
</style>
