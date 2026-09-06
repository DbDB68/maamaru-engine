<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { EventTimelineEntry, EventTimelineReport, HonmaruNote, HonmaruProfile, PlanningGoalAdvice, PlanningReport } from '../types'
import PaperCard from './PaperCard.vue'
import { eventTime, runTitle, runStatusLabel, shanghaiDate } from './report/reportModel'

const props = defineProps<{ activity: any; busy: boolean }>()
const emit = defineEmits<{ office: []; report: []; planning: [] }>()
const emptyProfile = (): HonmaruProfile => ({ honmaru_name: '', saniwa_name: '', province: '', attendant: '', motto: '', joined_on: '', avatar: '' })
const profile = ref<HonmaruProfile>(emptyProfile())
const draft = ref<HonmaruProfile>(emptyProfile())
const notes = ref<HonmaruNote[]>([])
const runs = ref<any[]>([])
const goals = ref<PlanningGoalAdvice[]>([])
const planning = ref<PlanningReport | null>(null)
const timeline = ref<EventTimelineReport | null>(null)
const inventory = ref<any>(null)
const editingProfile = ref(false)
const writing = ref(false)
const noteBody = ref('')
const noteId = ref<string | undefined>()
const savingProfile = ref(false)
const savingNote = ref(false)
const homeReady = ref(false)
const loading = ref(true)
const loadErrors = ref<string[]>([])
const formError = ref('')
const notice = ref('')
const filter = ref<'all' | 'notes'>('all')
const limit = ref(8)
const now = ref(Date.now())
let timer = 0
const editor = ref<HTMLDialogElement | null>(null)
watch(() => editingProfile.value || writing.value, async open => {
  if (!open) return
  await nextTick()
  editor.value?.showModal()
  editor.value?.querySelector<HTMLInputElement | HTMLTextAreaElement>('input:not([type="file"]), textarea')?.focus()
})
const today = computed(() => shanghaiDate(now.value / 1000))
const todayLabel = computed(() => new Date(`${today.value}T12:00:00+08:00`).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai' }))
const daysTogether = computed(() => {
  if (!profile.value.joined_on) return null
  const days = Math.floor((Date.parse(`${today.value}T00:00:00+08:00`) - Date.parse(`${profile.value.joined_on}T00:00:00+08:00`)) / 86400000) + 1
  return Number.isFinite(days) && days > 0 ? days.toLocaleString() : null
})
const welcome = computed(() => profile.value.saniwa_name ? `${profile.value.saniwa_name}，欢迎回来。` : '欢迎回到本丸。')
const active = computed(() => props.busy || props.activity?.active)
const homeName = computed(() => profile.value.honmaru_name || '我的本丸')
const entries = computed(() => {
  const personal = notes.value.map(note => ({ key: `note-${note.id}`, ts: note.created_at, note, run: null as any }))
  const work = filter.value === 'notes' ? [] : runs.value.map(run => ({ key: `run-${run.run_id}`, ts: Number(run.started_at), note: null as HonmaruNote | null, run }))
  return [...personal, ...work].sort((a, b) => b.ts - a.ts)
})
const visibleEntries = computed(() => entries.value.slice(0, limit.value))
const groups = computed(() => {
  const result: Array<{ date: string; entries: typeof visibleEntries.value }> = []
  for (const entry of visibleEntries.value) {
    const date = shanghaiDate(entry.ts)
    const last = result[result.length - 1]
    if (last?.date === date) last.entries.push(entry)
    else result.push({ date, entries: [entry] })
  }
  return result
})
const activeGoals = computed(() => goals.value.filter(goal => !['done', 'expired'].includes(goal.status)).slice(0, 3))
const resourceWatch = computed(() => planning.value?.resource_watch)
const kobanWatch = computed(() => planning.value?.koban_watch)
const nearestEvent = computed<EventTimelineEntry | null>(() => timeline.value?.ongoing[0] || timeline.value?.upcoming[0] || null)
const forgeCapacityPercent = computed(() => {
  const capacities = (resourceWatch.value?.resources || []).flatMap(item => item.forge_capacity == null ? [] : [item.forge_capacity])
  const maximum = Math.max(...capacities, 0)
  return maximum ? Math.max(5, Math.round(((resourceWatch.value?.forge_capacity || 0) / maximum) * 100)) : 0
})
const resourceNames = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符']
function fmt(value: number | null | undefined) { return value == null ? '尚未记录' : Math.round(value).toLocaleString() }
function resource(name: string) {
  const value = inventory.value?.resources?.[name]
  return typeof value === 'number' ? value.toLocaleString() : '未记录'
}
function goalName(goal: PlanningGoalAdvice) {
  if (goal.note) return goal.note
  if (goal.kind === 'event') return goal.event || '活动目标'
  return `${goal.resource}${goal.target == null ? '目标' : ` · ${goal.target.toLocaleString()}`}`
}
function dateLabel(date: string) { return date === today.value ? '今天' : date.replaceAll('-', '.') }
function eventMoment(event: EventTimelineEntry) {
  if (timeline.value?.ongoing.includes(event)) {
    if (event.days_left === 0) return '今天结束'
    return event.days_left == null ? '进行中' : `还剩 ${event.days_left} 天`
  }
  if (event.days_until_start === 0) return '今天开始'
  if (event.days_until_start === 1) return '明天开始'
  return event.days_until_start == null ? '即将开始' : `${event.days_until_start} 天后开始`
}
function eventMomentLabel(event: EventTimelineEntry) { return timeline.value?.ongoing.includes(event) ? '进度' : '日程' }
function eventBudget(event: EventTimelineEntry) {
  if (!event.budget || event.budget.koban_cost == null) return '暂未核算'
  if (event.budget.koban_cost === 0) return '无需额外小判'
  if (event.budget.sufficient === true) return '已经备齐'
  if (event.budget.shortfall != null) return `还差 ${fmt(event.budget.shortfall)}`
  return '正在核算'
}
function errorMessage(error: unknown) { return error instanceof Error ? error.message : '暂时没能保存，请再试一次。' }

async function loadHome() {
  const data = await api.honmaruHome()
  profile.value = { ...emptyProfile(), ...data.profile }
  notes.value = data.notes
  homeReady.value = true
}
async function loadSummaries() {
  const jobs = [
    { label: '近期记录', run: async () => { runs.value = (await api.dataRuns(12)).items } },
    { label: '规划', run: async () => { planning.value = await api.planning(); goals.value = planning.value.goals } },
    { label: '近期活动', run: async () => { timeline.value = await api.eventsTimeline() } },
    { label: '家底', run: async () => { inventory.value = (await api.dashboard()).inventory } },
  ]
  const results = await Promise.allSettled(jobs.map(job => job.run()))
  return results.flatMap((result, index) => result.status === 'rejected' ? [jobs[index]!.label] : [])
}
async function refresh() {
  if (loading.value && homeReady.value) return
  loading.value = true
  const results = await Promise.allSettled([loadHome(), loadSummaries()])
  loadErrors.value = [
    ...(results[0]!.status === 'rejected' ? ['个人档案和小记'] : []),
    ...(results[1]!.status === 'fulfilled' ? results[1]!.value : ['本丸近况']),
  ]
  loading.value = false
}
function editProfile() {
  draft.value = { ...profile.value }
  formError.value = ''
  notice.value = ''
  editingProfile.value = true
}
async function chooseAvatar(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  formError.value = ''
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 512 * 1024) {
    formError.value = '请选择 512 KB 以内的 PNG、JPG 或 WebP 头像。'
    input.value = ''
    return
  }
  try {
    draft.value.avatar = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(new Error('头像没能读到，请重新选择。'))
      reader.readAsDataURL(file)
    })
  } catch (error) { formError.value = errorMessage(error) }
}
async function saveProfile() {
  savingProfile.value = true
  formError.value = ''
  try {
    profile.value = (await api.saveHonmaruProfile(draft.value)).profile
    editingProfile.value = false
    notice.value = '档案收好了。'
  } catch (error) { formError.value = errorMessage(error) }
  finally { savingProfile.value = false }
}
function writeNote(note?: HonmaruNote) {
  noteId.value = note?.id
  noteBody.value = note?.body || ''
  formError.value = ''
  notice.value = ''
  writing.value = true
}
async function saveNote() {
  savingNote.value = true
  formError.value = ''
  try {
    const { note } = await api.saveHonmaruNote(noteBody.value, noteId.value)
    const index = notes.value.findIndex(item => item.id === note.id)
    if (index >= 0) notes.value[index] = note
    else notes.value.unshift(note)
    writing.value = false
    notice.value = '今天的这一笔，记下了。'
  } catch (error) { formError.value = errorMessage(error) }
  finally { savingNote.value = false }
}
onMounted(() => {
  void refresh()
  timer = window.setInterval(() => { now.value = Date.now() }, 60000)
})
onBeforeUnmount(() => window.clearInterval(timer))
watch(() => props.busy, (busy, previous) => { if (previous && !busy) void refresh() })
</script>

<template>
  <div class="honmaru-home">
    <p v-if="loadErrors.length" class="home-load-error" role="alert">{{ loadErrors.join('、') }}暂时没读到。<button type="button" :disabled="loading" @click="refresh">重新读取</button></p>
    <p v-if="notice" class="home-notice" role="status">{{ notice }}</p>
    <aside class="honmaru-profile" aria-label="审神者档案">
      <div class="profile-portrait"><img v-if="profile.avatar" :src="profile.avatar" alt="我的头像"><span v-else aria-hidden="true">{{ (profile.saniwa_name || profile.honmaru_name || '丸').slice(0, 1) }}</span></div>
      <p class="home-eyebrow">在这里，过我们的日子</p>
      <h1>{{ homeName }}</h1>
      <p class="profile-motto">{{ profile.motto || '留一句喜欢的话，给每次回来的自己。' }}</p>
      <div v-if="daysTogether" class="profile-anniversary"><small>就任第</small><strong>{{ daysTogether }}<span> 天</span></strong></div>
      <dl class="profile-facts">
        <div><dt>审神者</dt><dd>{{ profile.saniwa_name || '还没留名' }}</dd></div>
        <div><dt>属国</dt><dd>{{ profile.province || '待填写' }}</dd></div>
        <div><dt>就任日</dt><dd>{{ profile.joined_on?.replaceAll('-', '.') || '待填写' }}</dd></div>
        <div><dt>近侍刀</dt><dd>{{ profile.attendant || '待填写' }}</dd></div>
      </dl>
      <button type="button" class="home-text-button profile-edit" :disabled="!homeReady" @click="editProfile">{{ profile.saniwa_name ? '整理我的档案' : '写下我的档案' }} <span aria-hidden="true">↗</span></button>
      <p class="profile-footnote">庭院里有熟悉的身影，<br>这里有慢慢积攒的日常。</p>
    </aside>

    <section class="honmaru-journal" aria-label="本丸近况">
      <header class="journal-heading"><div><p class="home-eyebrow">{{ todayLabel }}</p><h2>{{ welcome }}</h2><p>今天，也在这里留一页。</p></div><button type="button" class="home-primary" :disabled="!homeReady" @click="writeNote()">＋ 写小记</button></header>
      <div class="home-office-link"><div><span class="office-dot" :class="{ active }"></span><p><strong>{{ active ? (activity?.label || '本丸正在执务') : '庭院无事，按自己的步调来。' }}</strong><small v-if="active && activity?.step">{{ activity.step }}</small></p></div><button type="button" class="home-text-button" @click="emit('office')">去执务 →</button></div>
      <div class="journal-filter" aria-label="记录筛选"><button type="button" :class="{ selected: filter === 'all' }" :aria-pressed="filter === 'all'" @click="filter = 'all'; limit = 8">本丸近况</button><button type="button" :class="{ selected: filter === 'notes' }" :aria-pressed="filter === 'notes'" @click="filter = 'notes'; limit = 8">我的小记 <span>{{ notes.length }}</span></button><button type="button" class="journal-refresh" :disabled="loading" @click="refresh">{{ loading ? '整理中…' : '刷新' }}</button></div>
      <div v-if="!entries.length" class="journal-empty"><span aria-hidden="true">✿</span><h3>{{ loading ? '正在翻看本丸记录…' : '日子还长，慢慢记。' }}</h3><p>{{ filter === 'notes' ? '今天的碎念、喜欢的一刻，都可以写在这里。' : '你写下的小记和最近的执务记录，会按日期留在这里。' }}</p><button v-if="!loading" type="button" class="home-text-button" :disabled="!homeReady" @click="writeNote()">写下第一笔 →</button></div>
      <section v-for="group in groups" :key="group.date" class="journal-day">
        <h3 class="journal-date">{{ dateLabel(group.date) }}<span v-if="group.date === today">{{ today.replaceAll('-', '.') }}</span></h3>
        <article v-for="entry in group.entries" :key="entry.key" class="journal-entry" :class="{ 'personal-entry': entry.note }">
          <template v-if="entry.note"><header><span class="entry-kind">我的小记</span><time>{{ eventTime(entry.ts) }}</time><button type="button" class="home-text-button" @click="writeNote(entry.note)">修改</button></header><p class="entry-body">{{ entry.note.body }}</p><small v-if="entry.note.updated_at" class="entry-updated">修改于 {{ eventTime(entry.note.updated_at) }}</small></template>
          <template v-else><header><span class="entry-kind">执务记录</span><time>{{ eventTime(entry.ts) }}</time><span class="entry-status" :class="{ 'needs-attention': entry.run.status === 'failed' }">{{ runStatusLabel(entry.run) }}</span></header><h4>{{ runTitle(entry.run) }}</h4><button type="button" class="home-text-button" @click="emit('report')">到本丸账查看 →</button></template>
        </article>
      </section>
      <button v-if="entries.length > limit" class="journal-more home-text-button" type="button" @click="limit += 12">再翻一些记录 ↓</button>
      <button v-if="runs.length && filter === 'all'" class="journal-more home-text-button" type="button" @click="emit('report')">更早的执务记录在本丸账里 →</button>
    </section>

    <aside class="honmaru-keepsakes" aria-label="目标与账房">
      <PaperCard variant="dashboard" class="home-goals"><header><p class="home-eyebrow">留张便笺</p><h2>最近惦记着</h2></header><ul v-if="activeGoals.length" class="home-goal-list"><li v-for="goal in activeGoals" :key="goal.id"><strong>{{ goalName(goal) }}</strong><p>{{ goal.message }}</p></li></ul><p v-else class="home-muted">想攒的家底、想完成的活动，定好目标就放在这里。</p><button type="button" class="home-text-button" @click="emit('planning')">去看看我的规划 →</button></PaperCard>
      <section class="home-planning-card home-forge-card">
        <p class="home-eyebrow">锻刀盘</p>
        <h2><span aria-hidden="true">⚒</span> {{ resourceWatch?.forge_capacity == null ? '等待资源盘点' : `现在最缺${resourceWatch.limiting.join('、') || '的资源'}` }}</h2>
        <p v-if="resourceWatch?.forge_capacity != null" class="planning-lead">还能锻 {{ fmt(resourceWatch.forge_capacity) }} 炉</p>
        <div class="forge-meter" role="progressbar" aria-label="最短资源相对余量" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="forgeCapacityPercent"><i :style="{ width: `${forgeCapacityPercent}%` }" /></div>
        <p class="planning-note">四项资源按当前配比折算；まあ丸只提醒最先卡住的那项。</p>
        <button type="button" class="home-text-button" @click="emit('planning')">去本丸 · 规划调整 →</button>
      </section>
      <section class="home-planning-card home-koban-card">
        <p class="home-eyebrow">博多账房</p>
        <h2><span class="hakata-mark" aria-hidden="true">博</span> 小判消耗监督</h2>
        <dl class="planning-rows">
          <div><dt>现有家底</dt><dd>{{ fmt(kobanWatch?.current) }}</dd></div>
          <div><dt>已经答应要花</dt><dd>{{ fmt(kobanWatch?.reserved) }}</dd></div>
          <div><dt>近 {{ kobanWatch?.spending_days || 14 }} 天支出</dt><dd>{{ fmt(kobanWatch?.confirmed_spending) }}</dd></div>
        </dl>
        <p class="planning-note">{{ kobanWatch?.current == null ? '等盘点读到小判，再把能花的、留好的分开算清楚。' : `账上真正能动的是 ${fmt(kobanWatch.available)} 小判。` }}</p>
        <button type="button" class="home-text-button" @click="emit('planning')">去本丸 · 规划安排 →</button>
      </section>
      <section class="home-planning-card home-event-card">
        <p class="home-eyebrow">近期活动</p>
        <template v-if="nearestEvent">
          <h2><span aria-hidden="true">⚑</span> {{ nearestEvent.name }}</h2>
          <dl class="planning-rows"><div><dt>{{ eventMomentLabel(nearestEvent) }}</dt><dd>{{ eventMoment(nearestEvent) }}</dd></div><div><dt>预算</dt><dd>{{ eventBudget(nearestEvent) }}</dd></div></dl>
          <p class="planning-note">{{ nearestEvent.budget?.message || nearestEvent.note || '活动安排已经收在日程里。' }}</p>
        </template>
        <template v-else><h2><span aria-hidden="true">⚑</span> 暂无近期活动</h2><p class="planning-note">有新日程时，会在这里提醒你。</p></template>
        <button type="button" class="home-text-button" @click="emit('planning')">去本丸 · 规划查看 →</button>
      </section>
      <section class="home-inventory"><header><h2>家底一角</h2><button type="button" class="home-text-button" @click="emit('report')">本丸账 ↗</button></header><p class="home-muted">最近一次记录</p><dl><div v-for="name in resourceNames" :key="name"><dt>{{ name }}</dt><dd>{{ resource(name) }}</dd></div></dl></section>
    </aside>

    <dialog v-if="editingProfile || writing" ref="editor" class="home-dialog-shell" :aria-label="editingProfile ? '整理我的档案' : '写小记'" @cancel.prevent="!savingProfile && !savingNote && (editingProfile = writing = false)">
      <section class="home-dialog">
        <header><h2>{{ editingProfile ? '整理我的档案' : noteId ? '修改小记' : '写一则小记' }}</h2><button type="button" aria-label="关闭" :disabled="savingProfile || savingNote" @click="editingProfile = writing = false">×</button></header>
        <form v-if="editingProfile" @submit.prevent="saveProfile"><fieldset :disabled="savingProfile"><label class="avatar-picker"><img v-if="draft.avatar" :src="draft.avatar" alt="头像预览"><span>选一张自己的头像<small>PNG / JPG / WebP，512 KB 以内</small></span><input type="file" accept="image/png,image/jpeg,image/webp" @change="chooseAvatar"></label><div class="profile-fields"><label>本丸名<input v-model="draft.honmaru_name" maxlength="40" placeholder="给这里起个名字"></label><label>审神者<input v-model="draft.saniwa_name" maxlength="40" placeholder="你的名字"></label><label>属国<input v-model="draft.province" maxlength="30" placeholder="例如：备前国"></label><label>就任日<input v-model="draft.joined_on" type="date" :max="today"></label><label class="field-wide">近侍刀<input v-model="draft.attendant" maxlength="40" placeholder="今天是谁陪在身边"></label><label class="field-wide">一言<textarea v-model="draft.motto" maxlength="120" rows="2" placeholder="写一句自己喜欢的话"></textarea></label></div></fieldset><p v-if="formError" role="alert" class="home-form-error">{{ formError }}</p><footer><button type="button" class="home-text-button" :disabled="savingProfile" @click="editingProfile = false">先不改了</button><button type="submit" class="home-primary" :disabled="savingProfile">{{ savingProfile ? '收好中…' : '收好档案' }}</button></footer></form>
        <form v-else @submit.prevent="saveNote"><label class="note-label">今天想记住什么？<textarea v-model="noteBody" rows="7" maxlength="2000" required :disabled="savingNote" placeholder="一点碎念，一件小事，或者今天终于等到的那个人。"></textarea></label><small>{{ noteBody.length }} / 2000</small><p v-if="formError" role="alert" class="home-form-error">{{ formError }}</p><footer><button type="button" class="home-text-button" :disabled="savingNote" @click="writing = false">先不写了</button><button type="submit" class="home-primary" :disabled="savingNote || !noteBody.trim()">{{ savingNote ? '记录中…' : '记在本丸里' }}</button></footer></form>
      </section>
    </dialog>
  </div>
</template>

<style scoped>
.honmaru-home { --home-green: #536d55; display: grid; grid-template-columns: 210px minmax(0, 1fr) 230px; gap: 30px; align-items: start; color: var(--ink); max-width: 1300px; margin: auto; }
.honmaru-home h1, .honmaru-home h2, .honmaru-home h3, .honmaru-home h4, .honmaru-home p { margin: 0; }
.honmaru-home button { transition: background .15s, color .15s; }
.honmaru-home button:disabled { cursor: default; opacity: .55; }
.honmaru-home :is(button, input, textarea):focus-visible { outline: 2px solid var(--home-green); outline-offset: 3px; }
.honmaru-home .home-eyebrow { color: var(--ink-dim); font-size: 11px; letter-spacing: .1em; margin-bottom: 10px; }
.home-text-button { color: var(--home-green); border: 0; background: transparent; padding: 4px 0; font-size: 12px; text-align: left; }
.home-text-button:hover { color: var(--ink); text-decoration: underline; }
.home-primary { padding: 9px 16px; border: 1px solid var(--home-green); border-radius: 5px; color: #fffaf0; background: var(--home-green); font-weight: 600; white-space: nowrap; }
.home-primary:hover { background: #405844; }
.honmaru-profile { padding: 5px 22px 22px 0; border-right: 1px solid var(--paper-line); overflow-wrap: anywhere; }
.profile-portrait { display: grid; place-items: center; width: 88px; height: 88px; padding: 5px; margin-bottom: 22px; border: 1px solid #c8bda6; background: var(--paper-card); box-shadow: 3px 4px 0 #d9ceba; transform: rotate(-3deg); }
.profile-portrait img { width: 100%; height: 100%; object-fit: cover; }
.profile-portrait > span { display: grid; place-items: center; width: 100%; height: 100%; font: 36px Georgia, 'Microsoft YaHei', serif; color: #65735d; background: #e2e7d6; }
.honmaru-profile h1 { font-size: 24px; line-height: 1.4; margin-bottom: 12px; }
.honmaru-profile .profile-motto { color: #716452; font-size: 13px; line-height: 1.9; white-space: pre-wrap; }
.profile-anniversary { display: grid; border-top: 1px solid var(--paper-line); margin-top: 23px; padding-top: 18px; }
.profile-anniversary small { color: var(--ink-dim); font-size: 11px; }
.profile-anniversary strong { color: var(--home-green); font: 32px Georgia, serif; }
.profile-anniversary strong span { font-size: 12px; font-family: inherit; }
.profile-facts { margin: 24px 0 16px; display: grid; gap: 13px; font-size: 12px; }
.profile-facts div { display: grid; grid-template-columns: 54px minmax(0, 1fr); gap: 8px; }
.profile-facts dt { color: var(--ink-dim); }
.profile-facts dd { margin: 0; }
.profile-edit { width: 100%; border-top: 1px dashed #c8bda6; padding-top: 15px; display: flex; justify-content: space-between; }
.honmaru-profile .profile-footnote { color: var(--ink-dim); font-size: 11px; margin-top: 32px; line-height: 1.9; }
.honmaru-journal { min-width: 0; }
.journal-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 22px; }
.journal-heading h2 { font-size: 22px; line-height: 1.5; overflow-wrap: anywhere; }
.journal-heading div > p:last-child { color: var(--ink-dim); margin-top: 5px; font-size: 12px; }
.home-office-link { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 12px 15px; background: #e8ecdf; border-left: 3px solid #a7b79b; margin-bottom: 24px; }
.home-office-link > div { display: flex; align-items: center; gap: 10px; min-width: 0; }
.home-office-link p { display: grid; gap: 3px; overflow-wrap: anywhere; }
.home-office-link strong { font-weight: 500; font-size: 12px; }
.home-office-link small { color: var(--ink-dim); font-size: 11px; }
.home-office-link button { flex-shrink: 0; }
.office-dot { width: 7px; height: 7px; background: #8ea082; border-radius: 50%; flex-shrink: 0; }
.office-dot.active { background: #c99430; }
.journal-filter { display: flex; align-items: center; gap: 22px; border-bottom: 1px solid var(--paper-line); }
.journal-filter button { padding: 0 0 11px; background: transparent; color: var(--ink-dim); border: 0; border-bottom: 2px solid transparent; font-size: 13px; }
.journal-filter button.selected { color: var(--ink); border-color: var(--home-green); font-weight: 600; }
.journal-filter span { font-size: 10px; margin-left: 5px; }
.journal-filter .journal-refresh { margin-left: auto; font-size: 11px; }
.journal-day { margin-top: 24px; }
.honmaru-home .journal-date { font-size: 13px; display: flex; align-items: center; gap: 10px; margin-bottom: 13px; color: var(--home-green); }
.journal-date span { font-size: 10px; color: var(--ink-dim); font-weight: 400; }
.journal-entry { padding: 17px 18px; margin-bottom: 12px; border: 1px solid var(--paper-line); background: var(--paper-card); border-radius: 3px; }
.journal-entry.personal-entry { border-left: 3px solid #c6ae76; box-shadow: 0 2px 3px #3d322908; }
.journal-entry header { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-bottom: 10px; font-size: 10px; color: var(--ink-dim); }
.journal-entry header button, .entry-status { margin-left: auto; font-size: 10px; }
.entry-kind { color: #7c715e; }
.honmaru-home .entry-body { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 14px; line-height: 1.9; }
.journal-entry h4 { font-size: 14px; font-weight: 500; margin-bottom: 10px; }
.entry-updated { display: block; color: var(--ink-dim); font-size: 10px; margin-top: 12px; }
.entry-status.needs-attention { color: #a03f32; }
.journal-more { display: block; margin: 18px auto; text-align: center; }
.journal-empty { padding: 50px 20px; text-align: center; }
.journal-empty > span { color: #afbaa2; font-size: 34px; }
.journal-empty h3 { margin: 14px 0 10px; font-size: 17px; font-weight: 500; }
.journal-empty p { color: var(--ink-dim); line-height: 1.9; font-size: 12px; margin-bottom: 18px; }
.honmaru-keepsakes { display: grid; gap: 25px; min-width: 0; }
.honmaru-keepsakes h2 { font-size: 15px; margin-bottom: 12px; }
.home-goals { position: relative; padding: 20px 18px 17px; border: 1px solid #e3d5b7; background: #f3ecd9; border-radius: 2px; box-shadow: 2px 3px 0 #e5dac4; }
.home-goals::before { content: ''; width: 45px; height: 13px; position: absolute; top: -6px; left: calc(50% - 22px); background: #d3c79a88; transform: rotate(-4deg); }
.home-goal-list { padding: 0; margin: 0; list-style: none; }
.home-goal-list li { border-bottom: 1px dashed #d5c8a9; padding-bottom: 12px; margin-bottom: 12px; overflow-wrap: anywhere; }
.home-goal-list strong { font-size: 13px; font-weight: 500; }
.home-goal-list p, .honmaru-home .home-muted { color: #796e5f; font-size: 12px; line-height: 1.8; margin: 6px 0 12px; }
.home-planning-card { padding: 17px 16px; border: 1px solid var(--paper-line); background: var(--paper-card); }
.honmaru-keepsakes .home-planning-card h2 { margin: 0 0 12px; color: #173d6e; font-size: 15px; font-weight: 500; }
.home-planning-card .home-eyebrow { margin-bottom: 5px; color: #a87416; }
.planning-lead { margin-bottom: 8px !important; color: #173d6e; font-size: 13px; }
.forge-meter { height: 8px; margin: 10px 0; overflow: hidden; background: #dfddd2; }
.forge-meter i { display: block; height: 100%; background: #668764; }
.planning-note { margin: 10px 0 8px !important; color: #796e5f; font-size: 11px; line-height: 1.7; }
.hakata-mark { margin-right: 4px; color: #173d6e; font-size: 11px; }
.planning-rows { margin: 0; border-top: 1px solid #ded6c7; }
.planning-rows div { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px solid #ded6c7; font-size: 12px; }
.planning-rows dt { color: #173d6e; }
.planning-rows dd { margin: 0; color: #173d6e; font-variant-numeric: tabular-nums; text-align: right; }
.home-inventory { padding: 0 5px; }
.home-inventory header { display: flex; justify-content: space-between; align-items: baseline; }
.home-inventory header h2 { margin: 0; }
.home-inventory dl { display: grid; gap: 8px; margin: 0; }
.home-inventory dl > div { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
.home-inventory dt { color: var(--ink-dim); }
.home-inventory dd { margin: 0; font-variant-numeric: tabular-nums; }
.home-load-error, .home-notice { grid-column: 1 / -1; padding: 10px 14px; background: #f2e2cd; font-size: 12px; }
.home-load-error button { background: transparent; border: 0; text-decoration: underline; margin-left: 12px; color: inherit; }
.home-notice { background: #e8ecdf; }
.home-dialog-shell { width: min(510px, calc(100% - 24px)); max-height: 90dvh; padding: 0; border: 0; border-radius: 8px; background: var(--paper-card); box-shadow: 0 18px 70px #0004; }
.home-dialog-shell::backdrop { background: #30291f77; }
.home-dialog { padding: 25px; color: var(--ink); border: 1px solid #c8bda6; border-radius: 8px; }
.home-dialog > header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 23px; }
.home-dialog h2 { font-size: 19px; }
.home-dialog > header button { color: var(--ink); background: transparent; border: 0; font-size: 24px; padding: 0 5px; }
.home-dialog fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.profile-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
.profile-fields label, .note-label { display: grid; gap: 6px; font-size: 12px; }
.field-wide { grid-column: 1 / -1; }
.home-dialog input:not([type='file']), .home-dialog textarea { width: 100%; min-width: 0; padding: 10px; color: var(--ink); background: var(--paper); border: 1px solid var(--paper-line); border-radius: 4px; }
.home-dialog textarea { resize: vertical; }
.home-dialog footer { display: flex; justify-content: flex-end; gap: 20px; margin-top: 22px; }
.home-dialog form > small { display: block; color: var(--ink-dim); text-align: right; margin-top: 5px; }
.home-dialog .home-form-error { color: #9b392b; margin-top: 15px; font-size: 12px; }
.avatar-picker { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding-bottom: 20px; font-size: 13px; }
.avatar-picker img { width: 54px; height: 54px; object-fit: cover; border: 3px solid #e5dac4; }
.avatar-picker small { display: block; color: var(--ink-dim); font-size: 10px; }
.avatar-picker input { font-size: 12px; width: 100%; }
@media (max-width: 1100px) { .honmaru-home { grid-template-columns: 175px minmax(0, 1fr); gap: 25px; } .honmaru-keepsakes { grid-column: 2; grid-template-columns: 1fr 1fr; gap: 20px; } .home-inventory { grid-column: 1 / -1; } .home-inventory dl { grid-template-columns: 1fr 1fr; gap: 10px 25px; } }
@media (max-width: 720px) { .honmaru-home { grid-template-columns: 1fr; gap: 25px; } .honmaru-profile { padding: 0 0 20px; border-right: 0; border-bottom: 1px solid var(--paper-line); display: grid; grid-template-columns: 66px minmax(0, 1fr); column-gap: 20px; } .profile-portrait { grid-row: 1 / 4; width: 66px; height: 66px; margin: 3px 0 0; } .honmaru-profile .home-eyebrow { margin-bottom: 4px; } .honmaru-profile h1 { font-size: 21px; margin-bottom: 6px; } .profile-motto { grid-column: 2; } .profile-facts { grid-column: 1 / -1; grid-template-columns: 1fr 1fr; margin: 20px 0 12px; gap: 12px; } .profile-anniversary { grid-column: 1 / -1; display: flex; align-items: baseline; gap: 12px; margin-top: 16px; padding-top: 12px; } .profile-anniversary strong { font-size: 24px; } .profile-edit { grid-column: 1 / -1; } .profile-footnote { display: none; } .journal-heading h2 { font-size: 20px; } .journal-heading { gap: 10px; } .home-primary { padding: 8px 12px; font-size: 12px; } .honmaru-keepsakes { grid-column: 1; grid-template-columns: 1fr; } .home-inventory { grid-column: 1; } .home-dialog { padding: 20px; } .home-dialog-backdrop { padding: 12px; } .journal-entry { padding: 14px; } }
@media (prefers-reduced-motion: reduce) { .honmaru-home button { transition: none; } }
</style>
