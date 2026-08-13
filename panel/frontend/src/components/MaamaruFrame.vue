<script setup lang="ts">
defineProps<{
  variant: 'overview' | 'tasks' | 'single'
  pageClass?: string
}>()
</script>

<template>
  <!--
    像素主题的框体必须保留三层真实盒子：木框 main → 金色底座 → 内容面板。
    金边是底座被上层面板遮住后露出的部分，不可“优化”为 border、outline 或伪元素，
    否则滚动内容会被浮在线上的描边切穿。
  -->
  <main class="maamaru-frame" :class="[`${variant}-frame`, pageClass]">
    <div class="maamaru-surface">
      <slot />
    </div>
  </main>
</template>
