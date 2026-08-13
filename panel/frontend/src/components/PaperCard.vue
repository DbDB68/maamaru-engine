<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  variant: 'task' | 'dashboard' | 'settings'
  tag?: 'article' | 'section'
}>(), { tag: 'article' })

const variantClass = computed(() => ({ task: 'task-card', dashboard: 'dash-card', settings: 'settings-card' })[props.variant])
</script>

<template>
  <component :is="tag" class="paper-card" :class="variantClass">
    <slot />
  </component>
</template>
