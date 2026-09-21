<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import LogPanel from './LogPanel.vue'
import PanelHeader from './PanelHeader.vue'
import PaperCard from './PaperCard.vue'
import SegmentedControl from './SegmentedControl.vue'
import type { FormationCandidate, FormationSwapEvent, FormationTeam, HonmaruFormationProfile } from '../types'
import {
  candidateEvidenceGaps,
  candidateFormLabel,
  candidateName,
  formationResultText,
  pickSwapEvent,
  swapEligibility,
} from '../formation'

// 编队页最小闭环：选部队 → 选位置 → 选一振刀 → 运行 → 如实回显后端
// 验收结果。匹配、翻页、同名裁决、换后验收全在后端执行器；这里只做
// 门闩（档案可信/没在跑/证据够），绝不自己宣称换人成功。
// 视觉复用现有组件（PanelHeader/PaperCard/SegmentedControl/LogPanel +
// 全局按钮类），本文件只管布局与编队特有的槽位/候选行。

const props = withDefaults(defineProps<{
  running?: boolean
  current?: string | null
  stopping?: boolean
}>(), { running: false, current: null, stopping: false })
const emit = defineEmits<{ stop: []; notify: [message: string] }>()

const TEAM_LABELS = ['部队一', '部队二', '部队三', '部队四', '部队五']

const profile = ref<HonmaruFormationProfile | null>(null)
const loading = ref(true)
const loadError = ref('')
const teamNo = ref(1)
const slotNo = ref<number | null>(null)
const selectedId = ref('')
const query = ref('')
const starting = ref(false)
const result = ref<FormationSwapEvent['payload'] | null>(null)
const resultMissing = ref(false)
const logOpen = ref(false)
let pendingRunId = ''
let pendingSince = 0
let pollTimer = 0
let seenRunning = false
let stoppedMisses = 0

const pool = computed(() => profile.value?.candidate_pool || null)
const poolDone = computed(() => Boolean(pool.value?.done))
const teams = computed(() => profile.value?.roster?.teams || [])
const entries = computed(() => poolDone.value ? pool.value?.entries || [] : [])
const team = computed<FormationTeam | null>(() =>
  teams.value.find(item => item.team_no === teamNo.value) || null)
const candidate = computed(() =>
  entries.value.find(item => item.observation_id === selectedId.value) || null)

const teamItems = computed(() => TEAM_LABELS.map((label, index) => {
  const no = index + 1
  const item = teams.value.find(t => t.team_no === no)
  return {
    value: no,
    label,
    caption: item?.observed_at ? `${fmtTime(item.observed_at)} 看过` : '还没看过',
  }
}))

interface SlotView {
  slot: number
  kind: 'unseen' | 'empty' | 'occupied' | 'unknown'
  text: string
  sub: string
}

function slotView(no: number): SlotView {
  const current = team.value
  if (!current || !current.slots.length) {
    return { slot: no, kind: 'unseen', text: '还没看过这支队', sub: '换人照常用，只是这里暂时没有名单可显示' }
  }
  const slot = current.slots.find(item => item.slot === no)
  if (!slot) return { slot: no, kind: 'unknown', text: '这个位置没读到', sub: '' }
  if (slot.slot_status === 'empty') return { slot: no, kind: 'empty', text: '空位', sub: '' }
  if (slot.slot_status !== 'occupied') {
    return { slot: no, kind: 'unknown', text: '没认出是谁', sub: slot.link_reason || '' }
  }
  const linked = slot.observation_id
    ? entries.value.find(item => item.observation_id === slot.observation_id)
    : null
  const name = linked ? candidateName(linked) : (slot.observed?.name || '没认出名字')
  const form = linked ? candidateFormLabel(linked)
    : slot.observed?.kiwame_status === 'kiwame' ? '极'
    : slot.observed?.kiwame_status === 'normal' ? '普通' : ''
  const level = linked?.level ?? slot.observed?.level
  const bits = [form, level != null ? `Lv.${level}` : ''].filter(Boolean).join(' · ')
  const note = slot.link_status === 'ambiguous'
    ? '档案里有同名多振，分不清是哪位'
    : slot.link_status === 'unknown' ? (slot.link_reason || '') : ''
  return { slot: no, kind: 'occupied', text: name + (bits ? `（${bits}）` : ''), sub: note }
}

const slots = computed(() => [1, 2, 3, 4, 5, 6].map(slotView))

interface CandidateGroup { name: string; rows: FormationCandidate[] }

const candidateGroups = computed<CandidateGroup[]>(() => {
  const grouped = new Map<string, FormationCandidate[]>()
  for (const entry of entries.value) {
    const key = candidateName(entry)
    const rows = grouped.get(key) || []
    rows.push(entry)
    grouped.set(key, rows)
  }
  return [...grouped]
    .map(([name, rows]) => ({ name, rows }))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})

const filteredGroups = computed(() => {
  const needle = query.value.trim()
  if (!needle) return candidateGroups.value
  return candidateGroups.value.filter(group => group.name.includes(needle))
})

// 同名多振的分组默认折起（单振组永远展开），否则 117 组全摊开会把
// 换人按钮埋到几千px 下面；搜名字时命中的组自动摊开，选中的组不收起。
const openGroups = ref(new Set<string>())
function isFolded(group: CandidateGroup) {
  if (group.rows.length <= 1) return false
  if (query.value.trim()) return false
  if (group.rows.some(row => row.observation_id === selectedId.value)) return false
  return !openGroups.value.has(group.name)
}
function toggleGroup(name: string) {
  const next = new Set(openGroups.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  openGroups.value = next
}

const eligibility = computed(() => swapEligibility({
  poolDone: poolDone.value,
  poolReason: pool.value?.reason,
  running: props.running || starting.value,
  slotNo: slotNo.value,
  candidate: candidate.value,
}))

const selectionSummary = computed(() => {
  const parts = [TEAM_LABELS[teamNo.value - 1]]
  if (slotNo.value != null) parts.push(`${slotNo.value}号位`)
  if (candidate.value) {
    const gaps = candidateEvidenceGaps(candidate.value)
    parts.push(`← ${candidateName(candidate.value)}（${candidateFormLabel(candidate.value)} · Lv.${candidate.value.level ?? '?'}${gaps.length ? '，档案缺' + gaps.join('、') : ''}）`)
  }
  return parts.join(' ')
})

const runningThis = computed(() => props.running && props.current === 'formation')
const resultText = computed(() => result.value ? formationResultText(result.value.result) : null)

const profileSummary = computed(() => {
  if (!profile.value) return ''
  if (!poolDone.value) return pool.value?.reason || '还没有可信的完整盘点'
  const skipped = pool.value?.skipped_newer_snapshots?.length || 0
  const base = `候选刀 ${pool.value?.entry_count ?? entries.value.length} 振 · 档案时间 ${pool.value?.observed_at ? fmtTime(pool.value.observed_at) : '—'} · 编队看过 ${teams.value.filter(t => t.observed_at).length}/5 队`
  return skipped ? `${base} · 之后还有 ${skipped} 次盘点没认全，以这份为准` : base
})

function fmtTime(value: number) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value * 1000))
}

function chooseCandidate(entry: FormationCandidate) {
  selectedId.value = selectedId.value === entry.observation_id ? '' : entry.observation_id
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    profile.value = await api.honmaruProfile()
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '本丸档案没有翻开'
  } finally {
    loading.value = false
  }
}

async function run() {
  if (!eligibility.value.ok || !candidate.value || slotNo.value == null) return
  starting.value = true
  result.value = null
  resultMissing.value = false
  try {
    const body = await api.run('formation', {
      team_no: teamNo.value,
      slot_no: slotNo.value,
      target: candidate.value,  // 完整档案条目原样交接，后端不认会自己拒
    })
    pendingRunId = body.run_id || ''
    pendingSince = Date.now() / 1000
    seenRunning = false
    stoppedMisses = 0
    emit('notify', '编队换人已开工，狐之助去游戏里翻名单了')
    if (pendingRunId) void pollResult()
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '没能开工，请重试')
  } finally {
    starting.value = false
  }
}

// 结果只认执行器落账的 formation.member_ensured 事件，按 run_id 认领。
// 开工后就持续轮询——任务在 App 两次状态刷新之间秒完也丢不了结果；
// 只有「见过在跑 → 已停 → 连续几次都查不到事件」才判定没拿到验收单
// （多半是被中途停止）。绝不靠 running 跳变这一下碰运气。
async function pollResult() {
  const runId = pendingRunId
  if (!runId) return
  try {
    const body = await api.formationEvents('formation.member_ensured', 20, pendingSince - 5)
    const found = pickSwapEvent(body.items || [], runId)
    if (found) {
      result.value = found.payload
      resultMissing.value = false
      pendingRunId = ''
      // 验收通过时执行器已把换后整队落账，刷新页面上的队伍名单
      void load()
      return
    }
  } catch (_) { /* 网络抖一下不算完，下一拍再来 */ }
  if (props.running) {
    seenRunning = true
    stoppedMisses = 0
  } else if (seenRunning) {
    stoppedMisses += 1
  }
  const elapsed = Date.now() / 1000 - pendingSince
  if (stoppedMisses >= 3 || elapsed > 600) {
    // 跑完了却没有回读验收——多半是被中途停止，队伍状态以游戏为准
    resultMissing.value = true
    pendingRunId = ''
    return
  }
  pollTimer = window.setTimeout(() => void pollResult(), 2000)
}

onMounted(load)
onBeforeUnmount(() => window.clearTimeout(pollTimer))
</script>

<template>
  <section class="formation-panel">
    <PaperCard variant="task" tag="section">
      <PanelHeader
        title="编队"
        :subtitle="profileSummary || '从本丸档案里点将：选部队、选位置、选要换上去的刀'"
        variant="embedded"
      >
        <template #actions>
          <button type="button" class="secondary" :disabled="loading" @click="load">{{ loading ? '正在翻档案……' : '刷新档案' }}</button>
        </template>
      </PanelHeader>
      <p v-if="!loadError && profile && !poolDone" class="formation-notice">
        档案还不可信，不能点将。去「流程工房 → 玩法设置 → 后勤配置 → 刀帐盘点」跑一次完整盘点，认清了再来。
      </p>
      <p v-else-if="!loadError && profile" class="formation-hintline">
        同名多振按档案逐振列出，狐之助换完会逐项回读对账。
      </p>
    </PaperCard>

    <p v-if="loadError" class="formation-error">{{ loadError }}</p>
    <div v-else-if="loading && !profile" class="formation-empty">正在翻本丸档案……</div>
    <template v-else-if="profile">
      <div class="formation-columns" :aria-disabled="runningThis">
        <PaperCard variant="task" tag="section" class="formation-left">
          <h3 class="formation-sub">1. 选部队</h3>
          <SegmentedControl v-model="teamNo" :items="teamItems" label="选部队" variant="wide" />
          <h3 class="formation-sub">2. 选位置</h3>
          <ol class="formation-slots">
            <li v-for="view in slots" :key="view.slot">
              <button
                type="button"
                class="formation-slot"
                :class="{ active: slotNo === view.slot, [view.kind]: true }"
                :disabled="runningThis"
                :aria-pressed="slotNo === view.slot"
                @click="slotNo = slotNo === view.slot ? null : view.slot"
              >
                <b>{{ view.slot }}号位</b>
                <span>{{ view.text }}</span>
                <small v-if="view.sub">{{ view.sub }}</small>
              </button>
            </li>
          </ol>
        </PaperCard>

        <PaperCard variant="task" tag="section" class="formation-right">
          <h3 class="formation-sub">3. 选要换上去的刀</h3>
          <label class="formation-search">
            <span>找一振刀</span>
            <input v-model="query" type="search" placeholder="输入刀名" :disabled="!poolDone">
            <em>{{ filteredGroups.length }} 种</em>
          </label>
          <div v-if="poolDone && filteredGroups.length" class="formation-candidates">
            <section v-for="group in filteredGroups" :key="group.name" class="formation-candidate-group">
              <button
                v-if="group.rows.length === 1"
                type="button"
                class="formation-candidate"
                :class="{ active: selectedId === group.rows[0].observation_id, 'lacks-evidence': candidateEvidenceGaps(group.rows[0]).length > 0 }"
                :disabled="runningThis"
                :aria-pressed="selectedId === group.rows[0].observation_id"
                @click="chooseCandidate(group.rows[0])"
              >
                <b>{{ group.name }}</b>
                <span class="formation-badges">
                  <i :class="{ kiwame: group.rows[0].form_status === 'kiwame' }" :title="(group.rows[0].form_evidence || []).join('；')">{{ candidateFormLabel(group.rows[0]) }}</i>
                  <i>Lv.{{ group.rows[0].level ?? '—' }}</i>
                  <i v-for="gap in candidateEvidenceGaps(group.rows[0])" :key="gap" class="formation-gap">缺{{ gap }}</i>
                </span>
              </button>
              <template v-else>
              <h4>
                <button
                  type="button"
                  class="formation-groupfold"
                  :aria-expanded="!isFolded(group)"
                  @click="toggleGroup(group.name)"
                >
                  <b>{{ group.name }}</b>
                  <small>同名 {{ group.rows.length }} 振，按档案逐振选</small>
                  <i>{{ isFolded(group) ? '▸' : '▾' }}</i>
                </button>
              </h4>
              <template v-if="!isFolded(group)">
              <button
                v-for="(entry, index) in group.rows"
                :key="entry.observation_id"
                type="button"
                class="formation-candidate"
                :class="{ active: selectedId === entry.observation_id, 'lacks-evidence': candidateEvidenceGaps(entry).length > 0 }"
                :disabled="runningThis"
                :aria-pressed="selectedId === entry.observation_id"
                @click="chooseCandidate(entry)"
              >
                <b>第 {{ index + 1 }} 振</b>
                <span class="formation-badges">
                  <i :class="{ kiwame: entry.form_status === 'kiwame' }" :title="(entry.form_evidence || []).join('；')">{{ candidateFormLabel(entry) }}</i>
                  <i>Lv.{{ entry.level ?? '—' }}</i>
                  <i v-for="gap in candidateEvidenceGaps(entry)" :key="gap" class="formation-gap">缺{{ gap }}</i>
                </span>
              </button>
              </template>
              </template>
            </section>
          </div>
          <p v-else-if="poolDone" class="formation-empty">没有找到这个刀名。</p>
          <p v-else class="formation-empty">档案可用之前，这里暂时没有候选。</p>
        </PaperCard>
      </div>

      <PaperCard variant="task" tag="section" class="formation-action">
        <p><strong>{{ selectionSummary }}</strong></p>
        <p v-if="!eligibility.ok" class="formation-hintline">{{ eligibility.reason }}</p>
        <div class="formation-buttons">
          <button
            v-if="!runningThis"
            type="button"
            class="primary"
            :disabled="!eligibility.ok"
            @click="run"
          >{{ starting ? '正在开工……' : '换人' }}</button>
          <button
            v-else
            type="button"
            class="danger"
            :disabled="stopping"
            @click="emit('stop')"
          >{{ stopping ? '正在停止…' : '紧急停止' }}</button>
        </div>
      </PaperCard>

      <section v-if="result && resultText" class="formation-result" :class="resultText.tone" role="status">
        <header>
          <b>{{ resultText.title }}</b>
          <span>部队{{ TEAM_LABELS[(result.team_no || 1) - 1].slice(-1) }} {{ result.slot_no }}号位 · {{ result.target?.name || '' }}</span>
        </header>
        <p>{{ resultText.detail }}</p>
        <p v-if="result.reason" class="formation-result-reason">狐之助说：{{ result.reason }}</p>
        <ul v-if="result.result === 'ambiguous' && result.candidates?.length">
          <li v-for="(item, index) in result.candidates" :key="index">
            {{ item.name || '没认出名字' }}<template v-if="item.level != null"> · Lv.{{ item.level }}</template>
            <small v-if="item.unknown_fields?.length">（缺 {{ item.unknown_fields.join('、') }}）</small>
          </li>
        </ul>
        <button type="button" class="secondary" @click="result = null">知道了</button>
      </section>
      <section v-else-if="resultMissing" class="formation-result warn" role="status">
        <header><b>没拿到回读验收</b></header>
        <p>任务结束了（多半是被中途停止），狐之助没能交回验收单。队伍现在什么样，以游戏里看到的为准。</p>
        <button type="button" class="secondary" @click="resultMissing = false">知道了</button>
      </section>

      <details class="formation-logfold" @toggle="logOpen = ($event.target as HTMLDetailsElement).open">
        <summary>看看编队换人的详细日志</summary>
        <div v-if="logOpen" class="formation-log">
          <LogPanel :running="running" :stopping="stopping" task-label="编队换人" only-script="formation" />
        </div>
      </details>
    </template>
  </section>
</template>

<style scoped>
/* 只管布局与编队特有零件；颜色、按钮、卡片全走全局样式与现有组件。 */
.formation-panel { display: grid; gap: 13px; }
.formation-notice { margin: 12px 18px 16px; padding: 10px 13px; color: #9f3d28; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); border: 1px solid #d8a195; border-radius: 8px; font-size: 12px; }
.formation-hintline { margin: 8px 18px 14px; color: var(--ink-dim); font-size: 12px; }
.formation-columns { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); gap: 13px; align-items: start; }
.formation-columns[aria-disabled='true'] { opacity: .82; }
.formation-left, .formation-right { min-width: 0; padding: 13px 15px; }
.formation-sub { margin: 2px 0 8px; color: var(--ink-dim); font-size: 12px; letter-spacing: .06em; }
.formation-sub + .formation-sub, .formation-left .formation-sub:nth-of-type(2) { margin-top: 14px; }
.formation-slots { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.formation-slot { display: grid; grid-template-columns: auto 1fr; gap: 1px 10px; width: 100%; padding: 9px 12px; text-align: left; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 9px; cursor: pointer; }
.formation-slot b { grid-row: span 2; align-self: center; font-size: 13px; }
.formation-slot span { font-size: 12px; }
.formation-slot small { color: var(--ink-dim); font-size: 10px; }
.formation-slot.empty span, .formation-slot.unseen span, .formation-slot.unknown span { color: var(--ink-dim); }
.formation-slot.active { background: var(--fox-gold-pale); border-color: var(--fox-gold); box-shadow: 3px 3px 0 color-mix(in srgb, var(--paper-line) 60%, transparent); }
.formation-slot:disabled { cursor: default; opacity: .75; }
.formation-search { display: grid; grid-template-columns: auto minmax(120px, 1fr) auto; align-items: center; gap: 9px; margin-bottom: 9px; color: var(--ink-dim); font-size: 12px; }
.formation-search input { width: 100%; min-width: 0; padding: 8px 10px; border: 1px solid var(--paper-line); border-radius: 8px; }
.formation-search em { font-style: normal; white-space: nowrap; }
/* 桌面双列：候选区定高内滚，页面不再长滚（双列布局下这是单层滚动）；
   窄屏/手机取消内滚整页滚动，避免候选/页面两层套滚。 */
.formation-candidates { display: grid; gap: 8px; }
@media (min-width: 901px) {
  .formation-candidates { max-height: 560px; overflow: auto; }
}
.formation-candidate-group { border: 1px solid var(--paper-line); border-radius: 9px; overflow: hidden; }
.formation-candidate-group h4 { display: flex; align-items: baseline; gap: 8px; margin: 0; padding: 7px 11px; background: color-mix(in srgb, var(--paper) 55%, var(--paper-card)); border-bottom: 1px solid var(--paper-line); font-size: 12px; }
.formation-candidate-group h4:has(.formation-groupfold[aria-expanded='true']) { border-bottom-color: var(--paper-line); }
.formation-candidate-group h4:has(.formation-groupfold[aria-expanded='false']) { border-bottom-color: transparent; }
.formation-groupfold { display: flex; align-items: baseline; gap: 8px; width: 100%; margin: -7px -11px; padding: 7px 11px; background: none; border: 0; font: inherit; text-align: left; cursor: pointer; }
.formation-groupfold i { margin-left: auto; font-style: normal; color: var(--ink-dim); }
.formation-candidate-group h4 small, .formation-groupfold small { color: var(--ink-dim); font-size: 10px; font-weight: 400; }
.formation-candidate { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; padding: 9px 11px; text-align: left; background: var(--paper); border: 0; border-top: 1px solid var(--paper-line); cursor: pointer; font-size: 12px; }
.formation-candidate:first-of-type { border-top: 0; }
.formation-candidate.active { background: var(--fox-gold-pale); box-shadow: inset 3px 0 0 var(--fox-gold); }
.formation-candidate:disabled { cursor: default; }
.formation-badges { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
.formation-badges i { padding: 2px 6px; font-size: 10px; font-style: normal; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 999px; }
.formation-badges i.kiwame { color: #8a5a18; border-color: color-mix(in srgb, var(--fox-gold) 65%, var(--paper-line)); }
.formation-badges .formation-gap { color: #9f3d28; border-color: #d8a195; }
.formation-action p { margin: 0 0 6px; font-size: 13px; }
.formation-action .formation-hintline { margin: 0 0 8px; color: #8a5a18; }
.formation-buttons { display: flex; gap: 8px; }
.formation-buttons button { min-height: 38px; padding: 8px 22px; }
.formation-result { display: grid; gap: 7px; padding: 14px 16px; border: 1px solid var(--paper-line); border-radius: 12px; font-size: 12px; }
.formation-result header { display: flex; align-items: baseline; gap: 10px; }
.formation-result header b { font-size: 15px; }
.formation-result header span { color: var(--ink-dim); }
.formation-result p { margin: 0; }
.formation-result.ok { color: #2f5527; background: color-mix(in srgb, #dcebd6 72%, var(--paper-card)); border-color: #b2caa8; }
.formation-result.warn { color: #7a5312; background: color-mix(in srgb, #f4e8cf 72%, var(--paper-card)); border-color: #d9bd84; }
.formation-result.bad { color: #8f3524; background: color-mix(in srgb, #f4dfd7 72%, var(--paper-card)); border-color: #d8a195; }
.formation-result-reason { opacity: .85; }
.formation-result ul { display: grid; gap: 3px; margin: 0; padding-left: 18px; }
.formation-result ul small { opacity: .75; }
.formation-result button { justify-self: start; }
.formation-error, .formation-empty { display: grid; gap: 3px; margin: 0; padding: 18px; color: var(--ink-dim); background: var(--paper-card); border: 1px dashed var(--paper-line); border-radius: 10px; font-size: 13px; }
.formation-error { color: #9f3d28; }
.formation-logfold { border: 1px dashed var(--paper-line); border-radius: 10px; background: var(--paper-card); }
.formation-logfold summary { padding: 10px 14px; color: var(--ink-dim); font-size: 12px; cursor: pointer; }
.formation-logfold[open] summary { border-bottom: 1px dashed var(--paper-line); }
.formation-log { height: 340px; min-width: 0; }
.formation-log :deep(.log-panel) { height: 100%; min-width: 0; }
.formation-log :deep(.log-row span) { overflow-wrap: anywhere; }
@media (max-width: 900px) {
  /* 窄屏重排：操作卡（与结果卡）提到候选名单上面——名单很长，
     选完刀不该再翻几千 px 才找得到换人按钮。 */
  .formation-panel { display: flex; flex-direction: column; }
  .formation-columns { display: contents; }
  .formation-left { order: 1; }
  .formation-action { order: 2; }
  .formation-result { order: 3; }
  .formation-right { order: 4; }
  .formation-logfold { order: 5; }
}
@media (max-width: 620px) {
  .formation-slot { grid-template-columns: 1fr; gap: 2px; }
  .formation-slot b { grid-row: auto; }
  .formation-candidate { align-items: flex-start; flex-direction: column; gap: 4px; }
  .formation-badges { justify-content: flex-start; }
  .formation-log { height: 300px; }
  .formation-log :deep(.head-actions) { flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
  .formation-slot, .formation-candidate { transition: none; }
}
</style>
