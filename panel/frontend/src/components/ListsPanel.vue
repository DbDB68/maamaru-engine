<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'
import PixelControl from './PixelControl.vue'

type ListKey = 'repair_blacklist' | 'dismantle_whitelist' | 'sword_wishlist'

const props = withDefaults(defineProps<{ embedded?: boolean; initial?: ListKey }>(), {
  embedded: false,
  initial: 'repair_blacklist',
})

const lists = ref<Record<ListKey, string[]>>({ repair_blacklist: [], dismantle_whitelist: [], sword_wishlist: [] })
const swords = ref<Array<{ name: string; name_zh: string; type: string }>>([])
const selected = ref<ListKey>(props.initial)
const search = ref('')
const message = ref('')
const typeOrder = ['短刀', '脇差', '打刀', '太刀', '大太刀', '槍', '薙刀', '剣']
const labels: Record<ListKey, string> = { repair_blacklist: '手入黑名单', dismantle_whitelist: '刀解白名单', sword_wishlist: '心愿刀名单' }
const description: Record<ListKey, string> = {
  repair_blacklist: '手入时看到这些刀会跳过。',
  dismantle_whitelist: '刀解只会从这份名单中选择。',
  sword_wishlist: '成绩单认出这些刀时，会额外把好消息放到本丸小结最前面。',
}
const candidates = computed(() => {
  const q = search.value.trim().toLowerCase()
  return swords.value.filter(sword => !q || `${sword.name}${sword.name_zh}${sword.type}`.toLowerCase().includes(q))
})
const groupedCandidates = computed(() => {
  const groups = new Map<string, typeof swords.value>()
  for (const sword of candidates.value) {
    const type = sword.type || '其他'
    if (!groups.has(type)) groups.set(type, [])
    groups.get(type)!.push(sword)
  }
  return [...groups.entries()].sort(([a], [b]) => {
    const ai = typeOrder.indexOf(a); const bi = typeOrder.indexOf(b)
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi)
  })
})
function displayName(sword: { name: string; name_zh: string }) { return sword.name_zh || sword.name }
function toggle(name: string) {
  const current = [...lists.value[selected.value]]
  const index = current.indexOf(name)
  if (index >= 0) current.splice(index, 1); else current.push(name)
  lists.value[selected.value] = current
}
async function load() {
  const [saved, roster] = await Promise.all([api.configLists(), api.swords()])
  lists.value = { ...lists.value, ...saved }
  swords.value = roster.swords
}
async function save() {
  await api.saveConfigLists({
    repair_blacklist: lists.value.repair_blacklist,
    dismantle_whitelist: lists.value.dismantle_whitelist,
    sword_wishlist: lists.value.sword_wishlist,
  })
  message.value = '名单已保存'
}
onMounted(load)
</script>

<template>
  <section class="lists-panel">
    <PanelHeader :variant="embedded ? 'embedded' : 'section'" :title="embedded ? labels[selected] : '名单设置'" subtitle="点名字即可添加或移除"><template #actions><button class="primary" @click="save">保存名单</button></template></PanelHeader>
    <div v-if="!embedded" class="list-tabs"><button v-for="(_, key) in labels" :key="key" :class="{ active: selected === key }" @click="selected = key">{{ labels[key] }}</button></div>
    <div class="list-body">
      <h3>{{ labels[selected] }}</h3><p>{{ description[selected] }}</p>
      <div class="list-selection-head"><b>当前名单</b><span>已选 {{ lists[selected].length }} 把</span></div>
      <div class="selected-chips"><button v-for="name in lists[selected]" :key="name" @click="toggle(name)">{{ name }} ×</button><span v-if="!lists[selected].length">名单为空</span></div>
      <PixelControl v-model="search" class="list-search" placeholder="搜索刀剑名字或刀种" />
      <div class="sword-groups">
        <section v-for="([type, group], index) in groupedCandidates" :key="type" class="sword-group">
          <header><h4>{{ type }}</h4><span>{{ group.length }}</span></header>
          <div class="candidate-grid"><button v-for="sword in group" :key="sword.name" :class="{ active: lists[selected].includes(displayName(sword)) }" @click="toggle(displayName(sword))"><b>{{ displayName(sword) }}</b><i v-if="lists[selected].includes(displayName(sword))">✓</i></button></div>
        </section>
        <p v-if="!groupedCandidates.length" class="empty">没有找到符合条件的刀剑</p>
      </div>
      <p v-if="message" class="inline-message">{{ message }}</p>
    </div>
  </section>
</template>
