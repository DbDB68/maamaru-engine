<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import PixelControl from './PixelControl.vue'

const config = ref<any>(null)
const message = ref('')
const teams = [1, 2, 3, 4, 5]

function mapLabel(map: any) { return `${map.code} · ${map.name}（${map.duration_text}）` }
function completeRows() {
  const rows = new Map((config.value.common_plan || []).map((row: any) => [Number(row.team_no), row]))
  config.value.common_plan = teams.map(team => rows.get(team) || { team_no: team, map_code: config.value.maps[0]?.code || '', enabled: false })
}
async function load() { config.value = await api.expeditionSchedule(); completeRows() }
async function save() {
  await api.saveExpeditionSchedule({ entries: config.value.entries, common_plan: config.value.common_plan, automation: config.value.automation })
  message.value = '立刻远征设置已保存'
}
onMounted(load)
</script>

<template>
  <section v-if="config" class="immediate-expedition">
    <div class="immediate-expedition-head"><div><h3>立刻远征</h3><p>运行“远征”后立即派出，不会到点自动接管游戏。</p></div><button type="button" class="secondary" @click="save">保存远征设置</button></div>
    <div v-for="row in config.common_plan" :key="row.team_no" class="setting-row">
      <label><input v-model="row.enabled" type="checkbox" /> 部队{{ row.team_no }}</label>
      <PixelControl v-model="row.map_code" as="select"><option v-for="map in config.maps" :key="map.code" :value="map.code">{{ mapLabel(map) }}</option></PixelControl>
    </div>
    <p v-if="message" class="inline-message">{{ message }}</p>
  </section>
</template>
