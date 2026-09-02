<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import type { HumanReport, ManualInventory, ManualSession } from '../types'
import { resourceNames, scriptNames, signed } from './report/reportModel'

type EntryKind = 'resource' | 'inventory' | 'session'

const props = defineProps<{
  reports: HumanReport[]
  inventories: ManualInventory[]
  sessions: ManualSession[]
}>()
const emit = defineEmits<{ changed: [] }>()

const activities = ['领邮箱', '手动领奖', '手动出阵', '锻刀', '手入', '万屋购买', '其他操作']
const sessionScripts = ['osaka', 'raid', 'edocastle', 'sortie', 'yosari', 'pumpkin']

const editor = ref<EntryKind | ''>('')
const notice = ref('')
const error = ref('')
const busy = ref(false)
const deletingKey = ref('')
const editingReport = ref<{ groupId?: string; reportId?: number } | null>(null)
const editingInventoryId = ref<number | null>(null)
const editingSessionId = ref<number | null>(null)
const resourceForm = ref({ occurred_at: '', source: '', note: '', amounts: {} as Record<string, number | null | ''> })
const inventoryForm = ref({ observed_at: '', resources: {} as Record<string, number | null | ''> })
const sessionForm = ref({ script: 'osaka', loops: 1, started_at: '', ended_at: '', note: '' })

interface ResourceGroup {
  key: string
  entries: HumanReport[]
  head: HumanReport
}

type LedgerEntry =
  | { kind: 'resource'; key: string; at: number; group: ResourceGroup }
  | { kind: 'inventory'; key: string; at: number; item: ManualInventory }
  | { kind: 'session'; key: string; at: number; item: ManualSession }

const resourceGroups = computed<ResourceGroup[]>(() => {
  const groups = new Map<string, HumanReport[]>()
  for (const report of props.reports) {
    if (report.source !== 'proactive' || !resourceNames.includes(String(report.resource || ''))
      || report.claimed_delta == null || !Number(report.claimed_delta)) continue
    const key = report.group_id || `single:${report.id}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(report)
  }
  return [...groups.entries()].map(([key, reports]) => ({
    key,
    entries: [...reports].sort((a, b) => resourceNames.indexOf(String(a.resource)) - resourceNames.indexOf(String(b.resource))),
    head: reports[0],
  }))
})

const entries = computed<LedgerEntry[]>(() => [
  ...resourceGroups.value.map(group => ({ kind: 'resource' as const, key: `resource:${group.key}`, at: Number(group.head.occurred_at), group })),
  ...props.inventories.map(item => ({ kind: 'inventory' as const, key: `inventory:${item.id}`, at: Number(item.ts), item })),
  ...props.sessions.map(item => ({ kind: 'session' as const, key: `session:${item.id}`, at: Number(item.started_at), item })),
].sort((a, b) => b.at - a.at))

function localDateTime(timestamp = Date.now()) {
  const date = new Date(timestamp - new Date(timestamp).getTimezoneOffset() * 60000)
  return date.toISOString().slice(0, 16)
}

function openEditor(kind: EntryKind) {
  error.value = ''
  notice.value = ''
  editingReport.value = null
  editingInventoryId.value = null
  editingSessionId.value = null
  editor.value = kind
  if (kind === 'resource') resourceForm.value = {
    occurred_at: localDateTime(), source: '', note: '',
    amounts: Object.fromEntries(resourceNames.map(name => [name, null])),
  }
  if (kind === 'inventory') inventoryForm.value = {
    observed_at: localDateTime(), resources: Object.fromEntries(resourceNames.map(name => [name, null])),
  }
  if (kind === 'session') {
    const ended = Date.now()
    sessionForm.value = { script: 'osaka', loops: 1, started_at: localDateTime(ended - 3600000), ended_at: localDateTime(ended), note: '' }
  }
}

function closeEditor() {
  editor.value = ''
  error.value = ''
}

function reportSource(report: HumanReport) {
  return report.activities?.find(value => !['暂不说明', '记不清了', '没有其他操作'].includes(value)) || '未标来源'
}

function entryTitle(entry: LedgerEntry) {
  if (entry.kind === 'resource') return reportSource(entry.group.head)
  if (entry.kind === 'inventory') return '家底盘点'
  return `${entry.item.activity || scriptNames[entry.item.script] || entry.item.script} · ${entry.item.loops} 圈`
}

function entryDetail(entry: LedgerEntry) {
  if (entry.kind === 'resource') {
    const amounts = entry.group.entries.map(report => `${report.resource} ${signed(Number(report.claimed_delta))}`).join(' · ')
    return `${amounts}${entry.group.head.note ? ` · ${entry.group.head.note}` : ''}`
  }
  if (entry.kind === 'inventory') return resourceNames.filter(name => entry.item.resources?.[name] != null)
    .map(name => `${name} ${Number(entry.item.resources[name]).toLocaleString()}`).join(' · ')
  const minutes = Math.max(1, Math.round(Number(entry.item.duration_seconds) / 60))
  return `用时 ${minutes} 分钟${entry.item.note ? ` · ${entry.item.note}` : ''}`
}

function entryTime(entry: LedgerEntry) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
    .format(new Date(entry.at * 1000))
}

function editEntry(entry: LedgerEntry) {
  notice.value = ''
  error.value = ''
  if (entry.kind === 'resource') {
    editor.value = 'resource'
    editingReport.value = entry.group.head.group_id ? { groupId: entry.group.head.group_id } : { reportId: entry.group.head.id }
    resourceForm.value = {
      occurred_at: localDateTime(entry.at * 1000), source: reportSource(entry.group.head) === '未标来源' ? '' : reportSource(entry.group.head),
      note: entry.group.head.note || '', amounts: Object.fromEntries(resourceNames.map(name => {
        const report = entry.group.entries.find(item => item.resource === name)
        return [name, report?.claimed_delta ?? null]
      })),
    }
  } else if (entry.kind === 'inventory') {
    editor.value = 'inventory'
    editingInventoryId.value = entry.item.id
    inventoryForm.value = { observed_at: localDateTime(entry.item.ts * 1000), resources: Object.fromEntries(resourceNames.map(name => [name, entry.item.resources?.[name] ?? null])) }
  } else {
    editor.value = 'session'
    editingSessionId.value = entry.item.id
    sessionForm.value = {
      script: entry.item.script, loops: entry.item.loops, started_at: localDateTime(entry.item.started_at * 1000),
      ended_at: localDateTime(entry.item.ended_at * 1000), note: entry.item.note || '',
    }
  }
}

async function saveResource() {
  const amounts = Object.fromEntries(resourceNames.flatMap(name => {
    const value = resourceForm.value.amounts[name]
    return value == null || value === '' || !Number(value) ? [] : [[name, Number(value)]]
  }))
  if (!Object.keys(amounts).length) { error.value = '至少填一项资源变化。'; return }
  busy.value = true
  error.value = ''
  try {
    const payload = {
      occurred_at: new Date(resourceForm.value.occurred_at).getTime() / 1000,
      activities: resourceForm.value.source ? [resourceForm.value.source] : [],
      note: resourceForm.value.note, entries: amounts,
    }
    if (editingReport.value?.groupId) await api.updateHumanReportGroup(editingReport.value.groupId, payload)
    else if (editingReport.value?.reportId) {
      const rows = Object.entries(amounts)
      if (rows.length !== 1) throw new Error('这条旧手账一次只能保留一种资源；多种资源请另记一笔。')
      await api.updateHumanReport(editingReport.value.reportId, {
        occurred_at: payload.occurred_at, activities: payload.activities, note: payload.note,
        resource: rows[0][0], claimed_delta: rows[0][1],
      })
    } else await api.addHumanReportBatch(payload)
    notice.value = `${editingReport.value ? '已修改' : '已记下'} ${Object.keys(amounts).length} 种资源的收支。`
    editor.value = ''
    emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '这笔收支没记下来' }
  finally { busy.value = false }
}

async function saveInventory() {
  const resources = Object.fromEntries(resourceNames.flatMap(name => {
    const value = inventoryForm.value.resources[name]
    return value == null || value === '' ? [] : [[name, Number(value)]]
  }))
  if (!Object.keys(resources).length) { error.value = '至少填一项当前家底。'; return }
  busy.value = true
  error.value = ''
  try {
    const observedAt = new Date(inventoryForm.value.observed_at).getTime() / 1000
    if (editingInventoryId.value) await api.updateManualInventory(editingInventoryId.value, resources, observedAt)
    else await api.addManualInventory(resources, observedAt)
    notice.value = `${editingInventoryId.value ? '已修改' : '已记录'} ${Object.keys(resources).length} 项家底。`
    editor.value = ''
    emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '家底没记下来' }
  finally { busy.value = false }
}

async function saveSession() {
  busy.value = true
  error.value = ''
  try {
    const payload = {
      script: sessionForm.value.script, loops: Number(sessionForm.value.loops), note: sessionForm.value.note,
      started_at: new Date(sessionForm.value.started_at).getTime() / 1000,
      ended_at: new Date(sessionForm.value.ended_at).getTime() / 1000,
    }
    if (payload.ended_at <= payload.started_at) throw new Error('结束时间要晚于开始时间。')
    if (editingSessionId.value) await api.updateManualSession(editingSessionId.value, payload)
    else await api.addManualSession(payload)
    notice.value = editingSessionId.value ? '这段活动已修改。' : '这段活动已经记进手账。'
    editor.value = ''
    emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '这段活动没记下来' }
  finally { busy.value = false }
}

async function deleteEntry(entry: LedgerEntry) {
  if (!window.confirm(`撤销这条${entry.kind === 'resource' ? '收支' : entry.kind === 'inventory' ? '家底' : '活动'}记录吗？`)) return
  deletingKey.value = entry.key
  error.value = ''
  try {
    if (entry.kind === 'resource') {
      if (entry.group.head.group_id) await api.deleteHumanReportGroup(entry.group.head.group_id)
      else await api.deleteHumanReport(entry.group.head.id)
    } else if (entry.kind === 'inventory') await api.deleteManualInventory(entry.item.id)
    else await api.deleteManualSession(entry.item.id)
    notice.value = '这条手账已撤销。'
    emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '撤销失败' }
  finally { deletingKey.value = '' }
}
</script>

<template>
  <section class="manual-ledger">
    <div class="manual-actions" aria-label="手动记账方式">
      <button type="button" @click="openEditor('resource')"><span>＋</span><b>记收支</b><small>获得或花掉资源</small></button>
      <button type="button" @click="openEditor('inventory')"><span>⌁</span><b>抄家底</b><small>记录现在的数字</small></button>
      <button type="button" @click="openEditor('session')"><span>◷</span><b>补活动</b><small>玩法、圈数与时间</small></button>
    </div>

    <p v-if="notice" class="manual-notice" role="status">✓ {{ notice }}</p>
    <p v-if="error" class="manual-error" role="alert">{{ error }}</p>

    <form v-if="editor === 'resource'" class="manual-editor" @submit.prevent="saveResource">
      <header><div><small>资源变化</small><h3>{{ editingReport ? '修改这笔收支' : '记一笔收支' }}</h3></div><button type="button" aria-label="关闭记账" @click="closeEditor">×</button></header>
      <div class="amount-grid">
        <label v-for="name in resourceNames" :key="name"><span>{{ name }}</span><input v-model.number="resourceForm.amounts[name]" type="number" step="1" placeholder="留空"></label>
      </div>
      <p class="form-tip">获得填正数，消耗填负数；没变化的留空。</p>
      <div class="meta-grid"><label>大概时间<input v-model="resourceForm.occurred_at" type="datetime-local" required></label><label>来源<select v-model="resourceForm.source"><option value="">不标来源</option><option v-for="item in activities" :key="item">{{ item }}</option></select></label></div>
      <label>补充说明<input v-model="resourceForm.note" maxlength="300" placeholder="可不填"></label>
      <footer><button type="submit" :disabled="busy">{{ busy ? '保存中……' : editingReport ? '保存修改' : '记下来' }}</button><button type="button" @click="closeEditor">取消</button></footer>
    </form>

    <form v-else-if="editor === 'inventory'" class="manual-editor" @submit.prevent="saveInventory">
      <header><div><small>当前家底</small><h3>{{ editingInventoryId ? '修改家底盘点' : '抄下当前家底' }}</h3></div><button type="button" aria-label="关闭家底盘点" @click="closeEditor">×</button></header>
      <div class="amount-grid">
        <label v-for="name in resourceNames" :key="name"><span>{{ name }}</span><input v-model.number="inventoryForm.resources[name]" type="number" min="0" step="1" placeholder="留空"></label>
      </div>
      <p class="form-tip">不确定的项目可以留空，下次再补。</p>
      <label>记录时间<input v-model="inventoryForm.observed_at" type="datetime-local" required></label>
      <footer><button type="submit" :disabled="busy">{{ busy ? '保存中……' : editingInventoryId ? '保存修改' : '记下家底' }}</button><button type="button" @click="closeEditor">取消</button></footer>
    </form>

    <form v-else-if="editor === 'session'" class="manual-editor" @submit.prevent="saveSession">
      <header><div><small>手动活动</small><h3>{{ editingSessionId ? '修改这段活动' : '补记一段活动' }}</h3></div><button type="button" aria-label="关闭手动活动" @click="closeEditor">×</button></header>
      <div class="meta-grid session-fields"><label>玩法<select v-model="sessionForm.script"><option v-for="script in sessionScripts" :key="script" :value="script">{{ scriptNames[script] }}</option></select></label><label>圈数<input v-model.number="sessionForm.loops" type="number" min="1" step="1" required></label><label>开始时间<input v-model="sessionForm.started_at" type="datetime-local" required></label><label>结束时间<input v-model="sessionForm.ended_at" type="datetime-local" required></label></div>
      <label>备注<input v-model="sessionForm.note" maxlength="200" placeholder="可不填"></label>
      <footer><button type="submit" :disabled="busy">{{ busy ? '保存中……' : editingSessionId ? '保存修改' : '记下活动' }}</button><button type="button" @click="closeEditor">取消</button></footer>
    </form>

    <div class="manual-list">
      <header><div><small>你自己记下的</small><h3>我的手账</h3></div><span>{{ entries.length }} 条</span></header>
      <ul v-if="entries.length">
        <li v-for="entry in entries" :key="entry.key">
          <time>{{ entryTime(entry) }}</time>
          <div><span class="entry-kind">{{ entry.kind === 'resource' ? '收支' : entry.kind === 'inventory' ? '家底' : '活动' }}</span><strong>{{ entryTitle(entry) }}</strong><small>{{ entryDetail(entry) }}</small></div>
          <footer><button type="button" @click="editEntry(entry)">修改</button><button type="button" :disabled="deletingKey === entry.key" @click="deleteEntry(entry)">{{ deletingKey === entry.key ? '处理中' : '撤销' }}</button></footer>
        </li>
      </ul>
      <div v-else class="manual-empty"><b>手账还是空的</b><span>先从上面选一种记法。</span></div>
    </div>
  </section>
</template>

<style scoped>
.manual-ledger { display: grid; gap: 18px; margin-top: 24px; }
.manual-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; }
.manual-actions button { display: grid; gap: 2px; min-width: 0; padding: 13px 10px; border: 2px solid #1d1a12; border-radius: 18px; background: #fff; color: #1d1a12; text-align: left; cursor: pointer; }
.manual-actions button:nth-child(1) { background: #ffb3d1; }
.manual-actions button:nth-child(2) { background: #a8d8ff; }
.manual-actions button:nth-child(3) { background: #b8e6a0; }
.manual-actions button > span { font-size: 22px; line-height: 1; }
.manual-actions b { font-size: 14px; }
.manual-actions small { overflow: hidden; font-size: 10.5px; opacity: .65; text-overflow: ellipsis; white-space: nowrap; }
.manual-notice, .manual-error { margin: 0; padding: 10px 13px; border-radius: 12px; font-size: 12px; font-weight: 750; }
.manual-notice { background: #e4f5d8; }
.manual-error { background: #ffe0dc; color: #842d27; }
.manual-editor, .manual-list { padding: 18px; border: 2px solid #1d1a12; border-radius: 22px; background: #fff; box-shadow: 0 6px 0 rgba(29, 26, 18, .14); }
.manual-editor { display: grid; gap: 14px; }
.manual-editor > header, .manual-list > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.manual-editor h3, .manual-editor small, .manual-list h3, .manual-list small { margin: 0; }
.manual-editor h3, .manual-list h3 { font-size: 21px; }
.manual-editor > header > button { padding: 0 6px; border: 0; background: none; color: #1d1a12; font-size: 24px; cursor: pointer; }
.manual-editor label { display: grid; gap: 5px; min-width: 0; font-size: 11px; font-weight: 750; }
.manual-editor input, .manual-editor select { width: 100%; min-width: 0; padding: 9px 10px; border: 1px solid #b9b3a6; border-radius: 10px; background: #f8f5ee; color: #1d1a12; font: inherit; }
.amount-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }
.meta-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.form-tip { margin: -6px 0 0; font-size: 11px; opacity: .65; }
.manual-editor > footer { display: flex; gap: 8px; }
.manual-editor > footer button { padding: 9px 16px; border: 0; border-radius: 999px; background: #1d1a12; color: #fff7d1; font-weight: 800; cursor: pointer; }
.manual-editor > footer button + button { background: #ebe7df; color: #1d1a12; }
.manual-editor button:disabled { cursor: wait; opacity: .55; }
.manual-list > header > span { font-size: 11px; font-weight: 800; opacity: .55; }
.manual-list ul { display: grid; gap: 8px; margin: 14px 0 0; padding: 0; list-style: none; }
.manual-list li { display: grid; grid-template-columns: 66px minmax(0, 1fr) auto; gap: 10px; align-items: start; padding: 12px; border-radius: 14px; background: #f3f0e8; }
.manual-list time { font-size: 10px; opacity: .6; }
.manual-list li > div { display: grid; gap: 3px; min-width: 0; }
.manual-list li strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.manual-list li small { overflow: hidden; font-size: 10.5px; opacity: .65; text-overflow: ellipsis; white-space: nowrap; }
.entry-kind { width: fit-content; padding: 2px 6px; border-radius: 999px; background: #1d1a12; color: #fff7d1; font-size: 9px; font-weight: 800; }
.manual-list li > footer { display: flex; gap: 4px; }
.manual-list li > footer button { padding: 4px 7px; border: 0; border-radius: 8px; background: #fff; color: #1d1a12; font-size: 10px; font-weight: 750; cursor: pointer; }
.manual-list li > footer button:last-child { color: #9d2d27; }
.manual-empty { display: grid; gap: 4px; margin-top: 14px; padding: 24px; border: 1px dashed #8a8375; border-radius: 16px; text-align: center; }
.manual-empty span { font-size: 12px; opacity: .65; }

@media (max-width: 560px) {
  .manual-actions small { display: none; }
  .amount-grid, .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .manual-list li { grid-template-columns: minmax(0, 1fr) auto; }
  .manual-list time { grid-column: 1 / -1; }
  .manual-list li small { white-space: normal; }
}
</style>
