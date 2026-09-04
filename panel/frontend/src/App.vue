<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { api } from './api'
import TaskForm from './components/TaskForm.vue'
import DashboardPanel from './components/DashboardPanel.vue'
import ReportPanel from './components/ReportPanel.vue'
import LogPanel from './components/LogPanel.vue'
import ChatPanel from './components/ChatPanel.vue'
import ListsPanel from './components/ListsPanel.vue'
import SchedulePanel from './components/SchedulePanel.vue'
import WorkflowPanel from './components/WorkflowPanel.vue'
import SystemPanel from './components/SystemPanel.vue'
import OverviewTaskCard from './components/OverviewTaskCard.vue'
import AdvancedSettingLink from './components/AdvancedSettingLink.vue'
import SwordListDrawer from './components/SwordListDrawer.vue'
import MaamaruFrame from './components/MaamaruFrame.vue'
import SideNavItem from './components/SideNavItem.vue'
import NotificationCenter from './components/NotificationCenter.vue'
import StageActors from './components/StageActors.vue'
import ImmediateExpeditionFields from './components/ImmediateExpeditionFields.vue'
import HonmaruHome from './components/HonmaruHome.vue'
import type { HomeLayoutEntry, ScriptInfo, ScriptParams, WorkflowPreset, WorkflowIdentity } from './types'

const scripts = ref<Record<string, ScriptInfo>>({})
const params = ref<Record<string, ScriptParams>>({})
const selected = ref('daily')
const running = ref(false)
const current = ref<string | null>(null)
const workflowDraft = ref<WorkflowPreset | null>(null)
const workflowPanel = ref<{ dirty: boolean; locked: boolean } | null>(null)
const dailyEntry = ref(0)
function openDailyWorkflow() { dailyEntry.value++; tab.value = 'workflow' }
const runningWorkflow = ref<WorkflowIdentity | null>(null)
const startingWorkflow = ref(false)
let statusRevision = 0
const workflowRunningLabel = computed(() => runningWorkflow.value ? `「${runningWorkflow.value.name}」正在执行` : '工作流正在执行')
function viewRunningWorkflow() {
  if (runningWorkflow.value) openWorkflowPreset(runningWorkflow.value.id)
  else tab.value = 'workflow'
}
function workflowStarted(identity: WorkflowIdentity) {
  statusRevision++
  running.value = true
  current.value = 'workflow'
  runningWorkflow.value = identity
}
function workflowSaved(preset: WorkflowPreset) {
  const index = homeWorkflows.value.findIndex(item => item.id === preset.id)
  if (index < 0) homeWorkflows.value.push(preset)
  else homeWorkflows.value[index] = preset
  homeLayoutEntries.value = homeLayoutEntries.value.map(entry => entry.key === `wf:${preset.id}` ? { ...entry, label: preset.name } : entry)
}
const loading = ref(true)
const message = ref('')
const tab = ref<'home' | 'office' | 'tasks' | 'workflow' | 'report' | 'chat' | 'system'>('home')
const ledgerMode = ref(false)
const reportEntry = ref<'report' | 'planning'>('report')
const launcherAvailable = ref(false)
const returningToLauncher = ref(false)
const theme = ref<'washi' | 'pixel'>('washi')
const schedulerWarning = ref('')
const advancedDrawer = ref<'pumpkin' | 'daily-pumpkin' | null>(null)
let pollTimer = 0
let toastTimer = 0
const stopping = ref(false)
const contentEl = ref<HTMLElement | null>(null)
const reportStageCollapsed = ref(false)
const workflowStageCollapsed = ref(false)
const homeFunctionsNav = ref<HTMLElement | null>(null)
const dashboardRun = ref<any>(null)
const immediateExpedition = ref<{ save: () => Promise<void> } | null>(null)
const clock = ref(Date.now())
const logRunning = computed(() => running.value || !!dashboardRun.value?.active)
const logTaskLabel = computed(() => running.value
  ? (current.value === 'workflow' ? runningWorkflow.value?.name || '工作流' : scripts.value[current.value || '']?.label || '任务')
  : dashboardRun.value?.active ? dashboardRun.value.label || '任务' : '')

const taskIcons: Record<string, string> = {
  // 活动任务也必须使用自己的素材，不能临时借用通用出阵图标后一直漏接。
  daily: 'daily.png', raid: 'raid.png', pumpkin: 'pumpkin.png', edocastle: 'edocastle.png', sortie: 'sortie.png', yosari: 'yosari.png', osaka: 'digging.png',
  sakura: 'sakura.png', practice: 'practice.png', expedition: 'expedition.png', smith: 'forge.png',
  sugar: 'sugar.png', snapshot: 'snapshot.png', repair: 'repair-tools.png', workflow: 'workflow.svg',
}

const selectedInfo = computed(() => scripts.value[selected.value])
// 常用功能默认清单：后端布局接口不可用时兜底用，顺序与旧版硬编码一致。
const fallbackHomeOrder = ['daily', 'sortie', 'yosari', 'osaka', 'edocastle', 'expedition', 'smith', 'pumpkin', 'raid', 'sugar', 'sakura', 'practice', 'snapshot']
const homeLayoutEntries = ref<HomeLayoutEntry[]>([])
const homeLayoutLoaded = ref(false)
const homeHiddenList = ref<string[]>([])
const homeWorkflows = ref<WorkflowPreset[]>([])
// 活动没开放的脚本从常用功能收起来（后端 /api/scripts 下发，配置页不受影响）
const eventHidden = ref<string[]>([])
const homeEntries = computed<HomeLayoutEntry[]>(() => (homeLayoutLoaded.value ? homeLayoutEntries.value : fallbackHomeOrder
  .filter(key => scripts.value[key])
  .map(key => ({ kind: 'script' as const, key, label: scripts.value[key].label })))
  .filter(entry => entry.kind !== 'script' || (scripts.value[entry.key] && !eventHidden.value.includes(entry.key))))
const eventHiddenLabels = computed(() => eventHidden.value
  .filter(key => scripts.value[key])
  .map(key => scripts.value[key].label))
const homeScriptIndex = computed(() => homeEntries.value.findIndex(entry => entry.key === selected.value))
async function chooseAdjacentHome(direction: -1 | 1) {
  const next = homeScriptIndex.value + direction
  if (next < 0 || next >= homeEntries.value.length) return
  selected.value = homeEntries.value[next].key
  await nextTick()
  homeFunctionsNav.value?.querySelector<HTMLElement>(`[data-script="${selected.value}"]`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
}
// ---- 常用功能自定义（编辑模式：排序、收起、把工作流钉进来）----
const editingHome = ref(false)
const editOrder = ref<string[]>([])
const editHidden = ref<string[]>([])
const savingHomeLayout = ref(false)
const hiddenHomeEntries = computed<HomeLayoutEntry[]>(() => editHidden.value.map(key => {
  if (key.startsWith('wf:')) {
    const preset = homeWorkflows.value.find(item => `wf:${item.id}` === key)
    return preset ? { kind: 'workflow' as const, key, label: preset.name } : null
  }
  const info = scripts.value[key]
  return info ? { kind: 'script' as const, key, label: info.label } : null
}).filter((entry): entry is HomeLayoutEntry => entry !== null))
// 默认日课已经由 daily 入口管理；收起后也只从「收起来的功能」加回。
const pinnableWorkflows = computed(() => homeWorkflows.value.filter(preset => preset.id !== 'builtin-daily' && !editOrder.value.includes(`wf:${preset.id}`)))
const selectedWorkflow = computed(() => selected.value.startsWith('wf:')
  ? homeWorkflows.value.find(preset => `wf:${preset.id}` === selected.value) || null
  : null)
async function startHomeEdit() {
  editingHome.value = true
  editOrder.value = (homeLayoutLoaded.value ? homeLayoutEntries.value : homeEntries.value).map(entry => entry.key)
  editHidden.value = [...homeHiddenList.value]
  try {
    homeWorkflows.value = (await api.workflows()).presets || []
  } catch (error) {
    message.value = error instanceof Error ? `工作流列表没加载出来：${error.message}` : '工作流列表没加载出来，只能调整现有功能'
  }
}
function finishHomeEdit() { editingHome.value = false }
async function applyHomeEdit(mutate: () => void) {
  if (savingHomeLayout.value) return
  const prevOrder = [...editOrder.value]
  const prevHidden = [...editHidden.value]
  mutate()
  savingHomeLayout.value = true
  try {
    const result = await api.saveHomeLayout(editOrder.value, editHidden.value)
    homeLayoutEntries.value = result.entries || []
    homeLayoutLoaded.value = true
    homeHiddenList.value = [...editHidden.value]
    editOrder.value = homeLayoutEntries.value.map(entry => entry.key)
  } catch (error) {
    editOrder.value = prevOrder
    editHidden.value = prevHidden
    message.value = error instanceof Error ? `这次调整没能保存：${error.message}` : '这次调整没能保存，请重试'
  } finally { savingHomeLayout.value = false }
}
function moveHomeEntry(index: number, delta: -1 | 1) {
  const target = index + delta
  if (target < 0 || target >= editOrder.value.length) return
  void applyHomeEdit(() => {
    const next = [...editOrder.value]
    ;[next[index], next[target]] = [next[target], next[index]]
    editOrder.value = next
  })
}
function hideHomeEntry(key: string) {
  void applyHomeEdit(() => {
    editOrder.value = editOrder.value.filter(item => item !== key)
    // 工作流拿掉就算取消钉住；脚本要记进 hidden，免得下版本自动冒回来。
    if (!key.startsWith('wf:') && !editHidden.value.includes(key)) editHidden.value = [...editHidden.value, key]
  })
}
function restoreHomeEntry(key: string) {
  void applyHomeEdit(() => {
    editHidden.value = editHidden.value.filter(item => item !== key)
    if (!editOrder.value.includes(key)) editOrder.value = [...editOrder.value, key]
  })
}
function pinHomeWorkflow(id: string) {
  void applyHomeEdit(() => {
    const key = `wf:${id}`
    editHidden.value = editHidden.value.filter(item => item !== key)
    if (!editOrder.value.includes(key)) editOrder.value = [...editOrder.value, key]
  })
}
// 常用功能里钉住的工作流：右侧直接给一条能跑的流程条。
const presetJump = ref<{ id: string; tick: number } | null>(null)
function openWorkflowPreset(id: string) {
  presetJump.value = { id, tick: (presetJump.value?.tick || 0) + 1 }
  tab.value = 'workflow'
}
async function runSelectedWorkflow() {
  const preset = selectedWorkflow.value
  if (!preset) return
  await startWorkflow(preset)
}
async function startWorkflow(preset: WorkflowIdentity) {
  if (running.value || stopping.value || startingWorkflow.value) return
  if (workflowDraft.value?.id === preset.id && (workflowPanel.value?.dirty || workflowPanel.value?.locked)) {
    openWorkflowPreset(preset.id)
    message.value = '这条流程有未保存的修改或正在保存，请在编辑页确认后运行'
    return
  }
  startingWorkflow.value = true
  statusRevision++
  try {
    const result = await api.run('workflow', { workflow_id: preset.id })
    if (!result.ok) throw new Error('这条流程没有启动，请重试')
    workflowStarted(result.workflow || preset)
    message.value = `「${runningWorkflow.value!.name}」已开始`
  } catch (error) { message.value = error instanceof Error ? error.message : '启动失败，请重试' }
  finally { startingWorkflow.value = false }
}
function openWishlist() {
  selected.value = '$wishlist'
  tab.value = 'tasks'
}
const scriptGroups = computed(() => {
  const entries = Object.entries(scripts.value)
  const take = (...keys: string[]) => entries.filter(([key]) => keys.includes(key))
  const used = new Set(['daily', 'raid', 'pumpkin', 'edocastle', 'sortie', 'yosari', 'osaka', 'sakura', 'practice', 'expedition', 'smith', 'sugar', 'snapshot'])
  return [
    { label: '日常配置', entries: take('daily') },
    { label: '出阵配置', entries: take('raid', 'pumpkin', 'edocastle', 'sortie', 'yosari', 'osaka', 'sakura', 'practice') },
    { label: '后勤配置', entries: take('expedition', 'smith', 'sugar', 'snapshot') },
    { label: '其他配置', entries: entries.filter(([key]) => !used.has(key)) },
  ].filter(group => group.entries.length)
})
const pumpkinTargets = computed({
  get: () => {
    const raw = params.value.pumpkin?.watch
    return Array.isArray(raw)
      ? raw.map(String)
      : String(raw || '').replace(/，/g, ',').split(',').map(name => name.trim()).filter(Boolean)
  },
  set: (watch: string[]) => {
    params.value.pumpkin = { ...(params.value.pumpkin || {}), watch }
  },
})
const dailyPumpkinTargets = computed({
  get: () => {
    const raw = params.value.daily?.pumpkin_watch
    return Array.isArray(raw)
      ? raw.map(String)
      : String(raw || '').replace(/，/g, ',').split(',').map(name => name.trim()).filter(Boolean)
  },
  set: (pumpkin_watch: string[]) => {
    params.value.daily = { ...(params.value.daily || {}), pumpkin_watch }
  },
})

const stagePlace = computed(() => {
  if (ledgerMode.value) return '本丸账房'
  if (!dashboardRun.value?.active) return '本丸庭院'
  const script = String(dashboardRun.value.script || '')
  const step = String(dashboardRun.value.step || '')
  if (/(锻刀|手入|刀解|合成|炼糖|根兵糖)/.test(step) || ['forge', 'repair', 'sugar'].includes(script)) return '锻冶工房'
  if (/(出阵|合战|异去|演练|远征|联队|南瓜|刷花|换队长|派遣)/.test(step) || ['raid', 'pumpkin', 'sortie', 'yosari', 'sakura', 'practice', 'expedition', 'dispatch', 'osaka'].includes(script)) return '出阵之路'
  return '本丸庭院'
})
const stageActive = computed(() => !ledgerMode.value && (running.value || Boolean(dashboardRun.value?.active)))
const stageFlavor = computed(() => ledgerMode.value ? '今天只算账' : dashboardRun.value?.active ? (dashboardRun.value.flavor || '正在本丸干活🔧') : '本丸待命')
const stageSub = computed(() => {
  if (ledgerMode.value) return '不连接游戏 · 手动记录与规划'
  if (!dashboardRun.value?.active) return '庭院无事'
  const label = dashboardRun.value.label || scripts.value[current.value || '']?.label || '本丸任务'
  const started = Number(dashboardRun.value.started || 0)
  if (!started) return label
  const elapsed = Math.max(0, Math.floor(clock.value / 1000 - started))
  const hours = Math.floor(elapsed / 3600)
  const minutes = Math.floor((elapsed % 3600) / 60)
  const seconds = elapsed % 60
  const duration = hours ? `${hours}小时${String(minutes).padStart(2, '0')}分` : minutes ? `${minutes}分${String(seconds).padStart(2, '0')}秒` : `${seconds}秒`
  return `${label} · 已跑 ${duration}`
})

function defaults(info: ScriptInfo): ScriptParams {
  return Object.fromEntries((info.params || []).map(field => [field.key, field.default ?? '']))
}

function taskIcon(key: string | number) {
  return `/static/img/ui/${taskIcons[String(key)] || 'request-token.png'}`
}

function migrateParams(script: string, value: ScriptParams): ScriptParams {
  const migrated = { ...value }
  if (script === 'daily' && !['none', 'raid', 'pumpkin', 'yosari', 'osaka', 'sortie'].includes(String(migrated.sortie_mode ?? ''))) migrated.sortie_mode = 'none'
  if (script === 'pumpkin' && String(migrated.difficulty ?? '') === '0') migrated.difficulty = '1'
  if (migrated.runs == null) {
    const legacyKey = script === 'raid' ? 'rounds'
      : script === 'pumpkin' ? 'max_skips'
      : (script === 'sortie' || script === 'yosari') ? 'loops'
      : null
    if (legacyKey && migrated[legacyKey] != null) migrated.runs = migrated[legacyKey]
  }
  return migrated
}

async function load() {
  loading.value = true
  try {
    const mode = await api.appMode()
    ledgerMode.value = mode.mode === 'ledger'
    if (ledgerMode.value) {
      const saved = await api.settings()
      theme.value = saved.theme === 'pixel' ? 'pixel' : 'washi'
      applyTheme()
      tab.value = 'report'
      scripts.value = {}
      params.value = {}
      return
    }
    const [scriptData, saved] = await Promise.all([api.scripts(), api.settings()])
    scripts.value = scriptData.scripts
    running.value = scriptData.running
    current.value = scriptData.current
    runningWorkflow.value = scriptData.workflow || null
    eventHidden.value = scriptData.event_hidden || []
    theme.value = saved.theme === 'pixel' ? 'pixel' : 'washi'
    applyTheme()
    applyBackdrop(saved.backdrop)
    params.value = Object.fromEntries(Object.entries(scriptData.scripts).map(([key, info]) => [
      key,
      { ...defaults(info), ...migrateParams(key, saved.params?.[key] || {}) },
    ]))
    if (!scripts.value[selected.value] && !selected.value.startsWith('wf:')) selected.value = Object.keys(scripts.value)[0] || ''
    // 常用功能布局与工作流预设：布局接口不可用时回落默认清单，不影响其余加载。
    try {
      const [layout, workflowData] = await Promise.all([api.homeLayout(), api.workflows()])
      homeLayoutEntries.value = layout.entries || []
      homeHiddenList.value = layout.hidden || []
      homeLayoutLoaded.value = true
      homeWorkflows.value = workflowData.presets || []
    } catch (_) { /* 兜底走 fallbackHomeOrder */ }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '面板加载失败'
  } finally {
    loading.value = false
  }
}

function applyTheme() { document.body.dataset.theme = theme.value }
function applyBackdrop(color?: string) {
  if (color && /^#[0-9a-fA-F]{6}$/.test(color)) document.body.style.setProperty('--space-backdrop', color)
  else document.body.style.removeProperty('--space-backdrop')
}
async function toggleTheme() { theme.value = theme.value === 'washi' ? 'pixel' : 'washi'; applyTheme(); await api.saveTheme(theme.value) }
type LauncherWindow = Window & { pywebview?: { api?: { return_to_launcher?: () => Promise<{ ok: boolean; message?: string }> } } }
function detectLauncherBridge() {
  launcherAvailable.value = typeof (window as LauncherWindow).pywebview?.api?.return_to_launcher === 'function'
}
async function returnToLauncher() {
  const bridge = (window as LauncherWindow).pywebview?.api
  if (!bridge?.return_to_launcher) {
    launcherAvailable.value = false
    message.value = '这个页面不是从启动器窗口打开的'
    return
  }
  returningToLauncher.value = true
  try {
    const result = await bridge.return_to_launcher()
    if (!result.ok) {
      message.value = result.message || '暂时没能返回启动器'
      returningToLauncher.value = false
    }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '暂时没能返回启动器'
    returningToLauncher.value = false
  }
}
async function pollStatus() {
  const revision = statusRevision
  try {
    const [state, dashboard] = await Promise.all([api.scripts(), api.dashboard()])
    if (revision !== statusRevision || startingWorkflow.value || workflowPanel.value?.locked) return
    dashboardRun.value = dashboard.running || null
    clock.value = Date.now()
    const wasRunning = running.value
    // 停止请求后后台进程可能还会短暂报告一次 running；在真正停稳前不让 UI 反跳回“运行中”。
    if (stopping.value && state.running) return
    if (stopping.value && !state.running) stopping.value = false
    running.value = state.running
    current.value = state.running ? state.current : null
    if (!state.running || state.current !== 'workflow') runningWorkflow.value = null
    else if ('workflow' in state) runningWorkflow.value = state.workflow || null
    if (state.event_hidden) eventHidden.value = state.event_hidden
    if (wasRunning && !state.running) message.value = '任务已结束'
  } catch (_) {}
}
function onSchedulerWarning(event: Event) { schedulerWarning.value = String((event as CustomEvent).detail || '') }
function onStageScroll(event: Event, state: Ref<boolean>) {
  const scroller = event.currentTarget as HTMLElement | null
  const scrollTop = scroller?.scrollTop || 0
  if (state.value) {
    if (scrollTop < 12) state.value = false
  } else if (scrollTop > 56) {
    // 短页面收掉舞台后可能立刻失去滚动空间，scrollTop 被压回顶部，
    // 继而触发“展开 → 又可滚 → 再收起”的抖动。只有收起后仍有余量才动舞台。
    const stageHeight = document.querySelector<HTMLElement>('.honmaru-stage')?.getBoundingClientRect().height || 0
    const scrollRange = scroller ? scroller.scrollHeight - scroller.clientHeight : 0
    if (scrollRange > stageHeight + 56) state.value = true
  }
}
function onReportScroll(event: Event) { onStageScroll(event, reportStageCollapsed) }
function onWorkflowScroll(event: Event) { onStageScroll(event, workflowStageCollapsed) }
async function pauseScheduler() { await api.pauseExpeditions(30); schedulerWarning.value = ''; message.value = '已暂停自动远征 30 分钟' }

// 通知中心事故单的「去看看」：按 entry 跳到对应页面/任务
function openIncidentEntry(entry: { tab?: string; script?: string }) {
  const target = String(entry.tab || 'report')
  if (['home', 'tasks', 'workflow', 'report', 'chat', 'system'].includes(target)) tab.value = target as typeof tab.value
  if (entry.script && scripts.value[entry.script]) selected.value = entry.script
}

async function save() {
  try {
    await Promise.all([
      api.saveSettings(params.value),
      selected.value === 'expedition' ? immediateExpedition.value?.save() : Promise.resolve(),
    ])
    message.value = selected.value === 'expedition' ? '配置和远征安排已保存' : '配置已保存'
  } catch (error) {
    message.value = error instanceof Error ? `保存失败：${error.message}` : '保存失败，请重试'
  }
}

async function run() {
  if (selected.value === 'daily') {
    await startWorkflow(homeWorkflows.value.find(preset => preset.id === 'builtin-daily') || { id: 'builtin-daily', name: '一键日课' })
    return
  }
  await api.run(selected.value, params.value[selected.value] || {})
  running.value = true
  current.value = selected.value
  message.value = `${selectedInfo.value.label}已开始`
}

async function stop() {
  statusRevision++
  stopping.value = true
  try {
    const result = await api.stop()
    if (!result.ok) throw new Error('停止请求未成功，请重试')
    // 保持当前任务，直到下一次状态轮询确认停止，避免提前显示“空闲”。
    message.value = '已发送停止请求'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '停止失败，请重试'
    stopping.value = false
  }
}

// 页面级提示统一短暂展示；重复提示会重新计时，点击仍可立即关闭。
watch(message, value => {
  window.clearTimeout(toastTimer)
  if (value) toastTimer = window.setTimeout(() => { message.value = '' }, 3200)
})

onMounted(async () => {
  detectLauncherBridge()
  window.addEventListener('pywebviewready', detectLauncherBridge)
  await load()
  if (!ledgerMode.value) {
    await pollStatus()
    pollTimer = window.setInterval(pollStatus, 2000)
    window.addEventListener('maamaru:scheduler-warning', onSchedulerWarning)
  }
})
onBeforeUnmount(() => { window.clearInterval(pollTimer); window.clearTimeout(toastTimer); window.removeEventListener('maamaru:scheduler-warning', onSchedulerWarning); window.removeEventListener('pywebviewready', detectLauncherBridge) })
watch(selected, async () => { await nextTick(); contentEl.value?.scrollTo({ top: 0 }) })
watch(tab, value => {
  if (value !== 'report') { reportStageCollapsed.value = false; reportEntry.value = 'report' }
  if (value !== 'workflow') workflowStageCollapsed.value = false
})
</script>

<template>
  <div class="shell" :class="{ 'report-stage-collapsed': reportStageCollapsed, 'workflow-stage-collapsed': workflowStageCollapsed, 'ledger-mode': ledgerMode }">
    <section class="honmaru-stage" :class="{ working: stageActive }" aria-label="狐之助工作现场">
      <div class="stage-brand"><strong>まあ丸</strong><small>{{ ledgerMode ? '纯净本丸账房' : '本丸自动管家' }}</small></div>
      <StageActors :active="stageActive" />
      <div class="stage-status">
        <small>{{ stagePlace }}</small>
        <strong>{{ stageFlavor }}</strong>
        <span>{{ stageSub }}</span>
      </div>
    </section>
    <header class="topbar">
      <nav class="topnav">
        <button v-if="ledgerMode" class="nav-report active">本丸账房</button>
        <template v-else>
          <button class="nav-home" :class="{ active: tab === 'home' }" @click="tab = 'home'">我的本丸</button>
          <button class="nav-office" :class="{ active: tab === 'office' }" @click="tab = 'office'">执务</button>
          <button class="nav-tasks" :class="{ active: tab === 'tasks' }" @click="selected === 'daily' && (selected = 'sortie'); tab = 'tasks'">配置</button>
          <button class="nav-workflow" :class="{ active: tab === 'workflow' }" @click="tab = 'workflow'">工作流</button>
          <button class="nav-report" :class="{ active: tab === 'report' }" @click="tab = 'report'">本丸</button>
          <button class="nav-chat" :class="{ active: tab === 'chat' }" @click="tab = 'chat'">近侍</button>
          <button class="nav-system" :class="{ active: tab === 'system' }" @click="tab = 'system'">系统</button>
        </template>
      </nav>
      <div class="top-status">
        <i :class="{ running: stageActive }"></i><span>{{ ledgerMode ? '纯净模式' : stageActive ? '执务中' : '待命中' }}</span>
        <NotificationCenter v-if="!ledgerMode" @open-entry="openIncidentEntry" />
        <button v-if="launcherAvailable" class="launcher-return" type="button" title="返回启动器，不会停止正在运行的任务" :disabled="returningToLauncher" @click="returnToLauncher">{{ returningToLauncher ? '正在返回…' : '返回启动器' }}</button>
        <button class="theme-button" :title="theme === 'washi' ? '切换像素主题' : '切换和纸主题'" :aria-label="theme === 'washi' ? '切换像素主题' : '切换和纸主题'" @click="toggleTheme"></button>
        <a v-if="!ledgerMode" href="/legacy">旧版备用</a>
      </div>
    </header>
    <MaamaruFrame v-if="!loading && tab === 'tasks'" variant="tasks" page-class="layout">
      <nav class="sidebar">
        <template v-for="group in scriptGroups" :key="group.label">
          <h3>{{ group.label }}</h3>
          <SideNavItem v-for="([key, info]) in group.entries" :key="key" :active="selected === key" :running="running && current === key" @click="key === 'daily' ? openDailyWorkflow() : selected = key">
            <span><img class="task-menu-icon" :src="taskIcon(key)" alt="">{{ info.label }}</span><small v-if="running && current === key">运行中</small>
          </SideNavItem>
          <SideNavItem v-if="group.label === '后勤配置'" :active="selected === '$schedule'" @click="selected = '$schedule'">
            <span><img class="task-menu-icon" :src="'/static/img/ui/expedition.png'" alt="">自动排班</span>
          </SideNavItem>
          <SideNavItem v-if="group.label === '后勤配置'" :active="false" @click="tab = 'workflow'">
            <span><img class="task-menu-icon" :src="taskIcon('workflow')" alt="">工作流</span>
          </SideNavItem>
        </template>
        <h3>名单设置</h3>
        <SideNavItem :active="selected === '$repair-list'" @click="selected = '$repair-list'">
          <span><img class="task-menu-icon" :src="'/static/img/ui/repair-tools.png'" alt="">手入黑名单</span>
        </SideNavItem>
        <SideNavItem :active="selected === '$dismantle-list'" @click="selected = '$dismantle-list'">
          <span><img class="task-menu-icon" :src="'/static/img/ui/dismantle.png'" alt="">刀解白名单</span>
        </SideNavItem>
        <SideNavItem :active="selected === '$wishlist'" @click="selected = '$wishlist'">
          <span><img class="task-menu-icon" :src="'/static/img/ui/menuList.png'" alt="">心愿刀名单</span>
        </SideNavItem>
      </nav>
      <section ref="contentEl" class="content">
        <TaskForm
          v-if="selectedInfo && selected !== 'daily'"
          :script-key="selected"
          :info="selectedInfo"
          :model-value="params[selected] || {}"
          :running="running && current === selected"
          :busy="running"
          :has-advanced="selected === 'expedition' || selected === 'pumpkin' || (selected === 'daily' && params.daily?.sortie_mode === 'pumpkin')"
          :advanced-label="selected === 'expedition' ? '派遣设置' : '特有高级设置'"
          @update:model-value="params[selected] = $event"
          @save="save"
          @run="run"
          @stop="stop"
        >
          <template #advanced>
            <ImmediateExpeditionFields v-if="selected === 'expedition'" ref="immediateExpedition" />
            <AdvancedSettingLink
              v-else-if="selected === 'pumpkin'"
              title="南瓜目标名单"
              :summary="pumpkinTargets.length ? `已选 ${pumpkinTargets.length} 把` : '未指定目标'"
              @open="advancedDrawer = 'pumpkin'"
            />
            <AdvancedSettingLink
              v-else
              title="日课南瓜目标名单"
              :summary="dailyPumpkinTargets.length ? `已选 ${dailyPumpkinTargets.length} 把` : '未指定目标'"
              @open="advancedDrawer = 'daily-pumpkin'"
            />
          </template>
        </TaskForm>
        <div v-else-if="selected === 'daily'" class="workflow-live-bar"><strong>一键日课已放进工作流</strong><button type="button" @click="openDailyWorkflow">打开日课安排</button></div>
        <SchedulePanel v-else-if="selected === '$schedule'" embedded />
        <ListsPanel v-else-if="selected === '$repair-list'" key="repair-list" embedded initial="repair_blacklist" />
        <ListsPanel v-else-if="selected === '$dismantle-list'" key="dismantle-list" embedded initial="dismantle_whitelist" />
        <ListsPanel v-else-if="selected === '$wishlist'" key="wishlist" embedded initial="sword_wishlist" />
        <p v-if="message" class="toast" @click="message = ''">{{ message }}</p>
      </section>
    </MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'home'" variant="single" page-class="single-layout personal-home-page"><HonmaruHome :activity="dashboardRun" :busy="running" @office="tab = 'office'" @report="tab = 'report'" @planning="reportEntry = 'planning'; tab = 'report'" @wishlist="openWishlist" /></MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'office'" variant="overview" page-class="overview-layout">
      <aside class="home-functions" :class="{ editing: editingHome }">
        <div class="home-functions-head">
          <h2>常用功能</h2>
          <span v-if="homeScriptIndex >= 0 && !editingHome">{{ homeScriptIndex + 1 }} / {{ homeEntries.length }}</span>
          <button type="button" class="home-customize" @click="editingHome ? finishHomeEdit() : startHomeEdit()">{{ editingHome ? '完成' : '自定义' }}</button>
        </div>
        <div class="home-functions-carousel">
          <button type="button" class="home-functions-arrow previous" aria-label="上一个常用功能" :disabled="editingHome || homeScriptIndex <= 0" @click="chooseAdjacentHome(-1)">‹</button>
        <nav ref="homeFunctionsNav">
          <template v-if="editingHome">
            <div v-for="(entry, index) in homeEntries" :key="entry.key" class="home-entry-row">
              <button
                :data-script="entry.key"
                :class="{ active: selected === entry.key }"
                @click="selected = entry.key"
              >
                <span><img class="task-menu-icon" :src="taskIcon(entry.kind === 'workflow' ? 'workflow' : entry.key)" alt="">{{ entry.label }}</span>
              </button>
              <span class="home-entry-tools">
                <button type="button" title="往上挪" :disabled="index === 0 || savingHomeLayout" @click="moveHomeEntry(index, -1)">↑</button>
                <button type="button" title="往下挪" :disabled="index === homeEntries.length - 1 || savingHomeLayout" @click="moveHomeEntry(index, 1)">↓</button>
                <button type="button" :disabled="savingHomeLayout" @click="hideHomeEntry(entry.key)">收起</button>
              </span>
            </div>
          </template>
          <template v-else>
            <button
              v-for="entry in homeEntries"
              :key="entry.key"
              :data-script="entry.key"
              :class="{ active: selected === entry.key, running: running && current === entry.key }"
              @click="selected = entry.key"
            >
              <span><img class="task-menu-icon" :src="taskIcon(entry.kind === 'workflow' ? 'workflow' : entry.key)" alt="">{{ entry.label }}</span><small v-if="running && current === entry.key">运行中</small>
            </button>
          </template>
        </nav>
          <button type="button" class="home-functions-arrow next" aria-label="下一个常用功能" :disabled="editingHome || homeScriptIndex < 0 || homeScriptIndex >= homeEntries.length - 1" @click="chooseAdjacentHome(1)">›</button>
        </div>
        <div v-if="editingHome" class="home-edit-panel">
          <h3>收起来的功能</h3>
          <p v-if="!hiddenHomeEntries.length" class="home-edit-empty">还没有收起来的功能</p>
          <div v-for="entry in hiddenHomeEntries" :key="entry.key" class="home-edit-row">
            <span><img class="task-menu-icon" :src="taskIcon(entry.kind === 'workflow' ? 'workflow' : entry.key)" alt="">{{ entry.label }}</span>
            <button type="button" :disabled="savingHomeLayout" @click="restoreHomeEntry(entry.key)">加回</button>
          </div>
          <h3>我的工作流</h3>
          <p v-if="!pinnableWorkflows.length" class="home-edit-empty">工作流都钉上啦</p>
          <div v-for="preset in pinnableWorkflows" :key="preset.id" class="home-edit-row">
            <span><img class="task-menu-icon" :src="taskIcon('workflow')" alt="">{{ preset.name }}<small>{{ preset.nodes.length }} 块积木</small></span>
            <button type="button" :disabled="savingHomeLayout" @click="pinHomeWorkflow(preset.id)">钉上</button>
          </div>
        </div>
        <p v-if="eventHiddenLabels.length" class="home-functions-hidden-note">{{ eventHiddenLabels.join('、') }} 未开放，先收起来了</p>
      </aside>
      <section class="home-center">
        <div v-if="running && current === 'workflow'" class="workflow-live-bar"><strong>{{ stopping ? "正在停止…" : workflowRunningLabel }}</strong><button type="button" class="secondary" @click="viewRunningWorkflow">查看流程</button><button type="button" class="danger" :disabled="stopping" @click="stop">{{ stopping ? '正在停止…' : '停止工作流' }}</button></div>
        <div v-if="selectedWorkflow && !(running && current === 'workflow')" class="workflow-live-bar"><strong>「{{ selectedWorkflow.name }}」 · {{ selectedWorkflow.nodes.length }} 块积木</strong><button type="button" class="secondary" @click="selectedWorkflow && openWorkflowPreset(selectedWorkflow.id)">调整</button><button type="button" class="primary" :disabled="running || stopping || startingWorkflow" @click="runSelectedWorkflow">跑这条</button></div>
        <div v-else-if="selected.startsWith('wf:') && !(running && current === 'workflow')" class="workflow-live-bar"><strong>这条工作流已经被删啦，去「自定义」里收拾一下常用功能吧</strong></div>
        <div v-if="selected === 'daily' && !(running && current === 'workflow')" class="workflow-live-bar"><strong>一键日课 · 默认流程</strong><button type="button" class="secondary" @click="openDailyWorkflow">调整日课安排</button><button type="button" class="primary" :disabled="running || stopping || startingWorkflow" @click="run">运行日课</button></div>
        <OverviewTaskCard
          v-if="selectedInfo && selected !== 'daily' && !(running && current === 'workflow')"
          :info="selectedInfo"
          :icon-src="taskIcon(selected)"
          :params="params[selected] || {}"
          :running="running && current === selected"
          :busy="running"
          @run="run"
          @stop="stop"
          @configure="tab = 'tasks'"
        />
        <LogPanel :running="logRunning" :stopping="stopping" :task-label="logTaskLabel" />
        <p v-if="message" class="toast" role="status" @click="message = ''">{{ message }}</p>
      </section>
      <aside class="home-dashboard"><DashboardPanel @open-report="tab = 'report'" /></aside>
    </MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'report'" variant="single" page-class="single-layout report-page" @scroll="onReportScroll"><ReportPanel :initial-section="reportEntry" @open-wishlist="openWishlist" /></MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'chat'" variant="single" page-class="single-layout chat-page"><ChatPanel /></MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'system'" variant="single" page-class="single-layout system-page"><SystemPanel /></MaamaruFrame>
    <div v-else-if="loading" class="loading">正在整理本丸配置……</div>
    <!-- Keep the editor mounted after first use, including in-flight saves and scroll position. -->
    <MaamaruFrame v-if="!loading && (tab === 'workflow' || workflowDraft)" v-show="tab === 'workflow'" variant="single" page-class="single-layout workflow-page" @scroll="onWorkflowScroll"><WorkflowPanel ref="workflowPanel" v-model:draft="workflowDraft" :daily-entry="dailyEntry" :preset-jump="presetJump" :active="tab === 'workflow'" :running="running" :current="current" :stopping="stopping" :busy="startingWorkflow" :running-workflow="runningWorkflow" @started="workflowStarted" @saved="workflowSaved" @stop="stop" @office="tab = 'office'" /><p v-if="message" class="toast" @click="message = ''">{{ message }}</p></MaamaruFrame>
    <div v-if="!ledgerMode && schedulerWarning" class="scheduler-warning"><strong>远征即将接管游戏</strong><span>{{ schedulerWarning }}</span><button @click="pauseScheduler">先别动游戏</button></div>
    <SwordListDrawer
      :open="advancedDrawer === 'pumpkin'"
      title="南瓜目标名单"
      description="只在需要调整剪影目标时进入这里；主出阵配置不会被长名单挤乱。"
      :model-value="pumpkinTargets"
      @update:model-value="pumpkinTargets = $event"
      @close="advancedDrawer = null"
    />
    <SwordListDrawer
      :open="advancedDrawer === 'daily-pumpkin'"
      title="日课南瓜目标名单"
      description="只用于一键日课里的南瓜出阵，不会修改单独南瓜的目标名单。留空则不筛选目标。"
      :model-value="dailyPumpkinTargets"
      @update:model-value="dailyPumpkinTargets = $event"
      @close="advancedDrawer = null"
    />
  </div>
</template>
