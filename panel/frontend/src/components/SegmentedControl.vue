<script setup lang="ts">
type SegmentValue = string | number
type SegmentItem = { value: SegmentValue; label: string; caption?: string; badge?: string | number }

withDefaults(defineProps<{
  modelValue: SegmentValue
  items: SegmentItem[]
  label: string
  variant?: 'compact' | 'wide'
}>(), { variant: 'compact' })

const emit = defineEmits<{ 'update:modelValue': [value: SegmentValue] }>()
</script>

<template>
  <div class="segmented-control" :class="`segmented-${variant}`" role="group" :aria-label="label">
    <button v-for="item in items" :key="item.value" type="button" :class="{ active: modelValue === item.value }" :aria-pressed="modelValue === item.value" @click="emit('update:modelValue', item.value)">
      <span><b>{{ item.label }}</b><small v-if="item.caption">{{ item.caption }}</small></span><em v-if="item.badge != null">{{ item.badge }}</em>
    </button>
  </div>
</template>
