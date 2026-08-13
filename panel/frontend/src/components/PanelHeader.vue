<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  title: string
  subtitle?: string
  variant?: 'section' | 'embedded' | 'system'
  titleClass?: string
}>(), { subtitle: '', variant: 'section', titleClass: '' })

const variantClass = computed(() => ({
  section: 'section-head',
  embedded: 'embedded-head',
  system: 'system-toolbar',
})[props.variant])
</script>

<template>
  <header class="panel-header" :class="variantClass">
    <div :class="titleClass"><h2>{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div>
    <slot name="actions" />
  </header>
</template>
