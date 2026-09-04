<script setup lang="ts">
defineProps<{
  variant: 'overview' | 'tasks' | 'single'
  pageClass?: string
}>()

const emit = defineEmits<{
  (event: 'scroll', value: Event): void
}>()
</script>

<template>
  <!--
    像素主题的框体必须保留三层真实盒子：木框 main → 金色底座 → 内容面板。
    金边是底座被上层面板遮住后露出的部分，不可“优化”为 border、outline 或伪元素，
    否则滚动内容会被浮在线上的描边切穿。
  -->
  <main class="maamaru-frame" :class="[`${variant}-frame`, pageClass]" @scroll="emit('scroll', $event)">
    <!-- scroll 不冒泡：像素主题由内层滚动，也要通知页面使用同一套滚动行为。 -->
    <div class="maamaru-surface" @scroll="emit('scroll', $event)">
      <slot />
    </div>
  </main>
</template>
