<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'
import PaperCard from './PaperCard.vue'

const emit = defineEmits<{ openReport: [] }>()

const data = ref<any>(null)
const activity = ref<any>(null)
const activityEvents = ref<any[]>([])
const error = ref('')
const now = ref(Date.now())
let timer = 0

const resources = computed(() => data.value?.inventory?.resources || null)
const primaryResources = ['小判', '甲州金', '委托符', '加速符']
const basicResources = ['木炭', '玉钢', '冷却材', '砥石']
const resourceIcons: Record<string, string> = {
  小判: 'koban.png', 甲州金: 'koushu-gold.png', 委托符: 'request-token.png', 加速符: 'speed-token.png',
}

function duration(seconds: number) {
  const value = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  if (hours) return `${hours}小时${String(minutes).padStart(2, '0')}分`
  if (minutes) return `${minutes}分${String(secs).padStart(2, '0')}秒`
  return `${secs}秒`
}

function remaining(item: any) {
  if (item.remain_sec == null) return '时间不明'
  const loadedAt = data.value?._loadedAt || now.value
  const left = Math.max(0, Number(item.remain_sec) - (now.value - loadedAt) / 1000)
  return left ? `剩 ${duration(left)}` : '🎉 该回来了'
}

function furnaceLabel(furnace: any) {
  if (furnace.state !== '锻造中') return `炉${furnace.slot} ${furnace.state}`
  if (furnace.remain_sec != null && Number(furnace.remain_sec) <= 0) return `炉${furnace.slot} 应该完成了`
  if (furnace.remain_sec == null) return `炉${furnace.slot} 锻造中 时间未识别`
  return `炉${furnace.slot} 锻造中 ${duration(Number(furnace.remain_sec))}`
}

function furnaceBusy(furnace: any) {
  return furnace.state === '锻造中' && (furnace.remain_sec == null || Number(furnace.remain_sec) > 0)
}

async function load() {
  try {
    data.value = { ...(await api.dashboard()), _loadedAt: Date.now() }
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '读取失败'
  }
  try {
    const [summary, recent] = await Promise.all([api.dataSummary(1), api.dataEvents(200)])
    activity.value = summary
    const since = Date.now() / 1000 - 86400
    activityEvents.value = recent.items.filter(item => item.ts >= since)
  } catch (_) {
    activity.value = null
    activityEvents.value = []
  }
}

function eventCount(...types: string[]) {
  return activityEvents.value.filter(item => types.includes(item.event_type)).length
}

onMounted(() => {
  load()
  timer = window.setInterval(() => { now.value = Date.now() }, 1000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <section class="dashboard-panel">
    <PanelHeader title="本丸快照" :subtitle="data?.server_time ? `更新于 ${data.server_time.slice(11)}` : error" title-class="dashboard-title">
      <template #actions><button class="secondary dashboard-refresh" type="button" aria-label="刷新本丸快照" title="刷新" @click="load"></button></template>
    </PanelHeader>
    <div class="dashboard-grid">
      <PaperCard variant="dashboard" class="activity-card">
        <h3>📜 今日小结 <small>近 24 小时</small></h3>
        <div class="activity-summary">
          <template v-if="activity">
            <span><strong>{{ eventCount('task_rewards.claimed') }}</strong>次领奖</span>
            <span><strong>{{ eventCount('sortie.completed', 'osaka.floor_completed', 'raid.round_completed', 'pumpkin.sortie_completed') }}</strong>次出阵</span>
            <span><strong>{{ eventCount('expedition.dispatched') }}</strong>次派遣</span>
          </template>
          <span v-else class="activity-waiting">新任务运行后开始记录</span>
        </div>
        <button class="report-link" type="button" @click="emit('openReport')">查看本丸成绩单 →</button>
      </PaperCard>
      <PaperCard variant="dashboard" class="resources-card">
        <h3>💰 家底 <small>{{ data?.inventory?.captured_at ? `快照 ${data.inventory.captured_at.slice(5, 16)}` : '' }}</small></h3>
        <template v-if="resources">
          <div class="resource-grid">
            <div v-for="name in primaryResources" :key="name" class="resource">
              <img class="resource-icon" :src="`/static/img/ui/${resourceIcons[name]}`" alt="">
              <strong>{{ Number(resources[name] ?? 0).toLocaleString() }}</strong><span>{{ name }}</span>
            </div>
          </div>
          <p class="resource-line"><span v-for="name in basicResources" :key="name">{{ name }} {{ Number(resources[name] ?? 0).toLocaleString() }}</span></p>
          <p v-if="data.inventory.doko">刀位 {{ data.inventory.doko }}</p>
          <div class="chips furnaces"><span v-for="furnace in data.inventory.furnaces || []" :key="furnace.slot" :class="{ busy: furnaceBusy(furnace), done: !furnaceBusy(furnace) }">{{ furnaceLabel(furnace) }}</span></div>
        </template>
        <p v-else class="empty">还没有库存快照</p>
      </PaperCard>
      <PaperCard variant="dashboard">
        <h3>🏕 远征</h3>
        <div v-for="item in data?.expeditions || []" :key="item.team_no" class="exp-row">
          <b>部队{{ item.team_no }}</b><span>{{ item.map_code }} {{ item.map_name }}</span><em>{{ remaining(item) }}</em>
        </div>
        <p v-if="!data?.expeditions?.length" class="empty">没有部队在外面跑</p>
      </PaperCard>
      <PaperCard variant="dashboard">
        <h3>📋 日课</h3>
        <div v-if="data?.latest_report?.steps?.length" class="step-list">
          <span v-for="step in data.latest_report.steps" :key="step.name" :class="{ bad: !String(step.status).startsWith('✓') }">{{ step.name }}</span>
        </div>
        <p v-else class="empty">今天还没跑过日课</p>
      </PaperCard>
      <PaperCard variant="dashboard">
        <h3>🌱 内番</h3>
        <p v-if="data?.naihanka?.started_at">🌱 {{ data.naihanka.started_at }} 开始</p>
        <p v-else class="empty">内番闲着呢</p>
      </PaperCard>
    </div>
  </section>
</template>
