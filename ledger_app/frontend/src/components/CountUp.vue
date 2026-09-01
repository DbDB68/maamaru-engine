<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

// 家底大数字的滚动 count-up；只负责展示，数值口径仍由父组件给出。
const props = withDefaults(defineProps<{ value: number | null; signed?: boolean }>(), { signed: false })

const display = ref('—')
let raf = 0
let current = 0

function format(value: number) {
  const rounded = Math.round(value)
  return `${props.signed && rounded > 0 ? '+' : ''}${rounded.toLocaleString()}`
}

function reducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function animateTo(target: number) {
  cancelAnimationFrame(raf)
  if (reducedMotion()) {
    current = target
    display.value = format(target)
    return
  }
  const from = current
  const started = performance.now()
  const duration = 650
  const tick = (now: number) => {
    const progress = Math.min(1, (now - started) / duration)
    const eased = 1 - Math.pow(1 - progress, 3)
    current = from + (target - from) * eased
    display.value = format(current)
    if (progress < 1) raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
}

watch(() => props.value, value => {
  if (value == null || Number.isNaN(value)) { cancelAnimationFrame(raf); display.value = '—'; return }
  animateTo(Number(value))
})

onMounted(() => {
  if (props.value != null && !Number.isNaN(props.value)) animateTo(Number(props.value))
})
</script>

<template>
  <span class="count-up">{{ display }}</span>
</template>
