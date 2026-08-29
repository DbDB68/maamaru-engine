<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from './api'
import TaskForm from './components/TaskForm.vue'
import DashboardPanel from './components/DashboardPanel.vue'
import ReportPanel from './components/ReportPanel.vue'
import LogPanel from './components/LogPanel.vue'
import ChatPanel from './components/ChatPanel.vue'
import ListsPanel from './components/ListsPanel.vue'
import SchedulePanel from './components/SchedulePanel.vue'
import SystemPanel from './components/SystemPanel.vue'
import OverviewTaskCard from './components/OverviewTaskCard.vue'
import AdvancedSettingLink from './components/AdvancedSettingLink.vue'
import SwordListDrawer from './components/SwordListDrawer.vue'
import MaamaruFrame from './components/MaamaruFrame.vue'
import SideNavItem from './components/SideNavItem.vue'
import ImmediateExpeditionFields from './components/ImmediateExpeditionFields.vue'
import type { ScriptInfo, ScriptParams } from './types'

const scripts = ref<Record<string, ScriptInfo>>({})
const params = ref<Record<string, ScriptParams>>({})
const selected = ref('daily')
const running = ref(false)
const current = ref<string | null>(null)
const loading = ref(true)
const message = ref('')
const tab = ref<'home' | 'tasks' | 'report' | 'chat' | 'system'>('home')
const theme = ref<'washi' | 'pixel'>('washi')
const schedulerWarning = ref('')
const advancedDrawer = ref<'pumpkin' | 'daily-pumpkin' | null>(null)
let pollTimer = 0
let toastTimer = 0
const stopping = ref(false)
const contentEl = ref<HTMLElement | null>(null)
const reportStageCollapsed = ref(false)
const homeFunctionsNav = ref<HTMLElement | null>(null)
const dashboardRun = ref<any>(null)
const immediateExpedition = ref<{ save: () => Promise<void> } | null>(null)
const clock = ref(Date.now())

const taskIcons: Record<string, string> = {
  // 活动任务也必须使用自己的素材，不能临时借用通用出阵图标后一直漏接。
  daily: 'daily.png', raid: 'raid.png', pumpkin: 'pumpkin.png', edocastle: 'edocastle.png', sortie: 'sortie.png', yosari: 'yosari.png', osaka: 'digging.png',
  sakura: 'sakura.png', practice: 'practice.png', expedition: 'expedition.png', smith: 'forge.png',
  sugar: 'sugar.png', snapshot: 'snapshot.png', repair: 'repair-tools.png',
}

const selectedInfo = computed(() => scripts.value[selected.value])
const homeScriptOrder = ['daily', 'sortie', 'yosari', 'osaka', 'edocastle', 'expedition', 'smith', 'pumpkin', 'raid', 'sugar', 'sakura', 'practice', 'snapshot']
// 活动没开放的脚本从常用功能收起来（后端 /api/scripts 下发，配置页不受影响）
const eventHidden = ref<string[]>([])
const homeScripts = computed(() => homeScriptOrder
  .filter(key => scripts.value[key] && !eventHidden.value.includes(key))
  .map(key => [key, scripts.value[key]] as const))
const eventHiddenLabels = computed(() => eventHidden.value
  .filter(key => scripts.value[key])
  .map(key => scripts.value[key].label))
const homeScriptIndex = computed(() => homeScripts.value.findIndex(([key]) => key === selected.value))
async function chooseAdjacentHome(direction: -1 | 1) {
  const next = homeScriptIndex.value + direction
  if (next < 0 || next >= homeScripts.value.length) return
  selected.value = homeScripts.value[next][0]
  await nextTick()
  homeFunctionsNav.value?.querySelector<HTMLElement>(`[data-script="${selected.value}"]`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
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
  if (!dashboardRun.value?.active) return '本丸庭院'
  const script = String(dashboardRun.value.script || '')
  const step = String(dashboardRun.value.step || '')
  if (/(锻刀|手入|刀解|合成|炼糖|根兵糖)/.test(step) || ['forge', 'repair', 'sugar'].includes(script)) return '锻冶工房'
  if (/(出阵|合战|异去|演练|远征|联队|南瓜|刷花|换队长|派遣)/.test(step) || ['raid', 'pumpkin', 'sortie', 'yosari', 'sakura', 'practice', 'expedition', 'dispatch', 'osaka'].includes(script)) return '出阵之路'
  return '本丸庭院'
})
const stageActive = computed(() => running.value || Boolean(dashboardRun.value?.active))
const stageFlavor = computed(() => dashboardRun.value?.active ? (dashboardRun.value.flavor || '正在本丸干活🔧') : '本丸待命')
const stageSub = computed(() => {
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
    const [scriptData, saved] = await Promise.all([api.scripts(), api.settings()])
    scripts.value = scriptData.scripts
    running.value = scriptData.running
    current.value = scriptData.current
    eventHidden.value = scriptData.event_hidden || []
    theme.value = saved.theme === 'pixel' ? 'pixel' : 'washi'
    applyTheme()
    params.value = Object.fromEntries(Object.entries(scriptData.scripts).map(([key, info]) => [
      key,
      { ...defaults(info), ...migrateParams(key, saved.params?.[key] || {}) },
    ]))
    if (!scripts.value[selected.value]) selected.value = Object.keys(scripts.value)[0] || ''
  } catch (error) {
    message.value = error instanceof Error ? error.message : '面板加载失败'
  } finally {
    loading.value = false
  }
}

function applyTheme() { document.body.dataset.theme = theme.value }
async function toggleTheme() { theme.value = theme.value === 'washi' ? 'pixel' : 'washi'; applyTheme(); await api.saveTheme(theme.value) }
async function pollStatus() {
  try {
    const [state, dashboard] = await Promise.all([api.scripts(), api.dashboard()])
    dashboardRun.value = dashboard.running || null
    clock.value = Date.now()
    const wasRunning = running.value
    // 停止请求后后台进程可能还会短暂报告一次 running；在真正停稳前不让 UI 反跳回“运行中”。
    if (stopping.value && state.running) return
    if (stopping.value && !state.running) stopping.value = false
    running.value = state.running
    current.value = state.running ? state.current : null
    if (state.event_hidden) eventHidden.value = state.event_hidden
    if (wasRunning && !state.running) message.value = '任务已结束'
  } catch (_) {}
}
function onSchedulerWarning(event: Event) { schedulerWarning.value = String((event as CustomEvent).detail || '') }
function onReportScroll(event: Event) {
  const scroller = event.currentTarget as HTMLElement | null
  const scrollTop = scroller?.scrollTop || 0
  if (reportStageCollapsed.value) {
    if (scrollTop < 12) reportStageCollapsed.value = false
  } else if (scrollTop > 56) {
    // 短规划页收掉舞台后可能立刻失去滚动空间，scrollTop 被压回顶部，
    // 继而触发“展开 → 又可滚 → 再收起”的抖动。只有收起后仍有余量才动舞台。
    const stageHeight = document.querySelector<HTMLElement>('.honmaru-stage')?.getBoundingClientRect().height || 0
    const scrollRange = scroller ? scroller.scrollHeight - scroller.clientHeight : 0
    if (scrollRange > stageHeight + 56) reportStageCollapsed.value = true
  }
}
async function pauseScheduler() { await api.pauseExpeditions(30); schedulerWarning.value = ''; message.value = '已暂停自动远征 30 分钟' }

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
  await api.run(selected.value, params.value[selected.value] || {})
  running.value = true
  current.value = selected.value
  message.value = `${selectedInfo.value.label}已开始`
}

async function stop() {
  stopping.value = true
  await api.stop()
  running.value = false
  current.value = null
  message.value = '已发送停止请求'
}

// 页面级提示统一短暂展示；重复提示会重新计时，点击仍可立即关闭。
watch(message, value => {
  window.clearTimeout(toastTimer)
  if (value) toastTimer = window.setTimeout(() => { message.value = '' }, 3200)
})

onMounted(() => { load(); pollStatus(); pollTimer = window.setInterval(pollStatus, 2000); window.addEventListener('maamaru:scheduler-warning', onSchedulerWarning) })
onBeforeUnmount(() => { window.clearInterval(pollTimer); window.clearTimeout(toastTimer); window.removeEventListener('maamaru:scheduler-warning', onSchedulerWarning) })
watch(selected, async () => { await nextTick(); contentEl.value?.scrollTo({ top: 0 }) })
watch(tab, value => { if (value !== 'report') reportStageCollapsed.value = false })
</script>

<template>
  <div class="shell" :class="{ 'report-stage-collapsed': reportStageCollapsed }">
    <section class="honmaru-stage" :class="{ working: stageActive }" aria-label="狐之助工作现场">
      <div class="stage-brand"><strong>まあ丸</strong><small>本丸自动管家</small></div>
      <div class="stage-fox" aria-hidden="true"></div>
      <div class="stage-status">
        <small>{{ stagePlace }}</small>
        <strong>{{ stageFlavor }}</strong>
        <span>{{ stageSub }}</span>
      </div>
    </section>
    <header class="topbar">
      <nav class="topnav">
        <button class="nav-home" :class="{ active: tab === 'home' }" @click="tab = 'home'">概览</button>
        <button class="nav-tasks" :class="{ active: tab === 'tasks' }" @click="tab = 'tasks'">配置</button>
        <button class="nav-report" :class="{ active: tab === 'report' }" @click="tab = 'report'">本丸</button>
        <button class="nav-chat" :class="{ active: tab === 'chat' }" @click="tab = 'chat'">近侍</button>
        <button class="nav-system" :class="{ active: tab === 'system' }" @click="tab = 'system'">系统</button>
      </nav>
      <div class="top-status">
        <i :class="{ running: stageActive }"></i><span>{{ stageActive ? '执务中' : '待命中' }}</span>
        <button class="theme-button" :title="theme === 'washi' ? '切换像素主题' : '切换和纸主题'" :aria-label="theme === 'washi' ? '切换像素主题' : '切换和纸主题'" @click="toggleTheme"></button>
        <a href="/legacy">旧版备用</a>
      </div>
    </header>
    <MaamaruFrame v-if="!loading && tab === 'tasks'" variant="tasks" page-class="layout">
      <nav class="sidebar">
        <template v-for="group in scriptGroups" :key="group.label">
          <h3>{{ group.label }}</h3>
          <SideNavItem v-for="([key, info]) in group.entries" :key="key" :active="selected === key" :running="running && current === key" @click="selected = key">
            <span><img class="task-menu-icon" :src="taskIcon(key)" alt="">{{ info.label }}</span><small v-if="running && current === key">运行中</small>
          </SideNavItem>
          <SideNavItem v-if="group.label === '后勤配置'" :active="selected === '$schedule'" @click="selected = '$schedule'">
            <span><img class="task-menu-icon" :src="'/static/img/ui/expedition.png'" alt="">自动排班</span>
          </SideNavItem>
        </template>
        <h3>名单设置</h3>
        <SideNavItem :active="selected === '$repair-list'" @click="selected = '$repair-list'">
          <span><img class="task-menu-icon" :src="'/static/img/ui/repair-tools.png'" alt="">手入黑名单</span>
        </SideNavItem>
        <SideNavItem :active="selected === '$dismantle-list'" @click="selected = '$dismantle-list'">
          <span><img class="task-menu-icon" :src="'/static/img/ui/dismantle.png'" alt="">刀解白名单</span>
        </SideNavItem>
      </nav>
      <section ref="contentEl" class="content">
        <TaskForm
          v-if="selectedInfo"
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
        <SchedulePanel v-else-if="selected === '$schedule'" embedded />
        <ListsPanel v-else-if="selected === '$repair-list'" key="repair-list" embedded initial="repair_blacklist" />
        <ListsPanel v-else-if="selected === '$dismantle-list'" key="dismantle-list" embedded initial="dismantle_whitelist" />
        <p v-if="message" class="toast" @click="message = ''">{{ message }}</p>
      </section>
    </MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'home'" variant="overview" page-class="overview-layout">
      <aside class="home-functions">
        <div class="home-functions-head"><h2>常用功能</h2><span v-if="homeScriptIndex >= 0">{{ homeScriptIndex + 1 }} / {{ homeScripts.length }}</span></div>
        <div class="home-functions-carousel">
          <button type="button" class="home-functions-arrow previous" aria-label="上一个常用功能" :disabled="homeScriptIndex <= 0" @click="chooseAdjacentHome(-1)">‹</button>
        <nav ref="homeFunctionsNav">
          <button
            v-for="([key, info]) in homeScripts"
            :key="key"
            :data-script="key"
            :class="{ active: selected === key, running: running && current === key }"
            @click="selected = String(key)"
          >
            <span><img class="task-menu-icon" :src="taskIcon(key)" alt="">{{ info.label }}</span><small v-if="running && current === key">运行中</small>
          </button>
        </nav>
          <button type="button" class="home-functions-arrow next" aria-label="下一个常用功能" :disabled="homeScriptIndex < 0 || homeScriptIndex >= homeScripts.length - 1" @click="chooseAdjacentHome(1)">›</button>
        </div>
        <p v-if="eventHiddenLabels.length" class="home-functions-hidden-note">{{ eventHiddenLabels.join('、') }} 未开放，先收起来了</p>
      </aside>
      <section class="home-center">
        <OverviewTaskCard
          v-if="selectedInfo"
          :info="selectedInfo"
          :icon-src="taskIcon(selected)"
          :params="params[selected] || {}"
          :running="running && current === selected"
          :busy="running"
          @run="run"
          @stop="stop"
          @configure="tab = 'tasks'"
        />
        <LogPanel />
      </section>
      <aside class="home-dashboard"><DashboardPanel @open-report="tab = 'report'" /></aside>
    </MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'report'" variant="single" page-class="single-layout report-page" @scroll="onReportScroll"><ReportPanel /></MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'chat'" variant="single" page-class="single-layout chat-page"><ChatPanel /></MaamaruFrame>
    <MaamaruFrame v-else-if="!loading && tab === 'system'" variant="single" page-class="single-layout system-page"><SystemPanel /></MaamaruFrame>
    <div v-else class="loading">正在整理本丸配置……</div>
    <div v-if="schedulerWarning" class="scheduler-warning"><strong>远征即将接管游戏</strong><span>{{ schedulerWarning }}</span><button @click="pauseScheduler">先别动游戏</button></div>
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
