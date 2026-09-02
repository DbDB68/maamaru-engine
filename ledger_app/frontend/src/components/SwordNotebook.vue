<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { mobileApi } from '../mobileApi'

interface SwordEntry { id: string; name: string; name_zh: string; type: string }
interface SwordRecord { level: number; ranbu: number; note?: string; updated_at: number }

const swords = ref<SwordEntry[]>([])
const records = ref<Record<string, SwordRecord>>({})
const search = ref('')
const editing = ref('')
const form = ref({ level: 1, ranbu: 1, note: '' })
const notice = ref('')
const busy = ref(false)

function displayName(sword: SwordEntry) { return sword.name_zh || sword.name }
function swordByName(name: string) { return swords.value.find(sword => displayName(sword) === name) }

const recorded = computed(() => Object.entries(records.value)
  .map(([name, record]) => ({ name, record, sword: swordByName(name) }))
  .sort((left, right) => right.record.updated_at - left.record.updated_at))
const candidates = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return []
  return swords.value
    .filter(sword => `${sword.name}${sword.name_zh}${sword.type}`.toLowerCase().includes(query))
    .slice(0, 12)
})

function edit(name: string) {
  const existing = records.value[name]
  editing.value = name
  form.value = existing
    ? { level: existing.level, ranbu: existing.ranbu, note: existing.note || '' }
    : { level: 1, ranbu: 1, note: '' }
  search.value = ''
  notice.value = ''
}

async function save() {
  if (!editing.value) return
  busy.value = true
  try {
    await mobileApi.saveSwordRecord(editing.value, form.value)
    records.value = await mobileApi.swordRecords()
    notice.value = `${editing.value}记好了。`
    editing.value = ''
  } finally { busy.value = false }
}

async function remove(name: string) {
  await mobileApi.deleteSwordRecord(name)
  records.value = await mobileApi.swordRecords()
  if (editing.value === name) editing.value = ''
  notice.value = `${name}已从刀帐移除。`
}

onMounted(async () => {
  const [roster, saved] = await Promise.all([mobileApi.swords(), mobileApi.swordRecords()])
  swords.value = roster.swords
  records.value = saved
})
</script>

<template>
  <section class="sword-notebook">
    <header class="sword-head"><p>我的刀帐</p><h2>刀剑男士</h2><strong>{{ recorded.length }} 把</strong></header>

    <p v-if="notice" class="sword-notice" role="status">{{ notice }}</p>

    <form v-if="editing" class="sword-editor" @submit.prevent="save">
      <header><div><small>{{ swordByName(editing)?.type || '刀剑男士' }}</small><h3>{{ editing }}</h3></div><button type="button" aria-label="关闭刀帐编辑" @click="editing = ''">×</button></header>
      <div><label>等级<input v-model.number="form.level" type="number" min="1" max="999" required></label><label>乱舞等级<input v-model.number="form.ranbu" type="number" min="1" max="99" required></label></div>
      <label>备注<input v-model="form.note" maxlength="80" placeholder="可不填"></label>
      <footer><button type="submit" :disabled="busy">{{ busy ? '保存中…' : '记进刀帐' }}</button><button type="button" @click="editing = ''">取消</button></footer>
    </form>

    <label v-else class="sword-search">＋ 记录一把<input v-model="search" type="search" placeholder="输入名字或刀种"></label>
    <div v-if="!editing && candidates.length" class="sword-candidates">
      <button v-for="sword in candidates" :key="sword.id" type="button" @click="edit(displayName(sword))"><small>{{ sword.type }}</small><span>{{ displayName(sword) }}</span><i>{{ records[displayName(sword)] ? '修改' : '＋' }}</i></button>
    </div>

    <div v-if="recorded.length" class="sword-records">
      <article v-for="item in recorded" :key="item.name">
        <header><small>{{ item.sword?.type || '刀剑男士' }}</small><strong>{{ item.name }}</strong></header>
        <div><b>Lv. {{ item.record.level }}</b><span>乱舞 {{ item.record.ranbu }}</span></div>
        <p v-if="item.record.note">{{ item.record.note }}</p>
        <footer><button type="button" @click="edit(item.name)">修改</button><button type="button" @click="remove(item.name)">移除</button></footer>
      </article>
    </div>
    <div v-else-if="!editing" class="sword-empty">刀帐还是空的。</div>
  </section>
</template>

<style scoped>
.sword-notebook { display: grid; gap: 16px; }
.sword-head { position: relative; }
.sword-head p { margin: 0 0 6px; font-size: 12px; font-weight: 800; letter-spacing: .14em; }
.sword-head h2 { margin: 0; font-size: clamp(38px, 10vw, 54px); line-height: 1; font-weight: 900; }
.sword-head > strong { position: absolute; right: 0; bottom: 2px; padding: 5px 11px; border: 2px solid #1d1a12; border-radius: 999px; background: #fff; font-size: 12px; }
.sword-notice { margin: 0; padding: 9px 12px; border-radius: 12px; background: #e4f5d8; font-size: 12px; font-weight: 750; }
.sword-search { display: grid; gap: 6px; margin-top: 10px; font-size: 12px; font-weight: 850; }
.sword-search input { width: 100%; padding: 12px 14px; border: 2px solid #1d1a12; border-radius: 15px; background: #fff; }
.sword-candidates { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; padding: 9px; border: 2px solid #1d1a12; border-radius: 18px; background: #fff; }
.sword-candidates button { display: grid; grid-template-columns: minmax(0, 1fr) auto; padding: 9px 10px; border: 0; border-radius: 12px; background: #f3f0e8; color: #1d1a12; text-align: left; }
.sword-candidates small { grid-column: 1; font-size: 9px; opacity: .55; }
.sword-candidates span { grid-column: 1; overflow: hidden; font-size: 12px; font-weight: 850; text-overflow: ellipsis; white-space: nowrap; }
.sword-candidates i { grid-row: 1 / 3; grid-column: 2; align-self: center; font-size: 11px; font-style: normal; font-weight: 800; }
.sword-editor { display: grid; gap: 13px; margin-top: 10px; padding: 18px; border: 2px solid #1d1a12; border-radius: 22px; background: #ffb3d1; box-shadow: 0 6px 0 rgba(29,26,18,.14); }
.sword-editor > header { display: flex; justify-content: space-between; }
.sword-editor h3, .sword-editor small { margin: 0; }
.sword-editor h3 { font-size: 22px; }
.sword-editor > header button { border: 0; background: none; font-size: 24px; }
.sword-editor > div { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.sword-editor label { display: grid; gap: 5px; font-size: 11px; font-weight: 800; }
.sword-editor input { width: 100%; min-width: 0; padding: 9px 10px; border: 1px solid #766c5e; border-radius: 10px; background: #fff; }
.sword-editor footer { display: flex; gap: 8px; }
.sword-editor footer button { padding: 9px 15px; border: 0; border-radius: 999px; background: #1d1a12; color: #fff7d1; font-weight: 800; }
.sword-editor footer button + button { background: rgba(255,255,255,.65); color: #1d1a12; }
.sword-records { display: grid; gap: 10px; }
.sword-records article { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 7px 12px; padding: 15px 16px; border: 2px solid #1d1a12; border-radius: 19px; background: #fff; box-shadow: 0 4px 0 rgba(29,26,18,.12); }
.sword-records article:nth-child(3n+1) { background: #a8d8ff; }
.sword-records article:nth-child(3n+2) { background: #b8e6a0; }
.sword-records article:nth-child(3n) { background: #ffb3d1; }
.sword-records header { display: grid; }
.sword-records header small { font-size: 9px; opacity: .55; }
.sword-records header strong { font-size: 17px; }
.sword-records article > div { display: flex; align-items: center; gap: 7px; }
.sword-records article > div b, .sword-records article > div span { padding: 4px 8px; border-radius: 999px; background: #1d1a12; color: #fff7d1; font-size: 11px; }
.sword-records article > p { grid-column: 1 / -1; margin: 0; font-size: 11px; opacity: .65; }
.sword-records article > footer { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 6px; }
.sword-records footer button { padding: 4px 8px; border: 0; border-radius: 8px; background: rgba(255,255,255,.7); font-size: 10px; font-weight: 750; }
.sword-records footer button:last-child { color: #9d2d27; }
.sword-empty { padding: 30px; border: 2px dashed #1d1a12; border-radius: 20px; text-align: center; font-weight: 800; opacity: .6; }
</style>
