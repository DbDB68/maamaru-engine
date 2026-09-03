<script setup lang="ts">
// 近侍舞台的演员层：狐之助 + 小狐丸（占位立绘）。
// 待命期间两位会随机串门打招呼；任务跑完时追加一次收工寒暄。
// 互动只改 CSS class，动画本体全部在 style.css，主题换皮不影响状态机。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ active: boolean }>()

type Phase = 'idle' | 'approach' | 'chat' | 'leave'
type ChatLine = { who: 'fox' | 'kogi'; text: string }

const phase = ref<Phase>('idle')
const foxLine = ref('')
const kogiLine = ref('')

const idleChats: ChatLine[][] = [
  [
    { who: 'fox', text: '小狐丸大人——！' },
    { who: 'kogi', text: '哦呀，是狐狸吗。' },
    { who: 'fox', text: '今天的本丸也很和平呢！' },
  ],
  [
    { who: 'kogi', text: '狐狸，毛色不错。' },
    { who: 'fox', text: '嘿嘿，被夸了！' },
  ],
  [
    { who: 'fox', text: '要一起喝茶吗？' },
    { who: 'kogi', text: '好啊，配油豆腐就更好了。' },
  ],
]
const finishChats: ChatLine[][] = [
  [
    { who: 'fox', text: '任务完成啦！' },
    { who: 'kogi', text: '辛苦了，来杯茶吧。' },
  ],
  [
    { who: 'kogi', text: '做得漂亮。' },
    { who: 'fox', text: '都是主人的功劳！' },
  ],
]

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
let timers: number[] = []
let disposed = false

function later(fn: () => void, ms: number) {
  timers.push(window.setTimeout(() => { if (!disposed) fn() }, ms))
}
function clearTimers() {
  timers.forEach(id => window.clearTimeout(id))
  timers = []
}
function pick<T>(list: T[]): T {
  return list[Math.floor(Math.random() * list.length)]
}

function scheduleNext() {
  if (props.active || reducedMotion.matches) return
  later(() => startInteraction(pick(idleChats)), 45000 + Math.random() * 45000)
}

function startInteraction(lines: ChatLine[]) {
  if (props.active || reducedMotion.matches || phase.value !== 'idle') return
  phase.value = 'approach'
  later(() => {
    phase.value = 'chat'
    let t = 0
    for (const line of lines) {
      later(() => {
        if (line.who === 'fox') foxLine.value = line.text
        else kogiLine.value = line.text
      }, t)
      t += 2300
    }
    later(() => {
      phase.value = 'leave'
      foxLine.value = ''
      kogiLine.value = ''
    }, t + 400)
    later(() => {
      phase.value = 'idle'
      scheduleNext()
    }, t + 1800)
  }, 1500)
}

function cancelInteraction() {
  clearTimers()
  phase.value = 'idle'
  foxLine.value = ''
  kogiLine.value = ''
}

watch(() => props.active, (now, before) => {
  if (now) {
    cancelInteraction()
  } else if (before) {
    // 刚收工：尽快安排一次庆祝寒暄
    later(() => startInteraction(pick(finishChats)), 2500)
  } else {
    scheduleNext()
  }
})

onMounted(() => { if (!props.active) scheduleNext() })
onBeforeUnmount(() => { disposed = true; clearTimers() })
</script>

<template>
  <div class="stage-actors" :class="`phase-${phase}`" aria-hidden="true">
    <div class="stage-kogi"></div>
    <div class="stage-fox"></div>
    <div v-if="kogiLine" class="stage-bubble bubble-kogi">{{ kogiLine }}</div>
    <div v-if="foxLine" class="stage-bubble bubble-fox">{{ foxLine }}</div>
  </div>
</template>
