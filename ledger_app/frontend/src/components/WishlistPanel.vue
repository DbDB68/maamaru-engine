<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'

interface SwordEntry { id: string; name: string; name_zh: string; type: string }

const wishlist = ref<string[]>([])
const swords = ref<SwordEntry[]>([])
const search = ref('')
const loading = ref(true)
const saving = ref(false)
const message = ref('')
const typeOrder = ['短刀', '脇差', '打刀', '太刀', '大太刀', '槍', '薙刀', '剣']

function displayName(sword: SwordEntry) { return sword.name_zh || sword.name }

const groupedCandidates = computed(() => {
  const query = search.value.trim().toLowerCase()
  const groups = new Map<string, SwordEntry[]>()
  for (const sword of swords.value) {
    if (query && !`${sword.name}${sword.name_zh}${sword.type}`.toLowerCase().includes(query)) continue
    const type = sword.type || '其他'
    if (!groups.has(type)) groups.set(type, [])
    groups.get(type)!.push(sword)
  }
  return [...groups.entries()].sort(([left], [right]) => {
    const leftIndex = typeOrder.indexOf(left), rightIndex = typeOrder.indexOf(right)
    return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex)
  })
})

function toggle(name: string) {
  message.value = ''
  wishlist.value = wishlist.value.includes(name)
    ? wishlist.value.filter(item => item !== name)
    : [...wishlist.value, name]
}

async function load() {
  loading.value = true
  try {
    const [saved, roster] = await Promise.all([api.configLists(), api.swords()])
    wishlist.value = saved.sword_wishlist || []
    swords.value = roster.swords || []
  } catch (cause) {
    message.value = cause instanceof Error ? cause.message : '心愿刀名单读取失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await api.saveConfigLists({ sword_wishlist: wishlist.value })
    message.value = wishlist.value.length
      ? `已记住 ${wishlist.value.length} 把心愿刀。以后认出她们时，成绩单会把好消息放在最前面。`
      : '心愿刀名单已清空。'
  } catch (cause) {
    message.value = cause instanceof Error ? cause.message : '心愿刀名单保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="wishlist-panel">
    <PanelHeader title="心愿刀名单" subtitle="想等谁来本丸，就把谁点亮。命中后成绩单会把好消息放在最前面。" variant="page">
      <template #actions><button type="button" class="primary" :disabled="loading || saving" @click="save">{{ saving ? '保存中……' : '保存名单' }}</button></template>
    </PanelHeader>
    <div class="wishlist-body">
      <section class="wishlist-current" aria-label="当前心愿刀">
        <header><div><small>当前名单</small><strong>{{ wishlist.length ? `正在等 ${wishlist.length} 把刀` : '还没有选心愿刀' }}</strong></div><span>{{ wishlist.length }} / {{ swords.length }}</span></header>
        <div class="wishlist-chips">
          <button v-for="name in wishlist" :key="name" type="button" :aria-label="`从心愿刀名单移除${name}`" @click="toggle(name)">{{ name }} <i>×</i></button>
          <p v-if="!wishlist.length">从下面点名字即可加入；名单不会在命中后自动删除，想继续等二号机也没问题。</p>
        </div>
      </section>

      <label class="wishlist-search">找刀剑<input v-model="search" type="search" placeholder="输入名字或刀种"></label>

      <div v-if="loading" class="wishlist-empty">正在展开刀帐……</div>
      <div v-else class="wishlist-groups">
        <section v-for="[type, group] in groupedCandidates" :key="type">
          <header><h3>{{ type }}</h3><span>{{ group.length }}</span></header>
          <div class="wishlist-candidates">
            <button v-for="sword in group" :key="sword.id" type="button" :class="{ active: wishlist.includes(displayName(sword)) }" :aria-pressed="wishlist.includes(displayName(sword))" @click="toggle(displayName(sword))">
              {{ displayName(sword) }}<i v-if="wishlist.includes(displayName(sword))">✓</i>
            </button>
          </div>
        </section>
        <p v-if="!groupedCandidates.length" class="wishlist-empty">没找到这把刀，换个名字试试。</p>
      </div>
      <p v-if="message" class="wishlist-message" aria-live="polite">{{ message }}</p>
    </div>
  </section>
</template>

<style scoped>
.wishlist-panel { min-height: 100%; color: var(--ink); }
.wishlist-body { display: grid; gap: 16px; padding: 18px; }
.wishlist-current { padding: 16px; background: linear-gradient(135deg, var(--fox-gold-pale), var(--paper-card)); border: 2px solid var(--fox-gold); box-shadow: var(--pixel-shadow); }
.wishlist-current > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.wishlist-current header div { display: grid; gap: 2px; }
.wishlist-current small { color: var(--ink-dim); }
.wishlist-current strong { font-family: var(--pixel-font); font-size: 18px; }
.wishlist-current header > span { padding: 4px 9px; color: var(--fox-gold-deep); background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: 999px; font-weight: 700; }
.wishlist-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
.wishlist-chips button { padding: 6px 9px; color: #6d471d; background: var(--paper-card); border: 1px solid var(--fox-gold); border-radius: 999px; }
.wishlist-chips button:hover { background: #fff5d5; }
.wishlist-chips i { font-style: normal; color: var(--shu); }
.wishlist-chips p { margin: 0; color: var(--ink-dim); }
.wishlist-search { display: grid; gap: 5px; color: var(--ink-dim); font-weight: 700; }
.wishlist-search input { width: 100%; min-height: 42px; padding: 8px 11px; color: var(--ink); background: var(--paper-card); border: 2px solid var(--paper-line); border-radius: 6px; }
.wishlist-groups { display: grid; gap: 14px; }
.wishlist-groups > section { padding: 13px; background: var(--paper-card); border: 1px solid var(--paper-line); }
.wishlist-groups section > header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 9px; }
.wishlist-groups h3 { margin: 0; font-size: 15px; }
.wishlist-groups header span { color: var(--ink-dim); font-size: 12px; }
.wishlist-candidates { display: flex; flex-wrap: wrap; gap: 7px; }
.wishlist-candidates button { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 6px 10px; color: var(--ink); background: var(--paper); border: 1px solid var(--paper-line); border-radius: 999px; }
.wishlist-candidates button:hover { border-color: var(--fox-gold); transform: translateY(-1px); }
.wishlist-candidates button.active { color: #6d4f0b; background: var(--fox-gold-pale); border-color: var(--fox-gold); font-weight: 700; }
.wishlist-candidates i { font-style: normal; }
.wishlist-empty { margin: 0; padding: 24px; color: var(--ink-dim); text-align: center; }
.wishlist-message { margin: 0; padding: 10px 12px; color: #365936; background: #e7f1dd; border-left: 4px solid var(--matcha); }
@media (max-width: 520px) {
  .wishlist-body { padding: 12px; }
  .wishlist-current > header { align-items: flex-start; }
}
</style>
