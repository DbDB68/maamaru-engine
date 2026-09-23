<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'
import PaperCard from './PaperCard.vue'
import type { CustomFormation, CustomFormationSlotEntry, FormationCandidate, HonmaruFormationProfile } from '../types'
import {
  candidateEvidenceGaps,
  candidateFormLabel,
  candidateName,
  presetCandidatePickable,
  presetLabel,
  presetSlotCount,
  presetSlotSummary,
  validatePresetDraft,
} from '../formation'

// 这里只管理「想套用什么队」的预设，不复刻游戏当前五队，也不把历史
// 点名冒充实时编队。真正套用预设由出阵/远征/任务流在开工前统一调用。

withDefaults(defineProps<{
  running?: boolean
  current?: string | null
  stopping?: boolean
}>(), { running: false, current: null, stopping: false })
const emit = defineEmits<{ stop: []; notify: [message: string] }>()

const TEAM_LABELS = ['部队一', '部队二', '部队三', '部队四', '部队五']
const MAX_PRESETS = 5 // 后端合同：预设编队最多存 5 套

const profile = ref<HonmaruFormationProfile | null>(null)
const catalog = ref<Array<{ id: string; name: string; name_zh: string; type: string }>>([])
const loading = ref(true)
const loadError = ref('')

const pool = computed(() => profile.value?.candidate_pool || null)
const poolDone = computed(() => Boolean(pool.value?.done))
const entries = computed(() => poolDone.value ? pool.value?.entries || [] : [])

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
const catalogMatches = computed(() => catalog.value.filter(sword =>
  (sword.name_zh || sword.name).includes(presetQuery.value.trim())))

const profileSummary = computed(() => {
  if (!profile.value) return ''
  if (!poolDone.value) return '没有完整刀账也能编队；具体一振仍需刀账'
  const skipped = pool.value?.skipped_newer_snapshots?.length || 0
  const base = `刀账候选 ${pool.value?.entry_count ?? entries.value.length} 振 · 档案时间 ${pool.value?.observed_at ? fmtTime(pool.value.observed_at) : '—'}`
  return skipped ? `${base} · 之后还有 ${skipped} 次盘点没认全，以这份为准` : base
})

function fmtTime(value: number) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value * 1000))
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [profileResult, catalogResult] = await Promise.allSettled([
      api.honmaruProfile(), api.swords(),
    ])
    if (profileResult.status === 'fulfilled') profile.value = profileResult.value
    else loadError.value = '刀账暂时没有翻开；仍可按上锁刀和等级设置预设。'
    if (catalogResult.status === 'fulfilled') catalog.value = catalogResult.value.swords
    else loadError.value = '刀剑名册暂时没有翻开，请稍后重新读取。'
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '本丸档案没有翻开'
  } finally {
    loading.value = false
  }
}

// 预设编队管理：增删改只动记录、不碰游戏；真正应用时由玩法入口把关。
const presets = ref<CustomFormation[]>([])
const presetsLoading = ref(false)
const presetsError = ref('')
const editorOpen = ref(false)
const editingId = ref('') // '' = 新建
const draftName = ref('')
const draftTeam = ref(1)
const draftSlots = ref<Record<string, CustomFormationSlotEntry>>({})
const pickerSlot = ref<number | null>(null) // 正在选刀的格子
const pickerMode = ref<'ranked' | 'exact'>('ranked')
const presetQuery = ref('')
const presetSaving = ref(false)
const presetMessage = ref('')
const presetFailed = ref(false)

const draftSlotCount = computed(() => presetSlotCount({ slots: draftSlots.value }))
const draftError = computed(() => validatePresetDraft({
  name: draftName.value,
  target_team: draftTeam.value,
  slots: draftSlots.value,
}))

// 预设选刀池直接复用本丸档案的候选分组（同名多振逐振列出，同一口径）。
const presetFilteredGroups = computed(() => {
  const needle = presetQuery.value.trim()
  if (!needle) return candidateGroups.value
  return candidateGroups.value.filter(group => group.name.includes(needle))
})

function cloneSlots(slots: Record<string, CustomFormationSlotEntry>): Record<string, CustomFormationSlotEntry> {
  return JSON.parse(JSON.stringify(slots || {})) as Record<string, CustomFormationSlotEntry>
}

async function loadPresets() {
  presetsLoading.value = true
  presetsError.value = ''
  try {
    const body = await api.customFormations()
    presets.value = body.formations || []
  } catch (cause) {
    presetsError.value = cause instanceof Error ? cause.message : '预设名单没有翻开'
  } finally {
    presetsLoading.value = false
  }
}

function openPresetEditor(preset?: CustomFormation) {
  if (preset) {
    editingId.value = preset.id
    draftName.value = preset.name
    draftTeam.value = preset.target_team
    draftSlots.value = cloneSlots(preset.slots)
  } else {
    editingId.value = ''
    draftName.value = ''
    draftTeam.value = 1
    draftSlots.value = {}
  }
  pickerSlot.value = null
  presetQuery.value = ''
  presetMessage.value = ''
  presetFailed.value = false
  editorOpen.value = true
}

function closePresetEditor() {
  if (presetSaving.value) return
  editorOpen.value = false
  pickerSlot.value = null
}

function togglePresetPicker(no: number) {
  pickerSlot.value = pickerSlot.value === no ? null : no
  presetQuery.value = ''
}

function assignRankedSword(sword: { id: string; name: string; name_zh: string }, form: 'normal' | 'kiwame') {
  if (pickerSlot.value == null) return
  const next = cloneSlots(draftSlots.value)
  next[String(pickerSlot.value)] = {
    selection_policy: 'locked_highest_level', sword_catalog_id: sword.id,
    name_zh: sword.name_zh || sword.name, form_status: form,
  }
  draftSlots.value = next
  const rest = [1, 2, 3, 4, 5, 6].find(no => no !== pickerSlot.value && !next[String(no)])
  pickerSlot.value = rest ?? null
}

function assignPresetCandidate(entry: FormationCandidate) {
  if (pickerSlot.value == null || !presetCandidatePickable(entry)) return
  const next = cloneSlots(draftSlots.value)
  next[String(pickerSlot.value)] = {
    ...(entry.observation_id ? { observation_id: entry.observation_id } : {}),
    ...(entry.sword_catalog_id ? { sword_catalog_id: entry.sword_catalog_id } : {}),
    ...(entry.same_team_exclusion_key ? { same_team_exclusion_key: entry.same_team_exclusion_key } : {}),
    ...(entry.name_zh ? { name_zh: entry.name_zh } : {}),
    ...(entry.level != null ? { level: entry.level } : {}),
    ...(entry.tou_level != null ? { tou_level: entry.tou_level } : {}),
    ...(entry.survival_max != null ? { survival_max: entry.survival_max } : {}),
    ...(entry.stats ? { stats: { ...entry.stats } } : {}),
    ...(entry.form_status ? { form_status: entry.form_status } : {}),
    ...(entry.kiwame_date ? { kiwame_date: entry.kiwame_date } : {}),
    ...(entry.source_snapshot_id != null ? { source_snapshot_id: entry.source_snapshot_id } : {}),
    ...(entry.observed_at != null ? { observed_at: entry.observed_at } : {}),
  }
  draftSlots.value = next
  presetMessage.value = ''
  // 选完自动滑到下一个空位，一口气能把六个格子点完
  const rest = [1, 2, 3, 4, 5, 6].find(no => no !== pickerSlot.value && !next[String(no)])
  pickerSlot.value = rest ?? null
}

function clearPresetSlot(no: number) {
  const next = cloneSlots(draftSlots.value)
  delete next[String(no)]
  draftSlots.value = next
}

async function savePreset() {
  if (presetSaving.value) return
  const problem = validatePresetDraft({
    name: draftName.value,
    target_team: draftTeam.value,
    slots: draftSlots.value,
  })
  if (problem) {
    presetMessage.value = problem
    presetFailed.value = true
    return
  }
  presetSaving.value = true
  presetMessage.value = ''
  try {
    const body = await api.saveCustomFormation(
      { name: draftName.value.trim(), target_team: draftTeam.value, slots: draftSlots.value },
      editingId.value || undefined,
    )
    if (!body.ok) throw new Error('没有保存成功，请重试')
    emit('notify', `预设「${body.formation.name}」已收好`)
    editorOpen.value = false
    pickerSlot.value = null
    await loadPresets()
  } catch (cause) {
    presetMessage.value = cause instanceof Error ? cause.message : '保存失败，请重试'
    presetFailed.value = true
  } finally {
    presetSaving.value = false
  }
}

async function removePreset(preset: CustomFormation) {
  if (presetSaving.value) return
  if (!window.confirm(`删除「${preset.name}」？这套预设将从名单里移除，无法恢复。`)) return
  try {
    const body = await api.deleteCustomFormation(preset.id)
    if (!body.ok) throw new Error('没有删除成功，请重试')
    presets.value = presets.value.filter(item => item.id !== preset.id)
    if (editingId.value === preset.id) closePresetEditor()
    emit('notify', `已删除预设「${preset.name}」`)
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '删除失败，请重试')
  }
}

onMounted(() => { load(); loadPresets() })
</script>

<template>
  <section class="formation-panel">
    <PaperCard variant="task" tag="section" class="formation-workspace">
      <PanelHeader
        title="部队预设"
        :subtitle="profileSummary || '选好要用的刀，出阵或远征时再整队套用'"
        variant="embedded"
      >
        <template #actions>
          <button type="button" class="secondary" :disabled="loading" @click="load">{{ loading ? '正在读取……' : '重新读取' }}</button>
        </template>
      </PanelHeader>
      <p class="formation-hintline">保存预设不会立刻动游戏；开工时会在名单里找上锁且等级最高的刀。</p>

      <p v-if="loadError" class="formation-error">{{ loadError }}</p>
      <div v-if="loading && !catalog.length" class="formation-empty">正在读取刀剑名册……</div>
      <template v-else>
        <section class="formation-presets">
          <header class="formation-presets-head">
            <div>
              <h3>我的部队预设</h3>
              <p>常用阵容收在这里，之后从出阵、活动或远征里直接选。编辑预设只改记录，不碰游戏。</p>
            </div>
            <button
              type="button"
              class="secondary"
              :disabled="presetsLoading || presets.length >= MAX_PRESETS"
              :title="presets.length >= MAX_PRESETS ? '最多存 5 套预设，先删掉一套不用的' : ''"
              @click="openPresetEditor()"
            >{{ presets.length >= MAX_PRESETS ? '最多 5 套' : '＋ 新建预设' }}</button>
          </header>

          <p v-if="presetsError" class="formation-error" role="alert">{{ presetsError }}</p>
          <p v-else-if="presetsLoading && !presets.length" class="formation-empty">正在翻预设名单……</p>
          <template v-else>
            <p v-if="!presets.length" class="formation-empty">还没有预设编队。把常用的阵容存下来，下次整套换上，不用一格一格点。</p>
            <ul v-else class="formation-preset-list">
              <li v-for="preset in presets" :key="preset.id" class="formation-preset-card">
                <div class="formation-preset-info">
                  <b>{{ presetLabel(preset) }}</b>
                  <span class="formation-badges">
                    <i>已指定 {{ presetSlotCount(preset) }}/6 槽</i>
                    <i v-if="!presetSlotCount(preset)" class="formation-gap">全是空位，应用时会直接停下</i>
                  </span>
                </div>
                <div class="formation-preset-tools">
                  <button type="button" class="secondary" :disabled="presetSaving" @click="openPresetEditor(preset)">编辑</button>
                  <button type="button" class="danger" :disabled="presetSaving" @click="removePreset(preset)">删除</button>
                </div>
              </li>
            </ul>
            <p v-if="presets.length >= MAX_PRESETS" class="formation-hintline">最多存 5 套预设；想存新的，先删掉一套不用的。</p>
          </template>

          <div v-if="editorOpen" class="formation-preset-editor">
            <h4>{{ editingId ? '编辑预设' : '新建预设' }}</h4>
            <div class="formation-preset-form">
              <label class="formation-preset-field">
                <span>预设名字</span>
                <input v-model="draftName" type="text" maxlength="20" placeholder="比如：演练主力队">
              </label>
              <label class="formation-preset-field">
                <span>覆盖部队</span>
                <select v-model.number="draftTeam">
                  <option v-for="(label, index) in TEAM_LABELS" :key="label" :value="index + 1">{{ label }}</option>
                </select>
              </label>
            </div>
            <p class="formation-hintline">按刀名选上锁最高级，或从刀账指定具体一振；留空的格子应用时保持原样。</p>
            <p v-if="draftSlotCount === 0" class="formation-preset-warn">一个位置都没指定也行，存是能存，但应用时没有可做的事，会直接停下。</p>
            <ol class="formation-preset-slots">
              <li v-for="no in [1, 2, 3, 4, 5, 6]" :key="no">
                <button
                  type="button"
                  class="formation-preset-slot"
                  :class="{ active: pickerSlot === no, filled: Boolean(draftSlots[String(no)]) }"
                  :aria-pressed="pickerSlot === no"
                  @click="togglePresetPicker(no)"
                >
                  <b>{{ no }}号位</b>
                  <span>{{ presetSlotSummary(draftSlots[String(no)]) }}</span>
                </button>
                <button
                  v-if="draftSlots[String(no)]"
                  type="button"
                  class="formation-preset-clear"
                  :aria-label="`清除 ${no} 号位，恢复成不动`"
                  title="清除，恢复成不动"
                  @click="clearPresetSlot(no)"
                >×</button>
              </li>
            </ol>

            <div v-if="pickerSlot != null" class="formation-preset-picker">
              <div class="formation-picker-modes" role="group" aria-label="选刀方式">
                <button type="button" class="secondary" :aria-pressed="pickerMode === 'ranked'" @click="pickerMode = 'ranked'">按上锁最高级</button>
                <button type="button" class="secondary" :aria-pressed="pickerMode === 'exact'" @click="pickerMode = 'exact'">指定刀账里的一振</button>
              </div>
              <label class="formation-search">
                <span>给 {{ pickerSlot }} 号位选刀</span>
                <input v-model="presetQuery" type="search" placeholder="输入刀名">
                <em>{{ pickerMode === 'ranked' ? catalogMatches.length : presetFilteredGroups.length }} 种</em>
              </label>
              <p v-if="pickerMode === 'ranked'" class="formation-hintline">选普通或极。开工时只考虑黄色上锁的刀；最高级并列或认不清时会停下。</p>
              <div v-if="pickerMode === 'ranked' && catalogMatches.length" class="formation-preset-candidates">
                <section v-for="sword in catalogMatches" :key="sword.id" class="formation-candidate-group formation-ranked-choice">
                  <b>{{ sword.name_zh || sword.name }}</b>
                  <button type="button" class="formation-candidate" @click="assignRankedSword(sword, 'normal')">普通 · 上锁最高级</button>
                  <button type="button" class="formation-candidate" @click="assignRankedSword(sword, 'kiwame')">极 · 上锁最高级</button>
                </section>
              </div>
              <p v-else-if="pickerMode === 'ranked'" class="formation-empty">没有找到这个刀名。</p>
              <p v-else-if="!poolDone" class="formation-empty">指定具体一振需要完整刀账；可以切回「按上锁最高级」。</p>
              <div v-else-if="presetFilteredGroups.length" class="formation-preset-candidates">
                <section v-for="group in presetFilteredGroups" :key="group.name" class="formation-candidate-group">
                  <h4 v-if="group.rows.length > 1"><b>{{ group.name }}</b><small>同名 {{ group.rows.length }} 振，按档案逐振选</small></h4>
                  <button
                    v-for="(entry, index) in group.rows"
                    :key="entry.observation_id"
                    type="button"
                    class="formation-candidate"
                    :class="{ 'lacks-evidence': !presetCandidatePickable(entry) }"
                    :disabled="!presetCandidatePickable(entry)"
                    :title="!presetCandidatePickable(entry) ? '档案里没认出这振的名字，先重新跑一次「刀帐盘点」再来' : ''"
                    @click="assignPresetCandidate(entry)"
                  >
                    <b>{{ group.rows.length > 1 ? `第 ${index + 1} 振` : group.name }}</b>
                    <span class="formation-badges">
                      <i :class="{ kiwame: entry.form_status === 'kiwame' }" :title="(entry.form_evidence || []).join('；')">{{ candidateFormLabel(entry) }}</i>
                      <i>Lv.{{ entry.level ?? '—' }}</i>
                      <i v-for="gap in candidateEvidenceGaps(entry)" :key="gap" class="formation-gap">缺{{ gap }}</i>
                    </span>
                  </button>
                </section>
              </div>
              <p v-else class="formation-empty">没有找到这个刀名。</p>
            </div>

            <p v-if="presetMessage" class="formation-preset-message" :class="{ failed: presetFailed }" :role="presetFailed ? 'alert' : 'status'">{{ presetMessage }}</p>
            <div class="formation-preset-actions">
              <button type="button" class="primary" :disabled="presetSaving || Boolean(draftError)" @click="savePreset">{{ presetSaving ? '正在收好……' : '保存预设' }}</button>
              <button type="button" class="secondary" :disabled="presetSaving" @click="closePresetEditor">取消</button>
            </div>
            <p v-if="draftError" class="formation-hintline">{{ draftError }}</p>
          </div>
        </section>
      </template>
    </PaperCard>
  </section>
</template>

<style scoped>
/* 只管布局与编队特有零件；颜色、按钮、卡片全走全局样式与现有组件。 */
.formation-panel { min-width: 0; }
.formation-workspace { overflow: hidden; }
.formation-notice { margin: 12px 18px 16px; padding: 10px 13px; color: #9f3d28; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); border: 1px solid #d8a195; border-radius: 8px; font-size: 12px; }
.formation-hintline { margin: 8px 18px 14px; color: var(--ink-dim); font-size: 12px; }
.formation-search { display: grid; grid-template-columns: auto minmax(120px, 1fr) auto; align-items: center; gap: 9px; margin-bottom: 9px; color: var(--ink-dim); font-size: 12px; }
.formation-search input { width: 100%; min-width: 0; padding: 8px 10px; border: 1px solid var(--paper-line); border-radius: 8px; }
.formation-search em { font-style: normal; white-space: nowrap; }
.formation-candidate-group { border: 1px solid var(--paper-line); border-radius: 9px; overflow: hidden; }
.formation-candidate-group h4 { display: flex; align-items: baseline; gap: 8px; margin: 0; padding: 7px 11px; background: color-mix(in srgb, var(--paper) 55%, var(--paper-card)); border-bottom: 1px solid var(--paper-line); font-size: 12px; }
.formation-candidate-group h4 small { color: var(--ink-dim); font-size: 10px; font-weight: 400; }
.formation-candidate { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; padding: 9px 11px; text-align: left; background: var(--paper); border: 0; border-top: 1px solid var(--paper-line); cursor: pointer; font-size: 12px; }
.formation-candidate:first-of-type { border-top: 0; }
.formation-candidate.active { background: var(--fox-gold-pale); box-shadow: inset 3px 0 0 var(--fox-gold); }
.formation-candidate:disabled { cursor: default; }
.formation-badges { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
.formation-badges i { padding: 2px 6px; font-size: 10px; font-style: normal; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 999px; }
.formation-badges i.kiwame { color: #8a5a18; border-color: color-mix(in srgb, var(--fox-gold) 65%, var(--paper-line)); }
.formation-badges .formation-gap { color: #9f3d28; border-color: #d8a195; }
.formation-error, .formation-empty { display: grid; gap: 3px; margin: 16px 18px; padding: 18px; color: var(--ink-dim); background: var(--paper-card); border: 1px dashed var(--paper-line); border-radius: 10px; font-size: 13px; }
.formation-error { color: #9f3d28; }
/* 预设编队管理区：列表 + 就地展开的编辑器，视觉零件与选人区同源。 */
.formation-presets { padding: 18px; }
.formation-presets-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.formation-presets-head h3 { margin: 0; font-size: 14px; }
.formation-presets-head p { max-width: 560px; margin: 4px 0 0; color: var(--ink-dim); font-size: 12px; line-height: 1.6; }
.formation-presets-head button { min-height: 32px; padding: 5px 14px; font-size: 12px; }
.formation-preset-list { display: grid; gap: 8px; margin: 12px 0 0; padding: 0; list-style: none; }
.formation-preset-card { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 9px; }
.formation-preset-info { display: grid; gap: 5px; min-width: 0; }
.formation-preset-info b { font-size: 13px; overflow-wrap: anywhere; }
.formation-preset-info .formation-badges { justify-content: flex-start; }
.formation-preset-tools { display: flex; flex: 0 0 auto; gap: 6px; }
.formation-preset-tools button { min-height: 30px; padding: 5px 13px; font-size: 12px; }
.formation-preset-editor { margin-top: 14px; padding: 13px; background: color-mix(in srgb, var(--paper-card) 62%, var(--paper)); border: 1px dashed var(--paper-line); border-radius: 10px; }
.formation-preset-editor h4 { margin: 0 0 10px; font-size: 13px; }
.formation-preset-editor .formation-hintline { margin: 8px 0 0; }
.formation-presets > .formation-hintline { margin: 10px 0 0; }
.formation-preset-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.formation-preset-field { display: grid; gap: 5px; color: var(--ink-dim); font-size: 12px; }
.formation-preset-field input, .formation-preset-field select { width: 100%; min-width: 0; padding: 8px 10px; color: var(--ink); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 8px; }
.formation-preset-warn { margin: 10px 0 0; padding: 8px 11px; color: #7a5312; background: color-mix(in srgb, #f4e8cf 72%, var(--paper-card)); border: 1px solid #d9bd84; border-radius: 8px; font-size: 12px; }
.formation-preset-slots { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 12px 0 0; padding: 0; list-style: none; }
.formation-preset-slots li { position: relative; min-width: 0; }
.formation-preset-slot { display: grid; gap: 3px; width: 100%; min-height: 54px; padding: 9px 28px 9px 11px; text-align: left; background: var(--paper); border: 1px solid var(--paper-line); border-radius: 9px; cursor: pointer; }
.formation-preset-slot b { font-size: 11px; color: var(--ink-dim); }
.formation-preset-slot span { font-size: 12px; overflow-wrap: anywhere; }
.formation-preset-slot.filled { background: color-mix(in srgb, var(--fox-gold-pale) 45%, var(--paper)); }
.formation-preset-slot.active { border-color: var(--fox-gold); box-shadow: 3px 3px 0 color-mix(in srgb, var(--paper-line) 60%, transparent); }
.formation-preset-clear { position: absolute; top: 6px; right: 6px; display: grid; place-items: center; width: 20px; height: 20px; padding: 0; color: var(--ink-dim); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 50%; font-size: 12px; line-height: 1; cursor: pointer; }
.formation-preset-clear:hover { color: #8f3524; border-color: #d8a195; }
.formation-preset-picker { margin-top: 10px; }
.formation-picker-modes { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.formation-picker-modes button { min-height: 30px; padding: 5px 10px; font-size: 12px; }
.formation-picker-modes button[aria-pressed="true"] { border-color: var(--fox-gold); background: var(--fox-gold-pale); }
.formation-preset-candidates { display: grid; gap: 8px; max-height: 300px; margin-top: 8px; overflow: auto; }
.formation-ranked-choice { display: grid; grid-template-columns: minmax(0, 1fr) repeat(2, minmax(0, auto)); align-items: center; }
.formation-ranked-choice > b { min-width: 0; padding: 8px 10px; font-size: 12px; overflow-wrap: anywhere; }
.formation-ranked-choice .formation-candidate { width: auto; height: 100%; border-top: 0; border-left: 1px solid var(--paper-line); white-space: nowrap; }
.formation-preset-message { margin: 10px 0 0; font-size: 12px; color: #2f5527; }
.formation-preset-message.failed { color: #8f3524; }
.formation-preset-actions { display: flex; gap: 8px; margin-top: 12px; }
.formation-preset-actions button { min-height: 34px; padding: 6px 18px; font-size: 12px; }
@media (max-width: 900px) {
  .formation-workspace { display: flex; flex-direction: column; overflow: visible; }
}
@media (max-width: 620px) {
  .formation-presets { padding: 14px; }
  .formation-candidate { align-items: flex-start; flex-direction: column; gap: 4px; }
  .formation-badges { justify-content: flex-start; }
  .formation-preset-card { align-items: flex-start; flex-direction: column; }
  .formation-preset-tools { width: 100%; }
  .formation-preset-tools button { flex: 1; }
  .formation-preset-slots { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .formation-ranked-choice { grid-template-columns: 1fr 1fr; }
  .formation-ranked-choice > b { grid-column: 1 / -1; }
  .formation-ranked-choice .formation-candidate { width: 100%; border-top: 1px solid var(--paper-line); }
}
@media (prefers-reduced-motion: reduce) {
  .formation-candidate, .formation-preset-slot { transition: none; }
}
</style>
